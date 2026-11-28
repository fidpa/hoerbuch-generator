#!/bin/bash
# sprechen.sh - Text sofort sprechen lassen, mit Qwen3-TTS lokal auf einem Mac mit Apple Silicon
#
# Usage:
#   ./sprechen.sh "Hallo, ich bin gleich fertig."   # sprechen, sofort zurück
#   echo "Text" | ./sprechen.sh                     # Text von stdin
#   ./sprechen.sh -v dozent -t 1.1 "Text"           # andere Stimme, anderes Tempo
#   ./sprechen.sh --lauter 8 "Text"                 # 8 dB lauter, etwa gegen Musik
#   ./sprechen.sh --warten "Text"                   # warten und Zeiten zeigen
#   ./sprechen.sh --liefern "Text" | <player>       # Ton als PCM nach stdout, etwa über ssh
#   ./sprechen.sh --datei "Text"                    # als MP3 ablegen, Pfad ausgeben
#   ./sprechen.sh --quelle ID --ansage "Aus X." -   # Kennung des Aufrufers mitgeben
#   ./sprechen.sh --stopp [--quelle ID [--sonst-aktuell]] | --status | --beenden
#
# Der erste Aufruf startet einen Dienst, der das Modell geladen hält; nach 20 Minuten
# ohne Auftrag beendet er sich (SPRECHDIENST_LEERLAUF in Sekunden setzt eine andere Zeit).
# Für lange Texte und MP3: vorlesen.sh.
# Alle Optionen: ./sprechen.sh -h
# Einmalig vorher: ./einrichten.sh

set -uo pipefail

ORDNER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly ORDNER
readonly PY="${ORDNER}/.venv/bin/python"

[[ -x "${PY}" ]] || { echo "FEHLER: Umgebung fehlt, zuerst ./einrichten.sh ausführen" >&2; exit 1; }
# Modelle sind öffentlich; ohne das mahnt Hugging Face bei jedem Lauf einen Token an
export HF_HUB_VERBOSITY=error
# Über ssh fehlt Homebrew im PATH. Ein so gestarteter Dienst fände ffmpeg nicht und spräche
# ohne Tempo und Anhebung; er erbt den PATH dieses Aufrufs
[[ -d /opt/homebrew/bin && ":${PATH}:" != *":/opt/homebrew/bin:"* ]] && PATH="/opt/homebrew/bin:${PATH}"
exec "${PY}" "${ORDNER}/werkzeuge/sprechdienst.py" "$@"
