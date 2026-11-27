"""
test_claude_code.py - Hook-Skript für Claude Code: Sprechmarke finden, Aufruf von sprechen.sh

Der Sprechdienst wird nicht gestartet. HOERBUCH_GENERATOR zeigt auf ein Verzeichnis mit
einem falschen sprechen.sh, das seine Argumente und stdin mitschreibt. Nur Standardbibliothek,
läuft deshalb auch in der CI ohne MLX.

Usage:
    .venv/bin/python -m unittest tests.test_claude_code -v
"""

import io
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

# So steht der Kontext des SessionStart-Hooks im Transkript einer Sitzung
START = {"type": "attachment", "attachment": {"type": "hook_additional_context", "content": [
    "Der Gesprächsmodus ist in dieser Sitzung von Anfang an eingeschaltet (SessionStart-Hook "
    "des Hörbuch-Generators) …"]}}


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

    def _prompt(self, text: str, env: dict | None = None) -> tuple[str, str]:
        lauf = subprocess.run([sys.executable, str(SKRIPT), "prompt"],
                              input=json.dumps({"prompt": text, "session_id": "abc"}),
                              text=True, capture_output=True,
                              env={"HOERBUCH_GENERATOR": str(self.tmp), "PATH": "/usr/bin:/bin",
                                   **(env or {})})
        self.assertEqual(lauf.returncode, 0)
        aufruf = self.protokoll.read_text(encoding="utf-8") if self.protokoll.exists() else ""
        return aufruf, lauf.stdout

    def test_neue_eingabe_laesst_zu_ende_sprechen(self):
        self.assertEqual(self._prompt("Weiter"), ("", ""))

    def test_stoppwort_stoppt_die_eigene_sitzung_und_erreicht_claude_nicht(self):
        for wort in ("Psst.", "  still ", "RUHE!", "pst", "Pssst!", "Psssst..."):
            self.protokoll.unlink(missing_ok=True)
            aufruf, ausgabe = self._prompt(wort)
            self.assertEqual(aufruf, "--stopp --quelle abc\n", wort)
            self.assertEqual(json.loads(ausgabe)["decision"], "block", wort)

    def test_stopp_und_saetze_sind_keine_stoppwoerter(self):
        # „Stopp“ soll Claude erreichen, etwa um eine laufende Arbeit anzuhalten
        for text in ("Stopp", "stop", "Psst, eine Frage noch", "still und leise"):
            self.assertEqual(self._prompt(text), ("", ""), text)

    def test_unterbrechen_wie_bis_0_6_1(self):
        aufruf, ausgabe = self._prompt("Weiter", {"SPRECHEN_UNTERBRECHEN": "1"})
        self.assertEqual(aufruf, "--stopp --quelle abc\n")
        self.assertEqual(ausgabe, "")

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

    # --- notification: fester Satz, wenn Claude wartet und der Modus an ist ---------------

    def _transkript(self, *eintraege: dict) -> str:
        datei = self.tmp / "sitzung.jsonl"
        datei.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in eintraege),
                         encoding="utf-8")
        return str(datei)

    @staticmethod
    def _command(argumente: str = "") -> dict:
        text = "<command-message>sprechen</command-message>\n<command-name>/sprechen</command-name>"
        if argumente:
            text += f"\n<command-args>{argumente}</command-args>"
        return {"type": "user", "message": {"role": "user", "content": text}}

    def _hinweis(self, *eintraege: dict, typ: str = "permission_prompt") -> str:
        rc, aufruf = self._lauf("notification", {
            "session_id": "abc", "hook_event_name": "Notification", "notification_type": typ,
            "message": "Claude needs your permission",
            "transcript_path": self._transkript(*eintraege)})
        self.assertEqual(rc, 0)
        return aufruf

    def test_freigabe_spricht_festen_satz(self):
        self.assertEqual(self._hinweis(START),
                         "-v marketing -t 1.1 --lauter 8 --quelle abc -\n"
                         "Claude wartet auf deine Freigabe.")

    def test_rueckfrage_von_claude(self):
        # So kam AskUserQuestion am 27.11.2026 in T3 Code an
        rc, aufruf = self._lauf("notification", {
            "session_id": "abc", "notification_type": "permission_prompt",
            "message": "Claude needs your permission to use AskUserQuestion",
            "transcript_path": self._transkript(START)})
        self.assertEqual(rc, 0)
        self.assertTrue(aufruf.endswith("Claude hat eine Frage an dich."), aufruf)

    def test_mcp_formular_spricht_eingabe(self):
        self.assertTrue(self._hinweis(self._command(), typ="elicitation_dialog")
                        .endswith("Claude wartet auf deine Eingabe."))

    def test_aus_und_datei_bleiben_stumm(self):
        for argument in ("aus", "datei", " AUS ", "aus.", "Datei!"):
            self.protokoll.unlink(missing_ok=True)
            self.assertEqual(self._hinweis(START, self._command(argument)), "", argument)

    def test_der_letzte_aufruf_zaehlt(self):
        self.assertNotEqual(self._hinweis(START, self._command("aus"), self._command()), "")
        self.protokoll.unlink(missing_ok=True)
        # Nach dem Kompaktieren setzt der SessionStart-Hook den Modus wieder an
        self.assertNotEqual(self._hinweis(self._command("aus"), START), "")

    def test_ohne_gespraechsmodus_stumm(self):
        self.assertEqual(self._hinweis({"type": "user", "message": {"content": "Hallo"}}), "")

    def test_zitat_in_einem_werkzeugergebnis_zaehlt_nicht(self):
        zitat = {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": self._command("aus")["message"]["content"]}]}}
        self.assertNotEqual(self._hinweis(START, zitat), "")

    def test_leerlauf_hinweis_bleibt_stumm(self):
        # idle_prompt kommt nach jeder gesprochenen Antwort; ein Satz dazu wäre doppelt
        self.assertEqual(self._hinweis(START, typ="idle_prompt"), "")

    def test_fehlendes_transkript_bricht_nicht_ab(self):
        for eingabe in ({"notification_type": "permission_prompt",
                         "transcript_path": str(self.tmp / "fehlt.jsonl")},
                        {"notification_type": "permission_prompt", "transcript_path": "a\x00b"},
                        {"notification_type": "permission_prompt"}, {}):
            rc, aufruf = self._lauf("notification", eingabe)
            self.assertEqual((rc, aufruf), (0, ""), eingabe)

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
            self.assertEqual(self._lauf("prompt", {"session_id": "abc", "prompt": "Psst"}), 0)
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
        self.assertEqual(self._lauf("prompt", {"session_id": "abc", "prompt": "Psst"}), 0)
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

    def test_ffmpeg_ueber_audiotoolbox_nur_auf_macos(self):
        import claude_sprechen
        for name in ("ffmpeg", "ffplay"):
            datei = self.bin / name
            datei.write_text("#!/bin/sh\n", encoding="utf-8")
            datei.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": str(self.bin)}), \
                mock.patch.dict(os.environ, {}, clear=False) as umgebung:
            umgebung.pop("SPRECHEN_PLAYER", None)
            for plattform, erwartet in (("darwin", "ffmpeg"), ("linux", "ffplay")):
                with mock.patch.object(claude_sprechen.sys, "platform", plattform):
                    self.assertEqual(claude_sprechen.player_befehl()[0], erwartet, plattform)

    def test_ssh_gibt_eine_tote_verbindung_auf(self):
        import claude_sprechen
        befehl = claude_sprechen.entfernter_befehl("mac", ["-"])
        self.assertIn("ServerAliveInterval=5", befehl)
        self.assertIn("ServerAliveCountMax=3", befehl)

    def _abspielen_mit_grenzen(self, ssh_skript: str, player: str) -> tuple[float, list[str]]:
        """abspielen im selben Prozess, mit Fristen von einer halben Sekunde."""
        import time

        import claude_sprechen
        (self.bin / "ssh").write_text(ssh_skript, encoding="utf-8")
        umgebung = {**self.env, "SPRECHEN_PLAYER": player}
        with mock.patch.dict(os.environ, umgebung), \
                mock.patch.multiple(claude_sprechen, OBERGRENZE_GRUND=0.5,
                                    OBERGRENZE_JE_ZEICHEN=0, NACHLAUF=0.5), \
                self.assertLogs("claude_sprechen", "ERROR") as protokoll:
            os.environ.pop("SPRECHEN_GERAETE", None)
            beginn = time.monotonic()
            rc = claude_sprechen.abspielen({"args": ["--quelle", "abc"], "text": "Hallo.",
                                            "quelle": "abc"})
            dauer = time.monotonic() - beginn
        self.assertEqual(rc, 0)
        self.assertEqual(list((self.tmp / "run" / "hoerbuch-generator").glob("laeuft-*")), [])
        return dauer, protokoll.output

    def test_protokoll_mit_uhrzeit_auch_fuer_fremde_meldungen(self):
        # Meldungen von ssh und Player stehen mit Uhrzeit im Protokoll, nicht roh dazwischen
        self.env["SPRECHEN_PLAYER"] = "/bin/sh -c 'cat > /dev/null; echo kaputt >&2; exit 3'"
        self.assertEqual(self._lauf("stop", {"session_id": "abc", "last_assistant_message":
                                             "<!-- sprechen: Hallo. -->"}), 0)
        log = self.tmp / "run" / "hoerbuch-generator" / "wiedergabe.log"
        import time
        frist = time.monotonic() + 10
        while time.monotonic() < frist and not all(t in (
                log.read_text(encoding="utf-8") if log.exists() else "")
                for t in ("endete mit", "kaputt")):
            time.sleep(0.05)
        zeilen = log.read_text(encoding="utf-8").splitlines()
        self.assertTrue(any("Player auf hier: kaputt" in z for z in zeilen), zeilen)
        self.assertTrue(any("Auftrag: 6 Zeichen" in z for z in zeilen), zeilen)
        for zeile in zeilen:
            self.assertRegex(zeile, r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d claude_sprechen: ")

    def test_haengender_player_endet_an_der_obergrenze(self):
        # Wie ein MacBook, das während der Wiedergabe einschläft: Der Player liest nicht weiter
        dauer, meldungen = self._abspielen_mit_grenzen(
            '#!/bin/sh\ncat > /dev/null; printf PCM\n', "sleep 30")
        self.assertLess(dauer, 5)
        self.assertIn("Obergrenze", meldungen[0])

    def test_haengender_rechenteil_endet_nach_dem_player(self):
        dauer, meldungen = self._abspielen_mit_grenzen(
            '#!/bin/sh\ncat > /dev/null; printf PCM; exec >&-; exec sleep 30\n',
            "/bin/sh -c 'cat > /dev/null'")
        self.assertLess(dauer, 5)
        self.assertIn("nach dem Player nicht", meldungen[0])


class Sitzungsbeginn(unittest.TestCase):
    """start: Der SessionStart-Hook gibt die Regeln aus sprechen.md als Kontext aus."""

    def test_regeln_als_kontext_ohne_bestaetigung(self):
        lauf = subprocess.run([sys.executable, str(SKRIPT), "start"],
                              input=json.dumps({"session_id": "abc", "source": "startup"}),
                              text=True, capture_output=True, timeout=20)
        self.assertEqual(lauf.returncode, 0)
        ausgabe = json.loads(lauf.stdout)["hookSpecificOutput"]
        self.assertEqual(ausgabe["hookEventName"], "SessionStart")
        kontext = ausgabe["additionalContext"]
        self.assertIn("von Anfang an eingeschaltet", kontext)
        self.assertIn("<!-- sprechen:", kontext)
        # Wächter für die beiden Überschriften in sprechen.md, an denen regeln() den Abschnitt
        # erkennt: Fehlt eine, bleibt stdout leer und json.loads oben scheitert
        self.assertIn("### Knapp", kontext)
        self.assertIn("### Was sonst gilt", kontext)
        self.assertNotIn("Bestätige", kontext)
        self.assertNotIn("## Bei `datei`", kontext)

    def test_ohne_abschnitt_kein_kontext_und_kein_abbruch(self):
        import claude_sprechen
        with tempfile.TemporaryDirectory() as ordner:
            datei = Path(ordner) / "sprechen.md"
            datei.write_text("# Nur eine Überschrift\n", encoding="utf-8")
            with mock.patch.object(claude_sprechen, "COMMAND", datei):
                self.assertEqual(claude_sprechen.regeln(), "")
                with mock.patch.object(sys, "argv", ["claude_sprechen.py", "start"]), \
                        mock.patch("sys.stdin", io.StringIO("{}")), \
                        mock.patch("sys.stdout", new_callable=io.StringIO) as aus:
                    self.assertEqual(claude_sprechen.main(), 0)
                self.assertEqual(aus.getvalue(), "")

    def test_fehlende_datei_kein_abbruch(self):
        import claude_sprechen
        with mock.patch.object(claude_sprechen, "COMMAND", Path("/gibt/es/nicht/sprechen.md")), \
                mock.patch.object(sys, "argv", ["claude_sprechen.py", "start"]), \
                mock.patch("sys.stdin", io.StringIO("{}")), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as aus:
            self.assertEqual(claude_sprechen.main(), 0)
        self.assertEqual(aus.getvalue(), "")


class Geraetewahl(unittest.TestCase):
    """SPRECHEN_GERAETE: Ein falsches ssh meldet je Gerät die Leerlaufzeit aus LEERLAUF_<gerät>
    und schreibt, was ein Player dort bekäme, nach ton.<gerät>; ein falsches ioreg meldet die
    Leerlaufzeit dieses Geräts, ein falsches sprechen.sh rechnet hier."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="geraete"))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.protokoll = self.tmp / "aufrufe.txt"
        self.log = self.tmp / "run" / "hoerbuch-generator" / "wiedergabe.log"
        dateien = {
            "bin/ssh": '#!/bin/sh\nprintf "ssh %s\\n" "$*" >> "$PROTOKOLL"\n'
                       'vorletztes=""; letztes=""\n'
                       'for a; do vorletztes="$letztes"; letztes="$a"; done\n'
                       'case "$letztes" in\n'
                       '  *HIDIdleTime*) eval "printf \'%s\' \\"\\${LEERLAUF_$vorletztes:-}\\"";;\n'
                       '  *--liefern*) cat > /dev/null; printf PCM;;\n'
                       '  *ffplay*) cat > "$TON.$vorletztes";;\n'
                       'esac\n',
            "bin/ioreg": '#!/bin/sh\necho "    | |   \\"HIDIdleTime\\" = $IOREG_NS"\n',
            "generator/sprechen.sh": '#!/bin/sh\nprintf "sprechen.sh %s\\n" "$*" >> "$PROTOKOLL"\n'
                                     'case "$*" in *--liefern*) cat > /dev/null; printf PCM;;\n'
                                     '*) cat > /dev/null;; esac\n',
        }
        for name, inhalt in dateien.items():
            datei = self.tmp / name
            datei.parent.mkdir(exist_ok=True)
            datei.write_text(inhalt, encoding="utf-8")
            datei.chmod(0o755)
        self.env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.tmp),
                    "XDG_RUNTIME_DIR": str(self.tmp / "run"),
                    "HOERBUCH_GENERATOR": str(self.tmp / "generator"),
                    "PROTOKOLL": str(self.protokoll), "TON": str(self.tmp / "ton")}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _stop(self, **env: str) -> None:
        lauf = subprocess.run([sys.executable, str(SKRIPT), "stop"], text=True,
                              input=json.dumps({"session_id": "abc", "last_assistant_message":
                                                "<!-- sprechen: Hallo. -->"}),
                              capture_output=True, env={**self.env, **env}, timeout=20)
        self.assertEqual(lauf.returncode, 0)

    def _warten(self, bedingung) -> bool:
        import time
        frist = time.monotonic() + 10
        while time.monotonic() < frist:
            if bedingung():
                time.sleep(0.1)  # der Hintergrundprozess schreibt noch zu Ende
                return True
            time.sleep(0.05)
        return False

    def _ton(self, geraet: str) -> Path:
        return self.tmp / f"ton.{geraet}"

    def test_spielt_auf_dem_zuletzt_benutzten_geraet(self):
        self._stop(SPRECHEN_ENTFERNT="mac", SPRECHEN_GERAETE="zuhause buero",
                   LEERLAUF_zuhause="11325", LEERLAUF_buero="0")
        self.assertTrue(self._warten(lambda: self._ton("buero").exists()))
        self.assertEqual(self._ton("buero").read_bytes(), b"PCM")
        self.assertFalse(self._ton("zuhause").exists())

    def test_alle_lange_unbenutzt_bleibt_stumm(self):
        self._stop(SPRECHEN_ENTFERNT="mac", SPRECHEN_GERAETE="zuhause buero",
                   LEERLAUF_zuhause="5000", LEERLAUF_buero="4000", SPRECHEN_LEERLAUF="600")
        self.assertTrue(self._warten(lambda: self.log.exists() and
                                     "stumm" in self.log.read_text(encoding="utf-8")))
        self.assertNotIn("--liefern", self.protokoll.read_text(encoding="utf-8"))

    def test_ohne_fernziel_rechnet_hier_und_spielt_dort(self):
        self._stop(SPRECHEN_GERAETE="hier buero", IOREG_NS="100000000000", LEERLAUF_buero="3")
        self.assertTrue(self._warten(lambda: self._ton("buero").exists()))
        self.assertEqual(self._ton("buero").read_bytes(), b"PCM")
        self.assertIn("sprechen.sh -v", self.protokoll.read_text(encoding="utf-8"))

    def test_hier_ohne_fernziel_spricht_der_dienst_selbst(self):
        self._stop(SPRECHEN_GERAETE="hier buero", IOREG_NS="2000000000", LEERLAUF_buero="300")
        self.assertTrue(self._warten(lambda: self.protokoll.exists() and
                                     "sprechen.sh -v" in self.protokoll.read_text(encoding="utf-8")))
        aufrufe = self.protokoll.read_text(encoding="utf-8")
        self.assertNotIn("--liefern", aufrufe)
        self.assertTrue(aufrufe.rstrip().endswith("-"), aufrufe)

    def test_linux_mit_gnome_ueber_dbus(self):
        # Ohne ioreg fragt der Befehl den Mutter IdleMonitor; gdbus meldet Millisekunden
        import claude_sprechen
        (self.bin / "ioreg").unlink()
        gdbus = self.bin / "gdbus"
        gdbus.write_text('#!/bin/sh\necho "(uint64 42000,)"\n', encoding="utf-8")
        gdbus.chmod(0o755)
        with mock.patch.dict(os.environ, {**self.env, "LEERLAUF_buero": "100"}):
            self.assertEqual(claude_sprechen.geraet_waehlen(["hier", "buero"]), "hier")
        with mock.patch.dict(os.environ, {**self.env, "LEERLAUF_buero": "41"}):
            self.assertEqual(claude_sprechen.geraet_waehlen(["hier", "buero"]), "buero")

    def test_prompt_beendet_die_wiedergabe_auch_ohne_fernziel(self):
        import claude_sprechen
        run = self.tmp / "run" / "hoerbuch-generator"
        run.mkdir(parents=True)
        laufend = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)",
                                    "claude_sprechen"], start_new_session=True)
        (run / f"laeuft-{claude_sprechen._kennung('abc')}-{laufend.pid}").touch()
        try:
            lauf = subprocess.run([sys.executable, str(SKRIPT), "prompt"],
                                  input=json.dumps({"session_id": "abc", "prompt": "Psst"}),
                                  text=True,
                                  capture_output=True, timeout=20,
                                  env={**self.env, "SPRECHEN_GERAETE": "hier buero"})
            self.assertEqual(lauf.returncode, 0)
            self.assertIsNotNone(laufend.wait(timeout=5))
        finally:
            laufend.kill()
            laufend.wait()
        self.assertIn("sprechen.sh --stopp --quelle abc", self.protokoll.read_text(encoding="utf-8"))

    def test_kein_geraet_antwortet(self):
        import claude_sprechen
        with mock.patch.dict(os.environ, self.env):
            self.assertIsNone(claude_sprechen.geraet_waehlen(["schlaeft"]))


class Pruefen(unittest.TestCase):
    """pruefen: liest die Hooks aus settings.json unter HOME und fragt über ein falsches ssh
    nach. Das ssh beantwortet --status, git describe und die Abfrage je Gerät; ein Gerät
    namens "schlaeft" ist nicht erreichbar."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pruefen"))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        ssh = self.bin / "ssh"
        ssh.write_text(
            '#!/bin/sh\nziel=""; letztes=""\n'
            'for a; do ziel="$letztes"; letztes="$a"; done\n'
            '[ "$ziel" = schlaeft ] && { echo "ssh: connect: Operation timed out" >&2; exit 255; }\n'
            'case "$letztes" in\n'
            '  *--status*) echo \'{"ok": true, "zustand": "bereit"}\';;\n'
            '  *describe*) echo v9.9.9;;\n'
            '  *leerlauf*) echo "leerlauf 12"; echo "player ffmpeg";;\n'
            'esac\n', encoding="utf-8")
        ssh.chmod(0o755)
        self.env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _settings(self, hooks: dict) -> None:
        (self.tmp / ".claude").mkdir(exist_ok=True)
        (self.tmp / ".claude" / "settings.json").write_text(json.dumps({"hooks": hooks}),
                                                            encoding="utf-8")

    @staticmethod
    def _hook(befehl: str) -> list:
        return [{"hooks": [{"type": "command", "command": befehl}]}]

    def _standard(self, geraete: str = "buero") -> None:
        skript = "python3 $HOME/hg/integrationen/claude-code/claude_sprechen.py"
        self._settings({
            "Stop": self._hook(f"SPRECHEN_ENTFERNT=mac SPRECHEN_GERAETE='{geraete}' {skript} stop"),
            "UserPromptSubmit": self._hook(f"SPRECHEN_ENTFERNT=mac {skript} prompt")})

    def _pruefen(self, **env: str) -> tuple[int, str]:
        lauf = subprocess.run([sys.executable, str(SKRIPT), "pruefen"], stdin=subprocess.DEVNULL,
                              text=True, capture_output=True, env={**self.env, **env}, timeout=30)
        return lauf.returncode, lauf.stdout

    def test_alles_da(self):
        self._standard()
        rc, aus = self._pruefen()
        self.assertEqual(rc, 0, aus)
        self.assertIn("Variable  SPRECHEN_GERAETE=buero", aus)
        self.assertIn("Rechnen   mac: ssh ok, v9.9.9", aus)
        self.assertIn("Dienst bereit", aus)
        self.assertIn("Gerät     buero: Leerlauf 12 s, Player ffmpeg", aus)
        self.assertIn("Notification fehlt (optional)", aus)
        self.assertTrue(aus.rstrip().endswith("Ergebnis: alles da"), aus)

    def test_schlafendes_geraet_ist_ein_hinweis(self):
        self._standard("buero schlaeft")
        rc, aus = self._pruefen()
        self.assertEqual(rc, 0, aus)
        self.assertIn("Hinweis: schlaeft: ssh antwortet nicht (ssh: connect: Operation timed out)",
                      aus)
        self.assertIn("Ergebnis: alles da (1 Hinweis)", aus)

    def test_antwortet_kein_geraet_ist_es_ein_problem(self):
        self._standard("schlaeft")
        rc, aus = self._pruefen()
        self.assertEqual(rc, 1, aus)
        self.assertIn("FEHLER: schlaeft: ssh antwortet nicht", aus)
        self.assertIn("Ergebnis: 1 Problem(e)", aus)

    def test_abweichende_variablen_zwischen_hooks(self):
        skript = "python3 $HOME/hg/integrationen/claude-code/claude_sprechen.py"
        self._settings({
            "Stop": self._hook(f"SPRECHEN_ENTFERNT=mac SPRECHEN_GERAETE=buero "
                               f"SPRECHEN_STIMME=a {skript} stop"),
            # Der Prompt-Hook braucht SPRECHEN_GERAETE nicht, nur den Fernbetrieb
            "UserPromptSubmit": self._hook(f"SPRECHEN_ENTFERNT=mac {skript} prompt"),
            "Notification": self._hook(f"SPRECHEN_GERAETE=buero {skript} notification")})
        rc, aus = self._pruefen()
        self.assertEqual(rc, 1, aus)
        self.assertIn("FEHLER: SPRECHEN_ENTFERNT weicht ab: Stop mac, UserPromptSubmit mac, "
                      "Notification (nicht gesetzt)", aus)
        self.assertIn("Hinweis: SPRECHEN_STIMME weicht ab", aus)
        self.assertNotIn("SPRECHEN_GERAETE weicht ab", aus)
        self.assertIn("Ergebnis: 1 Problem(e) (1 Hinweis)", aus)

    def test_fehlender_stop_hook_und_fehlende_settings(self):
        self._settings({"UserPromptSubmit": self._hook("python3 x/claude_sprechen.py prompt")})
        rc, aus = self._pruefen()
        self.assertEqual(rc, 1, aus)
        self.assertIn("FEHLER: Stop fehlt", aus)
        (self.tmp / ".claude" / "settings.json").unlink()
        rc, aus = self._pruefen()
        self.assertEqual(rc, 1, aus)
        self.assertIn("nicht lesbar", aus)

    def test_praefix_gilt_vor_settings_und_umgebung(self):
        # Wie beim Hook: Umgebung, darüber env aus settings.json, darüber das Präfix
        skript = "python3 $HOME/hg/integrationen/claude-code/claude_sprechen.py"
        (self.tmp / ".claude").mkdir(exist_ok=True)
        (self.tmp / ".claude" / "settings.json").write_text(json.dumps({
            "env": {"SPRECHEN_GERAETE": "schlaeft", "SPRECHEN_LAUTER": "5"},
            "hooks": {"Stop": self._hook(f"SPRECHEN_ENTFERNT=mac SPRECHEN_GERAETE=buero "
                                         f"{skript} stop"),
                      "UserPromptSubmit": self._hook(f"SPRECHEN_ENTFERNT=mac {skript} prompt")}}),
            encoding="utf-8")
        rc, aus = self._pruefen(SPRECHEN_GERAETE="terminal", SPRECHEN_LAUTER="9",
                                SPRECHEN_TEMPO="1.2")
        self.assertEqual(rc, 0, aus)
        self.assertIn("Variable  SPRECHEN_GERAETE=buero", aus)
        self.assertIn("Variable  SPRECHEN_LAUTER=5", aus)
        self.assertIn("Variable  SPRECHEN_TEMPO=1.2", aus)
        self.assertNotIn("schlaeft", aus)
        self.assertNotIn("terminal", aus)

    def test_hooks_lesen(self):
        import claude_sprechen
        umgebung, eingetragen, praefixe = claude_sprechen.hooks_lesen({
            "env": {"SPRECHEN_LAUTER": 12, "ANDERES": "x"},
            "hooks": {"Stop": self._hook("SPRECHEN_ENTFERNT_REPO='~/R/hg' "
                                         "python3 a/claude_sprechen.py stop"),
                      "Notification": [{"matcher": "permission_prompt", "hooks": [
                          {"type": "command", "command": "py claude_sprechen.py notification"}]}],
                      "PreToolUse": self._hook("andere.sh")}})
        self.assertEqual(umgebung, {"SPRECHEN_LAUTER": "12"})
        self.assertEqual(eingetragen, {"Stop": ["stop"], "Notification": ["notification"]})
        self.assertEqual(praefixe, {"Stop": {"SPRECHEN_ENTFERNT_REPO": "~/R/hg"},
                                    "Notification": {}})
        # Kaputte Einträge, die Claude Code selbst ablehnte, dürfen pruefen nicht abbrechen
        self.assertEqual(claude_sprechen.hooks_lesen({
            "env": ["SPRECHEN_LAUTER=12"],
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": None}]}]}}),
            ({}, {}, {}))
        self.assertTrue(claude_sprechen._dienst(0, "[1]", "")[1])

    def test_player_suche_spielt_nicht(self):
        import claude_sprechen
        name = claude_sprechen.FERN_PLAYER_NAME
        self.assertNotIn("exec", name)
        for player in ("echo paplay;", "echo ffmpeg;", "echo ffplay;"):
            self.assertIn(player, name)


if __name__ == "__main__":
    unittest.main()
