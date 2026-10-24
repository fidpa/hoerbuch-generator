"""
pruefen.py - Text vor dem Vertonen auf typische Problemstellen pruefen und Dauer schaetzen

Usage:
    .venv/bin/python werkzeuge/pruefen.py datei_hoerfassung.txt [weitere.txt ...]

Gibt je Datei aus:
    - Woerter, geschaetzte Hoerbuchlaenge (bei Tempo 1.20) und Rechenzeit
    - Kuerzel in Grossbuchstaben (die meisten liest die Stimme richtig als Buchstaben;
      Eigennamen wie "LAION" probehalber anhoeren)
    - Zeichen, die keine Satzzeichen sind (Aufzaehlungspunkte, Schraegstriche, Formeln)
    - falsch erkannte Aufzaehlungen ("Nummer 19: Jh.")
    - zerrissene Woerter in Grossbuchstaben ("GENERA-TED")
    - Saetze ueber 450 Zeichen (werden an Komma geteilt; meist lange Zitate, harmlos)

Die Richtwerte stammen aus vier Sachtexten auf einem Mac mini M4 Pro (24.10.2026):
rund 125 Woerter pro Minute bei Tempo 1.0, Rechenzeit etwa 2,6-mal schneller als Echtzeit.
"""

import re
import sys
from collections import Counter
from pathlib import Path

WPM_ROH = 125
TEMPO = 1.20
ECHTZEIT_FAKTOR = 2.6
KONTEXT = 35


def stellen(text: str, muster: str, n: int = 8) -> list[str]:
    out = []
    for m in re.finditer(muster, text):
        a, b = max(0, m.start() - KONTEXT), min(len(text), m.end() + KONTEXT)
        out.append("…" + text[a:b].replace("\n", " ") + "…")
        if len(out) >= n:
            break
    return out


def pruefe(pfad: Path) -> None:
    text = pfad.read_text(encoding="utf-8")
    woerter = len(text.split())
    audio_min = woerter / (WPM_ROH * TEMPO)
    rechen_min = woerter / WPM_ROH / ECHTZEIT_FAKTOR
    print(f"\n=== {pfad.name}: {woerter} Wörter")
    print(f"Hörbuch etwa {audio_min:.0f} min bei Tempo {str(TEMPO).replace('.', ',')}, "
          f"Rechenzeit etwa {rechen_min:.0f} min (M4 Pro; ältere Chips langsamer)")

    kuerzel = Counter(re.findall(r"(?<![\wÄÖÜäöü-])[A-ZÄÖÜ]{2,}[a-z]?(?![\wÄÖÜäöü])", text))
    if kuerzel:
        print("Kürzel (Anzahl):", ", ".join(f"{k} {n}" for k, n in kuerzel.most_common(30)))

    for titel, muster in [
        ("Zeichen, die keine Satzzeichen sind", r"[•◦▪➢►✓/+=<>|_#*]"),
        ("Falsch erkannte Aufzählung", r"\bNummer \d+: \S+"),
        ("Zerrissene Wörter in Großbuchstaben", r"\b[A-ZÄÖÜ]{2,}-[A-ZÄÖÜ]{2,}\b"),
    ]:
        treffer = stellen(text, muster)
        if treffer:
            print(f"{titel}:")
            for t in treffer:
                print("   ", t)

    lang = [s for s in re.split(r"(?<=[.!?:])\s+", text) if len(s) > 450]
    if lang:
        print(f"Sätze über 450 Zeichen: {len(lang)} (werden an Semikolon oder Komma geteilt)")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    for arg in sys.argv[1:]:
        pruefe(Path(arg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
