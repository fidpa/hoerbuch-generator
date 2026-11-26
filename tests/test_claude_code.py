"""
test_claude_code.py - Hook-Skript für Claude Code: Sprechmarke finden, Aufruf von sprechen.sh

Der Sprechdienst wird nicht gestartet. HOERBUCH_GENERATOR zeigt auf ein Verzeichnis mit
einem falschen sprechen.sh, das seine Argumente und stdin mitschreibt. Nur Standardbibliothek,
läuft deshalb auch in der CI ohne MLX.

Usage:
    .venv/bin/python -m unittest tests.test_claude_code -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKRIPT = Path(__file__).resolve().parent.parent / "integrationen" / "claude-code" / "claude_sprechen.py"
sys.path.insert(0, str(SKRIPT.parent))

from claude_sprechen import ansage, gesprochener_text  # noqa: E402


class Marke(unittest.TestCase):
    def test_ohne_marke_nichts(self):
        self.assertEqual(gesprochener_text("Nur eine Antwort mit `code`."), "")
        self.assertEqual(gesprochener_text(""), "")

    def test_marke_wird_gefunden_und_zusammengezogen(self):
        antwort = "Tabelle …\n\n<!-- sprechen:\n  Erster Satz.\n  Zweiter Satz.\n-->"
        self.assertEqual(gesprochener_text(antwort), "Erster Satz. Zweiter Satz.")

    def test_letzte_marke_gewinnt(self):
        self.assertEqual(gesprochener_text("<!-- sprechen: alt -->\nText\n<!-- Sprechen : neu -->"),
                         "neu")


class Ansage(unittest.TestCase):
    def test_projektordner_und_geglaetteter_name(self):
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": "/x/repos/hoerbuch-generator"}):
            self.assertEqual(ansage({"cwd": "/x/repos/hoerbuch-generator/tests"}),
                             "Aus Hoerbuch generator.")

    def test_ohne_ordner_keine_ansage(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ansage({}), "")


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cc"))
        self.protokoll = self.tmp / "aufruf.txt"
        (self.tmp / "sprechen.sh").write_text(
            f'printf "%s\\n" "$*" > "{self.protokoll}"\ncat >> "{self.protokoll}"\n',
            encoding="utf-8")

    def tearDown(self):
        for datei in self.tmp.iterdir():
            datei.unlink()
        self.tmp.rmdir()

    def _lauf(self, ereignis: str, eingabe: dict, env: dict | None = None) -> tuple[int, str]:
        lauf = subprocess.run([sys.executable, str(SKRIPT), ereignis], input=json.dumps(eingabe),
                              text=True, capture_output=True,
                              env={"HOERBUCH_GENERATOR": str(self.tmp), "PATH": "/usr/bin:/bin",
                                   **(env or {})})
        aufruf = self.protokoll.read_text(encoding="utf-8") if self.protokoll.exists() else ""
        return lauf.returncode, aufruf

    def test_stop_spricht_den_markierten_text(self):
        rc, aufruf = self._lauf("stop", {"last_assistant_message": "Text\n<!-- sprechen: Hallo. -->"})
        self.assertEqual(rc, 0)
        self.assertEqual(aufruf, "-v marketing -t 1.1 --lauter 8 -\nHallo.")

    def test_einstellungen_aus_der_umgebung(self):
        rc, aufruf = self._lauf("stop", {"last_assistant_message": "<!-- sprechen: Hallo. -->"},
                                {"SPRECHEN_STIMME": "dozent", "SPRECHEN_TEMPO": "1.2",
                                 "SPRECHEN_LAUTER": "12"})
        self.assertEqual(rc, 0)
        self.assertEqual(aufruf, "-v dozent -t 1.2 --lauter 12 -\nHallo.")

    def test_stop_ohne_marke_ruft_nichts_auf(self):
        rc, aufruf = self._lauf("stop", {"last_assistant_message": "Nur Text."})
        self.assertEqual(rc, 0)
        self.assertEqual(aufruf, "")

    def test_prompt_stoppt_nur_die_eigene_sitzung(self):
        rc, aufruf = self._lauf("prompt", {"prompt": "Weiter", "session_id": "abc"})
        self.assertEqual(rc, 0)
        self.assertEqual(aufruf, "--stopp --quelle abc\n")

    def test_sitzung_und_projekt_beim_sprechen(self):
        rc, aufruf = self._lauf("stop", {"session_id": "abc", "cwd": "/x/projekte/notizen",
                                         "last_assistant_message": "<!-- sprechen: Hallo. -->"})
        self.assertEqual(rc, 0)
        self.assertEqual(aufruf, "-v marketing -t 1.1 --lauter 8 --quelle abc --ansage Aus Notizen. -\nHallo.")

    def test_falsches_ereignis_sperrt_keine_eingabe(self):
        # Exit 2 bei UserPromptSubmit verwirft die Eingabe; argparse endet bei einem
        # falschen Argument genau so
        for argumente in ([], ["Stop"], ["prompt", "zuviel"]):
            lauf = subprocess.run([sys.executable, str(SKRIPT), *argumente], input="{}",
                                  text=True, capture_output=True,
                                  env={"HOERBUCH_GENERATOR": str(self.tmp), "PATH": "/usr/bin:/bin"})
            self.assertEqual(lauf.returncode, 0, argumente)

    def test_kaputte_eingabe_bricht_nicht_ab(self):
        lauf = subprocess.run([sys.executable, str(SKRIPT), "stop"], input="[1, 2]", text=True,
                              capture_output=True,
                              env={"HOERBUCH_GENERATOR": str(self.tmp), "PATH": "/usr/bin:/bin"})
        self.assertEqual(lauf.returncode, 0)

    def test_fehlender_generator_bricht_nicht_ab(self):
        lauf = subprocess.run([sys.executable, str(SKRIPT), "stop"],
                              input=json.dumps({"last_assistant_message": "<!-- sprechen: x -->"}),
                              text=True, capture_output=True,
                              env={"HOERBUCH_GENERATOR": str(self.tmp / "fehlt"),
                                   "PATH": "/usr/bin:/bin"})
        self.assertEqual(lauf.returncode, 0)
        self.assertIn("sprechen.sh fehlt", lauf.stderr)


if __name__ == "__main__":
    unittest.main()
