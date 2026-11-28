# Stimmwerk

[![Release](https://img.shields.io/github/v/release/fidpa/stimmwerk?style=flat-square)](https://github.com/fidpa/stimmwerk/releases)
[![Lint](https://github.com/fidpa/stimmwerk/actions/workflows/lint.yml/badge.svg)](https://github.com/fidpa/stimmwerk/actions/workflows/lint.yml)
![Lizenz: AGPL-3.0](https://img.shields.io/badge/Lizenz-AGPL--3.0-blue.svg?style=flat-square)
![Plattform](https://img.shields.io/badge/Plattform-Apple%20Silicon%20%7C%20macOS-black?style=flat-square&logo=apple)
![Python](https://img.shields.io/badge/Python-3.10%20bis%203.12-blue?style=flat-square&logo=python&logoColor=white)
![Status](https://img.shields.io/badge/Status-Alpha-orange?style=flat-square)

Stimmwerk spricht deutsche Texte mit natürlichen Stimmen, lokal auf dem Mac mit Apple Silicon und über Qwen3-TTS. Daraus entstehen Hörbücher als MP3 aus Büchern, Artikeln, Abschriften von Vorträgen, Skripten und eigenen Notizen, und im Gesprächsmodus gesprochene Antworten von Claude Code. Kein Text verlässt den Rechner, es gibt kein Konto und keine Kosten.

> **Sprachhinweis:** Diese Dokumentation ist durchgehend deutsch, weil Stimmwerk für deutsche Texte gebaut ist und sich an ein deutschsprachiges Publikum richtet.

> **Früherer Name:** Bis v0.16.0 hieß das Projekt Hörbuch-Generator. Die Ordner für Einstellungen, Zwischenspeicher und Protokolle heißen weiter `hoerbuch-generator`, etwa `~/.config/hoerbuch-generator`. So läuft eine bestehende Einrichtung ohne Umzug weiter.

> **Hinweis an Claude:** Lies diese Datei ganz, bevor du etwas startest, und folge dem Abschnitt [Anleitung für Claude](#anleitung-für-claude) am Ende. Alles, was du über Entscheidungen und Fallstricke wissen musst, steht in dieser Datei.

## Warum es Stimmwerk gibt

Wer einen längeren Text hören statt lesen will, hat zwei schlechte Wege. Die Cloud-Dienste klingen gut, aber der Text geht an einen fremden Server. Schnelle lokale Sprachausgaben wie Piper klangen im Test hölzern und sprachen englische Fachbegriffe deutsch aus. Und ein PDF direkt vorzulesen scheitert an Fußnoten, Seitenzahlen und Abkürzungen, gleich mit welcher Stimme.

Stimmwerk verbindet eine natürliche Stimme, die vollständig auf dem Mac läuft, mit einer Hörfassung für deutsche Texte. Die Hörfassung macht aus „z. B.“ „zum Beispiel“ und aus „am 3. Oktober“ „am dritten Oktober“ und lässt weg, was beim Hören stört.

## Funktionen

- **Natürliche Stimme, lokal:** Qwen3-TTS über MLX auf dem Grafikprozessor des Macs. Englische Fachbegriffe im deutschen Text spricht die Stimme englisch aus.
- **Hörfassung für PDFs:** lässt Inhaltsverzeichnis, Fußnoten, Seitenzahlen, Literaturliste und Internetadressen weg, schreibt Abkürzungen, Datumsangaben und Ordnungszahlen aus (`z. B.`, `vgl. S. 8-15`, `§ 2 Abs. 1`, `25.05.2018`) und liest Tabellen als Sätze. Gendersprache liest sie im generischen Maskulinum: Aus „Kund*innen“ wird „Kunden“, aus „jede*r“ „jeder“. Ausgeschriebene Paarformen wie „Kolleginnen und Kollegen“ bleiben, wie sie dastehen.
- **Vier Stimmen im Repo:** `erzaehler` (Hörbuch-Erzähler, mittlere Tonlage, Standard), `dozent` (engagierter Dozent, deutlich tiefer), `andacht` (ruhiger, besinnlicher Sprecher für Andachten und Predigten) und `marketing` (freundlicher Gesprächston mit Du-Ansprache für kurze Erklär- und Produktvideos, empfohlen mit `-t 1.1`). Alle vier sind künstlich erzeugt und gehören keiner echten Person. Eigene Stimmen entstehen aus einer Aufnahme von 10 bis 20 Sekunden.
- **Leisere Atemzüge:** Die künstliche Stimme atmet hörbar ein. Ein darauf trainiertes Erkennungsmodell findet die Atemzüge und senkt sie um 18 dB ab, ohne etwas herauszuschneiden.
- **Prüfung vorab:** `werkzeuge/pruefen.py` zeigt Stellen, die meist Nacharbeit brauchen, und schätzt Länge und Rechenzeit.
- **Fortsetzen nach Abbruch:** Fertige Stücke bleiben erhalten. Derselbe Aufruf macht nach einem Abbruch beim ersten fehlenden Stück weiter.
- **Sofort sprechen:** `sprechen.sh` spricht kurze Texte direkt aus dem Lautsprecher, Satz für Satz, über einen Dienst, der das Modell geladen hält. Gedacht für die Antworten eines KI-Assistenten, siehe [Sofort sprechen statt vorlesen](#sofort-sprechen-statt-vorlesen). Für Claude Code fertig angebunden: [Gesprächsmodus](integrationen/claude-code/README.md).
- **Einrichtung mit Claude:** Wer Claude Code nutzt, lässt sich durch Einrichtung, Hörprobe und lange Läufe führen. Die Anleitung dafür steht am Ende dieser Datei.

## Bekannte Grenzen

- **Nur Apple Silicon.** Die Sprachausgabe läuft über MLX. Getestet sind ein Mac mini M4 Pro und ein MacBook Pro M1 mit 16 GB. Macs mit M2 und M3 sollten laufen, sind aber nicht getestet. Intel-Macs, Linux und Windows gehen nicht.
- **Nur Deutsch geprüft.** Englische Zitate im deutschen Text liest die Stimme verständlich, ganze englische Texte sind nicht getestet.
- **Etwas gleichförmig im Vortrag.** Lebhaftere Beschreibungen der Stimme und andere Einstellungen haben im Test nicht geholfen. Wer einen ausdrucksstarken Vortrag braucht, kommt um einen Cloud-Anbieter kaum herum.
- **Die Hörfassung ist an gegliederten Sachtexten erprobt.** Hat das PDF eine nummerierte Gliederung („1 Einleitung“), beginnt die Hörfassung beim ersten Kapitel und lässt vom Deckblatt nur die Titelzeilen stehen. Bei anderen PDFs, etwa Romanen, die Hörfassung besonders genau ansehen.
- **Gescannte PDFs** ohne Textebene brauchen eine Texterkennung (`brew install tesseract tesseract-lang`). Danach erkennt `pdf_zu_text.py` Seiten ohne Text selbst, auf Deutsch. Mit echten Scans ist das nicht getestet.

### Wofür Stimmwerk nicht gedacht ist

- **Hörbücher zum Verkauf oder Veröffentlichen fremder Texte.** Stimmwerk prüft keine Rechte. Wer ein Hörbuch weitergibt, braucht die Rechte am Text.
- **Fremde Stimmen nachbilden.** Eine Stimme aus der Aufnahme einer anderen Person nur mit deren Erlaubnis anlegen.
- **Belletristik mit verteilten Rollen.** Eine Stimme liest den ganzen Text, ohne Rollen und ohne Kapitelmarken in der MP3.

## Voraussetzungen

- **Ein Mac mit Apple Silicon** (M1 oder neuer)
- **Platz:** rund 1,5 GB für die Programme und 2 GB für die Sprachmodelle
- **Internet nur beim ersten Lauf,** für den Download der Modelle; danach läuft alles offline
- [Homebrew](https://brew.sh) mit `ffmpeg` (`brew install ffmpeg`), für Word- und Markdown-Dateien zusätzlich `pandoc`
- [uv](https://docs.astral.sh/uv/) (`brew install uv`, empfohlen, besorgt Python selbst) oder Python 3.10 bis 3.12 (`brew install python@3.12`)
- Optional: [Claude Code](https://claude.com/claude-code) für die geführte Einrichtung

## Schnellstart

```bash
git clone https://github.com/fidpa/stimmwerk
cd stimmwerk
./einrichten.sh                                  # einmalig, einige Minuten
./vorlesen.sh text.txt                           # -> text.mp3 daneben
```

Ohne Git geht es auch: auf GitHub über „Code“ und „Download ZIP“ herunterladen und entpacken.

### Mit Claude

Den Ordner ablegen, wohin du willst. Dann Claude Code öffnen, egal in welchem Ordner, und schreiben:

**„Im Ordner `<pfad>/stimmwerk` liegt Stimmwerk, eine deutsche Sprachausgabe für Hörbücher. Lies dort die README.md und richte ihn für mich ein.“**

Claude prüft deinen Mac, richtet alles ein, fragt nach deinen Texten und macht zuerst eine Hörprobe. Erst wenn sie dir gefällt, wird der ganze Text vertont.

## Verwendung

```bash
./vorlesen.sh skript.pdf                         # -> skript_hoerfassung.txt und skript.mp3
./vorlesen.sh -v dozent text.txt                 # andere Stimme
./vorlesen.sh -t 1.0 text.txt                    # ohne Beschleunigung (Standard 1.20)
./vorlesen.sh --mit-atem text.txt                # Atemgeräusche nicht absenken
./vorlesen.sh -o hoerbuch.mp3 text.txt           # eigener Name (nur bei einer Datei)
./vorlesen.sh kapitel*.txt                       # mehrere Dateien, je eine MP3
./vorlesen.sh -l                                 # vorhandene Stimmen
.venv/bin/python werkzeuge/pruefen.py text.txt   # Problemstellen und Dauer vorab
```

Der erste Aufruf lädt die Sprachmodelle und braucht deshalb einige Minuten länger. Während der Vertonung meldet `vorlesen.sh` den Fortschritt als `Stück 12/470 (95 s)`.

**Eingaben:** `.txt` direkt; `.md`, `.docx`, `.odt` und `.epub` über pandoc; `.pdf` über die Hörfassung. In Textdateien trennen Leerzeilen die Absätze. Gibt es keine Leerzeilen, ist jede Zeile ein Absatz. Nach jedem Absatz macht die Stimme eine längere Pause.

Enthält eine Textdatei viele Abkürzungen, sie vorher durch die Hörfassung schicken: `.venv/bin/python werkzeuge/hoerfassung.py text.txt`. Die Hörfassung macht aus jedem nummerierten Kapitel („1 Einleitung“) einen Absatz. Hat der Text keine solchen Überschriften, wird er ein einziger Absatz.

**Dauer:** Auf einem Mac mini M4 Pro entstehen etwa 2,6 Sekunden Audio pro Sekunde Rechenzeit. Faustregel bei Tempo 1,2: Hörbuchminuten sind etwa Wörter durch 150, Rechenminuten etwa Wörter durch 325. Ein Text mit 22 000 Wörtern ergab 2,5 Stunden Hörbuch in gut einer Stunde Rechenzeit.

Ein MacBook Pro M1 mit 16 GB ist rund dreimal langsamer. Ein Testtext mit 5 100 Wörtern ergab dort 41 Minuten Hörbuch in 56 Minuten Rechenzeit, also 0,9 Sekunden Audio pro Sekunde Rechenzeit. Der M4 Pro brauchte für denselben Text 19 Minuten. Faustregel für den M1: Rechenminuten sind etwa Wörter durch 90.

Lange Texte am besten über Nacht laufen lassen. `caffeinate -i ./vorlesen.sh langer-text.txt` verhindert, dass der Mac einschläft. Bei einem MacBook das Netzteil anschließen und den Deckel offen lassen.

**Abbruch und Fortsetzen:** Jedes fertige Stück liegt sofort in einem Ordner neben der MP3, etwa `text.stuecke/` für `text.mp3`. Bricht der Lauf ab (Ctrl-C, Absturz, leerer Akku), setzt derselbe Aufruf beim ersten fehlenden Stück fort. Wer dazwischen die Stimme oder `--mit-atem` ändert, bekommt alle Stücke neu, damit sich keine zwei Stimmen mischen. Ist die MP3 fertig, löscht `vorlesen.sh` den Ordner. Bis dahin braucht er rund 170 MB je Stunde Audio.

### Befehlsübersicht

Ausgabe von `./vorlesen.sh -h`:

```
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
```

### Sofort sprechen statt vorlesen

Für kurze Texte, die gleich hörbar sein sollen, etwa die Antworten eines KI-Assistenten, gibt es `sprechen.sh`. Es schreibt keine MP3, sondern spricht direkt aus dem Lautsprecher:

```bash
./sprechen.sh "Ich bin fertig, die Tests laufen."   # sprechen, kehrt sofort zurück
echo "Text" | ./sprechen.sh -v dozent -t 1.1       # Text von stdin, andere Stimme
./sprechen.sh --lauter 8 "Auch bei Musik hörbar."   # 8 dB lauter, mit Limiter
./sprechen.sh --warten "Probe."                    # warten und Zeiten als JSON zeigen
./sprechen.sh --stopp                              # Ausgabe abbrechen, Warteschlange leeren
./sprechen.sh --status                             # Zustand, Ladezeit, letzter Auftrag
./sprechen.sh --beenden
```

Der erste Aufruf startet im Hintergrund einen Dienst (`werkzeuge/sprechdienst.py`), der das Modell geladen hält und über einen Unix-Socket Aufträge annimmt. Er teilt den Text in Sätze und erzeugt den nächsten, während der vorige klingt. Nach 20 Minuten ohne Auftrag beendet er sich und gibt den Speicher frei; `SPRECHDIENST_LEERLAUF` (Sekunden, in der Umgebung oder in `~/.config/hoerbuch-generator/sprechen.conf`) setzt eine andere Zeit. Stimmen, Tempo und Atem-Absenkung sind dieselben wie bei `vorlesen.sh`, ebenso die Prüfung je Stück; ein Stück, das zweimal misslingt, wird übersprungen statt den Auftrag abzubrechen. Das Protokoll des Dienstes steht in `~/Library/Logs/hoerbuch-generator/sprechdienst.log`.

**Lautstärke:** Die Stimmen liegen bei rund −21 LUFS (Lautheit nach EBU R 128), Musik bei Streamingdiensten bei rund −14 LUFS. Neben Musik geht die Stimme deshalb unter. `--lauter DB` hebt sie um 0 bis 15 dB an, ein Limiter hält die Spitzen bei −1,5 dBFS. Mit `--lauter 8` lag `marketing.wav` bei −14 LUFS (gemessen am 26.11.2026). Ohne die Option bleibt der Pegel wie erzeugt. Eine Kurzform gibt es nicht, weil `-l` bei `vorlesen.sh` die Stimmen auflistet.

**Mehrere Aufrufer:** Nutzen mehrere Sitzungen eines Assistenten denselben Dienst, gibt jede mit `--quelle ID` eine Kennung mit, beim Sprechen wie beim Stoppen. `--stopp --quelle ID` bricht dann nur die Aufträge dieser Sitzung ab, die Antworten der anderen laufen weiter. `--stopp` ohne `--quelle` bricht alles ab. Mit `--sonst-aktuell` dazu trifft ein Stopp, der für die Quelle nichts findet, den Auftrag einer anderen, den der Dienst gerade selbst abspielt (nicht einen mit `--liefern`), und der Aufruf gibt aus, was er getroffen hat (`eigene`, `aktuell`, `nichts`). Mit `--ansage "Aus Projekt X."` stellt der Dienst diesen Satz voran, wenn zuletzt eine andere Quelle sprach; so hört man, von wem die Antwort kommt.

**Für ein anderes Gerät rechnen:** Mit `--liefern` spielt der Dienst nichts ab, sondern schreibt den Ton Satz für Satz als 16-Bit-PCM (24 kHz, mono) nach stdout. Über ssh aufgerufen, rechnet der Mac, und ein Player auf dem anderen Gerät spielt ab, auch unter Linux ohne MLX:

```bash
echo "Das ist ein Satz vom Mac." | ssh mac '~/stimmwerk/sprechen.sh --liefern -' | aplay -q -t raw -f S16_LE -r 24000 -c 1
```

**Als Datei:** Mit `--datei` legt der Dienst die Sprache als MP3 unter `~/Library/Caches/hoerbuch-generator/dateien/` ab und gibt den Pfad aus, etwa zum Einbetten in eine Chat-Oberfläche. Dateien älter als sieben Tage löscht der nächste Aufruf.

**Claude Code:** Fertig angebunden ist der Dienst an Claude Code. Mit `/sprechen` hängt Claude jeder Antwort eine kurze, für das Ohr geschriebene Fassung an, und zwei Hooks geben sie an `sprechen.sh`. Zwei weitere sind optional: einer schaltet den Modus in jeder Sitzung von Anfang an ein, einer sagt an, wenn Claude auf eine Freigabe wartet. `claude_sprechen.py pruefen` meldet, ob auf einem Gerät alles dafür da ist. Hook-Skript, Command und Einrichtung: [integrationen/claude-code/](integrationen/claude-code/README.md).

Aus einer macOS-Sandbox heraus (etwa aus dem Shell-Werkzeug eines KI-Agenten) läuft der Dienst nicht: Dort fehlen Metal und Unix-Sockets. Ein Hook oder ein Terminal startet ihn außerhalb.

**Ganze Sätze:** Für ein einzelnes Wort liefert das Modell oft kein Audio. `"Probe."` blieb im Test stumm, und `--warten` meldete `"ausgelassen": 1`; `"Der Gesprächsmodus ist an."` war nach knapp zwei Sekunden zu hören (gemessen am 26.11.2026 auf einem Mac mini M4 Pro, Dienst schon geladen).

## Was beim Vorlesen passiert

1. **Hörfassung (nur PDF):** `werkzeuge/hoerfassung.py` holt den Fließtext aus dem PDF und bereitet ihn auf, wie unter [Funktionen](#funktionen) beschrieben. Die Hörfassung landet als `<name>_hoerfassung.txt` neben dem PDF. **Liegt diese Datei schon dort, nutzt `vorlesen.sh` sie unverändert.** So bleiben Korrekturen von Hand erhalten. Zum Neuerzeugen die Datei löschen.
2. **Vertonung:** Die Stimme liest den Text in Stücken von bis zu 450 Zeichen, geteilt an Satzenden. Längere Stücke erzeugt das Modell unzuverlässig. Findet das Modell für ein Stück kein Ende oder liefert es kein Audio, versucht `qwen.py` das Stück ein zweites Mal und bricht sonst mit Fehler ab.
3. **Atem absenken:** `werkzeuge/atem.py` erkennt die Atemzüge und macht sie um 18 dB leiser. Die Pausen bleiben gleich lang.
4. **Tempo und MP3:** Die Stimme spricht von sich aus rund 125 Wörter pro Minute. `vorlesen.sh` beschleunigt beim Umwandeln in MP3 auf das 1,2-Fache, also rund 150 Wörter pro Minute. Das ist ein übliches Hörbuchtempo. Die Tonhöhe bleibt gleich.

## Hörfassung prüfen

`werkzeuge/pruefen.py` listet die Stellen, an denen meist Nacharbeit nötig ist, und schätzt Länge und Rechenzeit. Die Korrektur passiert von Hand in der Hörfassung:

| Problem | Beispiel | Abhilfe |
|---------|----------|---------|
| Wörter, die das PDF an der Silbentrennung zerrissen hat | „AI GENERA-TED“ | zusammenschreiben |
| Einheiten als Kürzel | „945 TWh“ | ausschreiben, hier „Terawattstunden“ |
| Beschriftungen aus Grafiken, die als Text mitkommen | „Input Layer an Hidden Layern“ | Satz löschen |
| Eigennamen in Großbuchstaben | „LAION“ kam als „Leon“ heraus | probehalber vertonen und anhören, bei Bedarf nach Aussprache schreiben |
| Aufzählung falsch erkannt | „Nummer 19: Jh.“ | richtigstellen |
| Zusammengesetzte Wörter, deren zweiter Teil mit „ie“ beginnt | „Inkassodienstes“ kam als „Inkasso-di-enstes“ heraus | mit Bindestrich schreiben: „Inkasso-Dienstes“ |
| Mehrere Geldbeträge mit Komma in einem Satz | bei „51,50 Euro, die Hälfte davon 25,75 Euro“ verhaspelte sich die Stimme | wie gesprochen schreiben: „51 Euro 50“ |
| Bibelstellen | „Jesaja 55,8–9“ kam als „fünfundfünfzig achtneun“ heraus | ausschreiben: „Jesaja 55, Verse 8 bis 9“, „Johannes 6, Vers 68“ |

Die ersten fünf Beispiele stammen aus den Testtexten, die beiden folgenden aus dem Sprechtext eines Schulungsvideos, die Bibelstellen aus einer Andacht. Bis auf „LAION“, die Bibelstellen und die beiden aus dem Schulungsvideo korrigiert die Hörfassung genau diese Fälle inzwischen selbst, Grafik-Beschriftungen aber nur direkt vor einer Bildunterschrift. Aufzählungszeichen mitten im Text und doppelte Bildunterschriften korrigiert sie ebenfalls. Ähnliche Fälle meldet `pruefen.py` weiterhin. Bildunterschriften („Abbildung 2: …“) werden bewusst mitgelesen.

Kürzel wie „DSGVO“ oder „LLM“ liest die Stimme ohne Hilfe als Buchstaben. Auch Prozentzeichen und Gedankenstriche liest sie richtig.

## Eigene Stimme

Jede Stimme besteht aus zwei Dateien in `stimmen/`: einer Aufnahme `<name>.wav` von 10 bis 20 Sekunden und dem darin gesprochenen Text `<name>.txt`, Wort für Wort. Die Stimme wird aus dieser Aufnahme nachgebildet. Danach `./vorlesen.sh -v <name> text.txt`.

- **Eigene Aufnahme:** ruhiger Raum, gleichmäßig gesprochen, kein Hall, keine Musik, am Ende ein vollständig ausgesprochenes Wort. Mono, 24 kHz, zum Beispiel mit `ffmpeg -i roh.m4a -ac 1 -ar 24000 stimmen/meinestimme.wav`.
- **Fremde Stimmen nur mit Erlaubnis** der Person.
- **Die Aufnahme nicht nachbearbeiten.** Wer die Atemzüge in der Aufnahme durch Stille ersetzt, bekommt hörbar schlechtere Satzenden. Die Atemzüge senkt später ohnehin `atem.py` ab.

Die vier mitgelieferten Stimmen entstanden mit dem Modell `mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit` aus einer Beschreibung; gesprochen wurde der Text in `stimmen/<name>.txt`.

- `erzaehler`: „Ein deutscher Hörbuch-Erzähler, männlich, mittleres Alter, sonore warme Stimme, klare Aussprache ohne Akzent. Ausdrucksstark und erzählend wie bei einem Sachbuch-Podcast: starke Satzmelodie, Fragen klingen wie Fragen, Wichtiges wird hervorgehoben.“
- `dozent`: „Ein deutscher Sprecher, männlich, mittleres Alter, warme Stimme, klare Aussprache ohne Akzent. Lebendiger, engagierter Vortrag wie ein begeisterter Dozent: betont Schlüsselwörter, variiert Tonhöhe und Tempo deutlich, macht kleine Spannungspausen vor wichtigen Punkten.“
- `andacht`: „Ein deutscher Sprecher, männlich, reifes Alter, tiefe, warme und sanfte Stimme, klare Aussprache ohne Akzent. Ruhiger, besinnlicher Vortrag wie ein Seelsorger bei einer Andacht: langsames Tempo, gelassene Satzmelodie, nachdenkliche Pausen, leise Eindringlichkeit, nie gehetzt und nie theatralisch.“ Gesprochen langsamer wird sie dadurch nicht: Bei Tempo 1.0 war eine Probe so lang wie mit `erzaehler` und `dozent`. Der Unterschied liegt im Ton.
- `marketing`: „Ein deutscher Sprecher, männlich, mittleres Alter, warme, natürliche Stimme, klare Aussprache ohne Akzent. Ruhiger Gesprächston, nah am Hörer, wie jemand, der einem Kollegen am Schreibtisch ein Werkzeug zeigt: freundlich, sicher und unaufgeregt.“ Gedacht für kurze Erklär- und Produktvideos mit Du-Ansprache, empfohlenes Tempo `-t 1.1`. Sie wurde aus sechs Läufen mit drei Beschreibungen ausgewählt. In einer Probe von 68 Wörtern lag ihr Tonhöhenumfang etwas über dem von `erzaehler` (11,9 statt 10,5 Halbtöne). An das Geschlecht in der Beschreibung hielt sich das Modell dabei nicht verlässlich: Ein Lauf mit der Beschreibung eines Mannes ergab eine Frauenstimme, beide Läufe mit der Beschreibung einer Frau ergaben Männerstimmen. Jeden Kandidaten also anhören, bevor man ihn ablegt.

Dieselbe Beschreibung ergibt bei jedem Lauf eine etwas andere Stimme; exakt ist nur die abgelegte Datei.

## Aufbau

```
vorlesen.sh                 Text oder PDF -> MP3; das Einzige, was man zum Vertonen aufruft
sprechen.sh                 kurzen Text sofort sprechen, über den Sprechdienst
einrichten.sh               legt die Python-Umgebung .venv an
requirements.txt            getestete Paketversionen
stimmen/<name>.wav, .txt    Stimmen: Aufnahme und gesprochener Text
werkzeuge/qwen.py           Vertonung in Stücken, mit Prüfung und zweitem Versuch je Stück
werkzeuge/sprechdienst.py   Dienst mit geladenem Modell: Satz für Satz in den Lautsprecher
werkzeuge/atem.py           Atemzüge erkennen und absenken; auch einzeln für fertige Dateien
werkzeuge/hoerfassung.py    PDF oder Text -> vorlesbarer Text
werkzeuge/pdf_zu_text.py    Fließtext aus PDF (PyMuPDF, für Scans Tesseract)
werkzeuge/pruefen.py        Problemstellen finden, Länge und Rechenzeit schätzen
integrationen/claude-code/  Gesprächsmodus für Claude Code: Hook-Skript, /sprechen, Anleitung
tests/                      Test-PDF und erwartete Hörfassung; Sprechdienst und Hook-Skript ohne Modell
```

## Wie geprüft wurde

Geprüft wurde mit vier längeren Sachtexten (Skripte mit Fußnoten, Tabellen und vielen Abkürzungen) auf einem Mac mini M4 Pro, mit den Paketversionen aus `requirements.txt`. Die Rücktranskription mit einer Spracherkennung (Whisper) gab den Text vollständig wieder, und Hörproben wurden angehört.

Eine Spracherkennung schreibt aber oft die richtige Schreibweise zurück, auch wenn ein Wort nur ungefähr richtig klingt. Ein falsch betontes Wort findet nur, wer zuhört.

Auf einem MacBook Pro M1 mit macOS 15 liefen außerdem die Einrichtung ohne uv (mit Python 3.12 aus Homebrew), eine Hörprobe und ein Text mit 5 100 Wörtern, der nach der Hälfte abgebrochen und fortgesetzt wurde. Nicht ausprobiert sind Macs mit M2 und M3, echte Scans und erzählende Texte wie Romane.

Die Hörfassung prüft zusätzlich ein automatischer Test bei jeder Änderung. Ein selbst erzeugtes Test-PDF läuft durch `hoerfassung.py` und `pruefen.py`. Beide Ausgaben müssen Zeichen für Zeichen den Dateien in `tests/erwartet/` entsprechen. Die Vertonung prüft der Test nicht, weil sie nur auf Apple Silicon läuft.

Für den Sprechdienst prüfen die Tests alles außer der Sprache selbst: wie der Text in Stücke zerfällt, wie der Dienst über den Socket antwortet und falsche Anfragen abweist, dass ein Stopp nur die eigene Quelle trifft und dass das Hook-Skript für Claude Code nie mit einem Fehlercode endet, der eine Eingabe sperren würde. Sie laufen ohne Modell und bis auf zwei, die ffmpeg oder mlx-audio brauchen, auch in der CI. Gesprochen hat der Dienst bisher nur auf dem Mac mini M4 Pro; auf dem MacBook Pro M1 ist er nicht ausprobiert.

## Alternativen

| Werkzeug | Stärke | Schwäche für deutsche Texte |
|----------|--------|---------------------------------|
| Stimmwerk (dieses Repo) | natürliche Stimme, Hörfassung für Abkürzungen, Fußnoten und Tabellen | nur Apple Silicon, etwas gleichförmig, langsamer als Echtzeit-Stimmen |
| macOS-Sprachausgabe (`say`, Stimme Anna) | eingebaut, sofort da, sehr schnell | keine Aufbereitung des Textes; Klang hier nicht verglichen |
| [Piper](https://github.com/rhasspy/piper) | sehr schnell, läuft auf fast jedem Rechner | im Test hölzern; englische Wörter nur mit Lautschrift brauchbar |
| [ebook2audiobook](https://github.com/DrewThomasson/ebook2audiobook) | ganze E-Books mit Kapiteln, Stimmklon, plattformübergreifend | keine Aufbereitung deutscher Abkürzungen bekannt; hier nicht getestet |
| Cloud-Dienste (etwa ElevenLabs) | ausdrucksstarker Vortrag | Text verlässt den Rechner, kostet pro Zeichen |

## Mitwirken

Fehlerberichte und Vorschläge bitte als Issue. Besonders hilfreich sind Berichte von Macs mit M2 oder M3 (Chip, Rechengeschwindigkeit aus der Ausgabe von `vorlesen.sh`) und Stellen, die die Hörfassung falsch aufbereitet, jeweils mit einem kurzen Textausschnitt.

Wer eine Regel der Hörfassung ändert, lässt danach `.venv/bin/python -m unittest discover -s tests` laufen. Ist die neue Hörfassung gewollt, schreibt derselbe Befehl mit `ERWARTUNG_NEU=1` davor die Erwartung neu. Der Unterschied in `tests/erwartet/` gehört dann in den Pull Request.

## Lizenz

GNU Affero General Public License 3.0 oder neuer, siehe [LICENSE](LICENSE). Grund ist PyMuPDF, das `pdf_zu_text.py` für die PDF-Auswertung nutzt und das unter dieser Lizenz steht.

Die Sprachmodelle sind nicht Teil des Repos. Sie werden beim ersten Lauf von Hugging Face geladen und landen in `~/.cache/huggingface/`. Modelle, Bibliotheken und die Herkunft der mitgelieferten Stimmen stehen in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

## Autor

**Marc Allgeier** ([@fidpa](https://github.com/fidpa))

**Warum ich das gebaut habe:** Ich wollte für Sprachausgabe nichts bezahlen.

## Anleitung für Claude

Dieser Abschnitt richtet sich an Claude. Du kennst die Vorgeschichte dieses Ordners nicht; alles Nötige steht in dieser Datei. Fachliches steht weiter oben, hier steht, wie du vorgehst.

### Wo du arbeitest

- **Pfade immer vom Ordner dieses Repos aus** (im Folgenden `<ordner>`), nicht vom Arbeitsverzeichnis. `<ordner>/vorlesen.sh` findet Umgebung, Stimmen und Werkzeuge selbst.
- **Nichts außerhalb des Ordners ändern** außer den Text- und MP3-Dateien des Nutzers. Hörfassungen und MP3s entstehen neben der Eingabedatei. Existiert dort schon eine MP3 gleichen Namens, vorher fragen; `vorlesen.sh` überschreibt sie ohne Rückfrage. Während eines Laufs liegt neben der MP3 der Ordner `<name>.stuecke/`. Ihn nicht löschen, solange die MP3 fehlt: Er hält den Fortschritt.
- **Die Dateien in `stimmen/` und `werkzeuge/` nicht verändern,** solange der Nutzer nicht ausdrücklich eine Änderung an Stimmwerk will.
- **Ohne Befehlsausführung** (Chat im Browser) geht es nicht, weil die Vertonung auf dem Mac des Nutzers läuft. Dann die Befehle zum Kopieren geben.

### Zuerst prüfen und fragen

**Nicht sofort einrichten oder vertonen.** Erkläre in zwei Sätzen, was Stimmwerk tut, und prüfe dann selbst, statt zu fragen:

- `uname -m` muss `arm64` ergeben. Sonst sag deutlich, dass es auf diesem Rechner nicht läuft, und hör auf.
- Freier Platz (`df -h ~`, mindestens 4 GB), `ffmpeg`, `uv` oder Python 3.10 bis 3.12, bei Bedarf `pandoc`. Fehlt etwas, den `brew install`-Befehl nennen und vor dem Installieren um Erlaubnis fragen.
- Ob `<ordner>/.venv` schon existiert. Dann ist die Einrichtung bereits erledigt.

Dann in einer Runde fragen, jeweils mit Empfehlung:

- Welche Texte vertont werden sollen, in welchem Format und wo sie liegen.
- Wofür das Hörbuch gedacht ist: Lernen, Korrekturhören, Weitergeben. Beim Weitergeben auf die Rechte am Text hinweisen.
- Ob der Erzähler passt (Empfehlung) oder eine der anderen Stimmen aus [Funktionen](#funktionen) oder eine eigene Aufnahme gewünscht ist. Die Entscheidung fällt nach der Hörprobe.

### Ablauf

1. **Einrichten:** `<ordner>/einrichten.sh`. Dauert einige Minuten.
2. **Text vorbereiten:** Bei PDFs zuerst nur die Hörfassung erzeugen: `<ordner>/.venv/bin/python <ordner>/werkzeuge/hoerfassung.py <datei>.pdf` schreibt `<datei>_hoerfassung.txt`. Dann `<ordner>/.venv/bin/python <ordner>/werkzeuge/pruefen.py <datei>_hoerfassung.txt`, die Funde dem Nutzer zeigen und mit seinem Einverständnis in der Hörfassung korrigieren (Tabelle in [Hörfassung prüfen](#hörfassung-prüfen)). Bei Textdateien `pruefen.py` direkt auf die Datei anwenden.
3. **Hörprobe:** einen typischen Absatz von etwa 1 000 Zeichen in eine eigene Datei im Arbeitsordner des Nutzers kopieren und mit dem Erzähler und einer zweiten, zum Zweck passenden Stimme vertonen (etwa `-v erzaehler -o probe_erzaehler.mp3`, `-v dozent -o probe_dozent.mp3`). Der allererste Aufruf lädt etwa 2 GB Modelle; das vorher ankündigen. Die Dateien mit `open <datei>` öffnen und fragen, was dem Nutzer gefällt. Für Tempo-Varianten die Probe einmal mit `-t 1.0` vertonen und daraus ohne Neuvertonung ableiten: `ffmpeg -i probe.mp3 -af atempo=1.1 probe_1.1.mp3`. Der gewählte Wert kommt als `-t` in den Aufruf; ohne `-t` gilt 1.20.
4. **Ganzer Text:** Dauer vorher nennen, aus der Ausgabe von `pruefen.py`. Bei einem PDF mit fertiger Hörfassung `vorlesen.sh <datei>.pdf` aufrufen; es nutzt die korrigierte Hörfassung und schreibt `<datei>.mp3`.
   - **Läufe über zwei Minuten im Hintergrund starten,** sonst bricht die Zeitgrenze deines Werkzeugs sie ab. In Claude Code mit der Option für Hintergrundbefehle: `caffeinate -i <ordner>/vorlesen.sh <datei> > <datei>.log 2>&1`. Fortschritt: `grep Stück <datei>.log | tail -1`.
   - **Soll der Lauf später starten** (etwa nachts), zuerst prüfen, ob der Mac in den Ruhezustand geht (`pmset -g | grep sleep`), und eine Lösung vorschlagen, die nicht von deiner Session abhängt. In der Nacht der Zeitumstellung (letzter Sonntag im Oktober) gibt es 02:00 bis 03:00 Uhr zweimal.
5. **Ergebnis prüfen:** Die Länge der MP3 (`ffprobe -v error -show_entries format=duration -of csv=p=0 <datei>.mp3`, Sekunden) mit der Schätzung von `pruefen.py` vergleichen. Liegt sie deutlich darunter, fehlt vermutlich Text. Steht eine Spracherkennung zur Verfügung, ein paar Minuten zurückschreiben und gegen den Text halten. Einen Ausschnitt zum Anhören schneiden: `ffmpeg -ss 600 -t 60 -i <datei>.mp3 -c copy ausschnitt.mp3`.
6. **Abschluss:** Länge und Ort der MP3 nennen und offene Punkte auflisten, etwa Stellen, die der Nutzer gegenhören sollte.

### Gesprächsmodus einrichten

Will der Nutzer Antworten gesprochen hören statt ein Hörbuch zu erzeugen, gilt die Anleitung in [integrationen/claude-code/README.md](integrationen/claude-code/README.md). Dabei:

- **Die Hooks in `~/.claude/settings.json` liegen außerhalb dieses Ordners.** Den Eintrag erst zeigen und nur mit Zustimmung des Nutzers eintragen; bestehende Hooks bleiben stehen. Pfade absolut, mit dem Ordner dieses Repos.
- **`sprechen.sh` nicht aus deinem eigenen Shell-Werkzeug starten,** wenn es in einer Sandbox läuft: Dort fehlen Metal und Unix-Sockets, und ein so gestarteter Dienst meldet nur Fehler. Den ersten Start übernimmt der Hook oder der Nutzer im Terminal (`<ordner>/sprechen.sh --warten "Probe."`). Lief der Dienst schon aus der Sandbox, beendet ihn `<ordner>/sprechen.sh --beenden` im Terminal.
- **Nach einem Update** `<ordner>/sprechen.sh --beenden`; der nächste Auftrag lädt dann den neuen Stand.

### Meldungen und was zu tun ist

| Meldung | Bedeutung, Abhilfe |
|---------|--------------------|
| `Umgebung fehlt, zuerst ./einrichten.sh ausführen` | `.venv` fehlt; einrichten |
| `ffmpeg fehlt` / `pandoc fehlt` | `brew install ffmpeg` beziehungsweise `pandoc` |
| `Stimme '…' fehlt` | Name aus `vorlesen.sh -l` nehmen |
| `Token-Grenze erreicht …` oder `Kein Audio für Stück …`, danach `Stück … fehlgeschlagen, Abbruch` | Das Modell kam mit einer Stelle nicht zurecht. Die Meldung zeigt den Anfang des Stücks: die Stelle im Text umformulieren (oft Zeichensalat oder eine sehr lange Aufzählung; bei PDFs in `<name>_hoerfassung.txt`), dann denselben Aufruf wiederholen. Er übernimmt die fertigen Stücke davor |
| `Abgebrochen, … Stücken sind fertig` | Der Lauf wurde unterbrochen. Derselbe Aufruf setzt beim ersten fehlenden Stück fort |
| Download-Fehler beim ersten Lauf | Internetverbindung prüfen, erneut starten |
| Hinweise von `transformers` zum Modelltyp | harmlos |

### Was schon ausprobiert wurde

Diese Wege wurden beim Bau getestet und verworfen. Nicht erneut vorschlagen, außer der Nutzer will es ausdrücklich:

- **Stimme je Textstück aus einer Beschreibung erzeugen** (VoiceDesign-Modell direkt): Die Stimme wechselt von Stück zu Stück, und es fielen ganze Sätze weg. Deshalb wird eine feste Aufnahme geklont.
- **Atem über die Lautstärke herausfiltern** (leise Stellen absenken oder abschneiden): klang abgehackt und beschädigte leise Wortenden. Deshalb das trainierte Erkennungsmodell und nur Absenken.
- **Atemzüge in der Referenzaufnahme stummschalten:** weniger Atem, aber schlechtere Satzenden.
- **Satzzeichen wie „…“ am Ende eines Stücks,** damit das letzte Wort sauber ausklingt: machte das Ende eher knapper.
- **Lebhaftere Stimmbeschreibungen, auch auf Englisch, und eine höhere Temperatur** gegen den gleichförmigen Vortrag: kein messbarer Gewinn.
- **Die Sprachausgabe Piper:** viel schneller, aber hölzern und nur mit Lautschrift für englische Wörter brauchbar. Daher stammt der Piper-Zweig in `hoerfassung.py` (`--engine piper`), der hier ungenutzt bleibt.

### Gesprächsregeln

- Mit Empfehlung fragen: „Ich würde den Erzähler nehmen, weil …; passt das?“ statt offener Auswahllisten.
- Was sich messen lässt, messen: Wörter, Dauer, Länge der MP3. Wie die Stimme klingt, beurteilt nur der Nutzer; nach dem Anhören fragen, nicht behaupten.
- Wünscht der Nutzer eine andere Stimme, eine neue anlegen statt die vorhandenen zu ändern (siehe [Eigene Stimme](#eigene-stimme)).
