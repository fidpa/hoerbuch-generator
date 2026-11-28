"""
claude_sprechen.py - Claude-Code-Hooks für gesprochene Antworten über den Sprechdienst

Verbindet Claude Code mit dem Sprechdienst dieses Repos (sprechen.sh). Spricht nur, was
Claude ausdrücklich zum Sprechen markiert, nicht die ganze Antwort: Tabellen, Code und Pfade
lassen sich nicht vorlesen. Die Markierung schreibt Claude im Gesprächsmodus (/sprechen,
siehe sprechen.md daneben) als HTML-Kommentar ans Ende der Antwort:

    <!-- sprechen: Gesprochene Fassung der Antwort in ganzen Sätzen. -->

Usage (als Hook, Eingabe ist das Hook-JSON auf stdin; Einrichtung: README.md daneben):
    .venv/bin/python integrationen/claude-code/claude_sprechen.py stop     Marke sprechen
    .venv/bin/python integrationen/claude-code/claude_sprechen.py prompt   Stoppwort erkennen
    .venv/bin/python integrationen/claude-code/claude_sprechen.py start    Modus von Anfang an
    .venv/bin/python integrationen/claude-code/claude_sprechen.py notification  Ansage beim Warten
    .venv/bin/python integrationen/claude-code/claude_sprechen.py pruefen  Einrichtung prüfen

Was die Hooks tun, wann sie stumm bleiben und wie Fernbetrieb und Gerätewahl zusammenspielen,
steht in README.md daneben; hier nur das Nötigste zum Lesen des Codes:

- Den Modus je Sitzung (an, aus, datei) hält eine Datei unter XDG_RUNTIME_DIR (sonst ~/.cache)
  fest. Der Prompt-Hook schreibt sie bei /sprechen, der SessionStart-Hook beim ersten Start der
  Sitzung, nach einem Fork aus dem Transkript. Ohne Datei gilt das Transkript.
- Stop im Modus an ohne Sprechmarke spricht ERSATZ und schreibt eine Zeile in wiedergabe.log,
  außer die Sitzung pausiert nur (pausiert).
- Stop- und Prompt-Hook geben die session_id als --quelle mit, ein Stopp trifft die eigene
  Sitzung. Ein Stoppwort ohne eigene Ausgabe trifft, was gerade klingt (ausgabe_stoppen).
- Mit SPRECHEN_ENTFERNT oder SPRECHEN_GERAETE läuft die Wiedergabe in einem Hintergrundprozess
  (abspielen), damit der Stop-Hook sofort zurückkehrt. Sperren: wiedergabe.lock hier für die
  Sitzungen dieses Geräts, player.lock auf dem abspielenden Gerät (FERN_PLAYER).
- pruefen ist kein Hook, sondern ein Befehl für das Terminal: Er liest die Hook-Einträge aus
  ~/.claude/settings.json und meldet je Gerät, was fehlt (Exit 1).

Einstellungen über Umgebungsvariablen:
    SPRECHEN_STIMME  Stimme aus stimmen/ (Standard: marketing, ein ruhiger Gesprächston)
    SPRECHEN_TEMPO   Sprechtempo 0.5 bis 2.0 (Standard: 1.1)
    SPRECHEN_LAUTER  Anhebung in dB, 0 bis 15 (Standard: 8). Die Stimmen liegen bei rund
                     -21 LUFS; 8 dB mit Limiter bringen sie auf rund -14 LUFS, so laut wie
                     Musik bei Streamingdiensten, damit sie daneben hörbar bleiben.
    SPRECHEN_UNTERBRECHEN  1: jede neue Eingabe bricht die laufende Ausgabe ab (bis v0.6.1
                     das Verhalten ohne Einstellung)
    SPRECHEN_AUS     1: alle Hooks tun nichts, für Dienste, die Claude ohne Nutzer starten
                     (Bots, zeitgesteuerte Läufe) und dabei die Einstellungen des Nutzers laden.
                     Kein Modus von Anfang an, kein Ton, kein Stoppwort; die Eingabe geht
                     unverändert an Claude
    SPRECHEN_ENTFERNT       ssh-Ziel eines Macs, der rechnet (sprechen.sh --liefern); der Ton
                            spielt hier
    SPRECHEN_ENTFERNT_REPO  Ort dieses Repos dort (Standard: derselbe Pfad unter ~ wie hier)
    SPRECHEN_PLAYER         Player-Befehl, der 16-Bit-PCM (24 kHz, mono) von stdin spielt
                            (Standard: der erste aus PLAYER)
    SPRECHEN_GERAETE   ssh-Ziele oder "hier", durch Leerzeichen getrennt; der Ton spielt auf
                       dem zuletzt benutzten. Das Stoppwort liest die Variable aus dem Stop-Hook
                       in settings.json, wenn der Prompt-Hook sie nicht hat
    SPRECHEN_LEERLAUF  Sekunden; ist jedes Gerät länger unbenutzt, bleibt die Antwort stumm
                       (Standard: 1800)

Hooks laufen außerhalb einer Bash-Sandbox; nur dort stehen Metal und Audio zur Verfügung.
Fehler gehen nach stderr und brechen die Sitzung nie ab (Exit 0). Nur Standardbibliothek.
"""

# Ein Hook-Eintrag mit dem System-Python (3.9 auf macOS) scheiterte sonst schon beim
# Laden an "str | None"; das Skript selbst braucht nur die Standardbibliothek
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# SessionStart: der Abschnitt von sprechen.md, den /sprechen ohne Argument lädt, ohne die
# Bestätigung; so bleibt sprechen.md die einzige Quelle der Regeln
COMMAND = Path(__file__).resolve().parent / "sprechen.md"
EINSCHALTEN = "## Sonst: Modus einschalten"
BESTAETIGEN = "Bestätige das Einschalten"
START_KENNUNG = "Der Gesprächsmodus ist in dieser Sitzung von Anfang an eingeschaltet"
VORSPANN = (START_KENNUNG + " (SessionStart-Hook des Hörbuch-Generators), ohne Bestätigung. "
            "/sprechen aus schaltet ihn ab, /sprechen datei auf Audiodateien um. "
            "Bis dahin gilt:\n\n")
# Nach dem Kompaktieren im Datei-Modus: der Abschnitt „Bei datei“ statt der Regeln für Ton.
# Ohne START_KENNUNG, sonst läse modus() den Kontext im Transkript als „an“
DATEI_ABSCHNITT = "## Bei `datei`"
DATEI_BESTAETIGEN = "Bestätige mit genau dieser Antwort"
# Der Abschnitt verweist auf die Regeln „Knapp“ und „Natürlich“ weiter unten; die kommen mit
KNAPP = "### Knapp"
WAS_SONST = "### Was sonst gilt"
VORSPANN_DATEI = ("Der Gesprächsmodus dieser Sitzung steht auf Datei (/sprechen datei, vom "
                  "Hook des Hörbuch-Generators festgehalten), ohne Bestätigung. /sprechen "
                  "schaltet auf Ton, /sprechen aus ab. Bis dahin gilt:\n\n")
# Der Prompt-Hook bekommt die Eingabe so, wie sie getippt wurde (Hook-Doku, UserPromptSubmit)
SPRECHEN_EINGABE = re.compile(r"\s*/sprechen(?:\s+(.*))?\Z", re.DOTALL)
MODUS_HALTEN = 30 * 24 * 3600  # Sekunden; ältere Modus-Dateien räumt das nächste Schreiben weg
# Notification: ein fester Satz je Typ. idle_prompt fehlt mit Absicht: Er kommt rund 60 s nach
# jeder Antwort, die der Stop-Hook gerade gesprochen hat
HINWEISE = {
    "permission_prompt": "Claude wartet auf deine Freigabe.",
    "elicitation_dialog": "Claude wartet auf deine Eingabe.",
    "elicitation_url_dialog": "Claude wartet auf deine Eingabe.",
}
# Eine Rückfrage von Claude kommt in Oberflächen auf Basis des Agent SDK als permission_prompt mit
# "Claude needs your permission to use AskUserQuestion" (gemessen am 27.11.2026 in T3 Code)
RUECKFRAGE = "Claude hat eine Frage an dich."
# Stop im Gesprächsmodus ohne Sprechmarke; sonst bliebe offen, ob Claude noch arbeitet
ERSATZ = "Fertig, die Antwort steht im Text."
# So steht ein /sprechen-Aufruf im Transkript (gelesen am 27.11.2026, Claude Code 2.1.332)
SPRECHEN_COMMAND = "<command-name>/sprechen</command-name>"
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
# Uhrzeit in jeder Zeile: wiedergabe.log sammelt Meldungen mehrerer Hintergrundprozesse
LOG_FORMAT = "%(asctime)s claude_sprechen: %(message)s"
LOG_ZEIT = "%Y-%m-%d %H:%M:%S"
MARKE = re.compile(r"<!--\s*sprechen\s*:(.*?)-->", re.DOTALL | re.IGNORECASE)
STIMME = "marketing"
TEMPO = "1.1"
LAUTER = "8"
TIMEOUT = 30  # Sekunden; sprechen.sh kehrt nach dem Annehmen des Auftrags zurück
# Fernbetrieb: Der Prompt-Hook hat 10 s; ssh darf ihn nicht aufbrauchen, wenn der Mac schläft
# ServerAlive: Schläft ein Gerät mitten in der Wiedergabe ein, gibt ssh nach etwa 15 s auf. Sonst
# wartete es ohne Ende und hielte die Sperre, und jede spätere Antwort dieses Geräts bliebe stumm
SSH_OPTIONEN = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=4",
                "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3"]
STOPP_TIMEOUT = 8
# Obergrenze einer Wiedergabe, falls trotzdem etwas hängt: Grundzeit für Warteschlange und
# Modellstart, dazu reichlich Zeit je Zeichen (die Stimme spricht rund 15 Zeichen je Sekunde)
OBERGRENZE_GRUND = 120
OBERGRENZE_JE_ZEICHEN = 0.25
NACHLAUF = 10  # Sekunden, die der Rechenteil nach dem Ende des Players noch bekommt
# Eine Eingabe, die nur aus einem dieser Wörter besteht, beendet die Ausgabe der Sitzung.
# „Stopp“ fehlt mit Absicht: Damit hält man oft Claude selbst an, etwa in T3 Code während
# einer laufenden Antwort, und das Wort soll dann bei Claude ankommen
STOPPWORTE = {"psst", "pst", "still", "ruhe"}
# Format von sprechen.sh --liefern
PLAYER = [
    ["paplay", "--raw", "--rate=24000", "--channels=1", "--format=s16le"],
    ["pw-play", "--raw", "--rate", "24000", "--channels", "1", "--format", "s16", "-"],
    ["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", "24000", "-c", "1"],
    # Nur macOS: ffmpeg direkt über AudioToolbox. ffplay verwirft dort den Anfang eines Stroms,
    # der erst nach und nach kommt (gemessen am 27.11.2026: die ersten Wörter fehlten)
    ["ffmpeg", "-v", "error", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", "-",
     "-f", "audiotoolbox", "-"],
    ["ffplay", "-nodisp", "-nostats", "-autoexit", "-loglevel", "error",
     "-f", "s16le", "-ar", "24000", "-ch_layout", "mono", "-"],
]
NUR_MACOS = "audiotoolbox"
# Gerätewahl: "hier" ist dieses Gerät, alles andere ein ssh-Ziel
HIER = "hier"
LEERLAUF_MAX = 1800
ERKENNUNG_TIMEOUT = 6
# Sekunden seit der letzten Eingabe, als Shell-Befehl für das Gerät selbst. Über ssh fehlt die
# Session-Bus-Adresse, unter /run/user/<uid>/bus liegt sie bei systemd-Sitzungen
LEERLAUF = (
    "if command -v ioreg >/dev/null 2>&1; then "
    "ioreg -c IOHIDSystem | awk '/HIDIdleTime/ {print int($NF/1000000000); exit}'; "
    'else DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}" '
    "gdbus call --session --dest org.gnome.Mutter.IdleMonitor "
    "--object-path /org/gnome/Mutter/IdleMonitor/Core "
    "--method org.gnome.Mutter.IdleMonitor.GetIdletime | awk '{print int($2/1000)}'; fi")
# Player auf einem anderen Gerät; über ssh fehlt Homebrew im PATH
FERN_PATH = 'PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"; '
SPIELER_WAHL = (
    "if command -v paplay >/dev/null 2>&1; then "
    "exec paplay --raw --rate=24000 --channels=1 --format=s16le; "
    'elif [ "$(uname)" = Darwin ] && command -v ffmpeg >/dev/null 2>&1; then '
    "exec ffmpeg -v error -f s16le -ar 24000 -ac 1 -i - -f audiotoolbox -; "
    "elif command -v ffplay >/dev/null 2>&1; then "
    "exec ffplay -nodisp -nostats -autoexit -loglevel error -f s16le -ar 24000 -ch_layout mono -; "
    "else echo 'kein Player (paplay, ffmpeg, ffplay)' >&2; exit 127; fi")
# Sperre auf dem Gerät, das spielt: Antworten mehrerer Rechner, die dort landen, klängen sonst
# übereinander. Mehrere Rechner rechnen zwar auf demselben Mac, nacheinander; die Puffer von
# ssh fassen aber bis zu zwei MB, rund 40 Sekunden Ton. macOS hat kein flock(1), deshalb
# Python. Gesperrt wird erst, wenn Ton ankommt: Ein Player, der auf einen noch nicht
# gerechneten Auftrag wartet, hielte sonst die Sperre, während der Mac den Auftrag davor nicht
# loswird. Der Player erbt die Sperre und gibt sie mit seinem Ende frei; die Datei nennt seine
# PID und den Beginn für das Stoppwort. Gewartet wird in Runden statt blockierend: Ist ssh
# fort (Stopp beim Warten), wechselt der Elternprozess, und der Wartende endet sofort still.
# Reißt die Verbindung ohne Abbau ab (Gerät schlief ein), wartet der Player ohne Ende auf
# Ton, und sshd merkt es erst nach Stunden; ein Halter älter als SPERRE_ALTER gilt deshalb als
# hängend und wird beendet. Ohne Sperrdatei spielt der Player ohne Sperre.
SPERRE_DATEI = "$HOME/.cache/hoerbuch-generator/player.lock"
SPERRE_ALTER = 600  # Sekunden; eine gesprochene Antwort dauert selten eine Minute
SPERRE_PY = (
    "import fcntl, os, select, sys, time\n"
    "eltern = os.getppid()\n"
    "select.select([0], [], [])\n"
    "try:\n"
    "    os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True)\n"
    "    f = open(sys.argv[1], 'a+')\n"
    "except OSError:\n"
    "    f = None\n"
    "while f is not None:\n"
    "    try:\n"
    "        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    "        break\n"
    "    except OSError:\n"
    "        pass\n"
    "    if os.getppid() != eltern or eltern == 1:\n"
    "        sys.exit(0)\n"
    "    try:\n"
    "        f.seek(0)\n"
    "        pid, seit = f.read().split()[:2]\n"
    f"        if time.time() - float(seit) > {SPERRE_ALTER}:\n"
    "            os.kill(int(pid), 15)\n"
    "    except (OSError, ValueError):\n"
    "        pass\n"
    "    time.sleep(0.2)\n"
    "if os.getppid() != eltern or eltern == 1:\n"
    "    sys.exit(0)\n"
    "if f is not None:\n"
    "    f.seek(0); f.truncate(); f.write('%d %d' % (os.getpid(), time.time())); f.flush()\n"
    "    os.set_inheritable(f.fileno(), True)\n"
    "os.execvp(sys.argv[2], sys.argv[2:])\n")
# Unter macOS ohne Command Line Tools ist /usr/bin/python3 nur ein Platzhalter: Er scheitert
# und öffnet bei jedem Aufruf den Dialog zur Installation. xcode-select -p fragt, ohne ihn
SPERRE_DA = ('{ [ "$(uname)" != Darwin ] || [ "$(command -v python3)" != /usr/bin/python3 ] '
             "|| xcode-select -p >/dev/null 2>&1; } && python3 -c 'import fcntl' >/dev/null 2>&1")
FERN_PLAYER = (
    f'{FERN_PATH}S="{SPERRE_DATEI}"; '
    f"if {SPERRE_DA}; then exec python3 -c {shlex.quote(SPERRE_PY)} \"$S\" "
    f"sh -c {shlex.quote(SPIELER_WAHL)}; fi; {SPIELER_WAHL}")
# Stoppwort ohne eigene Ausgabe: den Player beenden, der dort gerade die Sperre hält. Ist sie
# frei, klingt dort nichts, und die PID in der Datei gehört einem beendeten Player
STOPP_PY = (
    "import fcntl, os, signal, sys\n"
    "f = open(sys.argv[1])\n"
    "try:\n"
    "    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    "except OSError:\n"
    "    try:\n"
    "        os.kill(int(f.read().split()[0]), signal.SIGTERM)\n"
    "    except (OSError, ValueError, IndexError):\n"
    "        pass\n")
FERN_STOPP = (f'{FERN_PATH}S="{SPERRE_DATEI}"; if [ -f "$S" ] && {SPERRE_DA}; then '
              f'python3 -c {shlex.quote(STOPP_PY)} "$S"; fi; true')
# Für pruefen: dieselbe Suche, nur den Namen ausgeben statt abzuspielen, dazu die Sperre
FERN_PLAYER_NAME = (FERN_PATH + re.sub(r"exec (\w+)[^;]*;", r"printf %s \1;", SPIELER_WAHL)
                    + f"; if {SPERRE_DA}; then echo ' mit Sperre'; "
                    "else echo ' ohne Sperre (kein python3)'; fi")
# Einträge in settings.json und der Unterbefehl, den jedes Ereignis aufruft
HOOKS = {"Stop": "stop", "UserPromptSubmit": "prompt", "SessionStart": "start",
         "Notification": "notification"}
HOOKS_NOETIG = ("Stop", "UserPromptSubmit")
# Variablen, die zwischen den Hooks gleich sein müssen, die sie nutzen; True: sonst ein Fehler.
# Der Prompt-Hook braucht den Fernbetrieb für den Stopp auf dem Mac, die Gerätewahl nicht
VERGLEICH = (
    (("SPRECHEN_ENTFERNT", "SPRECHEN_ENTFERNT_REPO"), ("Stop", "UserPromptSubmit", "Notification"),
     True),
    (("SPRECHEN_GERAETE", "SPRECHEN_LEERLAUF"), ("Stop", "Notification"), True),
    (("SPRECHEN_STIMME", "SPRECHEN_TEMPO", "SPRECHEN_LAUTER"), ("Stop", "Notification"), False),
)

log = logging.getLogger("claude_sprechen")


def gesprochener_text(antwort: str) -> str:
    """Inhalt der letzten Sprechmarke, Leerraum zusammengezogen; leer ohne Marke."""
    treffer = MARKE.findall(antwort or "")
    return " ".join(treffer[-1].split()) if treffer else ""


def regeln(von: str = EINSCHALTEN, bis: str = BESTAETIGEN) -> str:
    """Abschnitt aus sprechen.md von der Überschrift bis vor die Bestätigung, ohne beide;
    leer, wenn eine fehlt. Ohne Argumente die Regeln für Ton."""
    text = COMMAND.read_text(encoding="utf-8")
    anfang = text.find(von)
    ende = text.find(bis, anfang)
    if anfang < 0 or ende < 0:
        return ""
    return text[anfang + len(von):ende].strip()


def _modus_wort(argumente: str) -> str:
    """Modus aus den Argumenten von /sprechen: "aus", "datei", sonst "an". Satzzeichen am
    ersten Wort zählen nicht: „/sprechen aus.“ schaltet auch aus."""
    worte = argumente.split()
    erstes = re.sub(r"\W+", "", worte[0].casefold()) if worte else ""
    return erstes if erstes in ("aus", "datei") else "an"


def modus_aus_eingabe(prompt: str) -> str | None:
    """Modus, den eine Eingabe /sprechen [aus | datei] setzt; None bei jeder anderen Eingabe."""
    treffer = SPRECHEN_EINGABE.match(prompt or "")
    return _modus_wort(treffer.group(1) or "") if treffer else None


def _modus_pfad(sitzung: str) -> Path:
    return zustand_ordner() / "modus" / _kennung(sitzung)


def modus_schreiben(sitzung: str, wert: str) -> None:
    """Hält den Modus der Sitzung in einer Datei fest; das Kompaktieren behält die
    session_id, der SessionStart-Hook findet ihn danach wieder."""
    ziel = _modus_pfad(sitzung)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    grenze = time.time() - MODUS_HALTEN
    for alt in ziel.parent.iterdir():
        try:
            if alt.stat().st_mtime < grenze:
                alt.unlink()
        except OSError:
            pass  # eine zweite Sitzung räumt gerade dieselbe Datei weg
    neu = ziel.with_name(f"{ziel.name}.{os.getpid()}")
    neu.write_text(wert + "\n", encoding="utf-8")
    os.replace(neu, ziel)


def modus_lesen(sitzung: str) -> str | None:
    """Festgehaltener Modus der Sitzung: "an", "aus", "datei" oder None ohne Datei."""
    if not sitzung:
        return None
    try:
        wert = _modus_pfad(sitzung).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return wert if wert in ("an", "aus", "datei") else None


def modus(transcript: str) -> str | None:
    """Gesprächsmodus der Sitzung aus ihrem Transkript: "an", "aus", "datei" oder None ohne
    Hinweis. Es zählt der letzte Eintrag, der Kontext des SessionStart-Hooks (an) oder ein
    Aufruf von /sprechen. Das Transkript-Format ist nicht dokumentiert; ändert es sich, gibt es
    keinen Hinweis mehr, und Ansage und Ersatzsatz bleiben stumm."""
    zustand = None
    with open(transcript, encoding="utf-8", errors="replace") as datei:
        for zeile in datei:
            if START_KENNUNG not in zeile and SPRECHEN_COMMAND not in zeile:
                continue  # spart das Parsen der übrigen Zeilen, Transkripte werden groß
            try:
                eintrag = json.loads(zeile)
            except ValueError:
                continue
            if not isinstance(eintrag, dict):
                continue
            nachricht = eintrag.get("message")
            inhalt = nachricht.get("content") if isinstance(nachricht, dict) else None
            anhang = eintrag.get("attachment")
            # Nur die Eingabe selbst; Werkzeugergebnisse, die den Text zitieren, sind Listen
            if (eintrag.get("type") == "user" and isinstance(inhalt, str)
                    and SPRECHEN_COMMAND in inhalt):
                treffer = COMMAND_ARGS.search(inhalt)
                zustand = _modus_wort(treffer.group(1) if treffer else "")
            elif (isinstance(anhang, dict) and anhang.get("type") == "hook_additional_context"
                  and START_KENNUNG in str(anhang.get("content"))):
                zustand = "an"
    return zustand


def gespraechsmodus(eingabe: dict) -> str | None:
    """Modus der Sitzung: zuerst die Datei des Prompt-Hooks, sonst das Transkript (etwa eine
    Sitzung, die vor dem Update begann, oder eine Oberfläche, die /sprechen anders an den Hook
    gibt); None, wenn beide nichts sagen."""
    zustand = modus_lesen(str(eingabe.get("session_id") or ""))
    transcript = str(eingabe.get("transcript_path") or "")
    if zustand is None and transcript:
        try:
            zustand = modus(transcript)
        except (OSError, ValueError) as e:  # ValueError: Nullbyte im Pfad
            log.error("Transkript nicht lesbar: %s", e)
    return zustand


def pausiert(eingabe: dict) -> bool:
    """Ob der Stop-Hook eine Pause meldet statt eines Endes: Hintergrundaufgaben laufen oder ein
    Weckruf ist geplant (background_tasks, session_crons). Eine Zwischenmeldung trägt keine
    Sprechmarke, der Ersatzsatz „Fertig“ wäre dann falsch."""
    return any(isinstance(eingabe.get(feld), list) and bool(eingabe.get(feld))
               for feld in ("background_tasks", "session_crons"))


def protokollieren(meldung: str) -> None:
    """Eine Zeile in wiedergabe.log, auch ohne Hintergrundprozess, der dorthin schreibt."""
    ordner = zustand_ordner()
    try:
        ordner.mkdir(parents=True, exist_ok=True)
        with open(ordner / "wiedergabe.log", "a", encoding="utf-8") as datei:
            datei.write(f"{time.strftime(LOG_ZEIT)} claude_sprechen: {meldung}\n")
    except OSError as e:
        log.error("wiedergabe.log nicht beschreibbar: %s", e)


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


# --- Fernbetrieb -------------------------------------------------------------------------

def entfernter_befehl(ziel: str, args: list[str]) -> list[str]:
    """ssh-Aufruf von sprechen.sh auf dem Mac. ssh fügt die Argumente zu einer Zeile für die
    Shell dort zusammen, deshalb ist jedes einzeln gequotet; ~ wird zu "$HOME", damit es
    dort aufgelöst wird und nicht hier."""
    return ["ssh", *SSH_OPTIONEN, ziel,
            " ".join([_fern_pfad("sprechen.sh"), *map(shlex.quote, args)])]


def _fern_pfad(name: str) -> str:
    """Pfad einer Datei im Repo auf dem Mac, gequotet für die Shell dort."""
    repo = os.environ.get("SPRECHEN_ENTFERNT_REPO") or _repo_unter_home()
    if repo.startswith("~/"):
        return '"$HOME"/' + shlex.quote(repo[2:].rstrip("/") + "/" + name)
    return shlex.quote(repo.rstrip("/") + "/" + name)


def _repo_unter_home() -> str:
    try:
        return "~/" + str(REPO.relative_to(Path.home()))
    except ValueError:
        return str(REPO)


def player_befehl() -> list[str] | None:
    eigener = os.environ.get("SPRECHEN_PLAYER")
    if eigener:
        return shlex.split(eigener)
    return next((p for p in PLAYER if shutil.which(p[0])
                 and (NUR_MACOS not in p or sys.platform == "darwin")), None)


def rechen_befehl(args: list[str]) -> list[str]:
    """sprechen.sh mit --liefern: auf dem Mac aus SPRECHEN_ENTFERNT, sonst auf diesem Gerät."""
    ziel = os.environ.get("SPRECHEN_ENTFERNT", "")
    return entfernter_befehl(ziel, args) if ziel else ["/bin/bash", str(sprechen_sh()), *args]


# --- Gerätewahl --------------------------------------------------------------------------

def geraete() -> list[str]:
    return os.environ.get("SPRECHEN_GERAETE", "").split()


def _leerlauf_befehl(geraet: str) -> list[str]:
    return ["/bin/sh", "-c", LEERLAUF] if geraet == HIER else ["ssh", *SSH_OPTIONEN, geraet, LEERLAUF]


def geraet_waehlen(kandidaten: list[str]) -> str | None:
    """Das Gerät mit der kürzesten Zeit seit der letzten Eingabe; None, wenn keines antwortet
    oder alle länger als SPRECHEN_LEERLAUF unbenutzt sind. Die Geräte antworten parallel,
    ein schlafendes kostet höchstens ERKENNUNG_TIMEOUT."""
    laeufe = {}
    for geraet in kandidaten:
        try:
            laeufe[geraet] = subprocess.Popen(_leerlauf_befehl(geraet), stdin=subprocess.DEVNULL,
                                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError as e:
            log.error("Leerlauf von %s nicht abfragbar: %s", geraet, e)
    werte: dict[str, int] = {}
    frist = time.monotonic() + ERKENNUNG_TIMEOUT
    for geraet, lauf in laeufe.items():
        try:
            aus, _ = lauf.communicate(timeout=max(0.1, frist - time.monotonic()))
            werte[geraet] = int(aus.split()[0])
        except subprocess.TimeoutExpired:
            lauf.kill()
            lauf.wait()
        except (ValueError, IndexError):
            pass  # keine Zahl: kein ioreg, kein GNOME, oder ssh scheiterte
    try:
        grenze = float(os.environ.get("SPRECHEN_LEERLAUF", LEERLAUF_MAX))
    except ValueError:
        grenze = LEERLAUF_MAX
    if not werte:
        log.info("Gerätewahl: kein Gerät antwortet")
        return None
    geraet, sekunden = min(werte.items(), key=lambda w: w[1])
    log.info("Gerätewahl: %s", ", ".join(f"{g} {s} s" for g, s in werte.items()))
    return geraet if sekunden <= grenze else None


def zustand_ordner() -> Path:
    basis = os.environ.get("XDG_RUNTIME_DIR") or str(Path.home() / ".cache")
    return Path(basis) / "hoerbuch-generator"


def player_sperre() -> Path:
    """SPERRE_DATEI auf diesem Gerät. Nicht unter XDG_RUNTIME_DIR: FERN_PLAYER kommt über
    ssh, und dort fehlt die Variable oft."""
    return Path.home() / ".cache" / "hoerbuch-generator" / "player.lock"


def _kennung(quelle: str) -> str:
    return hashlib.sha256(quelle.encode()).hexdigest()[:16] if quelle else "ohne"


def wiedergabe_starten(args: list[str], text: str, quelle: str) -> None:
    """Wiedergabe an einen eigenen Prozess in eigener Sitzung übergeben und zurückkehren:
    Ein Hook, der bis zum Ende der Ausgabe liefe, stieße an das Zeitlimit von Claude Code."""
    ordner = zustand_ordner()
    ordner.mkdir(parents=True, exist_ok=True)
    with open(ordner / "wiedergabe.log", "a", encoding="utf-8") as protokoll:
        kind = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "abspielen"],
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=protokoll, start_new_session=True)
    kind.stdin.write(json.dumps({"args": args, "text": text, "quelle": quelle}).encode())
    kind.stdin.close()


def abspielen(auftrag: dict) -> int:
    """Im Hintergrundprozess: Gerät wählen, der Reihe nach warten, dann den gelieferten Ton in
    den Player leiten. Die Marke mit der eigenen PID lässt den Prompt-Hook diesen Prozess samt
    ssh und Player beenden; sie fallen in dieselbe Prozessgruppe."""
    ziel = os.environ.get("SPRECHEN_ENTFERNT", "")
    ordner = zustand_ordner()
    ordner.mkdir(parents=True, exist_ok=True)
    marke = ordner / f"laeuft-{_kennung(auftrag.get('quelle', ''))}-{os.getpid()}"
    marke.touch()
    beginn = time.monotonic()
    log.info("Auftrag: %d Zeichen", len(auftrag.get("text", "")))
    try:
        geraet = None
        if geraete():
            geraet = geraet_waehlen(geraete())
            if geraet is None:
                log.info("kein Gerät in Benutzung, die Antwort bleibt stumm")
                return 0
            if geraet == HIER and not ziel:
                # Rechnet und spielt dieses Gerät, spielt der Dienst selbst wie ohne Gerätewahl
                rc = aufrufen([*auftrag["args"], "-"], auftrag["text"])
                if rc == 0:
                    log.info("an den Dienst hier übergeben")
                return rc
        player = player_befehl() if geraet in (None, HIER) else ["ssh", *SSH_OPTIONEN, geraet,
                                                                 FERN_PLAYER]
        if not player:
            log.error("kein Player (paplay, pw-play, aplay, ffmpeg, ffplay, SPRECHEN_PLAYER)")
            return 1
        name = player[0]
        if geraet in (None, HIER):
            # Dieselbe Sperre wie FERN_PLAYER: Spielt ein anderer Rechner über ssh auf diesem
            # Gerät, bleiben beide in der Reihe, und ein Stoppwort trifft hier den Halter
            player = [sys.executable, "-c", SPERRE_PY, str(player_sperre()), *player]
        with open(ordner / "wiedergabe.lock", "w") as sperre:
            # Zwei Sitzungen auf diesem Gerät: Der Mac liefert schneller, als der Player
            # spielt, und beide Antworten klängen sonst übereinander
            fcntl.flock(sperre, fcntl.LOCK_EX)
            log.info("Wiedergabe auf %s, gerechnet auf %s", geraet or HIER, ziel or HIER)
            ssh = subprocess.Popen(rechen_befehl([*auftrag["args"], "--liefern", "-"]),
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
            spieler = subprocess.Popen(player, stdin=ssh.stdout, stderr=subprocess.PIPE)
            ssh.stdout.close()  # nur der Player liest; endet er, bekommt ssh SIGPIPE
            faeden = [_weiterleiten(ssh.stderr, f"Rechnen auf {ziel or HIER}"),
                      _weiterleiten(spieler.stderr, f"Player auf {geraet or HIER}")]
            try:
                try:
                    ssh.stdin.write(auftrag["text"].encode())
                    ssh.stdin.close()
                except BrokenPipeError:
                    pass
                frist = OBERGRENZE_GRUND + OBERGRENZE_JE_ZEICHEN * len(auftrag["text"])
                if not _warten(spieler, frist):
                    log.error("Wiedergabe auf %s nach %d s abgebrochen (Obergrenze)",
                              geraet or HIER, frist)
                    _warten(ssh, 0)
                    return 0
                if not _warten(ssh, NACHLAUF):
                    log.error("sprechen.sh auf %s endete %d s nach dem Player nicht, beendet",
                              ziel or HIER, NACHLAUF)
                    return 0
                # Endet der Player vorzeitig, stirbt ssh an SIGPIPE; kein Fehler des Macs
                if spieler.returncode == 0 and ssh.returncode != 0:
                    log.error("sprechen.sh auf %s endete mit %s", ziel or HIER, ssh.returncode)
                elif spieler.returncode != 0:
                    log.error("Player %s endete mit %s", name, spieler.returncode)
                else:
                    log.info("Wiedergabe auf %s fertig nach %.1f s", geraet or HIER,
                             time.monotonic() - beginn)
            finally:
                for faden in faeden:
                    faden.join(timeout=2)
    finally:
        marke.unlink(missing_ok=True)
    return 0


def _weiterleiten(strom, name: str) -> threading.Thread:
    """Meldungen von ssh oder Player mit Uhrzeit ins Protokoll, statt roh auf stderr."""
    def lesen() -> None:
        with strom:
            for zeile in strom:
                text = zeile.decode(errors="replace").rstrip()
                if text:
                    log.warning("%s: %s", name, text)
    faden = threading.Thread(target=lesen, daemon=True)
    faden.start()
    return faden


def _warten(prozess: subprocess.Popen, frist: float) -> bool:
    """Auf das Ende warten; nach Ablauf der Frist den Prozess beenden und False liefern."""
    try:
        prozess.wait(timeout=frist)
        return True
    except subprocess.TimeoutExpired:
        prozess.kill()
        prozess.wait()
        return False


def wiedergabe_stoppen(quelle: str) -> int:
    """Laufende und wartende Wiedergaben dieser Quelle auf diesem Gerät beenden; gibt zurück,
    wie viele Marken es gab."""
    marken = list(zustand_ordner().glob(f"laeuft-{_kennung(quelle)}-*"))
    for marke in marken:
        try:
            pid = int(marke.name.rsplit("-", 1)[1])
            if _gehoert_uns(pid):
                os.killpg(pid, signal.SIGTERM)
        except (ValueError, ProcessLookupError, PermissionError):
            pass
        marke.unlink(missing_ok=True)
    return len(marken)


def _gehoert_uns(pid: int) -> bool:
    """Schutz gegen eine wiederverwendete PID nach einem Absturz: Der Prozess muss noch
    dieses Skript sein. Unter Linux steht das in /proc, sonst (macOS) fragt ps."""
    cmdline = Path(f"/proc/{pid}/cmdline")
    if cmdline.exists():
        try:
            return b"claude_sprechen" in cmdline.read_bytes()
        except OSError:
            return False
    try:
        aus = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True,
                             timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return True  # ohne ps bleibt nur die Marke
    return b"claude_sprechen" in aus.stdout


def ist_stoppwort(prompt: str) -> bool:
    """Eingabe, die nur aus einem Stoppwort besteht; Groß- und Kleinschreibung und
    Satzzeichen zählen nicht, damit es auch per Diktat klappt („Psst.“). Ein Buchstabe, der
    drei- oder mehrmals steht, zählt doppelt: Die Spracherkennung schreibt auch „Pssst!“."""
    wort = re.sub(r"\W+", "", prompt.casefold())
    return re.sub(r"(.)\1{2,}", r"\1\1", wort) in STOPPWORTE


def _stopp_hier(args: list[str], frist: float) -> str:
    """sprechen.sh --stopp mit --sonst-aktuell; liefert, was der Dienst getroffen hat."""
    skript = sprechen_sh()
    try:
        lauf = subprocess.run(["/bin/bash", str(skript), "--stopp", *args], text=True,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=frist)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.error("sprechen.sh scheiterte: %s", e)
        return ""
    if lauf.returncode != 0:
        log.error("sprechen.sh: %s", lauf.stderr.strip())
    return lauf.stdout.strip()


def stopp_geraete() -> list[str]:
    """Geräte für das Stoppwort. Die Gerätewahl braucht nur der Stop-Hook, deshalb steht
    SPRECHEN_GERAETE oft nur vor ihm; fehlt die Variable im Prompt-Hook, gilt sein Wert aus
    settings.json."""
    if "SPRECHEN_GERAETE" in os.environ:
        return geraete()
    try:
        daten = json.loads(settings_pfad().read_text(encoding="utf-8"))
        if not isinstance(daten, dict):
            return []
        umgebung, _, praefixe = hooks_lesen(daten)
    except (OSError, ValueError, AttributeError, TypeError):
        return []
    return {**umgebung, **praefixe.get("Stop", {})}.get("SPRECHEN_GERAETE", "").split()


def fremd_stoppen(weitere: list[tuple[str, list[str]]] | None = None,
                  ende: float | None = None) -> None:
    """Stoppwort, während für die eigene Sitzung nichts läuft: beenden, was gerade klingt, also
    hier und auf jedem Gerät der Gerätewahl den Player, der die Sperre hält. Wartende bleiben.
    weitere sind Befehle (Ziel, Befehl), die gleichzeitig mit denen für die Geräte laufen; ende
    ist der Zeitpunkt (time.monotonic), bis zu dem alle fertig sein müssen."""
    befehle = [(g, ["ssh", *SSH_OPTIONEN, g, FERN_STOPP]) for g in stopp_geraete() if g != HIER]
    if player_sperre().is_file():
        # Auch ohne "hier" in der Gerätewahl: Eine andere Sitzung oder ein anderer Rechner
        # kann hier spielen
        befehle.insert(0, (HIER, [sys.executable, "-c", STOPP_PY, str(player_sperre())]))
    laeufe = []
    for geraet, befehl in [*befehle, *(weitere or [])]:
        try:
            laeufe.append((geraet, subprocess.Popen(befehl, stdin=subprocess.DEVNULL,
                                                    stdout=subprocess.DEVNULL,
                                                    stderr=subprocess.DEVNULL)))
        except OSError as e:
            log.error("Stopp auf %s nicht startbar: %s", geraet, e)
    # Parallel, damit ein schlafendes Gerät die übrigen nicht aufhält
    ende = time.monotonic() + STOPP_TIMEOUT if ende is None else ende
    for geraet, lauf in laeufe:
        if not _warten(lauf, max(0.0, ende - time.monotonic())):
            log.error("Stopp auf %s nicht rechtzeitig fertig, abgebrochen", geraet)


def ausgabe_stoppen(sitzung: str, quelle: list[str], entfernt: str,
                    fremd: bool = False) -> None:
    """Ausgabe der eigenen Sitzung beenden. Mit fremd (Stoppwort) und ohne eigene Ausgabe
    das, was gerade klingt, auch wenn es aus einer anderen Sitzung oder von einem anderen
    Rechner kommt."""
    # Mit Gerätewahl läuft die Wiedergabe womöglich als Hintergrundprozess; ohne Marke
    # kostet das nur einen Blick in den Ordner
    eigene = wiedergabe_stoppen(sitzung)
    sonst = fremd and bool(quelle) and not eigene
    if not entfernt:
        if not sonst:
            aufrufen(["--stopp", *quelle])
            return
        # Eine Frist für beides: Der Prompt-Hook hat zehn Sekunden. Der Dienst hier antwortet
        # sonst in einer Drittelsekunde, die Geräte bekommen den Rest
        ende = time.monotonic() + STOPP_TIMEOUT
        if _stopp_hier([*quelle, "--sonst-aktuell"], STOPP_TIMEOUT / 2) != "eigene":
            fremd_stoppen(ende=ende)
        return
    if sonst:
        # Den Mac zugleich mit den Geräten: Nacheinander passte ein schlafendes Gerät samt
        # ssh zum Mac nicht in die zehn Sekunden des Prompt-Hooks
        fremd_stoppen([(entfernt, entfernter_befehl(entfernt, ["--stopp", *quelle,
                                                               "--sonst-aktuell"]))])
        return
    # Erst hier verstummen, das geht sofort; dann den Auftrag auf dem Mac abbrechen. Ohne
    # Marke läuft für diese Sitzung nichts, auch dort nicht: Der Hintergrundprozess lebt, bis
    # ssh endet. ssh bei jedem Stopp kostete sonst den Aufbau, bei schlafendem Mac bis zum
    # ConnectTimeout
    if not eigene:
        return
    try:
        subprocess.run(entfernter_befehl(entfernt, ["--stopp", *quelle]),
                       capture_output=True, timeout=STOPP_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.error("Stopp auf %s gescheitert: %s", entfernt, e)


def sprechen_lassen(eingabe: dict, text: str) -> None:
    """Text mit Stimme, Sitzung und Ansage an den Dienst, über Gerätewahl oder Fernbetrieb in
    einem Hintergrundprozess, sonst direkt."""
    sitzung = str(eingabe.get("session_id") or "")
    quelle = ["--quelle", sitzung] if sitzung else []
    name = ansage(eingabe) if quelle else ""
    sprechen = ["-v", os.environ.get("SPRECHEN_STIMME", STIMME),
                "-t", os.environ.get("SPRECHEN_TEMPO", TEMPO),
                "--lauter", os.environ.get("SPRECHEN_LAUTER", LAUTER), *quelle,
                *(["--ansage", name] if name else [])]
    if os.environ.get("SPRECHEN_ENTFERNT") or geraete():
        try:
            wiedergabe_starten(sprechen, text, sitzung)
        except OSError as e:
            log.error("Wiedergabe nicht startbar: %s", e)
    else:
        aufrufen([*sprechen, "-"], text)


def hinweis(eingabe: dict) -> str:
    """Satz für einen Notification-Hook; leer, wenn der Typ keinen hat oder der
    Gesprächsmodus der Sitzung nicht erkennbar an ist."""
    satz = HINWEISE.get(str(eingabe.get("notification_type") or ""), "")
    if not satz:
        return ""
    zustand = gespraechsmodus(eingabe)
    if zustand != "an":
        log.info("Hinweis %s ohne Ton: Gesprächsmodus %s", eingabe.get("notification_type"),
                 zustand or "nicht erkennbar")
        return ""
    if "AskUserQuestion" in str(eingabe.get("message") or ""):
        return RUECKFRAGE
    return satz


# --- pruefen -----------------------------------------------------------------------------

def settings_pfad() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"


def hooks_lesen(daten: dict) -> tuple[dict[str, str], dict[str, list[str]],
                                       dict[str, dict[str, str]]]:
    """Aus settings.json: die SPRECHEN_*-Variablen unter env, je Ereignis die Unterbefehle
    dieses Skripts, die dort eingetragen sind, und je Ereignis die SPRECHEN_*-Variablen vor dem
    Befehl mit dem passenden Unterbefehl (beim ersten solchen Eintrag)."""
    env = daten.get("env")
    umgebung = {k: str(v) for k, v in (env.items() if isinstance(env, dict) else ())
                if k.startswith("SPRECHEN_")}
    eingetragen: dict[str, list[str]] = {}
    praefixe: dict[str, dict[str, str]] = {}
    hooks = daten.get("hooks") or {}
    for ereignis, gruppen in hooks.items() if isinstance(hooks, dict) else ():
        for gruppe in gruppen if isinstance(gruppen, list) else ():
            for hook in (gruppe.get("hooks") or []) if isinstance(gruppe, dict) else ():
                befehl = str(hook.get("command") or "") if isinstance(hook, dict) else ""
                if "claude_sprechen.py" not in befehl:
                    continue
                try:
                    teile = shlex.split(befehl)
                except ValueError:
                    teile = befehl.split()
                skript = next((i for i, t in enumerate(teile)
                               if t.endswith("claude_sprechen.py")), -1)
                unterbefehl = teile[skript + 1] if 0 <= skript < len(teile) - 1 else ""
                eingetragen.setdefault(ereignis, []).append(unterbefehl)
                if unterbefehl != HOOKS.get(ereignis) or ereignis in praefixe:
                    continue
                praefix = praefixe[ereignis] = {}
                for teil in teile:
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", teil):
                        break
                    name, wert = teil.split("=", 1)
                    if name.startswith("SPRECHEN_"):
                        praefix[name] = wert
    return umgebung, eingetragen, praefixe


def _abweichungen(umgebung: dict[str, str], praefixe: dict[str, dict[str, str]]
                  ) -> list[tuple[str, bool]]:
    """Variablen, die zwischen den Hooks abweichen, die sie nutzen, als Text und ob das ein
    Problem ist. Verglichen wird env aus settings.json mit dem Präfix darüber, je Hook."""
    meldungen = []
    for namen, ereignisse, problem in VERGLEICH:
        dabei = [e for e in ereignisse if e in praefixe]
        for name in namen:
            werte = {e: {**umgebung, **praefixe[e]}.get(name) for e in dabei}
            if len(set(werte.values())) > 1:
                meldungen.append((f"{name} weicht ab: " + ", ".join(
                    f"{e} {w if w is not None else '(nicht gesetzt)'}"
                    for e, w in werte.items()), problem))
    return meldungen


def _lauf(befehl: list[str], frist: float) -> tuple[int, str, str]:
    """Befehl mit Frist; Rückgabe Exit-Code (124 bei Zeitablauf), stdout, letzte stderr-Zeile."""
    try:
        lauf = subprocess.run(befehl, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=frist)
    except subprocess.TimeoutExpired:
        return 124, "", f"keine Antwort nach {frist:g} s"
    except OSError as e:
        return 127, "", str(e)
    fehler = lauf.stderr.strip().splitlines()
    return lauf.returncode, lauf.stdout, fehler[-1] if fehler else ""


def _version_hier() -> str:
    rc, aus, _ = _lauf(["git", "-C", str(REPO), "describe", "--tags", "--always", "--dirty"],
                       STOPP_TIMEOUT)
    return aus.strip() if rc == 0 and aus.strip() else "unbekannt"


def _dienst(rc: int, aus: str, fehler: str) -> tuple[str, bool]:
    """Ausgabe von sprechen.sh --status als Text und ob sie ein Problem zeigt."""
    try:
        status = json.loads(aus)
    except ValueError:
        return f"sprechen.sh scheiterte ({rc}): {fehler or 'keine Ausgabe'}", True
    if not isinstance(status, dict):
        return f"sprechen.sh --status lieferte kein JSON-Objekt: {aus.strip()[:80]}", True
    zustand = status.get("zustand")
    if zustand == "aus":
        return "Dienst aus, startet beim ersten Auftrag", False
    if zustand == "fehler" or not status.get("ok"):
        return f"Dienst mit Fehler: {status.get('fehler') or zustand}", True
    return f"Dienst {zustand}", False


def pruefen() -> int:
    """Einrichtung dieses Geräts prüfen und Zeile für Zeile melden; Exit 1, wenn etwas fehlt.
    Liest kein stdin und gehört in kein Hook-Ereignis."""
    probleme = 0
    hinweise = 0

    def melden(bereich: str, text: str, problem: bool = False, hinweis: bool = False) -> None:
        nonlocal probleme, hinweise
        probleme += problem
        hinweise += hinweis and not problem
        stufe = "FEHLER: " if problem else "Hinweis: " if hinweis else ""
        print(f"{bereich:<9} {stufe}{text}")

    pfad = settings_pfad()
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        if not isinstance(daten, dict):
            raise ValueError("kein JSON-Objekt")
    except (OSError, ValueError) as e:
        melden("Hooks", f"{pfad} nicht lesbar: {e}", True)
        daten = {}
    umgebung, eingetragen, praefixe = hooks_lesen(daten)
    if daten:
        for ereignis, unterbefehl in HOOKS.items():
            gefunden = eingetragen.get(ereignis, [])
            if unterbefehl in gefunden:
                melden("Hooks", f"{ereignis}: {unterbefehl}")
            elif gefunden:
                melden("Hooks", f"{ereignis} ruft {', '.join(gefunden)} auf statt {unterbefehl}",
                       True)
            else:
                melden("Hooks", f"{ereignis} fehlt" +
                       ("" if ereignis in HOOKS_NOETIG else " (optional)"),
                       ereignis in HOOKS_NOETIG)
        for text, problem in _abweichungen(umgebung, praefixe):
            melden("Hooks", text, problem, hinweis=True)
    # Wie beim Stop-Hook: Claude Code gibt ihm seine Umgebung samt env aus settings.json, das
    # Präfix vor dem Befehl gilt vor beidem. Die Umgebung hier steht für die von Claude Code
    os.environ.update({**umgebung, **praefixe.get("Stop", {})})
    aus = os.environ.get("SPRECHEN_AUS") == "1"
    for name in sorted(k for k in os.environ if k.startswith("SPRECHEN_")):
        if not (aus and name == "SPRECHEN_AUS"):  # dafür folgt der Hinweis
            melden("Variable", f"{name}={os.environ[name]}")
    if aus:
        melden("Variable", "SPRECHEN_AUS=1: alle Hooks tun nichts, gedacht für Dienste ohne Nutzer",
               hinweis=True)

    hier = _version_hier()
    melden("Version", f"{hier} (dieser Klon)")
    ziel = os.environ.get("SPRECHEN_ENTFERNT", "")
    if ziel:
        rc, aus, fehler = _lauf(entfernter_befehl(ziel, ["--status"]), STOPP_TIMEOUT)
        if rc == 255 or rc == 124:
            melden("Rechnen", f"{ziel}: ssh antwortet nicht ({fehler})", True)
        else:
            text, problem = _dienst(rc, aus, fehler)
            rc_v, version, _ = _lauf(["ssh", *SSH_OPTIONEN, ziel,
                                      f"git -C {_fern_pfad('')} describe --tags --always --dirty"],
                                     STOPP_TIMEOUT)
            version = version.strip() if rc_v == 0 and version.strip() else "unbekannt"
            abweichung = "" if version == hier else f", anders als hier ({hier})"
            melden("Rechnen", f"{ziel}: ssh ok, {version}{abweichung}, {text}", problem)
    else:
        rc, aus, fehler = _lauf(["/bin/bash", str(sprechen_sh()), "--status"], STOPP_TIMEOUT)
        text, problem = _dienst(rc, aus, fehler)
        melden("Rechnen", f"{HIER}: {text}", problem)

    # Einen Player hier braucht nur der Fernbetrieb; sonst spielt der Dienst selbst
    if ziel and (not geraete() or HIER in geraete()):
        player = player_befehl()
        melden("Player", f"{HIER}: {player[0] if player else 'keiner gefunden'}", not player)

    try:
        grenze = float(os.environ.get("SPRECHEN_LEERLAUF", LEERLAUF_MAX))
    except ValueError:
        grenze = LEERLAUF_MAX
    # Ein schlafendes Gerät ist der Normalfall der Gerätewahl, es spielt dann ein anderes.
    # Ein Fehler ist es erst, wenn keines antwortet
    befunde: list[tuple[str, bool, bool]] = []  # Text, Problem, ssh antwortet nicht
    for geraet in geraete():
        if geraet == HIER:
            befehl = _leerlauf_befehl(HIER)
        else:
            befehl = ["ssh", *SSH_OPTIONEN, geraet,
                      f'echo "leerlauf $({LEERLAUF})"; echo "player $({FERN_PLAYER_NAME})"']
        rc, aus, fehler = _lauf(befehl, ERKENNUNG_TIMEOUT)
        if geraet != HIER and rc in (124, 255):
            befunde.append((f"{geraet}: ssh antwortet nicht ({fehler})", True, True))
            continue
        werte = dict(zeile.split(" ", 1) for zeile in aus.splitlines() if " " in zeile)
        sekunden = (werte.get("leerlauf", "") if geraet != HIER else aus).strip()
        teile = []
        problem = False
        if sekunden.isdigit():
            teile.append(f"Leerlauf {sekunden} s" +
                         (f", über {grenze:g} s: dort spräche es nicht" if int(sekunden) > grenze
                          else ""))
        else:
            teile.append("keine Leerlaufzeit (weder ioreg noch GNOME)")
            problem = True
        if geraet != HIER:
            name = werte.get("player", "").strip()
            teile.append(f"Player {name}" if name else "kein Player (paplay, ffmpeg, ffplay)")
            problem = problem or not name
        befunde.append((f"{geraet}: {', '.join(teile)}", problem, False))
    keines = all(stumm for _, _, stumm in befunde)
    for text, problem, stumm in befunde:
        melden("Gerät", text, problem and (keines or not stumm), hinweis=stumm)

    zusatz = f" ({hinweise} Hinweis{'e' if hinweise > 1 else ''})" if hinweise else ""
    print(f"Ergebnis: {'alles da' if not probleme else f'{probleme} Problem(e)'}{zusatz}")
    return 1 if probleme else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude-Code-Hooks für den Sprechdienst")
    # abspielen ist intern: der Hintergrundprozess des Fernbetriebs
    parser.add_argument("ereignis", choices=["stop", "prompt", "start", "notification",
                                             "pruefen", "abspielen"])
    try:
        args = parser.parse_args()
    except SystemExit:
        # argparse endet bei falschem Argument mit Exit 2, und Exit 2 bei UserPromptSubmit
        # verwirft jede Eingabe. Ein Tippfehler im Hook-Eintrag (etwa "Stop") darf das nicht
        return 0
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format=LOG_FORMAT,
                        datefmt=LOG_ZEIT)

    if args.ereignis == "pruefen":
        return pruefen()

    try:
        eingabe = json.load(sys.stdin)
    except ValueError:
        eingabe = {}
    if not isinstance(eingabe, dict):
        eingabe = {}

    # Ein Dienst ohne Nutzer, der die Einstellungen des Nutzers lädt: kein Modus, kein Ton, und
    # ein „Psst“ in seiner Eingabe geht an Claude. stdin ist gelesen, damit Claude Code beim
    # Schreiben nicht auf ein geschlossenes Rohr trifft
    if os.environ.get("SPRECHEN_AUS") == "1" and args.ereignis != "abspielen":
        return 0

    # Hooks gelten meist global. Ohne Sitzungskennung bräche eine Eingabe in einer zweiten
    # Sitzung die Antwort der ersten ab
    sitzung = str(eingabe.get("session_id") or "")

    if args.ereignis == "start":
        # Nach dem Kompaktieren gilt der Modus, den /sprechen in dieser Sitzung gesetzt hat;
        # nach /clear beginnt eine neue Sitzung und mit ihr der Ton
        gesetzt = modus_lesen(sitzung)
        if gesetzt is None:
            if eingabe.get("source") in ("resume", "fork", "compact"):
                # Ein Fork hat eine neue Kennung und damit keine Datei, sein Transkript aber
                # den Verlauf der Ausgangssitzung; ebenso eine Sitzung von vor v0.10.0 oder
                # eine, deren Datei weggeräumt ist (MODUS_HALTEN, Neustart bei XDG_RUNTIME_DIR)
                gesetzt = gespraechsmodus(eingabe)
            if sitzung:
                # Auch "an": Ohne Datei läsen Stop- und Notification-Hook jedes Mal das
                # Transkript, um den Modus zu erfahren
                try:
                    modus_schreiben(sitzung, gesetzt or "an")
                except OSError as e:
                    log.error("Modus nicht festgehalten: %s", e)
        if gesetzt == "aus":
            return 0
        try:
            if gesetzt == "datei":
                datei, stil = regeln(DATEI_ABSCHNITT, DATEI_BESTAETIGEN), regeln(KNAPP, WAS_SONST)
                teil = f"{datei}\n\n{KNAPP}\n\n{stil}" if datei and stil else ""
            else:
                teil = regeln()
        except OSError as e:
            log.error("sprechen.md nicht lesbar: %s", e)
            return 0
        if not teil:
            log.error("Regeln in %s nicht gefunden", COMMAND)
            return 0
        vorspann = VORSPANN_DATEI if gesetzt == "datei" else VORSPANN
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": vorspann + teil}},
                         ensure_ascii=False))
        return 0

    if args.ereignis == "abspielen":
        try:
            return abspielen(eingabe)
        except (OSError, KeyError, TypeError) as e:
            log.error("Wiedergabe gescheitert: %s", e)
            return 1

    quelle = ["--quelle", sitzung] if sitzung else []
    entfernt = os.environ.get("SPRECHEN_ENTFERNT", "")

    if args.ereignis == "prompt":
        prompt = str(eingabe.get("prompt", ""))
        neu = modus_aus_eingabe(prompt)
        if neu and sitzung:
            try:
                modus_schreiben(sitzung, neu)
            except OSError as e:
                log.error("Modus nicht festgehalten: %s", e)
        # Eine neue Eingabe lässt die laufende Antwort zu Ende sprechen; die nächste reiht sich
        # dahinter ein. Nur ein Stoppwort oder SPRECHEN_UNTERBRECHEN=1 bricht ab
        stoppwort = ist_stoppwort(prompt)
        if stoppwort or os.environ.get("SPRECHEN_UNTERBRECHEN") == "1":
            ausgabe_stoppen(sitzung, quelle, entfernt, fremd=stoppwort)
        if stoppwort:
            # Claude bekommt das Stoppwort nicht; der Grund steht nur für den Nutzer da
            print(json.dumps({"decision": "block", "reason": "Gesprächsmodus: Ausgabe gestoppt."},
                             ensure_ascii=False))
        return 0

    if args.ereignis == "notification":
        text = hinweis(eingabe)
    elif modus_lesen(sitzung) in ("aus", "datei"):
        # Eine Marke trotz /sprechen aus, etwa zitiert; im Datei-Modus käme sie doppelt
        text = ""
    else:
        text = gesprochener_text(str(eingabe.get("last_assistant_message", "")))
        if not text and not pausiert(eingabe) and gespraechsmodus(eingabe) == "an":
            # Die Zeile zählt, wie oft Claude die Marke vergisst
            protokollieren(f"Antwort ohne Sprechmarke, Ersatzsatz ({_kennung(sitzung)})")
            text = ERSATZ
    if text:
        sprechen_lassen(eingabe, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
