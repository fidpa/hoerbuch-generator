#!/bin/bash
# einrichten.sh - Python-Umgebung .venv für vorlesen.sh anlegen (einmalig, etwa 1,5 GB)
#
# Braucht: Mac mit Apple Silicon, Python 3.10 bis 3.12 (oder uv), ffmpeg.
# Die Sprachmodelle (rund 2 GB) lädt erst der erste Aufruf von vorlesen.sh.

set -uo pipefail

ORDNER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly ORDNER
readonly VENV="${ORDNER}/.venv"

fehler() { echo "FEHLER: $*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]] \
    || fehler "Nur auf einem Mac mit Apple Silicon (M1 oder neuer): Qwen läuft über MLX auf der GPU."
command -v ffmpeg >/dev/null 2>&1 || fehler "ffmpeg fehlt: brew install ffmpeg"
command -v pandoc >/dev/null 2>&1 || echo "Hinweis: pandoc fehlt (brew install pandoc), nur nötig für .md, .docx, .odt, .epub" >&2

if command -v uv >/dev/null 2>&1; then
    echo "Lege ${VENV} mit uv an ..."
    uv venv -q --python 3.12 "${VENV}" || fehler "uv venv scheiterte"
    uv pip install -q --python "${VENV}/bin/python" -r "${ORDNER}/requirements.txt" || fehler "Installation scheiterte"
else
    py=""
    for kandidat in python3.12 python3.11 python3.10; do
        command -v "${kandidat}" >/dev/null 2>&1 && { py="${kandidat}"; break; }
    done
    [[ -n "${py}" ]] || fehler "Python 3.10 bis 3.12 fehlt: brew install python@3.12 (oder uv: brew install uv)"
    echo "Lege ${VENV} mit ${py} an ..."
    "${py}" -m venv "${VENV}" || fehler "venv scheiterte"
    "${VENV}/bin/pip" install -q --upgrade pip && "${VENV}/bin/pip" install -q -r "${ORDNER}/requirements.txt" \
        || fehler "Installation scheiterte"
fi

"${VENV}/bin/python" -c 'import mlx_audio, torch, librosa, soundfile, fitz' || fehler "Pakete nicht importierbar"
echo "Fertig. Test: echo 'Das ist ein Test.' > /tmp/test.txt && ${ORDNER}/vorlesen.sh /tmp/test.txt"
echo "Der erste Aufruf lädt die Sprachmodelle (rund 2 GB) und dauert deshalb einige Minuten."
