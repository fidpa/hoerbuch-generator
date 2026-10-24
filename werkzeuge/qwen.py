"""
qwen.py - Qwen3-TTS fuer vorlesen.sh (Textdatei -> WAV, 24 kHz mono)

Wird von vorlesen.sh aufgerufen und laeuft im venv .venv dieses Ordners
(mlx-audio, Apple-Silicon-GPU).

Usage:
    .venv/bin/python werkzeuge/qwen.py [--voice NAME] [--stuecke ORDNER] EINGABE.txt AUSGABE.wav

Was passiert:
    - Stimme: Klon einer Referenzaufnahme stimmen/NAME.wav (gesprochener Text in
      NAME.txt), Default "erzaehler", Alternative "dozent". Die Referenzen stammen aus
      dem VoiceDesign-Modell; Beschreibung und Rezept stehen in der README.
      Klonen statt Beschreibung, weil VoiceDesign die Stimme je Textstueck neu
      wuerfelt und bei langen Texten Saetze ausliess (Test vom 23.10.2026).
    - Absaetze: Enthaelt der Text Leerzeilen, trennen sie die Absaetze und einfache
      Zeilenumbrueche werden zusammengezogen (pdftotext, hart umbrochene .txt).
      Ohne Leerzeilen ist jede Zeile ein Absatz (Ausgabe von hoerfassung.py).
    - Lange Absaetze werden an Satzenden in Stuecke bis MAX_CHARS geteilt, ueberlange
      Saetze hilfsweise an Semikolon, Komma oder Leerzeichen. Lange Stuecke erzeugt
      das Modell unzuverlaessig.
    - Pausen: PAUSE_CHUNK zwischen Stuecken eines Absatzes, PAUSE_PARAGRAPH nach
      jedem Absatz.
    - Kontrolle je Stueck: kein Audio oder Abbruch an der Token-Grenze (Modell findet
      kein Ende und erzeugt Rauschen) gilt als Fehlversuch; nach MAX_ATTEMPTS
      Fehlversuchen bricht der Lauf mit Exit 1 ab.
    - Atem: Qwen atmet hoerbar ein, vor allem am Anfang jedes Stuecks. atem.py
      erkennt die Atemzuege (Modell Respiro-en) und senkt sie um 18 dB ab, ohne etwas
      herauszuschneiden. --keep-breath laesst den Atem unveraendert.
    - Jedes Stueck wird sofort in die WAV geschrieben (kein Sammeln im Speicher).
    - Fortsetzen: Mit --stuecke ORDNER landet jedes fertige Stueck zusaetzlich als WAV
      in ORDNER, benannt nach Nummer und Pruefsumme. Die Pruefsumme deckt alles ab,
      was den Klang bestimmt: Stuecktext, Modell, Stimme und --keep-breath. Ein
      Neustart uebernimmt passende Stuecke und erzeugt nur die fehlenden; Dateien,
      die nicht mehr passen, werden geloescht. vorlesen.sh loescht den Ordner nach
      der fertigen MP3.
    - Das Modell laedt beim ersten Lauf nach ~/.cache/huggingface (rund 2 GB).
"""

import argparse
import hashlib
import logging
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

SCRIPT_DIR = Path(__file__).resolve().parent
MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
VOICES_DIR = SCRIPT_DIR.parent / "stimmen"
DEFAULT_VOICE = "erzaehler"
MAX_CHARS = 450
PAUSE_CHUNK = 0.35
PAUSE_PARAGRAPH = 0.8
SAMPLE_RATE = 24000
# 12 Token je Sekunde Audio; gemessen rund 1 Token je Zeichen. Faktor 3 laesst
# langsames Sprechen zu und kappt ein Stueck, das kein Ende findet.
TOKENS_PER_CHAR = 3
MIN_TOKENS = 240
MAX_ATTEMPTS = 2
CHUNK_FILE_RE = re.compile(r"^\d{5}_[0-9a-f]{16}\.wav(\.tmp)?$")

log = logging.getLogger("qwen")


def read_paragraphs(text: str) -> list[str]:
    """Absaetze: Leerzeilen trennen, falls vorhanden; sonst jede Zeile ein Absatz."""
    if re.search(r"\n\s*\n", text):
        blocks = re.split(r"\n\s*\n", text)
        return [" ".join(b.split()) for b in blocks if b.strip()]
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def split_long(sentence: str) -> list[str]:
    """Satz ueber MAX_CHARS an Semikolon, Komma oder zuletzt am Leerzeichen teilen."""
    parts: list[str] = []
    rest = sentence
    while len(rest) > MAX_CHARS:
        window = rest[:MAX_CHARS]
        cut = max(window.rfind("; "), window.rfind(", "))
        if cut < MAX_CHARS // 3:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = MAX_CHARS - 1
        parts.append(rest[:cut + 1].strip())
        rest = rest[cut + 1:].strip()
    if rest:
        parts.append(rest)
    return parts


def split_paragraph(paragraph: str) -> list[str]:
    """Absatz an Satzenden in Stuecke bis MAX_CHARS teilen."""
    sentences = []
    for sentence in re.split(r"(?<=[.!?:])\s+", paragraph.strip()):
        sentences.extend(split_long(sentence) if len(sentence) > MAX_CHARS else [sentence])
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > MAX_CHARS:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def synthesize_chunk(model, chunk: str, ref_audio, ref_text: str) -> np.ndarray | None:
    """Ein Stueck erzeugen; None bei leerem Ergebnis oder Abbruch an der Token-Grenze."""
    max_tokens = max(MIN_TOKENS, len(chunk) * TOKENS_PER_CHAR)
    audio: list[np.ndarray] = []
    tokens = 0
    for result in model.generate(text=chunk, lang_code="german", max_tokens=max_tokens,
                                 ref_audio=ref_audio, ref_text=ref_text):
        audio.append(np.array(result.audio, dtype=np.float32))
        tokens += result.token_count
    if not audio:
        log.warning("Kein Audio für Stück: %.80s", chunk)
        return None
    if tokens >= max_tokens:
        log.warning("Token-Grenze erreicht (%d), Stück vermutlich entgleist: %.80s", max_tokens, chunk)
        return None
    # Kappen vor PCM_16: Werte ueber 1.0 wuerden sonst als Knacken umschlagen
    return np.clip(np.concatenate(audio), -1.0, 1.0)


def sound_key(ref_audio_path: Path, ref_text: str, keep_breath: bool) -> str:
    """Pruefsumme ueber alles ausser dem Text, was den Klang eines Stuecks bestimmt."""
    h = hashlib.sha256()
    for part in (MODEL.encode(), ref_audio_path.read_bytes(), ref_text.encode(),
                 b"keep-breath" if keep_breath else b"breath-attenuated"):
        h.update(hashlib.sha256(part).digest())
    return h.hexdigest()


def chunk_file(number: int, chunk: str, key: str) -> str:
    digest = hashlib.sha256(f"{key}\n{chunk}".encode()).hexdigest()[:16]
    return f"{number:05d}_{digest}.wav"


def save_chunk(path: Path, audio: np.ndarray) -> None:
    """Erst unter .tmp schreiben, dann umbenennen: Ein Abbruch beim Schreiben hinterlaesst
    sonst eine halbe WAV, die beim Neustart als fertig gaelte."""
    tmp = path.with_name(path.name + ".tmp")
    sf.write(tmp, audio, SAMPLE_RATE, subtype="PCM_16", format="WAV")
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Qwen3-TTS: Textdatei -> WAV (Stimmklon)")
    parser.add_argument("--voice", default=DEFAULT_VOICE,
                        help=f"Stimme aus stimmen/ (Default: {DEFAULT_VOICE})")
    parser.add_argument("--keep-breath", action="store_true",
                        help="Atemgeraeusche nicht absenken")
    parser.add_argument("--stuecke", type=Path, metavar="ORDNER",
                        help="fertige Stuecke hier ablegen und beim Neustart uebernehmen")
    parser.add_argument("input", type=Path, help="Textdatei (UTF-8)")
    parser.add_argument("output", type=Path, help="Ausgabe-WAV")
    args = parser.parse_args()

    # Root auf WARNING: sonst meldet httpx jede Modell-Anfrage an Hugging Face
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(message)s")
    log.setLevel(logging.INFO)

    ref_audio_path = VOICES_DIR / f"{args.voice}.wav"
    ref_text_path = VOICES_DIR / f"{args.voice}.txt"
    if not ref_audio_path.is_file():
        voices = sorted(f.stem for f in VOICES_DIR.glob("*.wav"))
        log.error("Unbekannte Stimme: %s (vorhanden: %s)", args.voice, ", ".join(voices))
        return 1
    for path in (args.input, ref_text_path):
        if not path.is_file():
            log.error("Datei fehlt: %s", path)
            return 1

    paragraphs = read_paragraphs(args.input.read_text(encoding="utf-8"))
    if not paragraphs:
        log.error("Kein Text in %s", args.input)
        return 1
    # Je Stueck: Text und ob es einen Absatz abschliesst (laengere Pause danach)
    plan = [(chunk, i == len(pc) - 1)
            for pc in (split_paragraph(p) for p in paragraphs) for i, chunk in enumerate(pc)]
    total = len(plan)
    ref_text = ref_text_path.read_text(encoding="utf-8").strip()

    files: list[Path | None] = [None] * total
    if args.stuecke:
        args.stuecke.mkdir(parents=True, exist_ok=True)
        key = sound_key(ref_audio_path, ref_text, args.keep_breath)
        files = [args.stuecke / chunk_file(n, chunk, key) for n, (chunk, _) in enumerate(plan, 1)]
        wanted = {f.name for f in files if f}
        for old in args.stuecke.iterdir():
            if CHUNK_FILE_RE.match(old.name) and old.name not in wanted:
                old.unlink()
        cached = sum(1 for f in files if f and f.is_file())
        if cached:
            log.info("Fortsetzung: %d von %d Stücken liegen schon in %s", cached, total, args.stuecke)
    missing = [f is None or not f.is_file() for f in files]

    model = ref_audio = attenuate = None
    if any(missing):
        # Import erst hier: dauert einige Sekunden und ist fuer --help unnoetig
        from mlx_audio.tts.utils import load_model
        from mlx_audio.utils import load_audio

        if not args.keep_breath:
            from atem import attenuate

        model = load_model(MODEL)
        ref_audio = load_audio(str(ref_audio_path), sample_rate=SAMPLE_RATE)
    pause_chunk = np.zeros(int(SAMPLE_RATE * PAUSE_CHUNK), dtype=np.float32)
    pause_paragraph = np.zeros(int(SAMPLE_RATE * PAUSE_PARAGRAPH), dtype=np.float32)

    resume_hint = (f"Fertige Stücke bleiben in {args.stuecke}; derselbe Aufruf setzt dort fort."
                   if args.stuecke else "")
    samples = 0
    breaths = 0
    n = 0
    start = time.time()
    try:
        with sf.SoundFile(args.output, "w", SAMPLE_RATE, 1, subtype="PCM_16") as out:
            for n, ((chunk, ends_paragraph), path, todo) in enumerate(
                    zip(plan, files, missing, strict=True), 1):
                if not todo:
                    audio, _ = sf.read(path, dtype="float32")
                else:
                    audio = None
                    for _ in range(MAX_ATTEMPTS):
                        audio = synthesize_chunk(model, chunk, ref_audio, ref_text)
                        if audio is not None:
                            break
                    if audio is None:
                        log.error("Stück %d/%d nach %d Versuchen fehlgeschlagen, Abbruch. %s",
                                  n, total, MAX_ATTEMPTS, resume_hint)
                        return 1
                    if attenuate is not None:
                        audio, k = attenuate(audio, SAMPLE_RATE)
                        breaths += k
                    if path:
                        save_chunk(path, audio)
                    log.info("Stück %d/%d (%.0f s)", n, total, time.time() - start)
                pause = pause_paragraph if ends_paragraph else pause_chunk
                out.write(audio)
                out.write(pause)
                samples += len(audio) + len(pause)
    except KeyboardInterrupt:
        if args.stuecke:
            ready = sum(1 for f in files if f and f.is_file())
            log.info("Abgebrochen, %d von %d Stücken sind fertig. %s", ready, total, resume_hint)
        else:
            log.info("Abgebrochen bei Stück %d/%d.", max(n, 1), total)
        return 130

    reused = total - sum(missing)
    summary = [f"Audio {samples / SAMPLE_RATE:.0f} s", f"Rechenzeit {time.time() - start:.0f} s"]
    if reused < total:
        summary.append("Atem unverändert" if args.keep_breath else f"{breaths} Atemzüge abgesenkt")
    if reused:
        summary.append(f"{reused} Stücke übernommen")
    log.info(", ".join(summary))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
