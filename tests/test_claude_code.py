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


class Fernbetrieb(unittest.TestCase):
    """SPRECHEN_ENTFERNT: ein falsches ssh schreibt seine Argumente mit und liefert "PCM",
    ein Player per SPRECHEN_PLAYER schreibt, was er bekommt, in eine Datei."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fern"))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.protokoll, self.eingabe, self.ausgabe = (self.tmp / n for n in
                                                      ("ssh.txt", "stdin.txt", "ton.raw"))
        ssh = self.bin / "ssh"
        ssh.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$PROTOKOLL"\n'
                       'case "$*" in *--liefern*) cat > "$EINGABE"; printf PCM;; esac\n',
                       encoding="utf-8")
        ssh.chmod(0o755)
        self.env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.tmp),
                    "XDG_RUNTIME_DIR": str(self.tmp / "run"), "SPRECHEN_ENTFERNT": "mac",
                    "SPRECHEN_PLAYER": "/bin/sh -c 'cat > \"$AUSGABE\"'",
                    "PROTOKOLL": str(self.protokoll), "EINGABE": str(self.eingabe),
                    "AUSGABE": str(self.ausgabe)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _lauf(self, ereignis: str, eingabe: dict) -> int:
        return subprocess.run([sys.executable, str(SKRIPT), ereignis], input=json.dumps(eingabe),
                              text=True, capture_output=True, env=self.env,
                              timeout=20).returncode

    def _warten_auf(self, datei: Path) -> bytes:
        import time
        frist = time.monotonic() + 10
        while time.monotonic() < frist:
            if datei.exists() and datei.stat().st_size:
                time.sleep(0.1)  # der Player schreibt noch zu Ende
                return datei.read_bytes()
            time.sleep(0.05)
        return b""

    def test_stop_rechnet_entfernt_und_spielt_hier(self):
        rc = self._lauf("stop", {"session_id": "abc",
                                 "last_assistant_message": "<!-- sprechen: Hallo. -->"})
        self.assertEqual(rc, 0)
        self.assertEqual(self._warten_auf(self.ausgabe), b"PCM")
        self.assertEqual(self.eingabe.read_text(encoding="utf-8"), "Hallo.")
        aufruf = self.protokoll.read_text(encoding="utf-8")
        self.assertIn("-o BatchMode=yes", aufruf)
        self.assertIn("--quelle abc", aufruf)
        self.assertTrue(aufruf.rstrip().endswith("--liefern -"), aufruf)

    def test_prompt_beendet_nur_die_eigene_wiedergabe_und_stoppt_dort(self):
        import claude_sprechen
        run = self.tmp / "run" / "hoerbuch-generator"
        run.mkdir(parents=True)
        # "claude_sprechen" im Aufruf: Unter Linux prüft der Hook das per /proc
        laufend = {q: subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)",
                                        "claude_sprechen"], start_new_session=True)
                   for q in ("abc", "andere")}
        for q, p in laufend.items():
            (run / f"laeuft-{claude_sprechen._kennung(q)}-{p.pid}").touch()
        try:
            self.assertEqual(self._lauf("prompt", {"session_id": "abc"}), 0)
            self.assertIsNotNone(laufend["abc"].wait(timeout=5))
            self.assertIsNone(laufend["andere"].poll())
        finally:
            for p in laufend.values():
                p.kill()
                p.wait()
        self.assertIn("--stopp --quelle abc", self.protokoll.read_text(encoding="utf-8"))

    def test_fremde_pid_wird_nicht_beendet(self):
        # Eine Marke, deren PID inzwischen einem anderen Prozess gehört, auf Linux wie macOS
        import claude_sprechen
        fremd = subprocess.Popen(["sleep", "30"])
        eigen = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)",
                                  "claude_sprechen"])
        try:
            self.assertFalse(claude_sprechen._gehoert_uns(fremd.pid))
            self.assertTrue(claude_sprechen._gehoert_uns(eigen.pid))
        finally:
            for p in (fremd, eigen):
                p.kill()
                p.wait()

    def test_prompt_ohne_wiedergabe_baut_keine_verbindung_auf(self):
        # Sonst kostete jede Eingabe einen ssh-Aufbau, bei schlafendem Mac bis zum Timeout
        self.assertEqual(self._lauf("prompt", {"session_id": "abc"}), 0)
        self.assertFalse(self.protokoll.exists())

    def test_befehl_quotet_fuer_die_shell_dort(self):
        import claude_sprechen
        with mock.patch.dict(os.environ, {"SPRECHEN_ENTFERNT_REPO": "~/Repos/mein repo"}):
            befehl = claude_sprechen.entfernter_befehl("mac", ["--ansage", "Aus X.", "-"])
        self.assertEqual(befehl[-2], "mac")
        self.assertEqual(befehl[-1], "\"$HOME\"/'Repos/mein repo/sprechen.sh' --ansage 'Aus X.' -")

    def test_player_der_erste_vorhandene(self):
        import claude_sprechen
        aplay = self.bin / "aplay"
        aplay.write_text("#!/bin/sh\n", encoding="utf-8")
        aplay.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": str(self.bin)}), \
                mock.patch.dict(os.environ, {}, clear=False) as umgebung:
            umgebung.pop("SPRECHEN_PLAYER", None)
            self.assertEqual(claude_sprechen.player_befehl()[0], "aplay")


if __name__ == "__main__":
    unittest.main()
