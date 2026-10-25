# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei
dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

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

[0.1.1]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.1.1
[0.1.0]: https://github.com/fidpa/hoerbuch-generator/releases/tag/v0.1.0
