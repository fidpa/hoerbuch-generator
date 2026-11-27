"""
sprechdienst.py - Qwen3-TTS als Sprechdienst: Text rein, Sprache sofort aus dem Lautsprecher

Wird von sprechen.sh aufgerufen und laeuft im venv .venv dieses Ordners. Gedacht fuer
kurze Texte, die sofort hoerbar sein sollen, etwa die Antworten eines KI-Assistenten.
Fuer lange Texte bleibt vorlesen.sh der Weg (MP3, Fortsetzen nach Abbruch).

Usage:
    .venv/bin/python werkzeuge/sprechdienst.py [-v STIMME] [-t TEMPO] [--lauter DB] [--mit-atem]
        [--warten | --liefern | --datei] [--quelle ID [--ansage TEXT]] [TEXT | -]
    .venv/bin/python werkzeuge/sprechdienst.py --stopp [--quelle ID] | --status | --beenden

Aufbau:
    - Ein Dienst haelt das Modell geladen und lauscht auf einem Unix-Socket
      (SPRECHDIENST_SOCKET, Vorgabe ~/Library/Caches/hoerbuch-generator/sprechdienst.sock).
      Der erste Aufruf startet ihn im Hintergrund; nach LEERLAUF Sekunden ohne Auftrag
      beendet er sich und gibt die rund 2 GB Speicher wieder frei. Als Auftrag zaehlt nur
      sprich, nicht stopp oder status.
    - Der Aufruf kehrt zurueck, sobald der Auftrag angenommen ist (ausser mit --warten).
      Auftraege werden der Reihe nach gesprochen; --stopp bricht die laufende Ausgabe ab
      und verwirft die Warteschlange. Mit --quelle tragen Auftraege eine Kennung des
      Aufrufers, und --stopp --quelle trifft nur dessen Auftraege. --ansage nennt den
      Aufrufer, wenn zuletzt ein anderer sprach.
    - Der Text wird in Saetze geteilt und Satz fuer Satz erzeugt, waehrend der vorige
      schon klingt. Kurze Saetze werden mit dem naechsten zusammengefasst, sonst klingt
      die Ausgabe abgehackt. Erzeugung, Kontrolle je Stueck und Stimmklon kommen aus
      qwen.py, damit es nur einen Qwen-Weg gibt.
    - Tempo wie in vorlesen.sh ueber ffmpeg atempo (Tonhoehe bleibt gleich), Atem wie
      dort ueber atem.py abgesenkt; --mit-atem laesst ihn unveraendert.
    - --lauter DB hebt die Stimme an, etwa gegen Musik im Hintergrund; ein Limiter haelt
      die Spitzen unter LIMIT_DB. Ohne die Option bleibt der Pegel wie erzeugt.
    - Wiedergabe ueber den AudioPlayer von mlx-audio (sounddevice, gepuffert). Mit --liefern
      spielt der Dienst nichts ab, sondern schreibt den Ton Satz fuer Satz als 16-Bit-PCM
      (24 kHz, mono) nach stdout. Ueber ssh aufgerufen, rechnet so ein Mac fuer ein anderes
      Geraet, das den Ton selbst abspielt; Warteschlange und Stopp je Quelle gelten weiter.
      Mit --datei legt der Aufruf den Ton als MP3 (ohne ffmpeg als WAV) in DATEI_ORDNER ab
      und gibt den Pfad aus, fuer Oberflaechen, die eine Audiodatei in der Antwort abspielen
      (etwa T3 Code am Handy).
    - Metal steht in einer macOS-Sandbox nicht zur Verfuegung. Wer den Dienst aus einer
      Sandbox heraus startet (etwa aus einem Agenten-Werkzeug), bekommt eine Fehlermeldung
      statt Sprache; Hooks oder ein Terminal starten ihn ausserhalb.

Protokoll: eine JSON-Zeile je Verbindung, eine JSON-Zeile als Antwort.
    {"cmd": "sprich", "text": "...", "stimme": "erzaehler", "tempo": 1.2, "lauter": 0,
     "quelle": "", "ansage": "", "mit_atem": false, "warten": false}
    {"cmd": "stopp", "quelle": ""} | {"cmd": "status"} | {"cmd": "beenden"}
    Ein stopp mit quelle bricht nur die Auftraege mit derselben quelle ab, ohne quelle alle.
    Die ansage wird vorangestellt, wenn zuletzt eine andere quelle hoerbar sprach.
    Mit "liefern": true (nicht zusammen mit warten) antwortet der Dienst mit der Kopfzeile
    {"ok": true, "format": "s16le", "rate": 24000, "kanaele": 1}, danach folgt roher Ton bis
    zum Ende der Verbindung.
    Fehlt ein Feld oder ist es null, gilt die Vorgabe; ein Feld mit anderem Typ als oben
    (etwa "false" als Zeichenkette fuer mit_atem) weist der Dienst mit ok false ab.
"""

import argparse
import fcntl
import io
import json
import logging
import os
import queue
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import qwen

SCRIPT = Path(__file__).resolve()
DEFAULT_SOCKET = Path.home() / "Library" / "Caches" / "hoerbuch-generator" / "sprechdienst.sock"
DEFAULT_LOG = Path.home() / "Library" / "Logs" / "hoerbuch-generator" / "sprechdienst.log"
DEFAULT_TEMPO = 1.20  # wie vorlesen.sh: rund 150 Woerter pro Minute
LEERLAUF = 20 * 60  # Sekunden ohne Auftrag, danach beendet sich der Dienst
START_WARTEN = 15.0  # Sekunden, die ein Aufruf auf den frisch gestarteten Dienst wartet
MIN_SATZ = 40  # kuerzere Saetze werden mit dem naechsten zusammengefasst
PAUSE_SATZ = 0.25
PAUSE_ABSATZ = 0.6
MAX_ANFRAGE = 1_000_000  # Bytes je Anfrage
# Verstaerkung in dB. Die Stimmen liegen bei rund -21 LUFS, Musik bei Streamingdiensten
# bei rund -14 LUFS; +8 dB mit Limiter brachte marketing.wav auf -14 LUFS (26.11.2026)
MAX_LAUTER = 15.0
LIMIT_DB = -1.5  # Obergrenze des Limiters, Abstand zu 0 dBFS fuer Spitzen zwischen den Samples
LIEFERN_TIMEOUT = 120.0  # Sekunden, die sendall bei --liefern auf einen lesenden Aufrufer wartet
# --datei: fester Ordner, damit ein Aufruf als Ausnahme einer Sandbox nirgendwo sonst schreibt
DATEI_ORDNER = Path.home() / "Library" / "Caches" / "hoerbuch-generator" / "dateien"
DATEI_ALTER = 7 * 24 * 3600  # Sekunden; ältere Dateien löscht der nächste Aufruf

log = logging.getLogger("sprechdienst")


def socket_pfad() -> Path:
    return Path(os.environ.get("SPRECHDIENST_SOCKET", DEFAULT_SOCKET))


# --- Text ------------------------------------------------------------------------------

def stuecke(text: str) -> list[tuple[str, bool]]:
    """Text in Sprechstuecke teilen; je Stueck: Text und ob es einen Absatz abschliesst."""
    plan: list[tuple[str, bool]] = []
    for absatz in qwen.read_paragraphs(text):
        saetze: list[str] = []
        # Nicht nach Ziffer und Punkt teilen: "am 26. November" bekaeme sonst mitten im
        # Datum ein Satzende samt Pause. Ein Satz, der auf eine Zahl endet, bleibt dafuer
        # mit dem naechsten in einem Stueck, was nur die Pause dazwischen kuerzt
        for satz in re.split(r"(?<=[.!?:])(?<!\d\.)\s+", absatz.strip()):
            if satz:
                saetze.extend(qwen.split_long(satz) if len(satz) > qwen.MAX_CHARS else [satz])
        zusammen: list[str] = []
        for satz in saetze:
            if (zusammen and len(zusammen[-1]) < MIN_SATZ
                    and len(zusammen[-1]) + len(satz) + 1 <= qwen.MAX_CHARS):
                zusammen[-1] = f"{zusammen[-1]} {satz}"
            else:
                zusammen.append(satz)
        # Ein kurzer Schlusssatz hat keinen Nachfolger und bliebe allein; als eigenes Stueck
        # ohne Kontext klingt er abgehackt, eine Schlussfrage hebt sich dann kaum
        if (len(zusammen) > 1 and len(zusammen[-1]) < MIN_SATZ
                and len(zusammen[-2]) + len(zusammen[-1]) + 1 <= qwen.MAX_CHARS):
            zusammen[-2:] = [f"{zusammen[-2]} {zusammen[-1]}"]
        plan.extend((s, i == len(zusammen) - 1) for i, s in enumerate(zusammen))
    return plan


def text_mit_ansage(auftrag: "Auftrag", letzte_quelle: str) -> str:
    """Ansage voranstellen, wenn zuletzt eine andere Quelle sprach. Beim ersten Auftrag
    nach dem Start nicht: Mit nur einem Aufrufer waere sie dann reines Rauschen."""
    if (auftrag.ansage and auftrag.quelle and letzte_quelle
            and auftrag.quelle != letzte_quelle):
        return f"{auftrag.ansage} {auftrag.text}"
    return auftrag.text


def stimmen() -> list[str]:
    return sorted(f.stem for f in qwen.VOICES_DIR.glob("*.wav"))


def filterkette(tempo: float, lauter: float) -> str:
    """ffmpeg-Filter fuer Tempo und Verstaerkung; leer, wenn beides neutral ist."""
    filter_: list[str] = []
    if abs(tempo - 1.0) >= 0.01:
        filter_.append(f"atempo={tempo}")
    if lauter > 0:
        # Der Limiter faengt die Spitzen ab, die die Verstaerkung ueber 0 dBFS hebt;
        # level=false, sonst gleicht er die Lautheit selbst wieder an
        filter_.append(f"volume={lauter}dB,alimiter=limit={LIMIT_DB}dB:level=false")
    return ",".join(filter_)


def nachbearbeiten(audio: np.ndarray, tempo: float, lauter: float) -> np.ndarray:
    """Tempo per ffmpeg atempo (wie vorlesen.sh) und Verstaerkung um LAUTER dB mit
    Limiter; ohne ffmpeg unveraendert."""
    kette = filterkette(tempo, lauter)
    if not kette:
        return audio
    try:
        out = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(qwen.SAMPLE_RATE), "-ac", "1",
             "-i", "pipe:0", "-af", kette, "-f", "f32le", "pipe:1"],
            input=audio.astype(np.float32).tobytes(), capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        log.warning("Tempo und Lautstärke nicht anwendbar (%s), spreche unverändert", e)
        return audio
    return np.frombuffer(out.stdout, dtype=np.float32)


# --- Dienst ----------------------------------------------------------------------------

_TYPNAME = {str: "eine Zeichenkette", float: "eine Zahl", bool: "true oder false"}


def _feld(anfrage: dict, name: str, typ: type, vorgabe):
    """Feld einer Anfrage mit Typpruefung; fehlt es oder ist es null, gilt die Vorgabe.
    TypeError bei falschem Typ, ValueError bei einer Zahl jenseits von float."""
    wert = anfrage.get(name)
    if wert is None:
        return vorgabe
    if typ is float:
        # bool ist in Python ein int; true als Tempo waere 1.0
        if isinstance(wert, (int, float)) and not isinstance(wert, bool):
            try:
                return float(wert)
            except OverflowError:
                raise ValueError(f"{name} ist zu groß") from None
    elif isinstance(wert, typ):
        return wert
    raise TypeError(f"{name} muss {_TYPNAME[typ]} sein")


@dataclass
class Auftrag:
    text: str
    stimme: str
    tempo: float
    mit_atem: bool
    runde: int
    lauter: float = 0.0
    quelle: str = ""  # Kennung des Aufrufers, etwa eine Sitzung; leer = ohne Zuordnung
    ansage: str = ""  # wird vorangestellt, wenn zuletzt eine andere Quelle sprach
    eingang: float = field(default_factory=time.monotonic)
    fertig: threading.Event = field(default_factory=threading.Event)
    abbruch: threading.Event = field(default_factory=threading.Event)
    # Zeiten dieses Auftrags fuer --warten; bleibt so, wenn er vor dem Sprechen endet
    ergebnis: dict = field(default_factory=lambda: {"abgebrochen": True})
    # Mit --liefern die Verbindung des Aufrufers: Der Ton geht dorthin statt in den
    # Lautsprecher, damit ein anderes Geraet ihn abspielen kann
    ziel: socket.socket | None = None

    def vorbei(self, runde: int) -> bool:
        return self.runde != runde or self.abbruch.is_set()


class Dienst:
    def __init__(self, pfad: Path, leerlauf: float):
        self.pfad = pfad
        self.leerlauf = leerlauf
        self.auftraege: queue.Queue[Auftrag] = queue.Queue()
        self.runde = 0  # --stopp zaehlt hoch; aeltere Auftraege werden verworfen
        self.zustand = "lädt"
        self.fehler = ""
        self.ladezeit = 0.0
        self.letzter: dict = {}
        self.spricht = False
        self.aktiv = time.monotonic()
        self.ende = threading.Event()
        self.player = None
        self.aktuell: Auftrag | None = None
        self.letzte_quelle = ""  # Quelle des zuletzt hoerbar gesprochenen Auftrags
        self._gestoppt: dict[str, float] = {}  # Quelle -> Zeitpunkt ihres letzten Stopps
        # Stopp kommt aus einem Verbindungs-Thread, Wiedergabe laeuft im Sprecher-Thread;
        # ohne Sperre schliessen beide denselben Stream (AttributeError in stop_stream).
        # Jeder Zugriff, der den Stream startet oder schliesst, laeuft deshalb darunter.
        self._player_sperre = threading.Lock()

    # Netz
    def laufen(self) -> int:
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        # Die Sperre gehoert dem laufenden Dienst, solange er lebt; der Kernel gibt sie beim
        # Prozessende frei. Ein zweiter Start (zwei Aufrufer gleichzeitig) endet hier, und
        # ein liegengebliebener Socket ist ohne Sperre sicher verwaist. Die Datei haengt an
        # self, weil CPython den Deskriptor sonst per Refcount schliesst und die Sperre verliert.
        self._sperre = open(self.pfad.with_suffix(".lock"), "w")
        try:
            fcntl.flock(self._sperre, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._sperre.close()
            log.info("Dienst läuft schon: %s", self.pfad)
            return 0
        server = None
        try:
            # Im try, damit ein Fehler beim Aufbau (Pfad zu lang, Sandbox) Socket und Sperre
            # ebenfalls freigibt
            self.pfad.unlink(missing_ok=True)
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            alt = os.umask(0o077)
            try:
                server.bind(str(self.pfad))
            finally:
                os.umask(alt)
            server.listen(8)
            server.settimeout(1.0)
            # signal.signal geht nur im Hauptthread; eingebettet in einem Thread (etwa in den
            # Tests) beendet der Aufrufer den Dienst ueber ende.set() oder {"cmd": "beenden"}
            if threading.current_thread() is threading.main_thread():
                signal.signal(signal.SIGTERM, lambda *_: self.ende.set())
            log.info("Dienst lauscht auf %s", self.pfad)

            threading.Thread(target=self._sprecher, daemon=True).start()
            while not self.ende.is_set():
                try:
                    conn, _ = server.accept()
                except TimeoutError:
                    if self._leerlauf_vorbei():
                        log.info("%d s ohne Auftrag, Dienst endet", self.leerlauf)
                        break
                    continue
                threading.Thread(target=self._verbindung, args=(conn,), daemon=True).start()
        finally:
            if server is not None:
                server.close()
            self.pfad.unlink(missing_ok=True)
            if self.player is not None:
                self.player.flush()
            # Erst nach dem Entfernen des Sockets: Solange die Sperre gilt, startet kein
            # zweiter Dienst, der den Socket noch vorfaende
            self._sperre.close()
        return 0

    def _leerlauf_vorbei(self) -> bool:
        return (not self.spricht and self.auftraege.empty()
                and time.monotonic() - self.aktiv > self.leerlauf)

    def _verbindung(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(10)
            try:
                anfrage = json.loads(_zeile_lesen(conn))
                antwort = self._bearbeiten(anfrage, conn)
                if antwort is None:  # --liefern: Kopfzeile und Ton sind schon gesendet
                    return
            except (ValueError, OSError) as e:
                antwort = {"ok": False, "fehler": f"Ungültige Anfrage: {e}"}
            except Exception as e:  # der Aufrufer soll eine Antwort bekommen, kein leeres {}
                log.exception("Anfrage gescheitert")
                antwort = {"ok": False, "fehler": f"Interner Fehler: {e}"}
            try:
                conn.sendall((json.dumps(antwort, ensure_ascii=False) + "\n").encode())
            except OSError:
                pass

    def _bearbeiten(self, anfrage: dict, conn: socket.socket | None = None) -> dict | None:
        if not isinstance(anfrage, dict):
            return {"ok": False, "fehler": "Anfrage muss ein JSON-Objekt sein"}
        cmd = anfrage.get("cmd")
        if cmd == "status":
            return {"ok": True, "zustand": self.zustand, "fehler": self.fehler,
                    "ladezeit_s": round(self.ladezeit, 1), "spricht": self.spricht,
                    "warteschlange": self.auftraege.qsize(), "letzter_auftrag": self.letzter}
        if cmd == "stopp":
            try:
                quelle = _feld(anfrage, "quelle", str, "")
            except TypeError as e:
                return {"ok": False, "fehler": str(e)}
            self._stoppen(quelle)
            return {"ok": True}
        if cmd == "beenden":
            self._stoppen()
            self.ende.set()
            return {"ok": True}
        if cmd != "sprich":
            return {"ok": False, "fehler": f"Unbekannter Befehl: {cmd}"}
        if self.zustand == "fehler":
            return {"ok": False, "fehler": self.fehler}
        # Erst die Typen: str() machte aus null den gesprochenen Text "None", bool() aus
        # "false" ein True, und float() auf eine riesige Zahl warf OverflowError
        try:
            text = _feld(anfrage, "text", str, "").strip()
            stimme = _feld(anfrage, "stimme", str, "") or qwen.DEFAULT_VOICE
            tempo = _feld(anfrage, "tempo", float, DEFAULT_TEMPO)
            lauter = _feld(anfrage, "lauter", float, 0.0)
            quelle = _feld(anfrage, "quelle", str, "")
            ansage = _feld(anfrage, "ansage", str, "").strip()
            mit_atem = _feld(anfrage, "mit_atem", bool, False)
            warten = _feld(anfrage, "warten", bool, False)
            liefern = _feld(anfrage, "liefern", bool, False)
        except (TypeError, ValueError) as e:
            return {"ok": False, "fehler": str(e)}
        if liefern and (warten or conn is None):
            return {"ok": False, "fehler": "liefern geht nicht zusammen mit warten"}
        if not text:
            return {"ok": False, "fehler": "Kein Text"}
        if stimme not in stimmen():
            return {"ok": False, "fehler": f"Unbekannte Stimme: {stimme}"}
        if not 0.5 <= tempo <= 2.0:
            return {"ok": False, "fehler": "Tempo muss zwischen 0.5 und 2.0 liegen"}
        if not 0.0 <= lauter <= MAX_LAUTER:
            return {"ok": False, "fehler": f"Lauter muss zwischen 0 und {MAX_LAUTER:g} dB liegen"}
        # Nur ein Auftrag zählt als Aktivität. Status und Stopp nicht: Der Hook für
        # Claude Code stoppt auch in Sitzungen ohne Gesprächsmodus, mit
        # SPRECHEN_UNTERBRECHEN=1 bei jeder Eingabe, und hielte den Dienst samt Modell
        # sonst unbegrenzt am Leben
        self.aktiv = time.monotonic()
        auftrag = Auftrag(text=text, stimme=stimme, tempo=tempo, mit_atem=mit_atem,
                          runde=self.runde, lauter=lauter, quelle=quelle, ansage=ansage,
                          ziel=conn if liefern else None)
        if liefern:
            return self._liefern(auftrag, conn)
        self.auftraege.put(auftrag)
        if warten:
            while not auftrag.fertig.wait(1.0):
                if self.ende.is_set():
                    break
            return {"ok": True, "auftrag": auftrag.ergebnis}
        return {"ok": True, "warteschlange": self.auftraege.qsize()}

    def _liefern(self, auftrag: Auftrag, conn: socket.socket) -> None:
        """Kopfzeile senden, Auftrag einreihen und die Verbindung offen halten, bis der
        Sprecher den Ton gesendet hat. Danach schliesst _verbindung sie, und der Aufrufer
        erkennt am Dateiende, dass nichts mehr kommt."""
        kopf = {"ok": True, "format": "s16le", "rate": qwen.SAMPLE_RATE, "kanaele": 1}
        try:
            conn.sendall((json.dumps(kopf) + "\n").encode())
        except OSError:
            return None
        # Ein Stueck Audio kann laenger dauern als die 10 s fuer Anfragen, und sendall
        # wartet, solange der Aufrufer nicht liest
        conn.settimeout(LIEFERN_TIMEOUT)
        self.auftraege.put(auftrag)
        while not auftrag.fertig.wait(1.0):
            if self.ende.is_set():
                break
        return None

    def _stoppen(self, quelle: str = "") -> None:
        """Ausgabe abbrechen. Mit quelle nur die Auftraege dieses Aufrufers, sonst alle:
        Laufen mehrere Sitzungen nebeneinander, soll ein Stopp in der einen nicht die
        Antwort der anderen abschneiden."""
        # Alles unter der Player-Sperre: Der Sprecher reiht Audio nur unter ihr ein und
        # prueft dabei, ob sein Auftrag vorbei ist. Ohne sie konnte der Sprecher zwischen
        # Markieren und flush den naechsten Auftrag beginnen, und der flush traf dessen Ton
        with self._player_sperre:
            if quelle:
                # Zeitpunkt zuerst: Ein Auftrag, den der Sprecher schon aus der Warteschlange
                # genommen, aber noch nicht als aktuell gesetzt hat, faende sonst keine der
                # beiden Pruefungen darunter; _uebernehmen vergleicht mit diesem Zeitpunkt
                self._gestoppt[quelle] = time.monotonic()
                with self.auftraege.mutex:
                    for wartend in self.auftraege.queue:
                        if wartend.quelle == quelle:
                            wartend.abbruch.set()
                aktuell = self.aktuell
                if aktuell is None or aktuell.quelle != quelle:
                    return
                aktuell.abbruch.set()
            else:
                self.runde += 1
                while True:
                    try:
                        self.auftraege.get_nowait().fertig.set()
                    except queue.Empty:
                        break
                aktuell = self.aktuell
            if aktuell is not None and aktuell.ziel is not None:
                # Mit --liefern kann der Sprecher in sendall haengen, wenn der Aufrufer nicht
                # mehr liest (Netz weg). Das Flag allein saehe er erst nach LIEFERN_TIMEOUT;
                # shutdown laesst sendall sofort scheitern
                try:
                    aktuell.ziel.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            if self.player is not None:
                self.player.flush()

    def _uebernehmen(self, auftrag: Auftrag) -> bool:
        """Auftrag aus der Warteschlange als aktuell setzen; False, wenn er schon gestoppt ist."""
        # Erst setzen, dann pruefen: Ein Stopp fuer diese Quelle sieht den Auftrag dann
        # als aktuell, oder sein Zeitpunkt steht schon in _gestoppt
        self.aktuell = auftrag
        if auftrag.quelle and auftrag.eingang <= self._gestoppt.get(auftrag.quelle, -1.0):
            auftrag.abbruch.set()
        if auftrag.vorbei(self.runde):
            self.aktuell = None
            auftrag.fertig.set()
            return False
        return True

    # Sprechen
    def _sprecher(self) -> None:
        start = time.monotonic()
        try:
            # Schwere Importe erst hier: Der Socket steht dann schon, und der Aufrufer
            # muss nicht auf das Laden warten
            from mlx_audio.tts.audio_player import AudioPlayer
            from mlx_audio.tts.utils import load_model
            from mlx_audio.utils import load_audio

            model = load_model(qwen.MODEL)
            from atem import attenuate
        except Exception as e:  # jeder Ladefehler soll beim Aufrufer ankommen
            self.zustand, self.fehler = "fehler", f"Modell nicht ladbar: {e}"
            log.error("%s", self.fehler)
            self._stoppen()
            return
        self.ladezeit = time.monotonic() - start
        self.player = AudioPlayer(sample_rate=qwen.SAMPLE_RATE)
        self.zustand = "bereit"
        log.info("Modell geladen in %.1f s", self.ladezeit)

        refs: dict[str, tuple] = {}
        while not self.ende.is_set():
            try:
                auftrag = self.auftraege.get(timeout=1.0)
            except queue.Empty:
                continue
            if not self._uebernehmen(auftrag):
                continue
            self.spricht = True
            try:
                if auftrag.stimme not in refs:
                    refs[auftrag.stimme] = (
                        load_audio(str(qwen.VOICES_DIR / f"{auftrag.stimme}.wav"),
                                   sample_rate=qwen.SAMPLE_RATE),
                        (qwen.VOICES_DIR / f"{auftrag.stimme}.txt").read_text(
                            encoding="utf-8").strip())
                auftrag.text = text_mit_ansage(auftrag, self.letzte_quelle)
                self._sprechen(model, auftrag, *refs[auftrag.stimme],
                               None if auftrag.mit_atem else attenuate)
                if auftrag.ergebnis.get("audio_s"):
                    self.letzte_quelle = auftrag.quelle
            except Exception as e:
                # Ohne das endete der Sprecher-Thread, etwa wenn kein Ausgabegeraet da ist,
                # und der Dienst naehme weiter Auftraege an, ohne je zu sprechen
                log.exception("Auftrag gescheitert")
                auftrag.ergebnis = {"abgebrochen": True, "fehler": str(e)}
                with self._player_sperre:
                    try:
                        self.player.flush()
                    except Exception:
                        log.exception("Player nicht zurückgesetzt")
            finally:
                self.aktuell = None
                self.spricht = False
                self.aktiv = time.monotonic()
                auftrag.fertig.set()

    def _sprechen(self, model, auftrag: Auftrag, ref_audio, ref_text: str, attenuate) -> None:
        plan = stuecke(auftrag.text)
        erster_ton = None
        rechnen = atem = audio_s = 0.0
        ausgelassen = 0
        for satz, absatzende in plan:
            if auftrag.vorbei(self.runde):
                break
            t = time.monotonic()
            audio = None
            for _ in range(qwen.MAX_ATTEMPTS):
                audio = qwen.synthesize_chunk(model, satz, ref_audio, ref_text)
                if audio is not None:
                    break
            rechnen += time.monotonic() - t
            if audio is None:
                ausgelassen += 1
                log.error("Stück ausgelassen: %.80s", satz)
                continue
            if attenuate is not None:
                t = time.monotonic()
                audio, _ = attenuate(audio, qwen.SAMPLE_RATE)
                atem += time.monotonic() - t
            audio = nachbearbeiten(audio, auftrag.tempo, auftrag.lauter)
            pause = PAUSE_ABSATZ if absatzende else PAUSE_SATZ
            audio = np.concatenate([audio, np.zeros(int(qwen.SAMPLE_RATE * pause), np.float32)])
            if auftrag.ziel is not None:
                # Ton an den Aufrufer statt in den Lautsprecher. Bricht dessen Verbindung
                # ab (Player beendet, Netz weg), endet der Auftrag hier
                if auftrag.vorbei(self.runde) or not _pcm_senden(auftrag.ziel, audio):
                    auftrag.abbruch.set()
                    break
            else:
                # Pruefen und Einreihen unter der Sperre, sonst landet nach einem Stopp noch
                # ein Stueck im Puffer
                with self._player_sperre:
                    if auftrag.vorbei(self.runde):
                        break
                    self.player.queue_audio(audio)
            audio_s += len(audio) / qwen.SAMPLE_RATE
            if erster_ton is None:
                erster_ton = time.monotonic() - auftrag.eingang
        if auftrag.ziel is None:
            # Ein kurzer Auftrag erreicht die Puffergrenze des Players nie, dann startet
            # erst wait_for_drain den Stream. Das geschieht hier unter der Sperre: Ohne sie
            # schloss ein gleichzeitiger Stopp den Stream mitten im Start (AttributeError)
            with self._player_sperre:
                if (not auftrag.vorbei(self.runde) and not self.player.playing
                        and self.player.buffered_samples() > 0):
                    self.player.start_stream()
            if not auftrag.vorbei(self.runde):
                self.player.wait_for_drain()
            with self._player_sperre:
                self.player.stop_stream()
        auftrag.ergebnis = self.letzter = {
            "stuecke": len(plan), "ausgelassen": ausgelassen,
            "erster_ton_s": round(erster_ton or 0.0, 2),
            "rechenzeit_s": round(rechnen, 2), "atem_s": round(atem, 2),
            "audio_s": round(audio_s, 1), "abgebrochen": auftrag.vorbei(self.runde),
            "geliefert": auftrag.ziel is not None}
        log.info("Auftrag: %s", json.dumps(self.letzter, ensure_ascii=False))


def pcm(audio: np.ndarray) -> bytes:
    """float32 im Bereich -1 bis 1 als 16-Bit-PCM, little endian, wie es Player erwarten."""
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def _pcm_senden(conn: socket.socket, audio: np.ndarray) -> bool:
    try:
        conn.sendall(pcm(audio))
        return True
    except OSError as e:
        log.info("Aufrufer nimmt keinen Ton mehr an (%s), Auftrag endet", e)
        return False


# --- Aufrufer --------------------------------------------------------------------------

def _zeile_lesen(conn: socket.socket) -> str:
    daten = b""
    while not daten.endswith(b"\n"):
        teil = conn.recv(65536)
        if not teil:
            break
        daten += teil
        if len(daten) > MAX_ANFRAGE:
            raise ValueError("Anfrage zu groß")
    return daten.decode("utf-8")


def _erreichbar(pfad: Path) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(str(pfad))
        return True
    except OSError:
        return False


def senden(anfrage: dict, timeout: float | None = 10.0) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(str(socket_pfad()))
        s.sendall((json.dumps(anfrage, ensure_ascii=False) + "\n").encode())
        return json.loads(_zeile_lesen(s) or "{}")


def empfangen(anfrage: dict, ausgabe) -> int:
    """Auftrag mit liefern senden und den Ton nach ausgabe schreiben, bis der Dienst die
    Verbindung schliesst. Gedacht fuer einen Aufruf ueber ssh, dessen stdout ein Player auf
    einem anderen Geraet liest."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(str(socket_pfad()))
        s.sendall((json.dumps({**anfrage, "liefern": True}, ensure_ascii=False) + "\n").encode())
        # Kopfzeile von Hand lesen: _zeile_lesen liest in grossen Stuecken und verschluckte
        # sonst den Anfang des Tons, der direkt hinter dem Zeilenende folgt
        puffer = b""
        while b"\n" not in puffer:
            teil = s.recv(65536)
            if not teil:
                break
            puffer += teil
        kopf, _, ton = puffer.partition(b"\n")
        antwort = json.loads(kopf or b"{}")
        if not antwort.get("ok"):
            log.error("%s", antwort.get("fehler", "unbekannter Fehler"))
            return 1
        try:
            # Was hinter der Kopfzeile schon mitkam, zuerst; dann lesen bis zum Ende. Meist
            # kommt die Kopfzeile allein, der erste Ton erst Sekunden spaeter
            if ton:
                ausgabe.write(ton)
                ausgabe.flush()
            while teil := s.recv(65536):
                ausgabe.write(teil)
                ausgabe.flush()
        except BrokenPipeError:
            # Der Player wurde beendet, etwa durch einen Stopp; der Dienst merkt es am
            # geschlossenen Socket und bricht den Auftrag ab. stdout auf /dev/null: Sonst
            # leert Python es beim Beenden erneut, meldet "Exception ignored" und endet mit
            # Exit 120 (Rezept aus der Python-Doku zu SIGPIPE)
            try:
                os.dup2(os.open(os.devnull, os.O_WRONLY), ausgabe.fileno())
            except (OSError, ValueError):  # ausgabe ohne Deskriptor, etwa in Tests
                pass
            return 0
    return 0


def datei_schreiben(anfrage: dict) -> Path | None:
    """Ton wie mit --liefern holen und als MP3 in DATEI_ORDNER ablegen, ohne ffmpeg als WAV.
    Gedacht für Oberflächen, die eine Audiodatei in der Antwort abspielen, etwa auf dem
    Handy. Dateien älter als DATEI_ALTER löscht dieser Aufruf; None, wenn kein Ton kam."""
    puffer = io.BytesIO()
    if empfangen(anfrage, puffer) != 0:
        return None
    pcm = puffer.getvalue()
    if not pcm:
        log.error("Kein Ton geliefert")
        return None
    DATEI_ORDNER.mkdir(parents=True, exist_ok=True)
    grenze = time.time() - DATEI_ALTER
    for alt in DATEI_ORDNER.glob("sprechen-*"):
        try:
            if alt.stat().st_mtime < grenze:
                alt.unlink(missing_ok=True)
        except FileNotFoundError:
            pass  # ein zweiter Aufruf war schneller
    name = f"sprechen-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    ziel = DATEI_ORDNER / f"{name}.mp3"
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(qwen.SAMPLE_RATE),
                        "-ac", "1", "-i", "pipe:0", "-b:a", "64k", "-y", str(ziel)],
                       input=pcm, capture_output=True, check=True)
        return ziel
    except (OSError, subprocess.CalledProcessError) as e:
        log.warning("Kein MP3 (%s), lege WAV ab", e)
        ziel.unlink(missing_ok=True)  # ein abgebrochenes ffmpeg hinterlässt sonst ein halbes MP3
    ziel = ziel.with_suffix(".wav")
    with wave.open(str(ziel), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(qwen.SAMPLE_RATE)
        w.writeframes(pcm)
    return ziel


def dienst_starten() -> bool:
    """Dienst im Hintergrund starten, falls er nicht laeuft; True, sobald er erreichbar ist."""
    pfad = socket_pfad()
    if _erreichbar(pfad):
        return True
    DEFAULT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(DEFAULT_LOG, "a", encoding="utf-8") as logdatei:
        subprocess.Popen([sys.executable, str(SCRIPT), "--dienst"], stdin=subprocess.DEVNULL,
                         stdout=logdatei, stderr=logdatei, start_new_session=True,
                         env={**os.environ, "HF_HUB_VERBOSITY": "error"})
    frist = time.monotonic() + START_WARTEN
    while time.monotonic() < frist:
        if _erreichbar(pfad):
            return True
        time.sleep(0.2)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Qwen3-TTS-Sprechdienst: Text sofort sprechen")
    parser.add_argument("text", nargs="?", help="zu sprechender Text; fehlt er oder ist er -, "
                                                "kommt er von stdin")
    parser.add_argument("-v", "--stimme", default=qwen.DEFAULT_VOICE,
                        help=f"Stimme aus stimmen/ (Standard: {qwen.DEFAULT_VOICE})")
    parser.add_argument("-t", "--tempo", type=float, default=DEFAULT_TEMPO,
                        help=f"Sprechtempo 0.5 bis 2.0 (Standard: {DEFAULT_TEMPO})")
    # Ohne Kurzform: -l heisst in vorlesen.sh --liste
    parser.add_argument("--lauter", type=float, default=0.0, metavar="DB",
                        help=f"Stimme um 0 bis {MAX_LAUTER:g} dB lauter, mit Limiter "
                             "(Standard: 0; gegen Musik im Hintergrund etwa 8)")
    parser.add_argument("--mit-atem", action="store_true", help="Atemgeräusche nicht absenken")
    parser.add_argument("--warten", action="store_true",
                        help="erst zurückkehren, wenn der Text gesprochen ist, und Zeiten zeigen")
    parser.add_argument("--liefern", action="store_true",
                        help="Ton nicht abspielen, sondern als 16-Bit-PCM (24 kHz, mono) nach "
                             "stdout schreiben, etwa für einen Player auf einem anderen Gerät")
    parser.add_argument("--datei", action="store_true",
                        help="Ton nicht abspielen, sondern als MP3 (ohne ffmpeg als WAV) unter "
                             f"{DATEI_ORDNER} ablegen und den Pfad ausgeben")
    gruppe = parser.add_mutually_exclusive_group()
    gruppe.add_argument("--stopp", action="store_true", help="Ausgabe abbrechen, Warteschlange leeren")
    gruppe.add_argument("--status", action="store_true", help="Zustand des Dienstes zeigen")
    gruppe.add_argument("--beenden", action="store_true", help="Dienst beenden")
    gruppe.add_argument("--dienst", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--quelle", default="",
                        help="Kennung des Aufrufers, etwa eine Sitzung; --stopp mit --quelle "
                             "bricht nur deren Aufträge ab")
    parser.add_argument("--ansage", default="",
                        help="mit --quelle: Satz, der vorangestellt wird, wenn zuletzt eine "
                             "andere Quelle sprach, etwa \"Aus Projekt X.\"")
    parser.add_argument("--leerlauf", type=float, default=LEERLAUF, help=argparse.SUPPRESS)
    args = parser.parse_args()

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.INFO)

    if args.dienst:
        return Dienst(socket_pfad(), args.leerlauf).laufen()

    if args.stopp or args.status or args.beenden:
        if not _erreichbar(socket_pfad()):
            if args.status:
                print(json.dumps({"ok": True, "zustand": "aus"}))
            return 0
        cmd = "stopp" if args.stopp else "status" if args.status else "beenden"
        antwort = senden({"cmd": cmd, "quelle": args.quelle})
        if args.status:
            print(json.dumps(antwort, ensure_ascii=False, indent=2))
        return 0 if antwort.get("ok") else 1

    if args.liefern + args.warten + args.datei > 1:
        log.error("--warten, --liefern und --datei schließen sich aus")
        return 1
    if not 0.5 <= args.tempo <= 2.0:
        log.error("Tempo %s liegt nicht zwischen 0.5 und 2.0", args.tempo)
        return 1
    if not 0.0 <= args.lauter <= MAX_LAUTER:
        log.error("Lauter %s liegt nicht zwischen 0 und %g dB", args.lauter, MAX_LAUTER)
        return 1
    if args.stimme not in stimmen():
        log.error("Unbekannte Stimme: %s (vorhanden: %s)", args.stimme, ", ".join(stimmen()))
        return 1
    text = sys.stdin.read() if args.text in (None, "-") else args.text
    if not text.strip():
        log.error("Kein Text")
        return 1
    try:
        gestartet = dienst_starten()
    except OSError as e:
        log.error("Dienst nicht startbar: %s", e)
        return 1
    if not gestartet:
        log.error("Dienst nicht erreichbar, siehe %s", DEFAULT_LOG)
        return 1
    anfrage = {"cmd": "sprich", "text": text, "stimme": args.stimme, "tempo": args.tempo,
               "lauter": args.lauter, "quelle": args.quelle, "ansage": args.ansage,
               "mit_atem": args.mit_atem}
    if args.liefern:
        try:
            return empfangen(anfrage, sys.stdout.buffer)
        except (OSError, ValueError) as e:
            log.error("Dienst antwortet nicht: %s", e)
            return 1
    if args.datei:
        try:
            pfad = datei_schreiben(anfrage)
        except (OSError, ValueError) as e:
            log.error("Datei nicht erzeugt: %s", e)
            return 1
        if pfad is None:
            return 1
        print(pfad)
        return 0
    try:
        antwort = senden({**anfrage, "warten": args.warten},
                         timeout=None if args.warten else 10.0)
    except OSError as e:
        log.error("Dienst antwortet nicht: %s", e)
        return 1
    if not antwort.get("ok"):
        log.error("%s", antwort.get("fehler", "unbekannter Fehler"))
        return 1
    if args.warten:
        print(json.dumps(antwort.get("auftrag", {}), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
