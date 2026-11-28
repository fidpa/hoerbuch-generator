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
import shutil
import subprocess
import sys
import tempfile
import time
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


def _ps_geht() -> bool:
    """Ob _gehoert_uns eine Befehlszeile lesen kann. Ohne beides gibt es True zurück, und der
    Test zur fremden PID schlüge fehl, ohne dass der Code falsch wäre."""
    if Path("/proc/self/cmdline").exists():
        return True
    try:
        return subprocess.run(["ps", "-p", str(os.getpid()), "-o", "command="],
                              capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


PS_GEHT = _ps_geht()


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
        shutil.rmtree(self.tmp)

    def _env(self, env: dict | None = None) -> dict:
        # XDG_RUNTIME_DIR im Testordner: Die Modus-Dateien echter Sitzungen bleiben unberührt.
        # HOME ebenso: Das Stoppwort liest settings.json und beendet den Player, der die
        # Sperre unter ~/.cache hält
        return {"HOERBUCH_GENERATOR": str(self.tmp), "PATH": "/usr/bin:/bin",
                "HOME": str(self.tmp), "XDG_RUNTIME_DIR": str(self.tmp / "run"), **(env or {})}

    def _lauf(self, ereignis: str, eingabe: dict, env: dict | None = None) -> tuple[int, str]:
        lauf = subprocess.run([sys.executable, str(SKRIPT), ereignis], input=json.dumps(eingabe),
                              text=True, capture_output=True, env=self._env(env))
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

    def test_sprechen_aus_schaltet_jeden_hook_ab(self):
        # Ein Dienst wie ein Bot setzt SPRECHEN_AUS=1 und lädt trotzdem die Hooks des Nutzers
        aus = {"SPRECHEN_AUS": "1"}
        for ereignis, eingabe in (
                ("stop", {"last_assistant_message": "<!-- sprechen: Hallo. -->"}),
                ("notification", {"notification_type": "permission_prompt"}),
                ("start", {}),
                ("prompt", {"prompt": "Psst", "session_id": "abc"})):
            lauf = subprocess.run([sys.executable, str(SKRIPT), ereignis],
                                  input=json.dumps(eingabe), text=True, capture_output=True,
                                  env={"HOERBUCH_GENERATOR": str(self.tmp),
                                       "PATH": "/usr/bin:/bin", **aus})
            self.assertEqual((lauf.returncode, lauf.stdout), (0, ""), ereignis)
            self.assertFalse(self.protokoll.exists(), ereignis)
        # Nur "1" schaltet ab, wie bei SPRECHEN_UNTERBRECHEN
        rc, aufruf = self._lauf("stop", {"last_assistant_message": "<!-- sprechen: Hallo. -->"},
                                {"SPRECHEN_AUS": "0"})
        self.assertEqual((rc, aufruf), (0, "-v marketing -t 1.1 --lauter 8 -\nHallo."))

    def test_stop_ohne_marke_ruft_nichts_auf(self):
        rc, aufruf = self._lauf("stop", {"last_assistant_message": "Nur Text."})
        self.assertEqual(rc, 0)
        self.assertEqual(aufruf, "")

    def _prompt(self, text: str, env: dict | None = None) -> tuple[str, str]:
        lauf = subprocess.run([sys.executable, str(SKRIPT), "prompt"],
                              input=json.dumps({"prompt": text, "session_id": "abc"}),
                              text=True, capture_output=True, env=self._env(env))
        self.assertEqual(lauf.returncode, 0)
        aufruf = self.protokoll.read_text(encoding="utf-8") if self.protokoll.exists() else ""
        return aufruf, lauf.stdout

    def test_neue_eingabe_laesst_zu_ende_sprechen(self):
        self.assertEqual(self._prompt("Weiter"), ("", ""))

    def test_stoppwort_stoppt_die_eigene_sitzung_und_erreicht_claude_nicht(self):
        for wort in ("Psst.", "  still ", "RUHE!", "pst", "Pssst!", "Psssst..."):
            self.protokoll.unlink(missing_ok=True)
            aufruf, ausgabe = self._prompt(wort)
            # Läuft für die Sitzung hier nichts, darf der Dienst die laufende Ausgabe treffen
            self.assertEqual(aufruf, "--stopp --quelle abc --sonst-aktuell\n", wort)
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
        # Steht der Kontext des SessionStart-Hooks nach dem Aufruf, gilt wieder an
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

    # --- Modus je Sitzung in einer Datei ------------------------------------------------

    def _modus(self) -> str | None:
        ordner = self.tmp / "run" / "hoerbuch-generator" / "modus"
        dateien = list(ordner.iterdir()) if ordner.exists() else []
        return dateien[0].read_text(encoding="utf-8").strip() if len(dateien) == 1 else None

    def _start(self, sitzung: str = "abc", source: str = "compact", transcript: str = "") -> str:
        eingabe = {"session_id": sitzung, "source": source}
        if transcript:
            eingabe["transcript_path"] = transcript
        lauf = subprocess.run([sys.executable, str(SKRIPT), "start"], input=json.dumps(eingabe),
                              text=True, capture_output=True, env=self._env())
        self.assertEqual(lauf.returncode, 0)
        return lauf.stdout

    def test_sprechen_haelt_den_modus_fest(self):
        for eingabe, erwartet in (("/sprechen aus", "aus"), ("/sprechen datei", "datei"),
                                  ("  /sprechen  Aus.", "aus"), ("/sprechen", "an"),
                                  ("/sprechen bitte", "an")):
            self.assertEqual(self._prompt(eingabe), ("", ""), eingabe)
            self.assertEqual(self._modus(), erwartet, eingabe)

    def test_andere_eingaben_halten_nichts_fest(self):
        for eingabe in ("Weiter", "/sprechenx aus", "bitte /sprechen aus", "Psst"):
            self.protokoll.unlink(missing_ok=True)
            self._prompt(eingabe)
            self.assertIsNone(self._modus(), eingabe)

    def test_aus_uebersteht_das_kompaktieren(self):
        self._prompt("/sprechen aus")
        self.assertEqual(self._start(), "")
        rc, aufruf = self._lauf("stop", {"session_id": "abc",
                                         "last_assistant_message": "<!-- sprechen: Hallo. -->"})
        self.assertEqual((rc, aufruf), (0, ""))
        # Eine andere Sitzung spricht weiter
        rc, aufruf = self._lauf("stop", {"session_id": "xyz",
                                         "last_assistant_message": "<!-- sprechen: Hallo. -->"})
        self.assertTrue(aufruf.endswith("Hallo."), aufruf)

    def test_datei_uebersteht_das_kompaktieren(self):
        self._prompt("/sprechen datei")
        kontext = json.loads(self._start())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("steht auf Datei", kontext)
        self.assertIn("--datei", kontext)
        self.assertNotIn("von Anfang an eingeschaltet", kontext)
        self.assertNotIn("Bestätige", kontext)
        # Der Abschnitt verweist auf „Knapp“ und „Natürlich“; ohne sie fehlten die Regeln für
        # die gesprochene Fassung. Die Sprechmarke gehört nicht dazu
        self.assertIn("### Knapp", kontext)
        self.assertIn("### Natürlich", kontext)
        self.assertNotIn("<!-- sprechen:", kontext)
        self.assertNotIn("### Was sonst gilt", kontext)
        rc, aufruf = self._lauf("stop", {"session_id": "abc",
                                         "last_assistant_message": "<!-- sprechen: Hallo. -->"})
        self.assertEqual((rc, aufruf), (0, ""))

    def test_wieder_an_nach_aus(self):
        self._prompt("/sprechen aus")
        self._prompt("/sprechen")
        self.assertIn("von Anfang an eingeschaltet", self._start())

    def test_datei_geht_vor_dem_transkript(self):
        self._prompt("/sprechen aus")
        self.assertEqual(self._hinweis(START), "")
        self._prompt("/sprechen")
        self.assertTrue(self._hinweis(self._command("aus")).endswith("Freigabe."))

    def test_ohne_sitzung_und_ohne_schreibrecht_kein_abbruch(self):
        lauf = subprocess.run([sys.executable, str(SKRIPT), "prompt"],
                              input=json.dumps({"prompt": "/sprechen aus"}),
                              text=True, capture_output=True, env=self._env())
        self.assertEqual((lauf.returncode, lauf.stdout), (0, ""))
        self.assertIsNone(self._modus())
        (self.tmp / "datei").write_text("", encoding="utf-8")
        lauf = subprocess.run([sys.executable, str(SKRIPT), "prompt"],
                              input=json.dumps({"prompt": "/sprechen aus", "session_id": "abc"}),
                              text=True, capture_output=True,
                              env=self._env({"XDG_RUNTIME_DIR": str(self.tmp / "datei")}))
        self.assertEqual((lauf.returncode, lauf.stdout), (0, ""))
        self.assertIn("Modus nicht festgehalten", lauf.stderr)

    def test_alte_modus_dateien_werden_geraeumt(self):
        ordner = self.tmp / "run" / "hoerbuch-generator" / "modus"
        ordner.mkdir(parents=True)
        alt = ordner / "0123456789abcdef"
        alt.write_text("aus\n", encoding="utf-8")
        os.utime(alt, (0, 0))
        self._prompt("/sprechen datei")
        self.assertFalse(alt.exists())
        self.assertEqual(self._modus(), "datei")

    # --- Fork: neue Kennung, Verlauf der Ausgangssitzung im Transkript ----------------------

    def test_fork_uebernimmt_den_modus_aus_dem_transkript(self):
        verlauf = self._transkript(START, self._command("aus"))
        self.assertEqual(self._start("fork1", "fork", verlauf), "")
        self.assertEqual(self._modus(), "aus")
        rc, aufruf = self._lauf("stop", {"session_id": "fork1",
                                         "last_assistant_message": "<!-- sprechen: Hallo. -->"})
        self.assertEqual((rc, aufruf), (0, ""))

    def test_fork_im_datei_modus(self):
        kontext = self._start("fork1", "fork", self._transkript(START, self._command("datei")))
        self.assertIn("steht auf Datei", kontext)
        self.assertEqual(self._modus(), "datei")

    def test_neue_sitzung_liest_kein_transkript_und_haelt_an_fest(self):
        # Nach /clear oder beim Start gehört ein Transkript nicht zu einem früheren Modus
        kontext = self._start("neu", "startup", self._transkript(START, self._command("aus")))
        self.assertIn("von Anfang an eingeschaltet", kontext)
        self.assertEqual(self._modus(), "an")

    def test_fork_ohne_hinweis_im_transkript_beginnt_mit_ton(self):
        kontext = self._start("fork1", "fork", self._transkript(self._command()))
        self.assertIn("von Anfang an eingeschaltet", kontext)
        self.assertIn("von Anfang an eingeschaltet",
                      self._start("fork2", "fork", str(self.tmp / "fehlt.jsonl")))

    # --- Ersatzsatz, wenn die Sprechmarke fehlt -------------------------------------------

    def _log(self) -> str:
        datei = self.tmp / "run" / "hoerbuch-generator" / "wiedergabe.log"
        return datei.read_text(encoding="utf-8") if datei.exists() else ""

    def test_ohne_marke_im_gespraechsmodus_spricht_der_ersatzsatz(self):
        self._start("abc", "startup")
        rc, aufruf = self._lauf("stop", {"session_id": "abc", "last_assistant_message": "Text."})
        self.assertEqual(rc, 0)
        self.assertEqual(aufruf, "-v marketing -t 1.1 --lauter 8 --quelle abc -\n"
                                 "Fertig, die Antwort steht im Text.")
        self.assertRegex(self._log(), r"\d\d:\d\d:\d\d claude_sprechen: Antwort ohne Sprechmarke")

    def test_ersatzsatz_auch_nach_dem_transkript(self):
        # Eine Sitzung von vor dem Update hat keine Datei
        rc, aufruf = self._lauf("stop", {"session_id": "abc", "last_assistant_message": "",
                                         "transcript_path": self._transkript(START)})
        self.assertEqual(rc, 0)
        self.assertTrue(aufruf.endswith("Fertig, die Antwort steht im Text."), aufruf)

    def test_kein_ersatzsatz_wenn_die_sitzung_nur_pausiert(self):
        # Hintergrundarbeit oder ein Weckruf: Die Antwort ist eine Zwischenmeldung ohne Marke
        self._start("abc", "startup")
        for feld, wert in (("background_tasks", [{"id": "b1", "type": "shell"}]),
                           ("session_crons", [{"id": "c1", "recurring": False}])):
            rc, aufruf = self._lauf("stop", {"session_id": "abc", "last_assistant_message": "Text.",
                                             feld: wert})
            self.assertEqual((rc, aufruf), (0, ""), feld)
        self.assertEqual(self._log(), "")
        # Leere Listen heißen: nichts in Arbeit
        rc, aufruf = self._lauf("stop", {"session_id": "abc", "last_assistant_message": "Text.",
                                         "background_tasks": [], "session_crons": []})
        self.assertTrue(aufruf.endswith("Fertig, die Antwort steht im Text."), aufruf)

    def test_kompaktieren_ohne_datei_liest_das_transkript(self):
        # Die Datei ist weggeräumt, das Transkript sagt aus: Das Kompaktieren schaltet nicht an
        self.assertEqual(self._start("abc", "compact",
                                     self._transkript(START, self._command("aus"))), "")
        self.assertEqual(self._modus(), "aus")

    def test_kein_ersatzsatz_ausserhalb_des_gespraechsmodus(self):
        # Modus aus, Datei-Modus oder kein Hinweis auf den Modus: stumm, keine Zeile
        for vorher in ("/sprechen aus", "/sprechen datei", None):
            self.protokoll.unlink(missing_ok=True)
            shutil.rmtree(self.tmp / "run", ignore_errors=True)
            if vorher:
                self._prompt(vorher)
            rc, aufruf = self._lauf("stop", {"session_id": "abc",
                                             "last_assistant_message": "Text."})
            self.assertEqual((rc, aufruf), (0, ""), vorher)
            self.assertEqual(self._log(), "", vorher)

    def test_ersatzsatz_ohne_schreibrecht_fuer_das_protokoll(self):
        self._start("abc", "startup")
        log = self.tmp / "run" / "hoerbuch-generator" / "wiedergabe.log"
        log.mkdir()  # ein Ordner statt der Datei: open scheitert
        rc, aufruf = self._lauf("stop", {"session_id": "abc", "last_assistant_message": "Text."})
        self.assertEqual(rc, 0)
        self.assertTrue(aufruf.endswith("Fertig, die Antwort steht im Text."), aufruf)

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

    @unittest.skipUnless(PS_GEHT, "weder /proc noch ps (etwa in einer Sandbox)")
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
        self.assertEqual(self._lauf("prompt", {"session_id": "abc", "prompt": "Weiter"}), 0)
        with mock.patch.dict(self.env, {"SPRECHEN_UNTERBRECHEN": "1"}):
            self.assertEqual(self._lauf("prompt", {"session_id": "abc", "prompt": "Weiter"}), 0)
        self.assertFalse(self.protokoll.exists())

    def test_stoppwort_ohne_eigene_wiedergabe_trifft_was_gerade_klingt(self):
        # Nur ein Stoppwort fragt den Mac und die Geräte, was gerade läuft
        env = {"SPRECHEN_GERAETE": "macbook hier"}
        with mock.patch.dict(self.env, env):
            self.assertEqual(self._lauf("prompt", {"session_id": "abc", "prompt": "Psst"}), 0)
        # Der Stopp für das Gerät ist mehrzeilig (Python), deshalb Teile statt Zeilen
        aufrufe = self.protokoll.read_text(encoding="utf-8")
        self.assertEqual(aufrufe.count("-o BatchMode=yes"), 2, aufrufe)
        self.assertRegex(aufrufe, r" mac \S*sprechen\.sh --stopp --quelle abc --sonst-aktuell")
        self.assertRegex(aufrufe, r" macbook PATH=.*player\.lock")

    def test_stoppwort_holt_die_geraete_aus_dem_stop_hook(self):
        # So steht es in der Anleitung: SPRECHEN_GERAETE nur vor dem Stop-Hook
        claude = self.tmp / ".claude"
        claude.mkdir()
        befehl = f"{sys.executable} {SKRIPT}"
        (claude / "settings.json").write_text(json.dumps({"hooks": {
            "Stop": [{"hooks": [{"type": "command",
                                 "command": f"SPRECHEN_GERAETE='hier macbook' {befehl} stop"}]}],
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": f"{befehl} prompt"}]}],
        }}), encoding="utf-8")
        self.assertEqual(self._lauf("prompt", {"session_id": "abc", "prompt": "Psst"}), 0)
        aufrufe = self.protokoll.read_text(encoding="utf-8")
        self.assertRegex(aufrufe, r" macbook PATH=.*player\.lock")
        self.assertNotIn(" hier ", aufrufe)

    def test_stoppwort_trifft_den_player_hier_und_keine_wartende_sitzung(self):
        import claude_sprechen
        ordner = self.tmp / "run" / "hoerbuch-generator"
        ordner.mkdir(parents=True)
        sperre = self.tmp / ".cache" / "hoerbuch-generator" / "player.lock"
        # Hält die Sperre wie ein Player, der Ton bekommt: eine andere Sitzung oder ein
        # anderer Rechner über ssh
        halter = subprocess.Popen([sys.executable, "-c", claude_sprechen.SPERRE_PY, str(sperre),
                                   "sleep", "30"], stdin=subprocess.PIPE)
        halter.stdin.write(b"PCM")
        halter.stdin.flush()
        wartend = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)",
                                    "claude_sprechen"], start_new_session=True)
        try:
            frist = time.monotonic() + 5
            while time.monotonic() < frist and not (sperre.exists() and sperre.read_text()):
                time.sleep(0.05)
            (ordner / f"laeuft-{claude_sprechen._kennung('uvw')}-{wartend.pid}").touch()
            self.assertEqual(self._lauf("prompt", {"session_id": "abc", "prompt": "Psst"}), 0)
            self.assertNotEqual(halter.wait(timeout=5), 0)
            self.assertIsNone(wartend.poll())
        finally:
            for prozess in (halter, wartend):
                prozess.kill()
                prozess.wait()
            halter.stdin.close()

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

    def _abspielen_mit_grenzen(self, ssh_skript: str, player: str,
                               obergrenze: float = 0.5) -> tuple[float, list[str]]:
        """abspielen im selben Prozess, mit Fristen von einer halben Sekunde."""
        import time

        import claude_sprechen
        (self.bin / "ssh").write_text(ssh_skript, encoding="utf-8")
        umgebung = {**self.env, "SPRECHEN_PLAYER": player}
        with mock.patch.dict(os.environ, umgebung), \
                mock.patch.multiple(claude_sprechen, OBERGRENZE_GRUND=obergrenze,
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
        # Der Player selbst endet; eine halbe Sekunde bis zur Obergrenze reichte ihm unter Last
        # samt Start der Sperre nicht immer, dann kam deren Meldung statt dieser
        dauer, meldungen = self._abspielen_mit_grenzen(
            '#!/bin/sh\ncat > /dev/null; printf PCM; exec >&-; exec sleep 30\n',
            "/bin/sh -c 'cat > /dev/null'", obergrenze=3)
        self.assertLess(dauer, 5)
        self.assertIn("nach dem Player nicht", meldungen[0])


class SperreAmPlayer(unittest.TestCase):
    """Die Sperre auf dem Gerät, das spielt (SPERRE_PY), und der Stopp dort (STOPP_PY), hier
    lokal mit einem Player, der Beginn und Ende in eine Datei schreibt."""

    def setUp(self):
        import claude_sprechen
        self.c = claude_sprechen
        self.tmp = Path(tempfile.mkdtemp(prefix="sperre"))
        self.sperre = self.tmp / "ordner" / "player.lock"
        self.ablauf = self.tmp / "ablauf.txt"
        self.prozesse: list[subprocess.Popen] = []

    def tearDown(self):
        for prozess in self.prozesse:
            # Erst SIGTERM: Der Halter beendet dann auch seinen Player, ein kill ließe ihn stehen
            prozess.terminate()
            try:
                prozess.wait(timeout=5)
            except subprocess.TimeoutExpired:
                prozess.kill()
                prozess.wait()
            if prozess.stdin:
                prozess.stdin.close()
        shutil.rmtree(self.tmp)

    def _player(self, name: str, dauer: float = 0.5, spieler: str = "") -> subprocess.Popen:
        spieler = spieler or (f'echo "start $1" >> "{self.ablauf}"; cat > /dev/null; '
                              f'sleep {dauer}; echo "ende $1" >> "{self.ablauf}"')
        prozess = subprocess.Popen([sys.executable, "-c", self.c.SPERRE_PY, str(self.sperre),
                                    "sh", "-c", spieler, "_", name], stdin=subprocess.PIPE)
        self.prozesse.append(prozess)
        return prozess

    def _ablauf(self) -> list[str]:
        return self.ablauf.read_text(encoding="utf-8").split() if self.ablauf.exists() else []

    def test_nacheinander_und_erst_wenn_ton_kommt(self):
        # b startet zuerst, bekommt aber noch keinen Ton: a darf nicht auf b warten
        b = self._player("b")
        time.sleep(0.3)
        a = self._player("a")
        a.stdin.write(b"PCM")
        a.stdin.close()
        time.sleep(0.2)
        b.stdin.write(b"PCM")
        b.stdin.close()
        self.assertEqual(a.wait(timeout=10), 0)
        self.assertEqual(b.wait(timeout=10), 0)
        self.assertEqual(self._ablauf(), ["start", "a", "ende", "a", "start", "b", "ende", "b"])

    def test_stopp_beendet_den_halter_und_sonst_nichts(self):
        stopp = [sys.executable, "-c", self.c.STOPP_PY, str(self.sperre)]
        # Der Prozess mit der PID aus der Datei ist der Halter, der Player sein Kind
        a = self._player("a", spieler=f'echo "start $1" >> "{self.ablauf}"; cat > /dev/null; '
                                      "exec sleep 30")
        a.stdin.write(b"PCM")
        a.stdin.close()
        frist = time.monotonic() + 5
        while "a" not in self._ablauf() and time.monotonic() < frist:
            time.sleep(0.05)
        self.assertEqual(subprocess.run(stopp, timeout=10).returncode, 0)
        self.assertNotEqual(a.wait(timeout=5), 0)
        # Sperre frei: Der Stopp findet niemanden und endet ohne Fehler
        self.assertEqual(subprocess.run(stopp, timeout=10).returncode, 0)

    def test_der_ton_wird_fuer_nochmal_mitgeschrieben(self):
        ausgabe = self.tmp / "gespielt.pcm"
        a = self._player("a", spieler=f'cat > "{ausgabe}"')
        a.stdin.write(b"PCM-eins")
        a.stdin.close()
        self.assertEqual(a.wait(timeout=10), 0)
        self.assertEqual(ausgabe.read_bytes(), b"PCM-eins")
        self.assertEqual((self.sperre.parent / "letzte.pcm").read_bytes(), b"PCM-eins")
        # Ein leerer Auftrag überschreibt die letzte Antwort nicht
        b = self._player("b", spieler="cat > /dev/null")
        b.stdin.close()
        self.assertEqual(b.wait(timeout=10), 0)
        self.assertEqual((self.sperre.parent / "letzte.pcm").read_bytes(), b"PCM-eins")
        self.assertEqual(sorted(p.name for p in self.sperre.parent.iterdir()),
                         ["letzte.pcm", "player.lock"])

    def test_stopp_beendet_auch_den_player_und_behaelt_den_anfang(self):
        pid = self.tmp / "player.pid"
        a = self._player("a", spieler=f'echo $$ > "{pid}"; exec sleep 30')
        a.stdin.write(b"Anfang")
        a.stdin.flush()
        frist = time.monotonic() + 5
        while not (pid.exists() and pid.read_text().strip()) and time.monotonic() < frist:
            time.sleep(0.05)
        spieler = int(pid.read_text())
        time.sleep(0.2)  # der Halter hat den Block weitergereicht
        subprocess.run([sys.executable, "-c", self.c.STOPP_PY, str(self.sperre)], timeout=10)
        self.assertEqual(a.wait(timeout=5), 143)
        frist = time.monotonic() + 5
        while time.monotonic() < frist:
            try:
                os.kill(spieler, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            os.kill(spieler, 9)
            self.fail("der Player lebt nach dem Stopp noch")
        self.assertEqual((self.sperre.parent / "letzte.pcm").read_bytes(), b"Anfang")

    def test_endet_der_elternprozess_endet_auch_der_player(self):
        # Wie ssh, das beim Stoppwort der eigenen Sitzung fortfällt: stdin bleibt hier offen,
        # nur der Elternprozess endet. Der Player soll nicht erst die Puffer ausspielen
        pid = self.tmp / "player.pid"
        zwischen = subprocess.Popen(
            [sys.executable, "-c", "import subprocess, sys; sys.exit(subprocess.call(sys.argv[1:]))",
             sys.executable, "-c", self.c.SPERRE_PY, str(self.sperre),
             "sh", "-c", f'echo $$ > "{pid}"; exec cat > /dev/null'], stdin=subprocess.PIPE)
        self.prozesse.append(zwischen)
        zwischen.stdin.write(b"Anfang")
        zwischen.stdin.flush()
        frist = time.monotonic() + 5
        while not (pid.exists() and pid.read_text().strip()) and time.monotonic() < frist:
            time.sleep(0.05)
        spieler = int(pid.read_text())
        time.sleep(0.2)
        zwischen.kill()
        zwischen.wait()
        frist = time.monotonic() + 3
        while time.monotonic() < frist:
            try:
                os.kill(spieler, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            os.kill(spieler, 9)
            self.fail("der Player lebt nach dem Ende des Elternprozesses noch")
        frist = time.monotonic() + 3
        while not (self.sperre.parent / "letzte.pcm").exists() and time.monotonic() < frist:
            time.sleep(0.05)
        self.assertEqual((self.sperre.parent / "letzte.pcm").read_bytes(), b"Anfang")

    def test_obergrenze_beendet_auch_einen_haengenden_player(self):
        pid = self.tmp / "player.pid"
        a = self._player("a", spieler=f'echo $$ > "{pid}"; exec sleep 30')
        a.stdin.write(b"PCM")
        a.stdin.close()  # der Player liest nicht: Er hängt, auch wenn kein Ton mehr kommt
        frist = time.monotonic() + 5
        while not (pid.exists() and pid.read_text().strip()) and time.monotonic() < frist:
            time.sleep(0.05)
        spieler = int(pid.read_text())
        self.assertFalse(self.c._warten(a, 0.3, gnade=2))
        frist = time.monotonic() + 3
        while time.monotonic() < frist:
            try:
                os.kill(spieler, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            os.kill(spieler, 9)
            self.fail("der Player lebt nach der Obergrenze noch")

    def test_liest_der_halter_eine_datei_schreibt_er_nicht_mit(self):
        # „Nochmal“: Ein Stopp mittendrin soll die letzte Antwort nicht kürzen
        self.sperre.parent.mkdir(parents=True)
        (self.sperre.parent / "letzte.pcm").write_bytes(b"ganze Antwort")
        quelle = self.tmp / "quelle.pcm"
        quelle.write_bytes(b"Anfang")
        with open(quelle, "rb") as eingabe:
            lauf = subprocess.run([sys.executable, "-c", self.c.SPERRE_PY, str(self.sperre),
                                   "sh", "-c", "cat > /dev/null"], stdin=eingabe, timeout=10)
        self.assertEqual(lauf.returncode, 0)
        self.assertEqual((self.sperre.parent / "letzte.pcm").read_bytes(), b"ganze Antwort")
        self.assertEqual(sorted(p.name for p in self.sperre.parent.iterdir()),
                         ["letzte.pcm", "player.lock"])

    def _warten_auf_start(self, name: str) -> None:
        frist = time.monotonic() + 5
        while name not in self._ablauf() and time.monotonic() < frist:
            time.sleep(0.05)
        self.assertIn(name, self._ablauf())

    def test_ohne_ssh_endet_der_wartende_still(self):
        # Ein Stopp beim Warten beendet ssh; sshd baut ab, der Wartende verliert die Eltern
        a = self._player("a", spieler=f'echo "start $1" >> "{self.ablauf}"; exec sleep 30')
        a.stdin.write(b"PCM")
        a.stdin.flush()
        self._warten_auf_start("a")
        eltern = subprocess.Popen(
            [sys.executable, "-c",
             "import subprocess, sys\n"
             "p = subprocess.Popen(sys.argv[1:], stdin=subprocess.PIPE)\n"
             "p.stdin.write(b'PCM'); p.stdin.flush()\n"
             "print(p.pid, flush=True)\n"
             "import time; time.sleep(0.5)\n",  # erst sterben, wenn das Kind wartet
             sys.executable, "-c", self.c.SPERRE_PY, str(self.sperre), "sh", "-c",
             f'echo "start b" >> "{self.ablauf}"'], stdout=subprocess.PIPE, text=True)
        b = int(eltern.stdout.readline())
        eltern.wait(timeout=5)
        eltern.stdout.close()
        frist = time.monotonic() + 5
        while time.monotonic() < frist:
            try:
                os.kill(b, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            os.kill(b, 9)
            self.fail("der Wartende ohne Eltern lebt noch")
        self.assertIsNone(a.poll())  # der Halter spielt weiter
        self.assertEqual(self._ablauf(), ["start", "a"])

    def test_haengender_halter_wird_abgeloest(self):
        # Ein Player, dessen Verbindung ohne Abbau abriss, wartet ohne Ende auf Ton
        a = self._player("a", spieler=f'echo "start $1" >> "{self.ablauf}"; exec sleep 30')
        a.stdin.write(b"PCM")
        a.stdin.flush()
        self._warten_auf_start("a")
        alt = time.time() - self.c.SPERRE_ALTER - 5
        self.sperre.write_text(f"{a.pid} {alt:.0f}", encoding="utf-8")
        b = self._player("b", dauer=0)
        b.stdin.write(b"PCM")
        b.stdin.close()
        self.assertNotEqual(a.wait(timeout=5), 0)
        self.assertEqual(b.wait(timeout=10), 0)
        self.assertEqual(self._ablauf(), ["start", "a", "start", "b", "ende", "b"])

    def test_ohne_sperrdatei_spielt_er_trotzdem(self):
        self.sperre = self.tmp / "datei" / "player.lock"
        self.sperre.parent.write_text("kein Ordner", encoding="utf-8")
        a = self._player("a", dauer=0)
        a.stdin.write(b"PCM")
        a.stdin.close()
        self.assertEqual(a.wait(timeout=10), 0)
        self.assertEqual(self._ablauf(), ["start", "a", "ende", "a"])

    @unittest.skipUnless(Path("/usr/bin/python3").exists(), "kein /usr/bin/python3")
    def test_platzhalter_von_macos_gilt_nicht_als_python(self):
        # Ohne Command Line Tools öffnete jeder Aufruf von /usr/bin/python3 einen Dialog
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        (bin_ / "uname").write_text("#!/bin/sh\necho Darwin\n", encoding="utf-8")
        for name, rc in (("ohne", 2), ("mit", 0)):
            (bin_ / "xcode-select").write_text(f"#!/bin/sh\nexit {rc}\n", encoding="utf-8")
            for datei in bin_.iterdir():
                datei.chmod(0o755)
            lauf = subprocess.run(["/bin/sh", "-c", f"{self.c.SPERRE_DA} && echo ja || echo nein"],
                                  env={"PATH": f"{bin_}:/usr/bin:/bin"}, capture_output=True,
                                  text=True, timeout=10)
            self.assertEqual(lauf.stdout.strip(), "nein" if name == "ohne" else "ja", name)


class Einstellungsdatei(unittest.TestCase):
    """~/.config/hoerbuch-generator/sprechen.conf: Vorgaben je Gerät, die Umgebung gilt davor."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="konfig"))
        self.datei = self.tmp / ".config" / "hoerbuch-generator" / "sprechen.conf"
        self.datei.parent.mkdir(parents=True)
        self.protokoll = self.tmp / "aufruf.txt"
        (self.tmp / "sprechen.sh").write_text(
            f'printf "%s\\n" "$*" > "{self.protokoll}"\ncat >> "{self.protokoll}"\n',
            encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _stop(self, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SKRIPT), "stop"],
                              input=json.dumps({"last_assistant_message": "<!-- sprechen: Ja. -->"}),
                              text=True, capture_output=True, timeout=30,
                              env={"HOME": str(self.tmp), "PATH": "/usr/bin:/bin",
                                   "HOERBUCH_GENERATOR": str(self.tmp), **(env or {})})

    def test_datei_setzt_vorgaben_und_die_umgebung_gilt_davor(self):
        self.datei.write_text("# Stimme dieses Geräts\nSPRECHEN_STIMME=dozent\n"
                              "SPRECHEN_LAUTER = 12  # neben Musik\n", encoding="utf-8")
        lauf = self._stop()
        self.assertEqual(lauf.returncode, 0)
        self.assertEqual(self.protokoll.read_text(encoding="utf-8"),
                         "-v dozent -t 1.1 --lauter 12 -\nJa.")
        self._stop({"SPRECHEN_STIMME": "erzaehler"})
        self.assertTrue(self.protokoll.read_text(encoding="utf-8").startswith("-v erzaehler "))

    def test_werte_wie_in_der_shell(self):
        import claude_sprechen
        self.datei.write_text(
            "SPRECHEN_GERAETE='hier notebook'\n"
            'SPRECHEN_ENTFERNT_REPO="~/repos/hoerbuch-generator"\n'
            "SPRECHEN_PLAYER=sh -c 'cat > /dev/null'\n"
            "SPRECHEN_UNTERBRECHEN=\n", encoding="utf-8")
        werte, meldungen = claude_sprechen.konfig_lesen(self.datei)
        self.assertEqual(meldungen, [])
        self.assertEqual(werte["SPRECHEN_GERAETE"], "hier notebook")
        self.assertEqual(werte["SPRECHEN_ENTFERNT_REPO"], "~/repos/hoerbuch-generator")
        self.assertEqual(werte["SPRECHEN_UNTERBRECHEN"], "")
        import shlex
        self.assertEqual(shlex.split(werte["SPRECHEN_PLAYER"]), ["sh", "-c", "cat > /dev/null"])

    def test_falsche_zeilen_gelten_nicht_und_brechen_nichts_ab(self):
        import claude_sprechen
        self.datei.write_text("SPRECHEN_AUS=1\nSPRECHEN_STIMM=dozent\nkeine Zuweisung\n"
                              "SPRECHEN_STIMME='offen\nSPRECHEN_TEMPO=1.3\n", encoding="utf-8")
        werte, meldungen = claude_sprechen.konfig_lesen(self.datei)
        self.assertEqual(werte, {"SPRECHEN_TEMPO": "1.3"})
        self.assertEqual(len(meldungen), 4, meldungen)
        self.assertIn("SPRECHEN_AUS gehört in die Umgebung", meldungen[0])
        lauf = self._stop()
        self.assertEqual(lauf.returncode, 0)
        # SPRECHEN_AUS aus der Datei macht nicht stumm, der Rest gilt
        self.assertEqual(self.protokoll.read_text(encoding="utf-8"),
                         "-v marketing -t 1.3 --lauter 8 -\nJa.")
        self.assertIn("Einstellungen: Zeile 1", lauf.stderr)

    def test_ohne_datei_wie_bisher(self):
        self.datei.unlink(missing_ok=True)
        lauf = self._stop()
        self.assertEqual((lauf.returncode, lauf.stderr), (0, ""))
        self.assertEqual(self.protokoll.read_text(encoding="utf-8"),
                         "-v marketing -t 1.1 --lauter 8 -\nJa.")

    def test_unlesbare_datei(self):
        import claude_sprechen
        self.datei.write_bytes(b"\xff\xfe")
        werte, meldungen = claude_sprechen.konfig_lesen(self.datei)
        self.assertEqual(werte, {})
        self.assertIn("nicht lesbar", meldungen[0])
        self.datei.unlink()
        self.datei.mkdir()
        werte, meldungen = claude_sprechen.konfig_lesen(self.datei)
        self.assertEqual(werte, {})
        self.assertIn("keine Datei", meldungen[0])

    def test_kommentar_nur_am_wortanfang(self):
        import claude_sprechen
        # Mit BOM, wie ein Editor unter Windows die Datei schreibt
        self.datei.write_text("﻿SPRECHEN_ENTFERNT=mac#2 # Kommentar\n"
                              "SPRECHEN_PLAYER='a # b' c\\ #d\n"
                              "SPRECHEN_STIMME=#nur Kommentar\n", encoding="utf-8")
        werte, meldungen = claude_sprechen.konfig_lesen(self.datei)
        self.assertEqual(meldungen, [])
        self.assertEqual(werte, {"SPRECHEN_ENTFERNT": "mac#2",
                                 "SPRECHEN_PLAYER": "'a # b' 'c #d'",
                                 "SPRECHEN_STIMME": ""})

    def test_nullzeichen_endet_nicht_mit_traceback(self):
        self.datei.write_bytes(b"SPRECHEN_STIMME=a\x00b\nSPRECHEN_TEMPO=1.3\n")
        lauf = self._stop()
        self.assertEqual(lauf.returncode, 0, lauf.stderr)
        self.assertIn("Nullzeichen", lauf.stderr)
        self.assertEqual(self.protokoll.read_text(encoding="utf-8"),
                         "-v marketing -t 1.3 --lauter 8 -\nJa.")

    def test_stoppwort_nimmt_das_praefix_des_stop_hooks_vor_der_datei(self):
        import claude_sprechen
        self.datei.write_text("SPRECHEN_GERAETE='aus-datei'\n", encoding="utf-8")
        (self.tmp / ".claude").mkdir()
        settings = self.tmp / ".claude" / "settings.json"
        skript = "python3 x/claude_sprechen.py"
        settings.write_text(json.dumps({"hooks": {
            "Stop": [{"hooks": [{"type": "command",
                                 "command": f"SPRECHEN_GERAETE='notebook mac' {skript} stop"}]}],
            "UserPromptSubmit": [{"hooks": [{"type": "command",
                                             "command": f"{skript} prompt"}]}]}}),
            encoding="utf-8")
        umgebung = {"HOME": str(self.tmp), "PATH": "/usr/bin:/bin"}
        with mock.patch.dict(os.environ, umgebung, clear=True), \
                mock.patch.object(claude_sprechen, "AUS_DATEI", set()):
            claude_sprechen.konfig_anwenden()
            self.assertEqual(os.environ["SPRECHEN_GERAETE"], "aus-datei")
            self.assertEqual(claude_sprechen.stopp_geraete(), ["notebook", "mac"])
            # Ohne Präfix gilt die Datei, ohne lesbare settings.json ebenso
            settings.write_text("{}", encoding="utf-8")
            self.assertEqual(claude_sprechen.stopp_geraete(), ["aus-datei"])
            settings.unlink()
            self.assertEqual(claude_sprechen.stopp_geraete(), ["aus-datei"])
        # Die Umgebung des Prompt-Hooks selbst gilt vor beidem
        with mock.patch.dict(os.environ, {**umgebung, "SPRECHEN_GERAETE": "hier"}, clear=True), \
                mock.patch.object(claude_sprechen, "AUS_DATEI", set()):
            claude_sprechen.konfig_anwenden()
            self.assertEqual(claude_sprechen.stopp_geraete(), ["hier"])


class Tastenkuerzel(unittest.TestCase):
    """taste-stopp und nochmal auf dem Gerät, das spielt; HOME im Testordner, dort liegen
    player.lock und letzte.pcm."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="taste"))
        self.ordner = self.tmp / ".cache" / "hoerbuch-generator"
        self.ordner.mkdir(parents=True)
        self.protokoll = self.tmp / "aufruf.txt"
        (self.tmp / "sprechen.sh").write_text(f'printf "%s\\n" "$*" >> "{self.protokoll}"\n',
                                              encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _lauf(self, befehl: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SKRIPT), befehl], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30,
                              env={"HOME": str(self.tmp), "PATH": "/usr/bin:/bin",
                                   "HOERBUCH_GENERATOR": str(self.tmp), **(env or {})})

    def test_nochmal_spielt_die_letzte_antwort_unter_der_sperre(self):
        (self.ordner / "letzte.pcm").write_bytes(b"PCM-letzte")
        gespielt = self.tmp / "gespielt.pcm"
        lauf = self._lauf("nochmal", {"SPRECHEN_PLAYER": f"sh -c 'cat > {gespielt}'"})
        self.assertEqual(lauf.returncode, 0, lauf.stderr)
        frist = time.monotonic() + 10
        while (gespielt.read_bytes() if gespielt.exists() else b"") != b"PCM-letzte":
            if time.monotonic() > frist:
                self.fail("nochmal spielte nichts")
            time.sleep(0.05)
        # Der Halter hat die Sperre genommen: Seine PID steht in der Datei
        frist = time.monotonic() + 5
        while not (self.ordner / "player.lock").read_text().strip() and time.monotonic() < frist:
            time.sleep(0.05)
        self.assertRegex((self.ordner / "player.lock").read_text(), r"^\d+ \d+$")

    def test_nochmal_ohne_antwort(self):
        lauf = self._lauf("nochmal", {"SPRECHEN_PLAYER": "cat"})
        self.assertEqual(lauf.returncode, 1)
        self.assertIn("Noch keine Antwort", lauf.stderr)

    def test_stopp_trifft_den_halter_und_den_dienst_hier(self):
        import claude_sprechen
        halter = subprocess.Popen([sys.executable, "-c", claude_sprechen.SPERRE_PY,
                                   str(self.ordner / "player.lock"), "sleep", "30"],
                                  stdin=subprocess.PIPE)
        try:
            halter.stdin.write(b"PCM")
            halter.stdin.flush()
            frist = time.monotonic() + 5
            while (not (self.ordner / "player.lock").exists()
                   or not (self.ordner / "player.lock").read_text().strip()):
                if time.monotonic() > frist:
                    self.fail("der Halter nahm die Sperre nicht")
                time.sleep(0.05)
            # Ohne .venv läuft hier kein Dienst: kein Aufruf von sprechen.sh
            self.assertEqual(self._lauf("taste-stopp").returncode, 0)
            self.assertEqual(halter.wait(timeout=5), 143)
            self.assertFalse(self.protokoll.exists())
        finally:
            halter.kill()
            halter.wait()
            halter.stdin.close()
        (self.tmp / ".venv" / "bin").mkdir(parents=True)
        (self.tmp / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
        self.assertEqual(self._lauf("taste-stopp").returncode, 0)
        self.assertEqual(self.protokoll.read_text(encoding="utf-8"),
                         "--stopp --quelle tastenkuerzel --sonst-aktuell\n")


class Sitzungsbeginn(unittest.TestCase):
    """start: Der SessionStart-Hook gibt die Regeln aus sprechen.md als Kontext aus."""

    def test_regeln_als_kontext_ohne_bestaetigung(self):
        with tempfile.TemporaryDirectory() as ordner:
            lauf = subprocess.run([sys.executable, str(SKRIPT), "start"],
                                  input=json.dumps({"session_id": "abc", "source": "startup"}),
                                  text=True, capture_output=True, timeout=20,
                                  env={**os.environ, "XDG_RUNTIME_DIR": ordner})
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

    def test_sprechen_aus_ist_ein_hinweis(self):
        self._standard()
        rc, aus = self._pruefen(SPRECHEN_AUS="1")
        self.assertEqual(rc, 0, aus)
        self.assertIn("Hinweis: SPRECHEN_AUS=1: alle Hooks tun nichts", aus)
        self.assertNotIn("Variable  SPRECHEN_AUS=1\n", aus)  # nur einmal, als Hinweis

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

    def test_einstellungsdatei_statt_praefix(self):
        # Gleiche Hook-Befehle auf jedem Gerät, die Werte stehen in der Datei
        skript = "python3 $HOME/hg/integrationen/claude-code/claude_sprechen.py"
        self._settings({"Stop": self._hook(f"{skript} stop"),
                        "UserPromptSubmit": self._hook(f"{skript} prompt"),
                        "Notification": self._hook(f"{skript} notification")})
        datei = self.tmp / ".config" / "hoerbuch-generator" / "sprechen.conf"
        datei.parent.mkdir(parents=True)
        datei.write_text("SPRECHEN_ENTFERNT=mac\nSPRECHEN_GERAETE='buero'\n", encoding="utf-8")
        rc, aus = self._pruefen()
        self.assertEqual(rc, 0, aus)
        self.assertIn(f"Datei     {datei}: 2 Einstellung(en)", aus)
        self.assertIn("Variable  SPRECHEN_GERAETE=buero", aus)
        self.assertIn("Rechnen   mac: ssh ok", aus)
        self.assertNotIn("weicht ab", aus)
        # Ein Präfix gilt vor der Datei, und dann weicht der Hook ab
        self._settings({"Stop": self._hook(f"SPRECHEN_ENTFERNT=rechner {skript} stop"),
                        "UserPromptSubmit": self._hook(f"{skript} prompt")})
        rc, aus = self._pruefen()
        self.assertIn("FEHLER: SPRECHEN_ENTFERNT weicht ab: Stop rechner, UserPromptSubmit mac", aus)
        # Eine Zeile, die nicht gilt, ist ein Fehler und kommt nur einmal
        datei.write_text("SPRECHEN_ENTFERNT=mac\nSPRECHEN_GERAET=buero\n", encoding="utf-8")
        lauf = subprocess.run([sys.executable, str(SKRIPT), "pruefen"], stdin=subprocess.DEVNULL,
                              text=True, capture_output=True, env=self.env, timeout=30)
        self.assertIn("Datei     FEHLER: Zeile 2: SPRECHEN_GERAET ist keine Einstellung",
                      lauf.stdout)
        self.assertNotIn("Zeile 2", lauf.stderr)

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
        for player in ("printf %s paplay;", "printf %s ffmpeg;", "printf %s ffplay;"):
            self.assertIn(player, name)
        self.assertNotIn("exec", claude_sprechen.FERN_STOPP)


if __name__ == "__main__":
    unittest.main()
