#!/bin/bash
# vorlesen.sh - Text zu Hörbuch (MP3) mit Qwen3-TTS, lokal auf einem Mac mit Apple Silicon
#
# Usage:
#   ./vorlesen.sh text.txt                 # -> text.mp3 daneben
#   ./vorlesen.sh skript.pdf               # PDF: erst Hörfassung skript_hoerfassung.txt, dann MP3
#   ./vorlesen.sh -v dozent text.txt       # andere Stimme aus stimmen/
#   ./vorlesen.sh -t 1.0 text.txt          # ohne Beschleunigung
#   ./vorlesen.sh kapitel*.txt             # mehrere Dateien, je eine MP3
#
# Einmalig vorher: ./einrichten.sh

set -uo pipefail

ORDNER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly ORDNER
readonly PY="${ORDNER}/.venv/bin/python"
readonly STANDARD_STIMME="erzaehler"
# Qwen spricht rund 125 Wörter pro Minute; 1.20 ergibt rund 150 (Tonhöhe bleibt gleich)
readonly STANDARD_TEMPO="1.20"

TMP_DIR=""
# Modelle sind öffentlich; ohne das mahnt Hugging Face bei jedem Lauf einen Token an
export HF_HUB_VERBOSITY=error

info()   { echo "$(date '+%H:%M:%S') $*" >&2; }
fehler() { echo "$(date '+%H:%M:%S') FEHLER: $*" >&2; }

aufraeumen() {
    [[ -n "${TMP_DIR}" && -d "${TMP_DIR}" ]] && rm -rf "${TMP_DIR}"
}
trap aufraeumen EXIT
trap 'exit 130' INT TERM

hilfe() {
    cat <<'EOF'
vorlesen.sh - Text zu Hörbuch (MP3) mit Qwen3-TTS

Verwendung:
  ./vorlesen.sh [-v STIMME] [-t TEMPO] [-o AUSGABE.mp3] [--mit-atem] DATEI [DATEI ...]

Optionen:
  -v, --stimme NAME   Stimme aus stimmen/ (Standard: erzaehler; -l zeigt alle)
  -t, --tempo FAKTOR  Sprechtempo, 0.5 bis 2.0 (Standard: 1.20, rund 150 Wörter pro Minute)
  -o, --ausgabe DATEI Ausgabepfad (nur bei genau einer Eingabedatei)
      --mit-atem      Atemgeräusche nicht absenken
  -l, --liste         vorhandene Stimmen zeigen
  -h, --hilfe         diese Hilfe

Eingabe: .txt direkt | .md .docx .odt .epub über pandoc | .pdf über werkzeuge/hoerfassung.py
EOF
}

stimmen_liste() {
    local f
    for f in "${ORDNER}"/stimmen/*.wav; do
        basename "${f}" .wav
    done
}

# Eingabe -> Textdatei für qwen.py; Pfad auf stdout
text_aus() {
    local src="$1" ext
    ext="$(printf '%s' "${src##*.}" | tr '[:upper:]' '[:lower:]')"
    case "${ext}" in
        pdf)
            local hoer="${src%.*}_hoerfassung.txt"
            # Vorhandene Hoerfassung nutzen: sie kann von Hand korrigiert sein
            if [[ -s "${hoer}" ]]; then
                info "Nutze vorhandene Hörfassung ${hoer} (zum Neuerzeugen löschen)"
            else
                info "Hörfassung: ${hoer}"
                "${PY}" "${ORDNER}/werkzeuge/hoerfassung.py" "${src}" -o "${hoer}" >&2 || return 1
            fi
            echo "${hoer}"
            ;;
        md|markdown|docx|odt|epub)
            command -v pandoc >/dev/null 2>&1 || { fehler "pandoc fehlt (brew install pandoc), nötig für .${ext}"; return 1; }
            # --wrap=none: eine Zeile je Absatz; qwen.py liest Zeilen als Absätze
            pandoc "${src}" -t plain --wrap=none -o "${TMP_DIR}/text.txt" 2>/dev/null || { fehler "pandoc scheiterte: ${src}"; return 1; }
            echo "${TMP_DIR}/text.txt"
            ;;
        *)
            echo "${src}"
            ;;
    esac
}

vertonen() {
    local src="$1" ziel="$2" stimme="$3" tempo="$4" atem="$5" text
    [[ -s "${src}" ]] || { fehler "Datei fehlt oder ist leer: ${src}"; return 1; }
    text="$(text_aus "${src}")" || return 1

    # Fertige Stücke neben der MP3, nicht im Temp-Verzeichnis: Nach einem Abbruch setzt
    # derselbe Aufruf dort fort. Gelöscht wird der Ordner erst mit der fertigen MP3.
    local stuecke="${ziel%.*}.stuecke"
    local -a opts=(--voice "${stimme}" --stuecke "${stuecke}")
    [[ "${atem}" == "1" ]] && opts+=(--keep-breath)
    info "Vertonung: ${src} (Stimme ${stimme}, Tempo ${tempo})"
    "${PY}" "${ORDNER}/werkzeuge/qwen.py" "${opts[@]}" "${text}" "${TMP_DIR}/audio.wav" || { fehler "Vertonung scheiterte: ${src}"; return 1; }

    local -a filter=()
    [[ "${tempo}" != "1" && "${tempo}" != "1.0" && "${tempo}" != "1.00" ]] && filter=(-af "atempo=${tempo}")
    ffmpeg -v error -y -i "${TMP_DIR}/audio.wav" "${filter[@]+"${filter[@]}"}" -codec:a libmp3lame -q:a 2 "${ziel}" \
        || { fehler "MP3 scheiterte: ${src}"; return 1; }
    rm -f "${TMP_DIR}/audio.wav" "${TMP_DIR}/text.txt"
    rm -rf "${stuecke}"
    info "Fertig: ${ziel} ($(du -h "${ziel}" | cut -f1))"
}

main() {
    local stimme="${STANDARD_STIMME}" tempo="${STANDARD_TEMPO}" ausgabe="" atem=0
    local -a eingaben=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -v|--stimme)  stimme="${2:?Stimme fehlt nach $1}"; shift 2 ;;
            -t|--tempo)   tempo="${2:?Tempo fehlt nach $1}"; shift 2 ;;
            -o|--ausgabe) ausgabe="${2:?Ausgabepfad fehlt nach $1}"; shift 2 ;;
            --mit-atem)   atem=1; shift ;;
            -l|--liste)   stimmen_liste; exit 0 ;;
            -h|--hilfe)   hilfe; exit 0 ;;
            -*)           fehler "Unbekannte Option: $1"; hilfe; exit 1 ;;
            *)            eingaben+=("$1"); shift ;;
        esac
    done

    [[ ${#eingaben[@]} -gt 0 ]] || { hilfe; exit 1; }
    [[ -z "${ausgabe}" || ${#eingaben[@]} -eq 1 ]] || { fehler "-o geht nur bei genau einer Eingabedatei"; exit 1; }
    [[ -x "${PY}" ]] || { fehler "Umgebung fehlt, zuerst ./einrichten.sh ausführen"; exit 1; }
    command -v ffmpeg >/dev/null 2>&1 || { fehler "ffmpeg fehlt (brew install ffmpeg)"; exit 1; }
    [[ -f "${ORDNER}/stimmen/${stimme}.wav" ]] || { fehler "Stimme '${stimme}' fehlt; vorhanden: $(stimmen_liste | tr '\n' ' ')"; exit 1; }
    awk -v t="${tempo}" 'BEGIN { exit !(t+0 >= 0.5 && t+0 <= 2.0) }' || { fehler "Tempo ${tempo} liegt nicht zwischen 0.5 und 2.0"; exit 1; }

    TMP_DIR="$(mktemp -d -t vorlesen.XXXXXX)" || { fehler "Temp-Verzeichnis nicht anlegbar"; exit 1; }

    local rc=0 src
    for src in "${eingaben[@]}"; do
        vertonen "${src}" "${ausgabe:-${src%.*}.mp3}" "${stimme}" "${tempo}" "${atem}" || rc=1
    done
    exit "${rc}"
}

main "$@"
