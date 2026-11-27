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

Fernbetrieb, etwa auf Linux ohne MLX: Mit SPRECHEN_ENTFERNT=<ssh-ziel> rechnet der Mac
dieses ssh-Ziels (sprechen.sh --liefern), und ein lokaler Player spielt den Ton hier ab:
    SPRECHEN_ENTFERNT       ssh-Ziel, etwa ein Host aus ~/.ssh/config
    SPRECHEN_ENTFERNT_REPO  Ort dieses Repos dort (Standard: derselbe Pfad unter ~ wie hier)
    SPRECHEN_PLAYER         Player-Befehl, der 16-Bit-PCM (24 kHz, mono) von stdin spielt;
                            sonst der erste von paplay, pw-play, aplay, ffplay
Der Stop-Hook übergibt die Wiedergabe einem eigenen Hintergrundprozess und kehrt sofort
zurück. Eine Sperre unter XDG_RUNTIME_DIR (sonst ~/.cache) hält mehrere Sitzungen dieses
Geräts in der Reihe; der Prompt-Hook beendet die Wiedergabe der eigenen Sitzung hier und
stoppt den Auftrag auf dem Mac. Läuft für die Sitzung nichts, unterbleibt der ssh-Aufruf.

Ton auf dem Gerät, an dem gerade gearbeitet wird, etwa wenn Claude Code auf einem Server oder
einem anderen Mac läuft und nur die Oberfläche hier ist (Terminal per ssh, T3 Code):
    SPRECHEN_GERAETE   Geräte, die den Ton abspielen dürfen, durch Leerzeichen getrennt: ssh-Ziele
                       oder "hier" für dieses Gerät. Vor jeder Antwort fragt der Hook alle nach
                       der Zeit seit der letzten Eingabe an Tastatur oder Maus (macOS: ioreg,
                       Linux mit GNOME: Mutter IdleMonitor) und spielt auf dem zuletzt benutzten.
    SPRECHEN_LEERLAUF  Sekunden; ist jedes Gerät länger unbenutzt, bleibt die Antwort stumm
                       (Standard: 1800). Dann wird woanders gearbeitet, etwa am Handy.
Auf einem anderen Gerät spielt paplay oder ffplay, aufgerufen über ssh. Ohne SPRECHEN_ENTFERNT
rechnet dieses Gerät selbst; fällt die Wahl auf "hier", spielt der Dienst wie gewohnt.

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
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MARKE = re.compile(r"<!--\s*sprechen\s*:(.*?)-->", re.DOTALL | re.IGNORECASE)
STIMME = "marketing"
TEMPO = "1.1"
LAUTER = "8"
TIMEOUT = 30  # Sekunden; sprechen.sh kehrt nach dem Annehmen des Auftrags zurück
# Fernbetrieb: Der Prompt-Hook hat 10 s; ssh darf ihn nicht aufbrauchen, wenn der Mac schläft
SSH_OPTIONEN = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=4"]
STOPP_TIMEOUT = 8
# Format von sprechen.sh --liefern
PLAYER = [
    ["paplay", "--raw", "--rate=24000", "--channels=1", "--format=s16le"],
    ["pw-play", "--raw", "--rate", "24000", "--channels", "1", "--format", "s16", "-"],
    ["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", "24000", "-c", "1"],
    ["ffplay", "-nodisp", "-nostats", "-autoexit", "-loglevel", "error",
     "-f", "s16le", "-ar", "24000", "-ch_layout", "mono", "-"],
]
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
FERN_PLAYER = (
    'PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"; '
    "if command -v paplay >/dev/null 2>&1; then "
    "exec paplay --raw --rate=24000 --channels=1 --format=s16le; "
    "elif command -v ffplay >/dev/null 2>&1; then "
    "exec ffplay -nodisp -nostats -autoexit -loglevel error -f s16le -ar 24000 -ch_layout mono -; "
    "else echo 'kein Player (paplay, ffplay)' >&2; exit 127; fi")

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


# --- Fernbetrieb -------------------------------------------------------------------------

def entfernter_befehl(ziel: str, args: list[str]) -> list[str]:
    """ssh-Aufruf von sprechen.sh auf dem Mac. ssh fügt die Argumente zu einer Zeile für die
    Shell dort zusammen, deshalb ist jedes einzeln gequotet; ~ wird zu "$HOME", damit es
    dort aufgelöst wird und nicht hier."""
    repo = os.environ.get("SPRECHEN_ENTFERNT_REPO") or _repo_unter_home()
    if repo.startswith("~/"):
        pfad = '"$HOME"/' + shlex.quote(repo[2:] + "/sprechen.sh")
    else:
        pfad = shlex.quote(repo.rstrip("/") + "/sprechen.sh")
    return ["ssh", *SSH_OPTIONEN, ziel, " ".join([pfad, *map(shlex.quote, args)])]


def _repo_unter_home() -> str:
    try:
        return "~/" + str(REPO.relative_to(Path.home()))
    except ValueError:
        return str(REPO)


def player_befehl() -> list[str] | None:
    eigener = os.environ.get("SPRECHEN_PLAYER")
    if eigener:
        return shlex.split(eigener)
    return next((p for p in PLAYER if shutil.which(p[0])), None)


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
    try:
        geraet = None
        if geraete():
            geraet = geraet_waehlen(geraete())
            if geraet is None:
                log.info("kein Gerät in Benutzung, die Antwort bleibt stumm")
                return 0
            if geraet == HIER and not ziel:
                # Rechnet und spielt dieses Gerät, spielt der Dienst selbst wie ohne Gerätewahl
                return aufrufen([*auftrag["args"], "-"], auftrag["text"])
        player = player_befehl() if geraet in (None, HIER) else ["ssh", *SSH_OPTIONEN, geraet,
                                                                 FERN_PLAYER]
        if not player:
            log.error("kein Player (paplay, pw-play, aplay, ffplay, SPRECHEN_PLAYER)")
            return 1
        with open(ordner / "wiedergabe.lock", "w") as sperre:
            # Zwei Sitzungen auf diesem Gerät: Der Mac liefert schneller, als der Player
            # spielt, und beide Antworten klängen sonst übereinander
            fcntl.flock(sperre, fcntl.LOCK_EX)
            ssh = subprocess.Popen(rechen_befehl([*auftrag["args"], "--liefern", "-"]),
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            spieler = subprocess.Popen(player, stdin=ssh.stdout)
            ssh.stdout.close()  # nur der Player liest; endet er, bekommt ssh SIGPIPE
            try:
                ssh.stdin.write(auftrag["text"].encode())
                ssh.stdin.close()
            except BrokenPipeError:
                pass
            spieler.wait()
            ssh.wait()
            # Endet der Player vorzeitig, stirbt ssh an SIGPIPE; das ist kein Fehler des Macs
            if spieler.returncode == 0 and ssh.returncode != 0:
                log.error("sprechen.sh auf %s endete mit %s", ziel or HIER, ssh.returncode)
            elif spieler.returncode != 0:
                log.error("Player %s endete mit %s", player[0], spieler.returncode)
    finally:
        marke.unlink(missing_ok=True)
    return 0


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude-Code-Hooks für den Sprechdienst")
    # abspielen ist intern: der Hintergrundprozess des Fernbetriebs
    parser.add_argument("ereignis", choices=["stop", "prompt", "abspielen"])
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

    if args.ereignis == "abspielen":
        try:
            return abspielen(eingabe)
        except (OSError, KeyError, TypeError) as e:
            log.error("Wiedergabe gescheitert: %s", e)
            return 1

    # Hooks gelten meist global. Ohne Sitzungskennung bräche eine Eingabe in einer zweiten
    # Sitzung die Antwort der ersten ab
    sitzung = str(eingabe.get("session_id") or "")
    quelle = ["--quelle", sitzung] if sitzung else []
    entfernt = os.environ.get("SPRECHEN_ENTFERNT", "")

    if args.ereignis == "prompt":
        if not entfernt:
            # Mit Gerätewahl läuft die Wiedergabe womöglich als Hintergrundprozess; ohne Marke
            # kostet das nur einen Blick in den Ordner
            wiedergabe_stoppen(sitzung)
            aufrufen(["--stopp", *quelle])
            return 0
        # Erst hier verstummen, das geht sofort; dann den Auftrag auf dem Mac abbrechen.
        # Ohne Marke läuft für diese Sitzung nichts, auch dort nicht: Der Hintergrundprozess
        # lebt, bis ssh endet. ssh bei jeder Eingabe kostete sonst jedes Mal den Aufbau,
        # bei schlafendem Mac bis zum ConnectTimeout
        if not wiedergabe_stoppen(sitzung):
            return 0
        try:
            subprocess.run(entfernter_befehl(entfernt, ["--stopp", *quelle]),
                           capture_output=True, timeout=STOPP_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.error("Stopp auf %s gescheitert: %s", entfernt, e)
        return 0

    text = gesprochener_text(str(eingabe.get("last_assistant_message", "")))
    if text:
        name = ansage(eingabe) if quelle else ""
        sprechen = ["-v", os.environ.get("SPRECHEN_STIMME", STIMME),
                    "-t", os.environ.get("SPRECHEN_TEMPO", TEMPO),
                    "--lauter", os.environ.get("SPRECHEN_LAUTER", LAUTER), *quelle,
                    *(["--ansage", name] if name else [])]
        if entfernt or geraete():
            try:
                wiedergabe_starten(sprechen, text, sitzung)
            except OSError as e:
                log.error("Wiedergabe nicht startbar: %s", e)
        else:
            aufrufen([*sprechen, "-"], text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
