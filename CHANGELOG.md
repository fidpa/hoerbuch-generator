# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei
dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [0.12.0] - 2026-11-28: Ein Satz statt Stille, und der Fork behält den Modus

### Hinzugefügt

- **Ersatzsatz, wenn die Sprechmarke fehlt:** Vergaß Claude im Gesprächsmodus die Marke, blieb
  die Antwort stumm, und am Ton war nicht zu erkennen, ob Claude noch arbeitet. Jetzt sagt der
  Stop-Hook „Fertig, die Antwort steht im Text.“ und schreibt eine Zeile in `wiedergabe.log`, die
  zählt, wie oft das vorkommt. Im Modus `aus` und `datei` bleibt es still, ebenso in Sitzungen
  ohne Hinweis auf den Gesprächsmodus und solange Hintergrundaufgaben laufen oder ein Weckruf
  geplant ist: Dann ist die Antwort eine Zwischenmeldung ohne Marke.

### Geändert

- **Ein Fork übernimmt den Modus:** Ein Fork (`--fork-session`, `/branch`, `/fork`) bekam eine
  neue Sitzungskennung und begann nach `/sprechen aus` wieder mit Ton. Jetzt liest der
  SessionStart-Hook bei `source` `fork`, `resume` und `compact` ohne Modus-Datei den letzten
  Aufruf von `/sprechen` aus dem Transkript. Beim ersten Start einer Sitzung legt er die Datei mit
  „an“ an.
- **Docstring des Hook-Skripts gekürzt:** Verhalten und Einrichtung stehen in der README der
  Integration, der Docstring nennt nur noch, was zum Lesen des Codes nötig ist, und die
  Umgebungsvariablen.
- **Test zur fremden PID** wird übersprungen, wo weder `/proc` noch `ps` eine Befehlszeile liefert,
  etwa in einer Sandbox.

## [0.11.0] - 2026-11-28: Zwei Rechner, ein Gerät, eine Antwort nach der anderen

### Hinzugefügt

- **Sperre auf dem Gerät, das spielt:** Landeten Antworten von zwei Rechnern auf demselben
  Gerät, etwa vom Server und vom Mac auf dem Notebook, klangen sie übereinander. Der Mac rechnet
  sie zwar nacheinander, die Puffer von ssh fassen aber bis zu 40 Sekunden Ton. Jetzt nimmt der
  Player dort eine Sperre, sobald der erste Ton ankommt, und gibt sie mit seinem Ende frei; der
  Player des Fernbetriebs auf dem Gerät selbst nimmt dieselbe. Ein Player, der die Sperre länger
  als zehn Minuten hält, gilt als hängend und wird abgelöst. Das braucht `python3` auf dem Gerät;
  ohne spielt es wie bisher, `pruefen` zeigt den Unterschied. Unter macOS ohne Command Line Tools
  zählt der Platzhalter `/usr/bin/python3` nicht, weil er bei jedem Aufruf einen
  Installationsdialog öffnete.
- **`sprechen.sh --stopp --quelle ID --sonst-aktuell`:** Hat die Quelle nichts laufen, bricht
  der Dienst den Auftrag einer anderen Quelle ab, den er gerade selbst abspielt, ohne die
  Warteschlange, und gibt aus, was er getroffen hat (`eigene`, `aktuell`, `nichts`). Einen
  gelieferten Auftrag (`--liefern`) trifft er nicht: Das ist oft die nächste Antwort, die auf dem
  Gerät noch auf die Sperre wartet.

### Geändert

- **Das Stoppwort trifft, was gerade klingt:** „Psst“ stoppte nur die eigene Sitzung. Man tippt
  es aber ins Fenster mit dem Fokus, und oft spricht gerade eine andere. Läuft für die eigene
  Sitzung nichts, stoppt es jetzt, was der Dienst selbst abspielt, und hier wie auf jedem Gerät
  aus `SPRECHEN_GERAETE` den Player, der die Sperre hält. Wartende Antworten bleiben. Steht
  `SPRECHEN_GERAETE` nur vor dem Stop-Hook, liest der Prompt-Hook den Wert aus `settings.json`.
  Dafür fragt das Stoppwort den Mac und die Geräte parallel, zusammen höchstens acht Sekunden;
  eine andere Eingabe baut weiter keine Verbindung auf.

## [0.10.0] - 2026-11-27: Der gewählte Modus übersteht das Kompaktieren

### Geändert

- **Der Modus übersteht das Kompaktieren:** `/sprechen aus` und `/sprechen datei` standen nur im
  Kontext der Sitzung. Nach dem Kompaktieren schaltete der SessionStart-Hook wieder auf Ton, und
  am Handy kam die Datei ohne Hinweis nicht mehr. Jetzt hält der UserPromptSubmit-Hook den Modus
  je Sitzung in einer Datei fest. Der SessionStart-Hook gibt danach nach `/sprechen aus` keinen
  Kontext aus und nach `/sprechen datei` die Regeln für Dateien samt „Knapp“ und „Natürlich“.
  Der Stop-Hook spricht in beiden Modi keine Marke, und der Notification-Hook liest den Modus aus
  der Datei, das Transkript nur noch ohne sie. Nach `/clear` und in einem Fork beginnt eine neue
  Sitzung, dann ist der Ton wieder an.
- **`sprechen.md`, Regel „Nach Gehör schreiben“:** Ein englisches Wort, das die Stimme deutsch
  liest, schreibt Claude in der Sprechmarke nach Gehör, etwa „Täg“ statt „Tag“ und „Mätter-Most“
  statt „Mattermost“.

## [0.9.0] - 2026-11-27: Gesprächsmodus für Dienste ohne Nutzer abschaltbar

### Hinzugefügt

- **`SPRECHEN_AUS=1`:** Startet ein Dienst Claude ohne Nutzer, etwa ein Bot über das Agent SDK
  oder ein zeitgesteuertes `claude -p`, und lädt dabei die Einstellungen des Nutzers, liefen
  bisher auch dessen Hooks: Der SessionStart-Hook schaltete den Gesprächsmodus ein, die Antworten
  des Dienstes endeten mit einer Sprechmarke, der Stop-Hook sprach sie auf dem Gerät des Nutzers,
  und ein „Psst“ in der Eingabe des Dienstes erreichte Claude nicht. Mit `SPRECHEN_AUS=1` in
  der Umgebung des Dienstes tun alle Hooks dieses Skripts nichts, die übrigen Sitzungen sprechen
  weiter. `pruefen` meldet die Variable als Hinweis.

## [0.8.0] - 2026-11-27: Ansage, wenn Claude wartet, und eine Prüfung der Einrichtung

### Hinzugefügt

- **Ansage bei Freigabe und Rückfrage:** Wartet Claude auf eine Freigabe, blieb es bisher still,
  weil kein Stop-Hook auslöst. Ein Notification-Hook mit dem neuen Unterbefehl `notification`
  spricht dann „Claude wartet auf deine Freigabe.“, bei einem Formular eines MCP-Servers „Claude
  wartet auf deine Eingabe.“, bei einer Rückfrage von Claude „Claude hat eine Frage an dich.“,
  über dieselbe Gerätewahl wie die Antworten. Claude Code meldet das, wenn eine Freigabe rund
  sechs Sekunden wartet. Den Hinweis nach 60 Sekunden ohne Eingabe
  (`idle_prompt`) spricht der Hook nicht, er folgte sonst auf jede gesprochene Antwort. Still
  bleibt er auch, wenn die Sitzung `/sprechen aus` oder `/sprechen datei` gesetzt hat; das liest
  er aus dem Transkript der Sitzung.
- **`claude_sprechen.py pruefen`:** meldet für ein Gerät, welche Hooks in
  `~/.claude/settings.json` eingetragen sind, mit welchen Variablen, ob der Mac zum Rechnen per
  ssh antwortet, welche Version sein Klon hat und ob der Dienst läuft, und je Gerät aus
  `SPRECHEN_GERAETE` die Leerlaufzeit und den Player. Er meldet auch, wenn Fernbetrieb oder
  Gerätewahl zwischen den Hooks abweichen, die sie nutzen. Fehlt etwas, endet er mit Exit 1; ein
  schlafendes Gerät ist nur ein Hinweis, solange ein anderes antwortet. Er ist ein Befehl für das
  Terminal, kein Hook.
- **Uhrzeit im Protokoll:** Jede Zeile von `wiedergabe.log` beginnt mit Datum und Uhrzeit, auch
  die Meldungen von ssh und Player, die bisher roh dazwischen standen. Dazu kommen Zeilen für den
  Auftrag, den Beginn der Wiedergabe und ihr Ende mit der Dauer.

## [0.7.1] - 2026-11-27: Ein schlafendes Gerät legt die Sprachausgabe nicht mehr still

### Behoben

- **Gerät verstummte nach einem Abbruch:** Schlief ein Gerät mitten in der Wiedergabe ein, etwa
  ein zugeklapptes MacBook, wartete die ssh-Verbindung zum Player ohne Ende. Der Prozess hielt
  dabei die Sperre der Wiedergabe, und jede spätere Antwort, die auf demselben Gerät rechnete,
  blieb stumm, bis der Prozess von Hand beendet wurde. ssh prüft die Verbindung jetzt alle fünf
  Sekunden und gibt nach drei ausbleibenden Antworten auf. Hängt trotzdem etwas, endet die
  Wiedergabe an einer Obergrenze von zwei Minuten plus einer Viertelsekunde je Zeichen, und der
  Rechenteil bekommt nach dem Ende des Players noch zehn Sekunden. Beides steht in
  `wiedergabe.log`.

## [0.7.0] - 2026-11-27: Antworten sprechen zu Ende, „Psst“ bricht ab

### Geändert

- **Eine neue Eingabe unterbricht nicht mehr:** Im Gesprächsmodus spricht die laufende Antwort
  zu Ende, die nächste reiht sich dahinter ein. Bisher brach jede Eingabe die Ausgabe ihrer
  Sitzung ab, auch der Bericht eines Hintergrund-Agenten. Abbrechen geht jetzt mit einer
  Eingabe, die nur aus einem Stoppwort besteht („Psst“, „Pst“, „Still“, „Ruhe“); Satzzeichen,
  Großschreibung und gedehnte Schreibweisen wie „Pssst!“ aus dem Diktat zählen nicht. Der Hook
  stoppt die Ausgabe der Sitzung, und Claude bekommt die Eingabe nicht. „Stopp“ ist bewusst
  kein Stoppwort, damit es Claude selbst anhalten kann. `SPRECHEN_UNTERBRECHEN=1` stellt das
  alte Verhalten wieder her.

## [0.6.1] - 2026-11-27: Antworten auf macOS-Geräten vom ersten Wort an

### Behoben

- **Anfang fehlte auf macOS-Geräten:** Im Fernbetrieb und bei der Gerätewahl verwarf `ffplay`
  unter macOS die ersten Sekunden, weil der Ton Satz für Satz nach und nach ankommt; zu hören
  waren Antworten erst ab dem dritten oder vierten Wort, auf Lautsprechern wie auf Kopfhörern.
  Unter macOS spielt jetzt `ffmpeg` direkt über AudioToolbox, `ffplay` bleibt der Rückfall.
  Nach einer neuen Eingabe klingt die Antwort dort auch kürzer nach, rund drei statt fünf
  Sekunden (gemessen auf einem Mac mini mit 20 Sekunden Ton, Zuleitung nach zwei Sekunden
  getrennt).

## [0.6.0] - 2026-11-27: Gesprächsmodus von Anfang an, ohne /sprechen

### Hinzugefügt

- **Gesprächsmodus von Anfang an:** `claude_sprechen.py start` für einen SessionStart-Hook gibt
  die Regeln aus `sprechen.md` als Kontext aus. Jede Sitzung beginnt dann im Gesprächsmodus,
  `/sprechen aus` schaltet ihn ab. Der Hook ist optional; ohne ihn bleibt es bei `/sprechen`.
  Er kostet rund 1 000 Tokens je Sitzung und schaltet den Modus auch beim Fortsetzen, nach
  `/clear` und nach dem Kompaktieren wieder ein. Die Regeln stehen weiter nur in `sprechen.md`;
  fehlt dort der Abschnitt, gibt der Hook nichts aus und endet mit Exit 0.

## [0.5.0] - 2026-11-27: Ton auf dem zuletzt benutzten Gerät, Sprache als Datei fürs Handy

### Hinzugefügt

- **Gerätewahl im Gesprächsmodus:** `SPRECHEN_GERAETE` nennt die Geräte, die den Ton abspielen
  dürfen (ssh-Ziele, `hier` für dieses Gerät). Vor jeder Antwort fragt der Hook ihre
  Leerlaufzeit ab (macOS `ioreg`, GNOME über D-Bus) und spielt auf dem zuletzt benutzten. Damit
  hört man Claude Code auch, wenn es auf einem Server oder einem anderen Mac läuft und nur die
  Oberfläche auf dem Notebook ist. Sind alle Geräte länger als `SPRECHEN_LEERLAUF` Sekunden
  (Standard 1800) unbenutzt, bleibt die Antwort stumm.
- **`sprechen.sh --datei` und `/sprechen datei`:** Der Sprechdienst legt die Sprache als MP3 in
  einem festen Ordner ab (ohne ffmpeg als WAV) und gibt den Pfad aus; Dateien älter als sieben
  Tage löscht der nächste Aufruf. Im Gesprächsmodus `/sprechen datei` bettet Claude die Datei in
  jede Antwort ein, für Oberflächen wie T3 Code auf dem Handy, die sie per Tippen abspielen.

### Behoben

- **`sprechen.sh` über ssh:** In einer ssh-Sitzung fehlt `/opt/homebrew/bin` im PATH. Startete
  ein solcher Aufruf den Sprechdienst, etwa im Fernbetrieb, fand der Dienst `ffmpeg` nicht und
  sprach ohne Tempo und ohne Anhebung der Lautstärke. `sprechen.sh` nimmt den Ordner jetzt in
  den PATH auf, wenn er existiert.
- **`ffplay` im Fernbetrieb:** Der Player schrieb trotz `-loglevel error` laufend seine
  Statuszeile nach `wiedergabe.log`. `-nostats` stellt das ab.

## [0.4.0] - 2026-11-27: Gesprächsmodus auch auf Geräten ohne MLX, der Mac rechnet über ssh

### Hinzugefügt

- **`sprechen.sh --liefern`:** Der Dienst spielt nichts ab, sondern schreibt den Ton Satz für
  Satz als 16-Bit-PCM (24 kHz, mono) nach stdout. Über ssh aufgerufen, rechnet ein Mac so für
  ein anderes Gerät, das den Ton selbst abspielt. Warteschlange und Stopp je Quelle gelten
  weiter.
- **Fernbetrieb im Gesprächsmodus:** Mit `SPRECHEN_ENTFERNT=<ssh-ziel>` nutzt das Hook-Skript
  den Sprechdienst eines Macs über ssh und spielt den Ton mit einem lokalen Player ab (paplay,
  pw-play, aplay oder ffplay, sonst `SPRECHEN_PLAYER`). Damit spricht Claude Code auch auf
  Linux-Geräten ohne MLX. Mehrere Sitzungen eines Geräts sprechen nacheinander, eine Eingabe
  beendet nur die Wiedergabe der eigenen Sitzung. Läuft für die Sitzung nichts, baut die
  Eingabe keine ssh-Verbindung auf.

### Gemessen

- **Fernbetrieb am 27.11.2026:** Ein Linux-Notebook spielte über `ssh` und `paplay` einen Satz
  ab, den ein Mac mini M4 Pro mit `--liefern` erzeugt hatte. Auf dem Mac selbst ergab
  `--liefern` für einen Satz mit neun Wörtern 2,94 s Ton. `ffplay` 9.1 lief mit den Optionen
  des Hook-Skripts; `pw-play`, `aplay` und die Hooks auf einem Linux-Gerät sind ungeprüft.

## [0.3.0] - 2026-11-27: Antworten sofort sprechen, mit Gesprächsmodus für Claude Code

### Hinzugefügt

- **`sprechen.sh` und Sprechdienst:** kurze Texte sofort aus dem Lautsprecher statt als MP3. Ein
  Dienst im Hintergrund hält das Modell geladen, nimmt Aufträge über einen Unix-Socket an und
  spricht Satz für Satz, während der nächste entsteht. `--stopp` bricht ab, nach 20 Minuten
  ohne Auftrag endet der Dienst. Gedacht für die Antworten eines KI-Assistenten.
- **`sprechen.sh --lauter DB`:** hebt die Stimme um bis zu 15 dB an, mit Limiter, damit sie neben
  Musik hörbar bleibt. Ohne die Option bleibt der Pegel unverändert.
- **`sprechen.sh --quelle ID`:** Aufträge tragen eine Kennung des Aufrufers, und
  `--stopp --quelle ID` bricht nur dessen Aufträge ab. So stoppt eine Eingabe in einer
  KI-Sitzung nicht die Antwort einer anderen. `--ansage TEXT` wird vorangestellt, wenn zuletzt
  eine andere Quelle sprach.
- **Gesprächsmodus für Claude Code** (`integrationen/claude-code/`): Hook-Skript für Stop und
  UserPromptSubmit, der Command `/sprechen` und eine Anleitung. Claude schreibt im Modus eine
  kurze gesprochene Fassung als HTML-Kommentar ans Ende jeder Antwort, die Hooks geben sie an
  `sprechen.sh`. Stimme, Tempo und Lautstärke über `SPRECHEN_STIMME`, `SPRECHEN_TEMPO`,
  `SPRECHEN_LAUTER`.
- **Tests für Sprechdienst und Hook-Skript:** Satzteilung, Protokoll samt Typprüfung, Stopp je
  Quelle und die Exit-Codes des Hook-Skripts. Die CI installiert dafür zusätzlich numpy und
  soundfile. Tests, die ffmpeg oder mlx-audio brauchen, überspringen sich ohne diese.
- **Anleitung für Claude:** Abschnitt zum Einrichten des Gesprächsmodus.

### Geändert

- **`requirements.txt` pinnt `sounddevice==0.5.6`.** Der Sprechdienst spielt darüber ab; bisher
  kam das Paket ohne feste Version über mlx-audio mit. Eingetragen in
  `THIRD_PARTY_LICENSES.md`, samt dem mitgelieferten PortAudio (MIT).

### Behoben

- **`vorlesen.sh` in einer Sandbox:** Das Temp-Verzeichnis entsteht jetzt unter `TMPDIR`.
  `mktemp -t` legte es auf macOS unter `/var/folders` an, was in einer Sandbox mit eigenem
  Temp-Verzeichnis scheiterte.

### Gemessen

- **Sprechdienst auf einem Mac mini M4 Pro**, Stimme `marketing`, ein Satz je Auftrag: Modell
  laden 4,2 bis 4,6 s je Dienststart, erster Ton 1,85 bis 1,94 s nach dem Auftrag bei schon
  geladenem Modell. Ein einzelnes Wort („Probe.“) ergab zweimal kein Audio, der Dienst ließ das
  Stück aus. Auf anderen Macs nicht gemessen.

## [0.2.0] - 2026-11-17: Zwei weitere Stimmen für Andacht und Marketing

### Hinzugefügt

- **Stimme `andacht`:** ruhiger, besinnlicher Sprecher für Andachten und Predigten, wie
  `erzaehler` und `dozent` mit VoiceDesign aus einer Beschreibung erzeugt. Die Beschreibung steht im
  README unter „Eigene Stimme“.
- **Stimme `marketing`:** freundlicher Gesprächston mit Du-Ansprache für kurze Erklär- und
  Produktvideos, empfohlen mit Tempo 1.1, ebenfalls mit VoiceDesign erzeugt. Beschreibung und
  ein Hinweis, dass sich das Modell nicht verlässlich an das Geschlecht in der Beschreibung
  hält, stehen im README unter „Eigene Stimme“.
- **Tabelle „Hörfassung prüfen“:** Bibelstellen wie „Jesaja 55,8–9“ las die Stimme als
  „fünfundfünfzig achtneun“; ausgeschrieben („Verse 8 bis 9“) stimmt es.

### Geändert

- **Anleitung für Claude:** Die Hörprobe läuft mit dem Erzähler und einer zweiten, zum Zweck
  passenden Stimme statt immer mit dem Dozenten.

## [0.1.2] - 2026-10-25: Zwei weitere Fälle zum Gegenhören

### Geändert

- **Tabelle „Hörfassung prüfen“ im README:** zwei Fälle, die die Hörfassung nicht selbst
  korrigiert und die erst beim Anhören auffielen. Zusammengesetzte Wörter, deren zweiter
  Teil mit „ie“ beginnt, klangen falsch („Inkassodienstes“ wurde „Inkasso-di-enstes“); mit
  Bindestrich spricht die Stimme sie richtig. Bei mehreren Geldbeträgen mit Komma in einem
  Satz verhaspelte sie sich; geschrieben wie gesprochen („51 Euro 50“) lief der Satz sauber.

## [0.1.1] - 2026-10-25: Gendersprache als generisches Maskulinum

### Geändert

- **Gendersprache als generisches Maskulinum:** Die Hörfassung liest „Kund*innen“ als
  „Kunden“, „jede*r“ als „jeder“ und „der*die“ als „der“, auch mit Doppelpunkt,
  Unterstrich, Schrägstrich, Klammer und Binnen-I („LehrerInnen“), und setzt nach dem Artikel die
  Fallendung („mit den Lehrern“, „einen Kollegen“). Bisher entstanden Doppelnennungen,
  und nur für neun fest eingetragene Wörter; andere kamen verstümmelt heraus
  („Lehrer oder innen“). Ausgeschriebene Paarformen wie „Kolleginnen und Kollegen“
  bleiben, wie sie dastehen.

## [0.1.0] - 2026-10-25: Deutsche Texte als Hörbuch, lokal auf dem Mac

### Hinzugefügt

- **Vertonung deutscher Texte und PDFs zu MP3** mit Qwen3-TTS über MLX, in Stücken
  bis 450 Zeichen, mit zweitem Versuch je Stück
- **Hörfassung für PDFs:** Inhaltsverzeichnis, Fußnoten, Seitenzahlen, Literaturliste
  und Internetadressen fallen weg, Abkürzungen, Datumsangaben und Ordnungszahlen werden
  ausgeschrieben, Tabellen als Sätze gelesen
- **Zwei künstlich erzeugte Stimmen** (`erzaehler`, `dozent`) und eigene Stimmen aus
  einer Aufnahme von 10 bis 20 Sekunden
- **Atemabsenkung** um 18 dB mit dem Erkennungsmodell Respiro-en
- **`pruefen.py`** listet typische Problemstellen und schätzt Länge und Rechenzeit
- **Fortsetzen nach Abbruch:** Fertige Stücke liegen in `<name>.stuecke/` neben der MP3;
  derselbe Aufruf übernimmt sie und erzeugt nur die fehlenden
- **Anleitung für Claude** im README für die geführte Einrichtung
- **Test der Hörfassung** mit einem selbst erzeugten Test-PDF und erwarteter Ausgabe von
  `hoerfassung.py` und `pruefen.py`, als eigener Job in der CI

[0.12.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.12.0
[0.11.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.11.0
[0.10.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.10.0
[0.9.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.9.0
[0.8.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.8.0
[0.7.1]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.7.1
[0.7.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.7.0
[0.6.1]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.6.1
[0.6.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.6.0
[0.5.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.5.0
[0.4.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.4.0
[0.3.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.3.0
[0.2.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.2.0
[0.1.2]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.1.2
[0.1.1]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.1.1
[0.1.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.1.0
