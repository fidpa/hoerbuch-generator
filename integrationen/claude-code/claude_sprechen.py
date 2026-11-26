"""
claude_sprechen.py - Claude-Code-Hooks für gesprochene Antworten über den Sprechdienst

Verbindet Claude Code mit dem Sprechdienst dieses Repos (sprechen.sh). Spricht nur, was
Claude ausdrücklich zum Sprechen markiert, nicht die ganze Antwort: Tabellen, Code und Pfade
lassen sich nicht vorlesen. Die Markierung schreibt Claude im Gesprächsmodus (/sprechen,
siehe sprechen.md daneben) als HTML-Kommentar ans Ende der Antwort:

    <!-- sprechen: Gesprochene Fassung der Antwort in ganzen Sätzen. -->

Usage (als Hook, Eingabe ist das Hook-JSON auf stdin; Einrichtung: README.md daneben):
    .venv/bin/python integrationen/claude-code/claude_sprechen.py stop     Marke sprechen
    .venv/bin/python integrationen/claude-code/claude_sprechen.py prompt   Ausgabe abbrechen

Einstellungen über Umgebungsvariablen:
    SPRECHEN_STIMME  Stimme aus stimmen/ (Standard: marketing, ein ruhiger Gesprächston)
    SPRECHEN_TEMPO   Sprechtempo 0.5 bis 2.0 (Standard: 1.1)
    SPRECHEN_LAUTER  Anhebung in dB, 0 bis 15 (Standard: 8). Die Stimmen liegen bei rund
                     -21 LUFS; 8 dB mit Limiter bringen sie auf rund -14 LUFS, so laut wie
                     Musik bei Streamingdiensten, damit sie daneben hörbar bleiben.

Mehrere Sitzungen: Beide Hooks geben die session_id als --quelle mit, eine Eingabe bricht
also nur die Ausgabe der eigenen Sitzung ab. Dazu kommt „Aus <Projekt>.“ als --ansage; der
Dienst spricht sie nur, wenn zuletzt eine andere Sitzung sprach. UserPromptSubmit feuert auch
bei Berichten von Hintergrund-Agenten; die brechen die Ausgabe ihrer Sitzung ebenfalls ab.

Hooks laufen außerhalb einer Bash-Sandbox; nur dort stehen Metal und Audio zur Verfügung.
Fehler gehen nach stderr und brechen die Sitzung nie ab (Exit 0). Nur Standardbibliothek.
"""

# Ein Hook-Eintrag mit dem System-Python (3.9 auf macOS) scheiterte sonst schon beim
# Laden an "str | None"; das Skript selbst braucht nur die Standardbibliothek
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MARKE = re.compile(r"<!--\s*sprechen\s*:(.*?)-->", re.DOTALL | re.IGNORECASE)
STIMME = "marketing"
TEMPO = "1.1"
LAUTER = "8"
TIMEOUT = 30  # Sekunden; sprechen.sh kehrt nach dem Annehmen des Auftrags zurück

log = logging.getLogger("claude_sprechen")


def gesprochener_text(antwort: str) -> str:
    """Inhalt der letzten Sprechmarke, Leerraum zusammengezogen; leer ohne Marke."""
    treffer = MARKE.findall(antwort or "")
    return " ".join(treffer[-1].split()) if treffer else ""


def ansage(eingabe: dict) -> str:
    """„Aus <Projekt>.“ für den Sprechdienst, der sie nur beim Wechsel der Sitzung spricht.
    Projekt ist der letzte Teil von CLAUDE_PROJECT_DIR, das Claude Code den Hooks setzt;
    das cwd der Eingabe kann nach einem cd ein Unterordner sein."""
    ordner = os.environ.get("CLAUDE_PROJECT_DIR") or str(eingabe.get("cwd") or "")
    name = re.sub(r"[-_.]+", " ", Path(ordner).name).strip() if ordner else ""
    return f"Aus {name[:1].upper()}{name[1:]}." if name else ""


def sprechen_sh() -> Path:
    # HOERBUCH_GENERATOR nur für Tests und abweichende Aufstellungen; sonst dieses Repo
    return Path(os.environ.get("HOERBUCH_GENERATOR", REPO)) / "sprechen.sh"


def aufrufen(args: list[str], text: str | None = None) -> int:
    skript = sprechen_sh()
    if not skript.is_file():
        log.error("sprechen.sh fehlt: %s", skript)
        return 1
    try:
        lauf = subprocess.run(["/bin/bash", str(skript), *args], input=text or "", text=True,
                              capture_output=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.error("sprechen.sh scheiterte: %s", e)
        return 1
    if lauf.returncode != 0:
        log.error("sprechen.sh: %s", lauf.stderr.strip())
    return lauf.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude-Code-Hooks für den Sprechdienst")
    parser.add_argument("ereignis", choices=["stop", "prompt"])
    try:
        args = parser.parse_args()
    except SystemExit:
        # argparse endet bei falschem Argument mit Exit 2, und Exit 2 bei UserPromptSubmit
        # verwirft jede Eingabe. Ein Tippfehler im Hook-Eintrag (etwa "Stop") darf das nicht
        return 0
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="claude_sprechen: %(message)s")

    try:
        eingabe = json.load(sys.stdin)
    except ValueError:
        eingabe = {}
    if not isinstance(eingabe, dict):
        eingabe = {}

    # Hooks gelten meist global. Ohne Sitzungskennung bräche eine Eingabe in einer zweiten
    # Sitzung die Antwort der ersten ab
    quelle = ["--quelle", str(eingabe["session_id"])] if eingabe.get("session_id") else []

    if args.ereignis == "prompt":
        aufrufen(["--stopp", *quelle])
        return 0

    text = gesprochener_text(str(eingabe.get("last_assistant_message", "")))
    if text:
        name = ansage(eingabe) if quelle else ""
        aufrufen(["-v", os.environ.get("SPRECHEN_STIMME", STIMME),
                  "-t", os.environ.get("SPRECHEN_TEMPO", TEMPO),
                  "--lauter", os.environ.get("SPRECHEN_LAUTER", LAUTER), *quelle,
                  *(["--ansage", name] if name else []), "-"], text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
