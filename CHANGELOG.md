# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei
dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

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

[0.3.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.3.0
[0.2.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.2.0
[0.1.2]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.1.2
[0.1.1]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.1.1
[0.1.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.1.0
