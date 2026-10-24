"""
beispiel_pdf.py - Test-PDF fuer die Hoerfassung erzeugen

Ein kurzes Skript im Aufbau eines gegliederten Sachtexts: Deckblatt,
Inhaltsverzeichnis, Kopfzeile mit Seitenzahl,
Kapitel, Fussnote, Aufzaehlung, ein Absatz ueber die Seitengrenze, Tabelle und
Literaturverzeichnis. Der Text ist ausgedacht und enthaelt die Faelle, die die
Hoerfassung umschreiben, weglassen oder zusammenfuehren soll.

Das PDF entsteht bei jedem Testlauf neu, damit der Inhalt im Repo lesbar bleibt.
PyMuPDF ist in requirements.txt gepinnt; dieselbe Version setzt den Text gleich.

Usage:
    .venv/bin/python tests/beispiel_pdf.py ziel.pdf
"""

import sys
from pathlib import Path

import fitz

BREITE, HOEHE = fitz.paper_size("a4")
LINKS, RECHTS = 70, BREITE - 70
SATZSPIEGEL = fitz.Rect(LINKS, 90, RECHTS, 700)

CSS = """
* { font-family: sans-serif; font-size: 11pt; line-height: 1.4; }
h1 { font-size: 15pt; font-weight: bold; margin: 0 0 8pt 0; }
h2 { font-size: 13pt; font-weight: bold; margin: 12pt 0 8pt 0; }
p, li { margin: 0 0 12pt 0; }
ul { margin: 0 0 12pt 0; }
table { border-collapse: collapse; margin: 0 0 12pt 0; }
td, th { border: 1px solid black; padding: 3pt; text-align: left; }
.titel { font-size: 22pt; font-weight: bold; margin-bottom: 16pt; }
"""

DECKBLATT = """
<p class="titel">Musterskript Medienarchiv</p>
<p>Arbeitsunterlage für das Vertonungsteam</p>
<p>Stand: 01.10.2026</p>
"""

INHALT = """
<h1>Inhaltsverzeichnis</h1>
<p>1 Einleitung .................................................. 3</p>
<p>2 Vom Text zum Hörbuch ........................................ 3</p>
<p>Literaturverzeichnis ......................................... 4</p>
"""

SEITE_3 = """
<h1>1 Einleitung</h1>
<p>Das Medienarchiv sammelt seit dem 25.05.2018 Vorträge und Bücher aus der
gesamten EU.<sup>1</sup> Viele liegen nur als Text vor, z. B. als Abschrift
eines Vortrags oder als PDF eines vergriffenen Buchs.</p>
<h1>2 Vom Text zum Hörbuch</h1>
<h2>2.1 Auswahl der Texte</h2>
<p>Nach § 2 Abs. 1 der Satzung i. V. m. Nr. 4 der Archivordnung entscheidet die
sog. Redaktion über die Auswahl (vgl. S. 8-15). Die Mitgliederversammlung hat
das am 3. Oktober bestätigt. Stichtag ist der 1. Januar 2027.</p>
<ul>
<li>Kolleg*innen bekommen den Text vorab, und</li>
<li>die Redaktion hört jede Aufnahme gegen.</li>
</ul>
<p>Die Hinweise aus Teil III des Leitfadens gelten für alle Texte, die das
Archiv als Hörbuch</p>
"""

SEITE_4 = """
<p>veröffentlichen oder an Partner weitergeben will.</p>
<table>
<tr><th>Begriff</th><th>Erläuterung</th></tr>
<tr><td>Hörfassung</td><td>Text, der für das Vorlesen aufbereitet ist</td></tr>
<tr><td>Stück</td><td>Abschnitt, den die KI-Stimme in einem Zug liest</td></tr>
</table>
<p>Der Grundsatz der Verständlichkeit gilt umfassend („a script is written for
the ear, not for the eye“). Für Sprecher/Hörer gelten zusätzlich die Regeln
aus Kap. 3 ff.; die Sammlung LIBRIVOX zeigt, wie weit das reicht.</p>
<h1>Literaturverzeichnis</h1>
<p>Mustermann, Vorlesen und Vertonen, 3. Aufl. 2025.</p>
"""


def _kopfzeile(seite: fitz.Page, nummer: int) -> None:
    seite.insert_text((LINKS, 50), "Musterskript Medienarchiv", fontsize=9)
    seite.insert_text((RECHTS - 10, 50), str(nummer), fontsize=9)


def _fussnote(seite: fitz.Page, text: str) -> None:
    seite.insert_text((LINKS, 740), "_" * 20, fontsize=9)
    seite.insert_text((LINKS, 756), text, fontsize=9)


def erzeuge(ziel: Path) -> None:
    pdf = fitz.open()
    for nummer, html in enumerate([DECKBLATT, INHALT, SEITE_3, SEITE_4], start=1):
        seite = pdf.new_page(width=BREITE, height=HOEHE)
        if nummer > 1:
            _kopfzeile(seite, nummer)
        seite.insert_htmlbox(SATZSPIEGEL, html, css=CSS)
        if nummer == 3:
            _fussnote(seite, "1 Siehe www.example.org/archiv und Kap. 1.")
    pdf.save(ziel, garbage=4, deflate=True)
    pdf.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    erzeuge(Path(sys.argv[1]))
