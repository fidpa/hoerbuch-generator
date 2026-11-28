"""
test_sprechdienst.py - Satzteilung und Protokoll des Sprechdienstes, ohne Modell

Die Sprachausgabe selbst bleibt aussen vor: Sie braucht MLX, eine GPU und rund 2 GB
Modelle. Geprueft wird, wie der Text in Stuecke zerfaellt und wie der Dienst ueber den
Socket antwortet. Dafuer ersetzt der Test den Sprecher-Thread durch einen, der nichts
laedt. Ohne numpy und soundfile (CI-Lauf nur mit PyMuPDF) wird der Test uebersprungen.

Usage:
    .venv/bin/python -m unittest discover -s tests -v
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "werkzeuge"))

ABHAENGIG = all(importlib.util.find_spec(m) for m in ("numpy", "soundfile"))


@unittest.skipUnless(ABHAENGIG, "numpy und soundfile fehlen")
class Stuecke(unittest.TestCase):
    def setUp(self):
        import sprechdienst
        self.s = sprechdienst

    def test_kurze_saetze_werden_zusammengefasst(self):
        plan = self.s.stuecke("Ja. Gut. Das ist ein Satz, der lang genug ist, um allein zu stehen.")
        self.assertEqual(plan, [("Ja. Gut. Das ist ein Satz, der lang genug ist, um allein zu stehen.",
                                 True)])

    def test_lange_saetze_bleiben_getrennt(self):
        a = "Der erste Satz ist lang genug, um ein eigenes Stück zu bilden."
        b = "Der zweite Satz ist ebenfalls lang genug für ein eigenes Stück."
        self.assertEqual(self.s.stuecke(f"{a} {b}"), [(a, False), (b, True)])

    def test_kurzer_schlusssatz_haengt_am_vorigen(self):
        a = "Der erste Satz ist lang genug, um ein eigenes Stück zu bilden."
        b = "Der zweite Satz ist ebenfalls lang genug für ein eigenes Stück."
        self.assertEqual(self.s.stuecke(f"{a} {b} Soll ich das vorbereiten?"),
                         [(a, False), (f"{b} Soll ich das vorbereiten?", True)])

    def test_absaetze_markieren_ihr_ende(self):
        plan = self.s.stuecke("Erster Absatz.\n\nZweiter Absatz.")
        self.assertEqual(plan, [("Erster Absatz.", True), ("Zweiter Absatz.", True)])

    def test_ordnungszahl_teilt_den_satz_nicht(self):
        satz = ("Der Termin, über den wir gestern gesprochen haben, ist am 26. November "
                "um zehn Uhr im großen Raum im dritten Stock.")
        self.assertEqual(self.s.stuecke(satz), [(satz, True)])

    def test_nur_leerraum_ergibt_nichts(self):
        self.assertEqual(self.s.stuecke(""), [])
        self.assertEqual(self.s.stuecke("  \n\n  "), [])
        self.assertEqual(self.s.stuecke("Ja."), [("Ja.", True)])

    def test_ueberlange_saetze_werden_geteilt(self):
        satz = ", ".join(["ein Glied der Aufzählung"] * 40) + "."
        plan = self.s.stuecke(satz)
        self.assertGreater(len(plan), 1)
        self.assertTrue(all(len(t) <= self.s.qwen.MAX_CHARS for t, _ in plan))


@unittest.skipUnless(ABHAENGIG, "numpy und soundfile fehlen")
class Nachbearbeitung(unittest.TestCase):
    def setUp(self):
        import sprechdienst
        self.s = sprechdienst

    def test_neutral_ohne_filter(self):
        self.assertEqual(self.s.filterkette(1.0, 0.0), "")

    def test_filterkette(self):
        self.assertEqual(self.s.filterkette(1.1, 0.0), "atempo=1.1")
        self.assertEqual(self.s.filterkette(1.0, 8.0),
                         f"volume=8.0dB,alimiter=limit={self.s.LIMIT_DB}dB:level=false")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg fehlt")
    def test_lauter_hebt_an_und_begrenzt_spitzen(self):
        import numpy as np
        rate = self.s.qwen.SAMPLE_RATE
        t = np.arange(rate) / rate
        leise = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        laut = self.s.nachbearbeiten(leise, 1.0, 12.0)
        grenze = 10 ** (self.s.LIMIT_DB / 20)
        self.assertGreater(np.sqrt(np.mean(laut ** 2)), 2 * np.sqrt(np.mean(leise ** 2)))
        self.assertLessEqual(np.max(np.abs(laut)), grenze + 0.01)


@unittest.skipUnless(ABHAENGIG, "numpy und soundfile fehlen")
class StoppJeQuelle(unittest.TestCase):
    """Ohne Socket und Modell: Dienst direkt, Auftraege von Hand in die Warteschlange."""

    def setUp(self):
        import sprechdienst
        self.s = sprechdienst
        self.dienst = sprechdienst.Dienst(Path(tempfile.gettempdir()) / "unbenutzt.sock", 60)

    def _auftrag(self, quelle: str):
        a = self.s.Auftrag(text="Hallo.", stimme="erzaehler", tempo=1.0, mit_atem=False,
                           runde=self.dienst.runde, quelle=quelle)
        self.dienst.auftraege.put(a)
        return a

    def test_stopp_mit_quelle_trifft_nur_diese(self):
        a, b = self._auftrag("sitzung-a"), self._auftrag("sitzung-b")
        self.dienst.aktuell = self.s.Auftrag(text="x", stimme="erzaehler", tempo=1.0,
                                             mit_atem=False, runde=self.dienst.runde,
                                             quelle="sitzung-b")
        self.dienst._stoppen("sitzung-a")
        self.assertTrue(a.vorbei(self.dienst.runde))
        self.assertFalse(b.vorbei(self.dienst.runde))
        self.assertFalse(self.dienst.aktuell.vorbei(self.dienst.runde))

    def test_stopp_mit_quelle_bricht_laufenden_auftrag_ab(self):
        laufend = self.s.Auftrag(text="x", stimme="erzaehler", tempo=1.0, mit_atem=False,
                                 runde=self.dienst.runde, quelle="sitzung-a")
        self.dienst.aktuell = laufend
        self.dienst._stoppen("sitzung-a")
        self.assertTrue(laufend.vorbei(self.dienst.runde))

    def test_stopp_zwischen_entnahme_und_uebernahme_greift(self):
        # Der Sprecher hat den Auftrag schon aus der Warteschlange genommen, ihn aber noch
        # nicht als aktuell gesetzt: Der Stopp findet ihn an keiner der beiden Stellen
        a = self._auftrag("sitzung-a")
        self.assertIs(self.dienst.auftraege.get_nowait(), a)
        self.dienst._stoppen("sitzung-a")
        self.assertFalse(self.dienst._uebernehmen(a))
        self.assertTrue(a.fertig.is_set())
        self.assertIsNone(self.dienst.aktuell)
        self.assertEqual(a.ergebnis, {"abgebrochen": True})

    def test_auftrag_nach_dem_stopp_laeuft(self):
        self.dienst._stoppen("sitzung-a")
        b = self._auftrag("sitzung-a")
        self.assertTrue(self.dienst._uebernehmen(self.dienst.auftraege.get_nowait()))
        self.assertIs(self.dienst.aktuell, b)

    def test_ansage_nur_beim_wechsel_der_quelle(self):
        a = self.s.Auftrag(text="Fertig.", stimme="erzaehler", tempo=1.0, mit_atem=False,
                           runde=0, quelle="sitzung-a", ansage="Aus Notizen.")
        self.assertEqual(self.s.text_mit_ansage(a, "sitzung-b"), "Aus Notizen. Fertig.")
        self.assertEqual(self.s.text_mit_ansage(a, "sitzung-a"), "Fertig.")
        self.assertEqual(self.s.text_mit_ansage(a, ""), "Fertig.")  # erster Auftrag

    def _laufend(self, quelle: str):
        self.dienst.aktuell = self.s.Auftrag(text="x", stimme="erzaehler", tempo=1.0,
                                             mit_atem=False, runde=self.dienst.runde,
                                             quelle=quelle)
        return self.dienst.aktuell

    def test_sonst_aktuell_trifft_die_laufende_fremde_ausgabe(self):
        # Ein Stoppwort im Fenster mit dem Fokus, gesprochen hat eine andere Sitzung
        wartend, laufend = self._auftrag("sitzung-b"), self._laufend("sitzung-b")
        self.assertEqual(self.dienst._stoppen("sitzung-a", sonst_aktuell=True), "aktuell")
        self.assertTrue(laufend.vorbei(self.dienst.runde))
        self.assertFalse(wartend.vorbei(self.dienst.runde))

    def test_sonst_aktuell_nur_ohne_eigene_ausgabe(self):
        laufend = self._laufend("sitzung-b")
        eigen = self._auftrag("sitzung-a")
        self.assertEqual(self.dienst._stoppen("sitzung-a", sonst_aktuell=True), "eigene")
        self.assertTrue(eigen.vorbei(self.dienst.runde))
        self.assertFalse(laufend.vorbei(self.dienst.runde))
        self._laufend("sitzung-a")
        self.assertEqual(self.dienst._stoppen("sitzung-a", sonst_aktuell=True), "eigene")

    def test_sonst_aktuell_trifft_keinen_gelieferten_auftrag(self):
        # Geliefert wird oft die nächste Antwort, die am Gerät noch auf die Sperre wartet
        laufend = self._laufend("sitzung-b")
        laufend.ziel = unittest.mock.Mock()
        self.assertEqual(self.dienst._stoppen("sitzung-a", sonst_aktuell=True), "nichts")
        self.assertFalse(laufend.vorbei(self.dienst.runde))
        laufend.ziel.shutdown.assert_not_called()

    def test_ohne_sonst_aktuell_bleibt_die_fremde_ausgabe(self):
        laufend = self._laufend("sitzung-b")
        self.assertEqual(self.dienst._stoppen("sitzung-a"), "nichts")
        self.assertFalse(laufend.vorbei(self.dienst.runde))
        self.dienst.aktuell = None
        self.assertEqual(self.dienst._stoppen("sitzung-a", sonst_aktuell=True), "nichts")

    def test_stopp_antwortet_mit_dem_treffer(self):
        self._laufend("sitzung-b")
        antwort = self.dienst._bearbeiten({"cmd": "stopp", "quelle": "sitzung-a",
                                           "sonst_aktuell": True})
        self.assertEqual(antwort, {"ok": True, "getroffen": "aktuell"})
        self.assertFalse(self.dienst._bearbeiten({"cmd": "stopp", "sonst_aktuell": "ja"})["ok"])

    def test_stopp_ohne_quelle_trifft_alle(self):
        a, b = self._auftrag("sitzung-a"), self._auftrag("")
        self.assertEqual(self.dienst._stoppen(), "alle")
        self.assertTrue(a.vorbei(self.dienst.runde))
        self.assertTrue(b.vorbei(self.dienst.runde))
        self.assertEqual(self.dienst.auftraege.qsize(), 0)


MLX_AUDIO = ABHAENGIG and all(importlib.util.find_spec(m) for m in ("mlx_audio", "sounddevice"))


@unittest.skipUnless(MLX_AUDIO, "mlx-audio fehlt (nur in der .venv auf dem Mac)")
class PlayerNurUnterSperre(unittest.TestCase):
    """Der echte AudioPlayer von mlx-audio, nur ohne Geraet: Wer den Stream startet oder
    schliesst, muss die Player-Sperre halten, sonst schliesst ein Stopp aus einem
    Verbindungs-Thread den Stream mitten im Start."""

    def test_kurzer_auftrag_startet_den_stream_unter_der_sperre(self):
        import numpy as np
        import sprechdienst
        from mlx_audio.tts.audio_player import AudioPlayer

        dienst = sprechdienst.Dienst(Path(tempfile.gettempdir()) / "unbenutzt.sock", 60)
        ohne_sperre: list[str] = []

        class OhneGeraet(AudioPlayer):
            def start_stream(self):
                if not dienst._player_sperre.locked():
                    ohne_sperre.append("start_stream")
                # wie ein Geraet, das alles abgespielt hat
                with self.buffer_lock:
                    self.audio_buffer.clear()
                self.playing = False
                self.drain_event.set()

            def stop_stream(self, *, abort=False):
                if not dienst._player_sperre.locked():
                    ohne_sperre.append("stop_stream")
                self.playing = False
                self.drain_event.set()

        dienst.player = OhneGeraet(sample_rate=sprechdienst.qwen.SAMPLE_RATE)
        kurz = np.zeros(sprechdienst.qwen.SAMPLE_RATE // 5, np.float32)  # unter 1,5 s Puffer
        auftrag = sprechdienst.Auftrag(text="Ja.", stimme="erzaehler", tempo=1.0,
                                       mit_atem=False, runde=dienst.runde)
        with tempfile.TemporaryDirectory() as ordner, \
                unittest.mock.patch.object(sprechdienst, "LETZTE_PCM", Path(ordner) / "l.pcm"), \
                unittest.mock.patch.object(sprechdienst.qwen, "synthesize_chunk",
                                           return_value=kurz):
            dienst._sprechen(None, auftrag, None, "", None)
            # Für „Nochmal“: der Ton samt Pause, wie ihn der Lautsprecher bekam
            self.assertGreater((Path(ordner) / "l.pcm").stat().st_size, len(kurz) * 2)
        self.assertEqual(ohne_sperre, [])
        self.assertFalse(auftrag.ergebnis["abgebrochen"])
        self.assertGreater(auftrag.ergebnis["audio_s"], 0)


@unittest.skipUnless(ABHAENGIG, "numpy und soundfile fehlen")
class LetzteAusgabe(unittest.TestCase):
    def test_schreibt_ersetzend_und_nichts_ohne_ton(self):
        import sprechdienst
        with tempfile.TemporaryDirectory() as ordner:
            ziel = Path(ordner) / "unter" / "letzte.pcm"
            with unittest.mock.patch.object(sprechdienst, "LETZTE_PCM", ziel):
                sprechdienst.letzte_schreiben(b"")
                self.assertFalse(ziel.exists())
                sprechdienst.letzte_schreiben(b"\x01\x00")
                sprechdienst.letzte_schreiben(b"\x02\x00\x03\x00")
            self.assertEqual(ziel.read_bytes(), b"\x02\x00\x03\x00")
            self.assertEqual([p.name for p in ziel.parent.iterdir()], ["letzte.pcm"])

    def test_ohne_schreibrecht_nur_eine_warnung(self):
        import sprechdienst
        with tempfile.TemporaryDirectory() as ordner:
            (Path(ordner) / "datei").write_text("", encoding="utf-8")
            ziel = Path(ordner) / "datei" / "letzte.pcm"
            with unittest.mock.patch.object(sprechdienst, "LETZTE_PCM", ziel), \
                    self.assertLogs("sprechdienst", "WARNING"):
                sprechdienst.letzte_schreiben(b"\x01\x00")


@unittest.skipUnless(ABHAENGIG, "numpy und soundfile fehlen")
class Leerlaufzeit(unittest.TestCase):
    """SPRECHDIENST_LEERLAUF aus der Umgebung oder der Einstellungsdatei unter
    XDG_CONFIG_HOME im Testordner."""

    def setUp(self):
        import sprechdienst
        self.s = sprechdienst
        self.tmp = tempfile.TemporaryDirectory()
        self.datei = Path(self.tmp.name) / "hoerbuch-generator" / "sprechen.conf"
        self.datei.parent.mkdir()
        umgebung = {k: v for k, v in os.environ.items() if k != "SPRECHDIENST_LEERLAUF"}
        self.env = unittest.mock.patch.dict(os.environ, {**umgebung,
                                                         "XDG_CONFIG_HOME": self.tmp.name},
                                            clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_ohne_einstellung_die_vorgabe(self):
        self.assertEqual(self.s.leerlauf_vorgabe(), self.s.LEERLAUF)

    def test_aus_der_datei_und_die_umgebung_davor(self):
        self.datei.write_text("SPRECHEN_GERAETE='hier buero'\n"
                              "SPRECHDIENST_LEERLAUF='3600'  # eine Stunde\n", encoding="utf-8")
        self.assertEqual(self.s.leerlauf_vorgabe(), 3600.0)
        os.environ["SPRECHDIENST_LEERLAUF"] = "7200"
        self.assertEqual(self.s.leerlauf_vorgabe(), 7200.0)

    def test_unbrauchbar_gilt_nicht(self):
        for wert in ("30", "eine Stunde", "nan", "-5", "inf", "1e400", "3600 7200"):
            self.datei.write_text(f"SPRECHDIENST_LEERLAUF={wert}\n", encoding="utf-8")
            with self.assertLogs("sprechdienst", "WARNING"):
                self.assertEqual(self.s.leerlauf_vorgabe(), self.s.LEERLAUF, wert)
        # Eine Zeile, die shlex nicht lesen kann, zählt wie keine
        self.datei.write_text("SPRECHDIENST_LEERLAUF='3600\n", encoding="utf-8")
        self.assertEqual(self.s.leerlauf_vorgabe(), self.s.LEERLAUF)

    def test_leer_zaehlt_wie_nicht_gesetzt(self):
        # Leer in der Datei setzt der Hook als leere Umgebung; beides ohne Warnung
        self.datei.write_text("SPRECHDIENST_LEERLAUF=\n", encoding="utf-8")
        os.environ["SPRECHDIENST_LEERLAUF"] = ""
        with self.assertNoLogs("sprechdienst", "WARNING"):
            self.assertEqual(self.s.leerlauf_vorgabe(), self.s.LEERLAUF)
        # Leer in der Umgebung lässt die Datei gelten
        self.datei.write_text("SPRECHDIENST_LEERLAUF=3600\n", encoding="utf-8")
        self.assertEqual(self.s.leerlauf_vorgabe(), 3600.0)

    def test_keine_datei_an_der_stelle(self):
        self.datei.mkdir()
        self.assertEqual(self.s.leerlauf_vorgabe(), self.s.LEERLAUF)
        self.datei.rmdir()
        # Eine Pipe hielte den Start beim Lesen fest
        os.mkfifo(self.datei)
        self.assertEqual(self.s.leerlauf_vorgabe(), self.s.LEERLAUF)

    def test_dieselbe_zeile_ergibt_denselben_wert_wie_im_hook_skript(self):
        sys.path.insert(0, str(REPO / "integrationen" / "claude-code"))
        import claude_sprechen
        name = "SPRECHDIENST_LEERLAUF"
        for text in ("SPRECHDIENST_LEERLAUF=3600\n",
                     "﻿SPRECHDIENST_LEERLAUF=3600\n",
                     "SPRECHDIENST_LEERLAUF = \"3600\"  # eine Stunde\n",
                     "SPRECHDIENST_LEERLAUF=3600#x\n",
                     "SPRECHDIENST_LEERLAUF=3600 7200\n",
                     "SPRECHDIENST_LEERLAUF='36 00'\n",
                     "SPRECHDIENST_LEERLAUF=\n",
                     "# SPRECHDIENST_LEERLAUF=60\n",
                     "SPRECHDIENST_LEERLAUF=600\nSPRECHDIENST_LEERLAUF=3600\n",
                     "SPRECHDIENST_LEERLAUF=600\nSPRECHDIENST_LEERLAUF='3600\n",
                     "SPRECHDIENST_LEERLAUF=600\nSPRECHDIENST_LEERLAUF=36\x0000\n"):
            self.datei.write_text(text, encoding="utf-8")
            self.assertEqual(self.s._aus_konfig(name),
                             claude_sprechen.konfig_lesen(self.datei)[0].get(name), repr(text))
        self.datei.write_text("SPRECHDIENST_LEERLAUF=3600\n", encoding="utf-8")
        self.assertEqual(claude_sprechen.konfig_lesen(self.datei),
                         ({"SPRECHDIENST_LEERLAUF": "3600"}, []))


@unittest.skipUnless(ABHAENGIG, "numpy und soundfile fehlen")
class Stummschalter(unittest.TestCase):
    """Liegt die Datei stumm neben LETZTE_PCM, spielt der Dienst nichts selbst ab, auch einen
    Auftrag nicht, der nach dem Stopp des Stummschalters ankam. Geliefert wird weiter."""

    def setUp(self):
        import socket

        import numpy as np
        import sprechdienst
        self.s = sprechdienst
        self.dienst = sprechdienst.Dienst(Path(tempfile.gettempdir()) / "unbenutzt.sock", 60)
        self.gespielt: list[int] = []

        class Player:
            playing = False

            def queue_audio(_, audio):
                self.gespielt.append(len(audio))

            def buffered_samples(_):
                return 0

            def start_stream(_):
                pass

            def wait_for_drain(_):
                pass

            def stop_stream(_, *, abort=False):
                pass

        self.dienst.player = Player()
        self.ordner = Path(tempfile.mkdtemp(prefix="stumm"))
        self.stumm = self.ordner / "stumm"
        self.stumm.write_text("1700000000\n", encoding="utf-8")
        self.dienst_seite, self.aufrufer = socket.socketpair()
        self.ton = np.zeros(sprechdienst.qwen.SAMPLE_RATE // 5, np.float32)
        self.patches = [
            unittest.mock.patch.object(sprechdienst, "LETZTE_PCM", self.ordner / "letzte.pcm"),
            unittest.mock.patch.object(sprechdienst.qwen, "synthesize_chunk",
                                       return_value=self.ton)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.dienst_seite.close()
        self.aufrufer.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def _auftrag(self, **weitere):
        return self.s.Auftrag(text="Ein Satz, der lang genug für ein eigenes Stück ist.",
                              stimme="erzaehler", tempo=1.0, mit_atem=True,
                              runde=self.dienst.runde, **weitere)

    def test_stumm_spielt_nichts_ab(self):
        auftrag = self._auftrag()
        with self.assertLogs("sprechdienst", "INFO"):
            self.dienst._sprechen(None, auftrag, None, "", None)
        self.assertEqual(self.gespielt, [])
        self.assertTrue(auftrag.ergebnis["abgebrochen"])
        self.assertFalse((self.ordner / "letzte.pcm").exists())
        self.stumm.unlink()
        auftrag = self._auftrag()
        self.dienst._sprechen(None, auftrag, None, "", None)
        self.assertNotEqual(self.gespielt, [])
        self.assertFalse(auftrag.ergebnis["abgebrochen"])

    def test_geliefert_wird_trotzdem(self):
        auftrag = self._auftrag(ziel=self.dienst_seite)
        # Lesen in einem eigenen Thread wie bei Liefern: Der Puffer eines socketpair fasst nur
        # wenige KB
        empfangen: list[bytes] = []

        def lesen():
            while teil := self.aufrufer.recv(65536):
                empfangen.append(teil)

        leser = threading.Thread(target=lesen, daemon=True)
        leser.start()
        self.dienst._sprechen(None, auftrag, None, "", None)
        self.dienst_seite.shutdown(2)
        leser.join(timeout=5)
        self.assertFalse(auftrag.ergebnis["abgebrochen"])
        self.assertGreater(len(b"".join(empfangen)), 0)
        self.assertEqual(self.gespielt, [])


@unittest.skipUnless(ABHAENGIG, "numpy und soundfile fehlen")
class SprecherUebersteht(unittest.TestCase):
    """Ein Fehler in einem Auftrag (etwa kein Ausgabegeraet) darf den Sprecher-Thread nicht
    beenden; der Dienst naehme sonst weiter Auftraege an, ohne je zu sprechen. MLX und
    das Atem-Modell ersetzt der Test durch leere Module."""

    def test_fehler_im_auftrag_beendet_den_sprecher_nicht(self):
        import types

        import numpy as np
        import sprechdienst

        class Player:
            def __init__(self, **_):
                pass

            def flush(self):
                pass

        def modul(name, **inhalt):
            m = types.ModuleType(name)
            m.__dict__.update(inhalt)
            return m

        attrappen = {
            "mlx_audio": modul("mlx_audio"),
            "mlx_audio.tts": modul("mlx_audio.tts"),
            "mlx_audio.tts.audio_player": modul("mlx_audio.tts.audio_player", AudioPlayer=Player),
            "mlx_audio.tts.utils": modul("mlx_audio.tts.utils", load_model=lambda _: object()),
            "mlx_audio.utils": modul("mlx_audio.utils",
                                     load_audio=lambda *_, **__: np.zeros(10, np.float32)),
            "atem": modul("atem", attenuate=None),
        }
        dienst = sprechdienst.Dienst(Path(tempfile.gettempdir()) / "unbenutzt.sock", 60)
        gesprochen: list[str] = []

        def sprechen(_model, auftrag, *_):
            if auftrag.text == "kaputt":
                raise RuntimeError("kein Ausgabegerät")
            gesprochen.append(auftrag.text)
            auftrag.ergebnis = {"abgebrochen": False, "audio_s": 1.0}

        auftraege = [sprechdienst.Auftrag(text=t, stimme="erzaehler", tempo=1.0,
                                          mit_atem=True, runde=0) for t in ("kaputt", "gut")]
        for a in auftraege:
            dienst.auftraege.put(a)
        with unittest.mock.patch.dict(sys.modules, attrappen), \
                unittest.mock.patch.object(dienst, "_sprechen", sprechen), \
                self.assertLogs("sprechdienst", "ERROR"):
            thread = threading.Thread(target=dienst._sprecher, daemon=True)
            thread.start()
            self.assertTrue(auftraege[1].fertig.wait(5))
            dienst.ende.set()
            thread.join(timeout=5)
        self.assertEqual(gesprochen, ["gut"])
        self.assertTrue(auftraege[0].ergebnis["abgebrochen"])
        self.assertIn("kein Ausgabegerät", auftraege[0].ergebnis["fehler"])


@unittest.skipUnless(ABHAENGIG, "numpy und soundfile fehlen")
class Datei(unittest.TestCase):
    """--datei: Der gelieferte Ton landet als MP3 (ohne ffmpeg als WAV) im festen Ordner,
    alte Dateien verschwinden. empfangen ist ersetzt, ein Dienst läuft nicht."""

    def setUp(self):
        import sprechdienst
        self.s = sprechdienst
        self.ordner = Path(tempfile.mkdtemp(prefix="dateien"))
        self.ton = (b"\x00\x10" * sprechdienst.qwen.SAMPLE_RATE)  # eine Sekunde
        self.patches = [
            unittest.mock.patch.object(sprechdienst, "DATEI_ORDNER", self.ordner),
            unittest.mock.patch.object(sprechdienst, "empfangen",
                                       lambda anfrage, aus: aus.write(self.ton) and 0),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.ordner, ignore_errors=True)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg fehlt")
    def test_mp3_im_festen_ordner(self):
        pfad = self.s.datei_schreiben({"cmd": "sprich", "text": "Hallo."})
        self.assertEqual(pfad.parent, self.ordner)
        self.assertEqual(pfad.suffix, ".mp3")
        self.assertGreater(pfad.stat().st_size, 1000)

    def test_ohne_ffmpeg_wav(self):
        import wave
        with unittest.mock.patch.object(self.s.subprocess, "run", side_effect=OSError("fehlt")):
            pfad = self.s.datei_schreiben({"cmd": "sprich", "text": "Hallo."})
        self.assertEqual(pfad.suffix, ".wav")
        with wave.open(str(pfad)) as w:
            self.assertEqual(w.getnframes(), self.s.qwen.SAMPLE_RATE)

    def test_datei_schliesst_liefern_und_warten_aus(self):
        # Die Prüfung greift vor dem Start des Dienstes, ein Modell braucht es nicht
        for option in ("--liefern", "--warten"):
            lauf = subprocess.run([sys.executable, str(REPO / "werkzeuge" / "sprechdienst.py"),
                                   "--datei", option, "Hallo."],
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(lauf.returncode, 1, option)
            self.assertIn("schließen sich aus", lauf.stderr)

    def test_alte_dateien_verschwinden(self):
        alt = self.ordner / "sprechen-alt.mp3"
        alt.write_bytes(b"x")
        os.utime(alt, (0, 0))
        with unittest.mock.patch.object(self.s.subprocess, "run", side_effect=OSError("fehlt")):
            self.s.datei_schreiben({"cmd": "sprich", "text": "Hallo."})
        self.assertFalse(alt.exists())


@unittest.skipUnless(ABHAENGIG, "numpy und soundfile fehlen")
class Liefern(unittest.TestCase):
    """--liefern: Der Ton geht als 16-Bit-PCM an den Aufrufer statt in den Lautsprecher.
    socketpair statt eines gebundenen Sockets, das geht auch in einer Sandbox; Modell und
    Player braucht der Weg nicht."""

    def setUp(self):
        import socket

        import numpy as np
        import sprechdienst
        self.np, self.s = np, sprechdienst
        self.dienst = sprechdienst.Dienst(Path(tempfile.gettempdir()) / "unbenutzt.sock", 60)
        self.dienst_seite, self.aufrufer = socket.socketpair()
        self.rate = sprechdienst.qwen.SAMPLE_RATE

    def tearDown(self):
        self.dienst_seite.close()
        self.aufrufer.close()

    def _auftrag(self, text="Ein Satz, der lang genug für ein eigenes Stück ist."):
        return self.s.Auftrag(text=text, stimme="erzaehler", tempo=1.0, mit_atem=True,
                              runde=self.dienst.runde, ziel=self.dienst_seite)

    def test_ton_kommt_als_pcm_beim_aufrufer_an(self):
        stueck = self.np.full(self.rate // 10, 0.5, self.np.float32)
        auftrag = self._auftrag()
        # Lesen in einem eigenen Thread: Der Puffer eines socketpair fasst nur wenige KB,
        # sendall wartete sonst ewig auf einen Leser
        empfangen: list[bytes] = []

        def lesen():
            while teil := self.aufrufer.recv(65536):
                empfangen.append(teil)

        leser = threading.Thread(target=lesen, daemon=True)
        leser.start()
        with unittest.mock.patch.object(self.s.qwen, "synthesize_chunk", return_value=stueck):
            self.dienst._sprechen(None, auftrag, None, "", None)
        self.dienst_seite.shutdown(2)  # SHUT_RDWR: der Leser sieht dann das Ende
        leser.join(timeout=5)
        daten = b"".join(empfangen)
        pause = int(self.rate * self.s.PAUSE_ABSATZ)
        self.assertEqual(len(daten), (len(stueck) + pause) * 2)
        werte = self.np.frombuffer(daten, "<i2")
        self.assertEqual(int(werte[0]), 16383)
        self.assertEqual(int(werte[-1]), 0)  # Pause am Ende
        self.assertTrue(auftrag.ergebnis["geliefert"])
        self.assertFalse(auftrag.ergebnis["abgebrochen"])

    def test_geschlossener_aufrufer_bricht_den_auftrag_ab(self):
        self.aufrufer.close()
        stueck = self.np.zeros(self.rate // 10, self.np.float32)
        auftrag = self._auftrag()
        with unittest.mock.patch.object(self.s.qwen, "synthesize_chunk", return_value=stueck), \
                self.assertLogs("sprechdienst", "INFO"):
            self.dienst._sprechen(None, auftrag, None, "", None)
        self.assertTrue(auftrag.ergebnis["abgebrochen"])

    def test_stopp_loest_ein_haengendes_senden(self):
        # Liest der Aufrufer nicht mehr (Netz weg, Player haengt), wartete sendall bis
        # LIEFERN_TIMEOUT, und der Sprecher stuende so lange auch fuer alle anderen still
        import socket
        self.dienst_seite.settimeout(30)
        # Kleine Puffer und 10 s Ton (480 KB): Unter Linux fasst ein socketpair sonst rund
        # 200 KB, und 96 KB liefen durch, ohne dass sendall je wartete (CI zu v0.4.0)
        self.dienst_seite.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        self.aufrufer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        stueck = self.np.zeros(self.rate * 10, self.np.float32)
        auftrag = self._auftrag()
        auftrag.quelle = "sitzung-a"
        self.dienst.aktuell = auftrag
        fertig = threading.Event()

        def sprechen():
            self.dienst._sprechen(None, auftrag, None, "", None)
            fertig.set()

        with unittest.mock.patch.object(self.s.qwen, "synthesize_chunk", return_value=stueck), \
                self.assertLogs("sprechdienst", "INFO"):
            threading.Thread(target=sprechen, daemon=True).start()
            self.assertFalse(fertig.wait(0.5))  # haengt wirklich in sendall
            self.dienst._stoppen("sitzung-a")
            self.assertTrue(fertig.wait(5))
        self.assertTrue(auftrag.ergebnis["abgebrochen"])

    def test_pcm_begrenzt_auf_16_bit(self):
        werte = self.np.frombuffer(self.s.pcm(self.np.array([2.0, -2.0, 0.0], self.np.float32)),
                                   "<i2")
        self.assertEqual(werte.tolist(), [32767, -32767, 0])


def _sockets_erlaubt() -> bool:
    """Agenten-Sandboxen (Seatbelt auf macOS) verbieten oft das Binden von Unix-Sockets."""
    import socket
    pfad = Path(tempfile.mkdtemp(prefix="sd")) / "probe.sock"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.bind(str(pfad))
        return True
    except PermissionError:
        return False
    finally:
        pfad.unlink(missing_ok=True)
        pfad.parent.rmdir()


@unittest.skipUnless(ABHAENGIG, "numpy und soundfile fehlen")
@unittest.skipUnless(_sockets_erlaubt(), "Unix-Sockets sind hier gesperrt (Sandbox)")
class Protokoll(unittest.TestCase):
    def setUp(self):
        import sprechdienst
        self.s = sprechdienst
        # Kurzer Pfad: Unix-Sockets vertragen auf macOS nur rund 100 Zeichen
        self.tmp = tempfile.mkdtemp(prefix="sd")
        self.pfad = Path(self.tmp) / "s.sock"
        os.environ["SPRECHDIENST_SOCKET"] = str(self.pfad)
        self.dienst = sprechdienst.Dienst(self.pfad, leerlauf=60)

        def ohne_modell():
            self.dienst.zustand = "bereit"

        self.dienst._sprecher = ohne_modell
        self.thread = threading.Thread(target=self.dienst.laufen, daemon=True)
        self.thread.start()
        frist = time.monotonic() + 5
        while not self.s._erreichbar(self.pfad) and time.monotonic() < frist:
            time.sleep(0.05)

    def tearDown(self):
        self.dienst.ende.set()
        self.thread.join(timeout=5)
        os.environ.pop("SPRECHDIENST_SOCKET", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_liefern_schickt_kopfzeile_und_ton(self):
        import io

        import numpy as np

        def sprecher_attrappe():
            auftrag = self.dienst.auftraege.get(timeout=5)
            self.s._pcm_senden(auftrag.ziel, np.full(1000, 0.25, np.float32))
            auftrag.fertig.set()

        threading.Thread(target=sprecher_attrappe, daemon=True).start()
        ausgabe = io.BytesIO()
        rc = self.s.empfangen({"cmd": "sprich", "text": "Hallo.", "quelle": "a"}, ausgabe)
        self.assertEqual(rc, 0)
        self.assertEqual(len(ausgabe.getvalue()), 2000)  # Kopfzeile nicht im Ton
        self.assertEqual(int(np.frombuffer(ausgabe.getvalue(), "<i2")[0]), 8191)

    def test_liefern_endet_still_wenn_der_player_schliesst(self):
        # Der Normalfall beim Stopp im Fernbetrieb: Der Player endet mitten im Ton. Ohne
        # Vorkehrung endete der Client mit Exit 120 und "Exception ignored" auf stderr
        import numpy as np

        def sprecher_attrappe():
            auftrag = self.dienst.auftraege.get(timeout=10)
            for _ in range(50):
                if not self.s._pcm_senden(auftrag.ziel, np.zeros(12000, np.float32)):
                    break
            auftrag.fertig.set()

        threading.Thread(target=sprecher_attrappe, daemon=True).start()
        skript = REPO / "werkzeuge" / "sprechdienst.py"
        lauf = subprocess.run(
            ["/bin/bash", "-c", f'echo "Ein Satz." | "{sys.executable}" "{skript}" --liefern - '
                                '| head -c 100 > /dev/null; exit "${PIPESTATUS[1]}"'],
            capture_output=True, text=True, timeout=30, env={**os.environ})
        self.assertEqual(lauf.returncode, 0, lauf.stderr)
        self.assertNotIn("Exception ignored", lauf.stderr)

    def test_status(self):
        antwort = self.s.senden({"cmd": "status"})
        self.assertTrue(antwort["ok"])
        self.assertEqual(antwort["zustand"], "bereit")

    def test_auftrag_wird_angenommen_und_stopp_leert(self):
        self.assertTrue(self.s.senden({"cmd": "sprich", "text": "Hallo."})["ok"])
        self.assertEqual(self.dienst.auftraege.qsize(), 1)
        self.assertTrue(self.s.senden({"cmd": "stopp"})["ok"])
        self.assertEqual(self.dienst.auftraege.qsize(), 0)

    def test_fehlerhafte_auftraege(self):
        for anfrage in ({"cmd": "sprich", "text": ""},
                        {"cmd": "sprich", "text": "Hallo.", "stimme": "gibtesnicht"},
                        {"cmd": "sprich", "text": "Hallo.", "tempo": 5},
                        {"cmd": "sprich", "text": "Hallo.", "lauter": 30},
                        {"cmd": "sprich", "text": "Hallo.", "lauter": -3},
                        {"cmd": "sprich", "text": "Hallo.", "lauter": "laut"},
                        {"cmd": "sprich", "text": "Hallo.", "liefern": True, "warten": True},
                        {"cmd": "sprich", "text": "Hallo.", "liefern": "ja"},
                        {"cmd": "unbekannt"},
                        ["kein", "objekt"],
                        # falsche Typen: frueher als "None", "['a']" oder True durchgereicht
                        {"cmd": "sprich", "text": None},
                        {"cmd": "sprich", "text": ["a"]},
                        {"cmd": "sprich", "text": "Hallo.", "tempo": True},
                        {"cmd": "sprich", "text": "Hallo.", "tempo": "1.2"},
                        {"cmd": "sprich", "text": "Hallo.", "tempo": 10**400},
                        {"cmd": "sprich", "text": "Hallo.", "mit_atem": "false"},
                        {"cmd": "sprich", "text": "Hallo.", "warten": 1},
                        {"cmd": "sprich", "text": "Hallo.", "quelle": {"x": 1}},
                        {"cmd": "stopp", "quelle": 7}):
            antwort = self.s.senden(anfrage)
            self.assertFalse(antwort["ok"], anfrage)
            self.assertTrue(antwort.get("fehler"), anfrage)
        self.assertEqual(self.dienst.auftraege.qsize(), 0)

    def test_nur_auftraege_halten_den_dienst_wach(self):
        # Der Hook fuer Claude Code stoppt bei jeder Eingabe; das darf den Leerlauf nicht
        # zuruecksetzen, sonst bliebe das Modell geladen, solange jemand tippt
        vorher = self.dienst.aktiv
        self.assertTrue(self.s.senden({"cmd": "status"})["ok"])
        self.assertTrue(self.s.senden({"cmd": "stopp", "quelle": "x"})["ok"])
        self.assertEqual(self.dienst.aktiv, vorher)
        self.assertTrue(self.s.senden({"cmd": "sprich", "text": "Hallo."})["ok"])
        self.assertGreater(self.dienst.aktiv, vorher)

    def test_zweiter_dienst_endet_sofort(self):
        zweiter = self.s.Dienst(self.pfad, leerlauf=60)
        self.assertEqual(zweiter.laufen(), 0)
        self.assertTrue(self.s._erreichbar(self.pfad))

    def test_beenden_raeumt_den_socket_weg(self):
        # Solange der Dienst läuft, hält er die Sperre
        self.assertFalse(self.s.ende_abwarten(self.pfad, frist=0.3))
        self.assertTrue(self.s.senden({"cmd": "beenden"})["ok"])
        # --beenden kehrt erst zurück, wenn ein neuer Dienst starten kann: Socket weg und
        # Sperre frei, ohne auf den Thread zu warten
        self.assertTrue(self.s.ende_abwarten(self.pfad, frist=5))
        self.assertFalse(self.pfad.exists())
        self.thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
