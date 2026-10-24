"""
test_hoerfassung.py - Hoerfassung und Pruefung gegen erwartete Ausgaben

Erzeugt das Test-PDF (beispiel_pdf.py), schickt es wie vorlesen.sh durch
hoerfassung.py, danach durch pruefen.py, und vergleicht beide Ausgaben Zeichen
fuer Zeichen mit tests/erwartet/. Die Vertonung bleibt aussen vor: Sie braucht
MLX und rund 2 GB Modelle, die Hoerfassung nur PyMuPDF.

Usage:
    .venv/bin/python -m unittest discover -s tests -v
    ERWARTUNG_NEU=1 .venv/bin/python -m unittest discover -s tests

ERWARTUNG_NEU=1 schreibt die erwarteten Ausgaben neu, nach einer gewollten
Aenderung an der Hoerfassung. Danach den Unterschied mit git diff lesen: Jede
geaenderte Zeile muss genau diese Aenderung sein, sonst ist es ein Fehler.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from beispiel_pdf import erzeuge

REPO = Path(__file__).resolve().parent.parent
ERWARTET = REPO / "tests" / "erwartet"
NEU = os.environ.get("ERWARTUNG_NEU") == "1"


def _werkzeug(name: str, *args: str) -> str:
    lauf = subprocess.run([sys.executable, str(REPO / "werkzeuge" / name), *args],
                          capture_output=True, text=True, check=False)
    if lauf.returncode != 0:
        raise AssertionError(f"{name} endete mit {lauf.returncode}:\n{lauf.stderr}")
    return lauf.stdout


class Hoerfassung(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        pdf = tmp / "beispiel.pdf"
        erzeuge(pdf)
        cls.hoerfassung_pfad = tmp / "beispiel_hoerfassung.txt"
        _werkzeug("hoerfassung.py", str(pdf), "-o", str(cls.hoerfassung_pfad))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _vergleiche(self, ist: str, datei: str) -> None:
        pfad = ERWARTET / datei
        if NEU:
            pfad.write_text(ist, encoding="utf-8")
            return
        self.assertEqual(pfad.read_text(encoding="utf-8"), ist)

    def test_hoerfassung(self) -> None:
        self._vergleiche(self.hoerfassung_pfad.read_text(encoding="utf-8"), "hoerfassung.txt")

    def test_pruefen(self) -> None:
        self._vergleiche(_werkzeug("pruefen.py", str(self.hoerfassung_pfad)), "pruefen.txt")


if __name__ == "__main__":
    unittest.main()
