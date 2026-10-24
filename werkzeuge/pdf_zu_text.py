#!/usr/bin/env python3
"""
pdf_zu_text.py - PDF zu Text Konvertierung

Extrahiert Text aus PDF-Dateien mit PyMuPDF (primär), pypdf (Fallback)
und Tesseract OCR (automatisch fuer gescannte PDFs).

Usage:
    pdf_zu_text.py input.pdf                  # Ganzes PDF -> STDOUT
    pdf_zu_text.py input.pdf -o output.txt    # Ganzes PDF -> Datei
    pdf_zu_text.py *.pdf                       # Batch: je <name>.txt neben Quelle
    pdf_zu_text.py *.pdf -o txt/               # Batch: nach Verzeichnis txt/
    pdf_zu_text.py input.pdf --pages 1-5      # Seiten 1-5
    pdf_zu_text.py input.pdf --pages 3        # Nur Seite 3
    pdf_zu_text.py input.pdf --pages 5-       # Ab Seite 5 bis Ende
    pdf_zu_text.py input.pdf --lang deu       # OCR auf Deutsch
    pdf_zu_text.py input.pdf --no-ocr         # OCR-Fallback deaktivieren
    pdf_zu_text.py input.pdf --clean          # Layout bereinigen (Fliesstext)
    pdf_zu_text.py input.pdf --clean --page-markers  # dazu [Seite N] je Seite

Version: 1.3.0
Date: 2026-10-07

Changelog:
    v1.3.0 (2026-10-07): Bereinigungsmodus --clean, Seitenmarker
        - --clean rekonstruiert Fliesstext aus den Zeilen-Koordinaten:
          Kopf-/Fusszeilen (an Seitenzahlen verankert) entfernt, Zeilen zu
          Absaetzen verbunden, Silbentrennung aufgeloest (Bindestriche und
          URL-Striche ueber den Wortschatz des Dokuments entschieden),
          hochgestellte Fussnotenziffern als [n], Fussnoten als "[n] Text",
          Aufzaehlungszeichen und Kapitelnummern mit ihrer Zeile vereint,
          Tabellen als Markdown, Randnotizen als "[Randnotiz: ...]" (in schmalen
          Kaesten ohne Trennstrich umbrochene Woerter werden ueber Worthaeufigkeit
          und Wortschatz wieder zusammengesetzt)
        - --page-markers stellt jeder Seite "[Seite N]" voran (mit --clean
          die gedruckte Seitenzahl, sonst PDF-Label bzw. "PDF-Seite N")
        - Tesseract laeuft nicht mehr auf echten Leerseiten
        - pypdf-Strukturwarnungen ("parsing for Object Streams") unterdrueckt
    v1.2.0 (2026-07-14): Batch-Modus, seitenweise Extraktion, hoehere OCR-DPI
        - Mehrere Dateien pro Aufruf (nargs); -o wird zum Output-Verzeichnis,
          ohne -o entsteht <name>.txt neben jeder Quelle
        - Seitenweise Fallback-Chain: gescannte Seiten in sonst digitalen PDFs
          werden gezielt per OCR ergaenzt statt still verworfen (Hybrid-Fix)
        - OCR rendert mit ~300 DPI (vorher ~144 DPI) fuer bessere Erkennung
        - which(1)-Subprozess durch shutil.which ersetzt
    v1.1.0 (2026-05-25): Tesseract OCR als automatischer Fallback
        - Auto-Detection gescannter PDFs (< 50 Zeichen/Seite Durchschnitt)
        - Tesseract OCR als Stufe 3 in der Fallback-Chain
        - --lang fuer Tesseract-Sprache (default: eng)
        - --no-ocr zum Deaktivieren des OCR-Fallbacks
    v1.0.1 (2025-12-02): Umzug auf macOS
        - Shebang fuer das venv unter macOS angepasst
    v1.0.0 (2025-11-28): Initial version
        - PyMuPDF als primaerer Extractor
        - pypdf als Fallback
        - Page-Range Support (--pages)
"""

import argparse
import collections
import contextlib
import io
import itertools
import logging
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

OCR_CHARS_PER_PAGE_THRESHOLD = 50

# OCR-Render-Aufloesung: PDF-Basis ist 72 DPI, Faktor 300/72 ergibt ~300 DPI
# (Tesseract-Empfehlung fuer zuverlaessige Erkennung; 2x/144 DPI war zu niedrig).
OCR_ZOOM = 300 / 72


def parse_page_range(page_spec: str, total_pages: int) -> list[int]:
    """
    Parse page range specification.

    Formats:
        "3"     -> [2]           (Seite 3, 0-indexed = 2)
        "1-5"   -> [0,1,2,3,4]   (Seiten 1-5)
        "5-"    -> [4,5,6,...]   (Ab Seite 5 bis Ende)

    Returns list of 0-indexed page numbers. Empty list on invalid input.
    """
    try:
        page_spec = page_spec.strip()

        if '-' in page_spec:
            parts = page_spec.split('-', 1)
            start = int(parts[0]) - 1 if parts[0] else 0
            end = int(parts[1]) if parts[1] else total_pages

            start = max(0, start)
            end = min(end, total_pages)

            if start >= end:
                return []
            return list(range(start, end))
        page_num = int(page_spec) - 1
        if 0 <= page_num < total_pages:
            return [page_num]
        return []
    except ValueError:
        return []


def _pages_pymupdf(pdf_path: Path, page_indices: list[int]) -> list[str] | None:
    """
    Per-Seite Text via PyMuPDF (fitz).

    Returns eine Liste, ausgerichtet auf page_indices (leerer String fuer
    Seiten ohne Text-Layer), oder None wenn PyMuPDF nicht verfuegbar/fehlerhaft.
    """
    try:
        import fitz
    except ImportError:
        return None

    try:
        pdf = fitz.open(str(pdf_path))
        total_pages = len(pdf)
        out = [pdf[i].get_text() if 0 <= i < total_pages else "" for i in page_indices]
        pdf.close()
        return out
    except Exception as e:
        print(f"PyMuPDF error: {e}", file=sys.stderr)
        return None


def _pages_pypdf(pdf_path: Path, page_indices: list[int]) -> list[str] | None:
    """Per-Seite Text via pypdf (Fallback fuer Seiten, die PyMuPDF nicht lieferte)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None

    # pypdf meldet harmlose Strukturhinweise ("parsing for Object Streams") als Warnung
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        reader = PdfReader(str(pdf_path))
        total_pages = len(reader.pages)
        out = []
        for i in page_indices:
            text = reader.pages[i].extract_text() if 0 <= i < total_pages else ""
            out.append(text or "")
        return out
    except Exception as e:
        print(f"pypdf error: {e}", file=sys.stderr)
        return None


def _pages_tesseract(
    pdf_path: Path,
    page_indices: list[int],
    lang: str = "eng",
    quiet: bool = False,
) -> list[str] | None:
    """
    Per-Seite OCR via Tesseract — fuer gescannte Seiten ohne Text-Layer.

    Rendert jede angeforderte Seite via PyMuPDF als PNG (OCR_ZOOM ~= 300 DPI)
    und verarbeitet sie mit Tesseract. Returns eine auf page_indices
    ausgerichtete Liste, oder None wenn OCR nicht verfuegbar ist.
    """
    try:
        import fitz
    except ImportError:
        print("Tesseract OCR: PyMuPDF nicht verfuegbar (fuer Seiten-Rendering benoetigt).",
              file=sys.stderr)
        return None

    if shutil.which("tesseract") is None:
        print("Tesseract OCR: tesseract nicht gefunden. Installation: brew install tesseract",
              file=sys.stderr)
        return None

    try:
        pdf = fitz.open(str(pdf_path))
        total_pages = len(pdf)

        # Echte Leerseiten (ohne Bild-/Vektorinhalt) brauchen kein OCR
        page_indices = [i if 0 <= i < total_pages and _page_needs_ocr(pdf[i]) else -1
                        for i in page_indices]
        if all(i < 0 for i in page_indices):
            pdf.close()
            return [""] * len(page_indices)

        if not quiet:
            print(f"Gescannte Seiten erkannt — Tesseract OCR (Sprache: {lang})...",
                  file=sys.stderr)

        out = []
        mat = fitz.Matrix(OCR_ZOOM, OCR_ZOOM)

        with tempfile.TemporaryDirectory() as tmpdir:
            for n, page_num in enumerate(page_indices, 1):
                if not (0 <= page_num < total_pages):
                    out.append("")
                    continue

                if not quiet:
                    print(f"  OCR Seite {page_num + 1} ({n}/{len(page_indices)})...",
                          end="\r", file=sys.stderr)

                pix = pdf[page_num].get_pixmap(matrix=mat)
                img_path = os.path.join(tmpdir, f"page_{page_num:04d}.png")
                txt_base = os.path.join(tmpdir, f"page_{page_num:04d}")
                pix.save(img_path)

                subprocess.run(
                    ["tesseract", img_path, txt_base, "-l", lang, "--psm", "1"],
                    capture_output=True,
                )

                txt_file = txt_base + ".txt"
                text = ""
                if os.path.exists(txt_file):
                    text = Path(txt_file).read_text(encoding="utf-8", errors="replace").strip()
                out.append(text)

        pdf.close()

        if not quiet and page_indices:
            done = sum(1 for t in out if t.strip())
            print(f"  OCR abgeschlossen ({done}/{len(page_indices)} Seiten mit Text).  ",
                  file=sys.stderr)

        return out

    except Exception as e:
        print(f"Tesseract OCR error: {e}", file=sys.stderr)
        return None


def _page_is_thin(text: str) -> bool:
    """
    True, wenn eine einzelne Seite zu wenig Text hat, um als Text-Layer zu gelten
    (Kandidat fuer Fallback/OCR). Ersetzt die alte dokumentweite Mittelung, die
    gescannte Seiten in sonst digitalen PDFs verschluckte.
    """
    return len(text.strip()) < OCR_CHARS_PER_PAGE_THRESHOLD


def _page_needs_ocr(page: Any) -> bool:
    """
    True, wenn eine duenne Seite ueberhaupt Bildinhalt hat. Echte Leerseiten
    (z.B. Vakatseiten) bekommen so keinen sinnlosen Tesseract-Lauf.
    """
    return bool(page.get_images(full=False)) or len(page.get_drawings()) > 50


# --- Bereinigungsmodus (--clean) ---------------------------------------------
#
# Layout-basierte Rekonstruktion aus den Zeilen-Koordinaten von PyMuPDF:
# Kopf-/Fusszeilen raus, Zeilen zu Absaetzen, Silbentrennung aufloesen,
# Fussnotenziffern als [n], Tabellen als Markdown. Ziel ist Fliesstext, der
# sich durchsuchen und von Sprachmodellen verarbeiten laesst.

# Seitenzahl in Kopf-/Fusszeile: "12", "IV", "Seite 3", "3 / 100", "3 von 100"
_PAGE_NUMBER_RE = re.compile(
    r"^(?:Seite\s+|Page\s+)?(\d{1,4}|[ivxlcdm]{1,7})(?:\s*(?:/|von|of)\s*\d{1,4})?$",
    re.IGNORECASE,
)
_SUPERSCRIPT_REF_RE = re.compile(r"^\d{1,4}(?:\s*[,–-]\s*\d{1,4})*$")
_NUMBERING_RE = re.compile(r"^(?:\d{1,3}(?:\.\d{1,3})*\.?|[a-zA-Z]\)|\(?[ivxIVX]{1,5}[.)])$")
_DOT_LEADER_RE = re.compile(r"(?:\s*\.){4,}\s*")
_FOOTNOTE_RULE_RE = re.compile(r"^_{5,}$")
_TOC_END_RE = re.compile(r" \.\.\. \S{1,8}$")  # "Kapitel ... 12" / "... IV"
_FOOTNOTE_START_RE = re.compile(r"^(\d{1,4})\s+(?=\S)")
_URL_TAIL_RE = re.compile(r"(?:https?://|www\.)\S*$")

# Aufzaehlungszeichen, die als eigenes Text-Fragment vor dem Eintrag stehen.
# Word setzt Unterpunkte oft als "o" (Courier New), Symbolfonts landen in der
# Private Use Area.
_BULLETS = {"•": "•", "·": "•", "▪": "▪", "■": "▪", "◦": "◦", "o": "◦",
            "➢": "➢", "►": "►", "✓": "✓", "-": "-", "–": "–"}

# Woerter nach einem Ergaenzungsstrich ("Rechts- und Wirtschaftsgueter"):
# Hier ist der Strich am Zeilenende echt und bleibt samt Leerzeichen stehen.
_COORDINATING = {"und", "oder", "bzw", "bzw.", "sowie", "als", "wie", "bis",
                 "noch", "respektive", "beziehungsweise", "and", "or", "to"}

# Wortschatz des aktuellen Dokuments (von _pages_clean gesetzt): Steht ein
# Wort im Innern einer Zeile mit Bindestrich ("Wenn-dann"), aber nirgends
# zusammengeschrieben, bleibt der Strich auch am Zeilenende erhalten.
_HYPHEN_PAIRS: set[str] = set()   # benachbarte Glieder: "wenn-dann-regeln" -> "wenn-dann", "dann-regeln"
_PLAIN_WORDS: set[str] = set()
_WORD_COUNTS: collections.Counter[str] = collections.Counter()
_JOINED_WORDS: set[str] = set()
_WORD_RE = re.compile(r"\w(?:[\w-]*\w)?")


def _collect_vocabulary(texts: list[str]) -> None:
    """Wortschatz fuer _join_lines aus allen Zeilentexten des Dokuments aufbauen."""
    _HYPHEN_PAIRS.clear()
    _PLAIN_WORDS.clear()
    for text in texts:
        for word in _WORD_RE.findall(text.lower()):
            parts = word.split("-")
            if len(parts) == 1:
                _PLAIN_WORDS.add(word)
            _HYPHEN_PAIRS.update(f"{x}-{y}" for x, y in itertools.pairwise(parts) if x and y)
    # Nur fuer Randnotizen: Worthaeufigkeiten und ueber das Zeilenende getrennte
    # Woerter in zusammengesetzter Form (getrennt von _PLAIN_WORDS, das die
    # Silbentrennung im Fliesstext steuert und sonst "Wenn-dann" verlieren wuerde)
    _WORD_COUNTS.clear()
    _JOINED_WORDS.clear()
    for text in texts:
        _WORD_COUNTS.update(_WORD_RE.findall(text.lower()))
    for prev, nxt in itertools.pairwise(texts):
        left = re.search(r"([^\W\d_]+)-\s*$", prev)
        right = re.match(r"\s*([^\W\d_]+)", nxt)
        if left and right and right.group(1)[0].islower():
            _JOINED_WORDS.add((left.group(1) + right.group(1)).lower())


def _bullet(text: str) -> str | None:
    """Normiertes Aufzaehlungszeichen, wenn text ein alleinstehendes ist."""
    t = text.strip()
    if t in _BULLETS:
        return _BULLETS[t]
    if len(t) == 1 and 0xF000 <= ord(t) <= 0xF0FF:  # Symbol/Wingdings (PUA)
        return "▪" if ord(t) == 0xF0A7 else "•"
    return None


def _join_lines(prev: str, nxt: str, prev_full: bool = True) -> str:
    """
    Zwei Zeilen eines Absatzes verbinden und dabei die Silbentrennung aufloesen.

    "dis-" + "kutiert"      -> "diskutiert"
    "KI-" + "Chatbot"       -> "KI-Chatbot"   (Grossbuchstabe: echter Bindestrich)
    "Rechts-" + "und ..."   -> "Rechts- und"  (Ergaenzungsstrich)
    "Wenn-" + "dann"        -> "Wenn-dann"    (im Dokument so belegt)
    URL ueber Zeilenende    -> ohne Leerzeichen; Silbentrennung ("eu-ropa")
                               faellt weg, belegte Striche ("legal-content")
                               und Striche zwischen Ziffern bleiben
    """
    prev = prev.rstrip()
    nxt = nxt.lstrip()
    if not prev:
        return nxt
    if not nxt:
        return prev
    in_url = _URL_TAIL_RE.search(prev) is not None
    if prev.endswith("-") and len(prev) > 1 and prev[-2].isalnum():
        first_word = nxt.split(" ", 1)[0]
        # Grossbuchstabe: echter Bindestrich ("KI-Chatbot"); in URLs nicht bei
        # Versalwoertern, die Word ebenfalls trennt ("STATE-MENT")
        if not nxt[0].islower() and not (in_url and prev[-2].isupper()):
            return prev + nxt
        if not in_url and first_word.rstrip(",;:") in _COORDINATING:
            return prev + " " + nxt
        if _hyphen_is_real(prev[:-1], first_word, in_url):
            return prev + nxt
        return prev[:-1] + nxt
    if in_url and _url_continues(prev, prev_full):
        return prev + nxt
    return prev + " " + nxt


def _hyphen_is_real(left_text: str, right_text: str, in_url: bool) -> bool:
    """
    Entscheidet, ob ein Strich am Zeilenende (kleingeschriebene Fortsetzung)
    zum Wort gehoert oder eine Silbentrennung ist.

    Fliesstext: echt nur, wenn das Dokument die Bindestrichform kennt und die
    zusammengeschriebene nicht. URLs: Word trennt auch dort nach Silben; echt
    sind Striche in Kennungen ("412d-be4c"), belegte Formen und Striche in
    Pfadsegmenten, die ohnehin Striche als Worttrenner nutzen ("he-said-what").
    """
    if in_url:
        m = _URL_TAIL_RE.search(left_text)
        left_text = re.sub(r"%[0-9a-fA-F]{2}", " ", m.group(0) if m else left_text)
    left = re.split(r"[^a-z0-9äöüß]+", left_text.lower())[-1]
    right = re.split(r"[^a-z0-9äöüß]+", right_text.lower().lstrip())[0]
    if not left or not right:
        return in_url
    pair, plain = f"{left}-{right}", left + right
    if not in_url:
        return pair in _HYPHEN_PAIRS and plain not in _PLAIN_WORDS

    def is_id(seg: str) -> bool:
        return re.fullmatch(r"[0-9a-f]+", seg) is not None and any(c.isdigit() for c in seg)

    if is_id(left) or is_id(right):
        return True
    if plain in _PLAIN_WORDS:
        return False
    if pair in _HYPHEN_PAIRS:
        return True
    path = left_text.split("://", 1)[-1]
    if "/" not in path:
        return False  # Hostname: Silbentrennung ("eu-ropa", "stan-ford")
    right_segment = re.split(r"[/?#\s]", right_text.lstrip(), maxsplit=1)[0]
    return "-" in path.rsplit("/", 1)[-1] or "-" in right_segment


def _url_continues(prev: str, prev_full: bool) -> bool:
    """
    True, wenn prev mitten in einer URL umbricht. URLs koennen nicht frei
    umbrechen, die Zeile ist deshalb oft kurz; ein Strich oder Schraegstrich
    am Ende zeigt die Fortsetzung dann trotzdem an.
    """
    if not _URL_TAIL_RE.search(prev):
        return False
    if prev.endswith(("-", "/", "_", "=", "?", "&", "%")):
        return True
    return prev_full and not prev.endswith((".", ",", ";", ")"))


def _line_text(line: dict[str, Any]) -> tuple[str, bool, float]:
    """
    Text einer PyMuPDF-Zeile; hochgestellte Fussnotenziffern werden zu "[n]".

    Returns (text, beginnt_mit_fussnotenzeichen, vorherrschende_schriftgroesse).
    """
    parts = []
    starts_sup = None
    sizes: collections.Counter[float] = collections.Counter()
    for span in line["spans"]:
        t = span["text"]
        if not t:
            continue
        if not span["flags"] & 1:
            sizes[round(span["size"], 1)] += len(t.strip())
        is_ref = bool(span["flags"] & 1) and _SUPERSCRIPT_REF_RE.match(t.strip())
        if starts_sup is None and t.strip():
            starts_sup = bool(is_ref)
        if is_ref:
            t = t.replace(t.strip(), f"[{t.strip()}]")
        parts.append(t)
    size = sizes.most_common(1)[0][0] if sizes else 0.0
    return "".join(parts), bool(starts_sup), size


def _table_markdown(table: Any) -> str | None:
    """
    Tabelle als Markdown. Word-Tabellen kommen bei find_tables() oft mit
    zersplitterten Spalten und Zeilen an; deshalb werden Zellen ueber ihre
    horizontale Lage zu logischen Spalten gruppiert und Folgezeilen, deren
    erste Spalte von oben verbunden ist (None), in die Vorzeile gezogen.
    """
    data = table.extract()
    rows = []  # je Zeile: Liste (x_mitte, text) und Flag "Folgezeile"
    for r_idx, row in enumerate(table.rows):
        cells = []
        for c_idx, bbox in enumerate(row.cells):
            text = data[r_idx][c_idx] if c_idx < len(data[r_idx]) else None
            if bbox is None or not text or not text.strip():
                continue
            lines = [ln for ln in text.split("\n") if ln.strip()]
            joined = ""
            for ln in lines:
                joined = _join_lines(joined, ln, prev_full=False)
            cells.append(((bbox[0] + bbox[2]) / 2, joined.replace("|", "/")))
        if cells:
            rows.append((cells, bool(row.cells) and row.cells[0] is None))

    if not rows:
        return None

    centers = sorted(x for cells, _ in rows for x, _ in cells)
    columns: list[float] = []
    for x in centers:
        if not columns or x - columns[-1] > 20:
            columns.append(x)
    if len(columns) < 2 and len(rows) < 2:
        return None

    def col_of(x: float) -> int:
        return min(range(len(columns)), key=lambda i: abs(columns[i] - x))

    grid: list[list[str]] = []
    for cells, continuation in rows:
        line = [""] * len(columns)
        for x, text in cells:
            j = col_of(x)
            line[j] = _join_lines(line[j], text, prev_full=False) if line[j] else text
        if continuation and grid:
            grid[-1] = [_join_lines(a, b, prev_full=False) if b else a
                        for a, b in zip(grid[-1], line, strict=True)]
        else:
            grid.append(line)

    out = ["| " + " | ".join(grid[0]) + " |",
           "|" + "|".join("---" for _ in columns) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in grid[1:]]
    return "\n".join(out)


def _detect_running_heads(
    pages_lines: list[list[dict[str, Any]]], heights: list[float]
) -> tuple[float | None, float | None, list[str | None]]:
    """
    Kopf-/Fusszeilenbaender dokumentweit bestimmen.

    Anker sind Seitenzahlen im oberen/unteren Seitenrand: Tragen mindestens
    30 % der Seiten dort eine, wird alles oberhalb (bzw. unterhalb) ihrer
    typischen Lage als Kopf- (bzw. Fuss-)zeile verworfen. So verschwinden auch
    Kolumnentitel, die nur auf einer Seite vorkommen.

    Returns (top_cut, bottom_cut, gedruckte_seitenzahl_je_seite).
    """
    top_y, bottom_y = [], []
    numbers: list[str | None] = []
    for lines, h in zip(pages_lines, heights, strict=True):
        found = None
        for ln in lines:
            m = _PAGE_NUMBER_RE.match(ln["text"].strip())
            if not m:
                continue
            if ln["y1"] < 0.12 * h:
                top_y.append(ln["y1"])
                found = found or m.group(1)
            elif ln["y0"] > 0.88 * h:
                bottom_y.append(ln["y0"])
                found = found or m.group(1)
        numbers.append(found)

    need = max(2, int(0.3 * len(pages_lines)))
    top_cut = statistics.median(top_y) + 3 if len(top_y) >= need else None
    bottom_cut = statistics.median(bottom_y) - 3 if len(bottom_y) >= need else None
    return top_cut, bottom_cut, numbers


def _rows(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Zeilen auf gleicher Hoehe (Aufzaehlungszeichen, Kapitelnummer) zu Reihen."""
    rows: list[dict[str, Any]] = []
    for ln in sorted(lines, key=lambda ln: (ln["y0"] + ln["y1"]) / 2):
        if rows:
            r = rows[-1]
            overlap = min(r["y1"], ln["y1"]) - max(r["y0"], ln["y0"])
            if overlap >= 0.5 * min(r["y1"] - r["y0"], ln["y1"] - ln["y0"]):
                r["parts"].append(ln)
                r["y0"], r["y1"] = min(r["y0"], ln["y0"]), max(r["y1"], ln["y1"])
                continue
        rows.append({"y0": ln["y0"], "y1": ln["y1"], "parts": [ln]})

    for r in rows:
        parts = sorted(r["parts"], key=lambda ln: ln["x0"])
        texts = [p["text"].strip() for p in parts]
        bullet = _bullet(texts[0]) if len(texts) > 1 else None
        if bullet:
            texts[0] = bullet
        text = " ".join(t for t in texts if t)
        if not bullet and re.match(r"o\s+[A-ZÄÖÜ„\"]", text):
            text, bullet = "◦" + text[1:], "◦"  # Word-Unterpunkt im selben Fragment
        r["text"] = re.sub(r"\s+", " ", _DOT_LEADER_RE.sub(" ... ", text)).strip()
        r["x0"] = parts[0]["x0"]
        r["x1"] = max(p["x1"] for p in parts)
        r["sup"] = parts[0]["sup"]
        r["size"] = max(p["size"] for p in parts)
        r["blocks"] = {p["block"] for p in parts}
        r["bullet"] = bullet is not None
    return [r for r in rows if r["text"]]


def _paragraphs(
    rows: list[dict[str, Any]], note_spans: Sequence[tuple[float, float]] = ()
) -> list[tuple[float, str]]:
    """
    Reihen zu Absaetzen verbinden (Abstand, Einzug, kurze Vorzeile,
    Schriftgroesse). Neben Randnotizen umfliesst der Text die Notiz; dort
    zaehlen Einzug und kurze Zeilen nicht als Absatzsignal.
    Returns (y0, text) je Absatz.
    """
    def beside_note(r: dict[str, Any]) -> bool:
        # Der Umfluss reicht etwas ueber den Notizkasten hinaus
        return any(min(r["y1"], y1 + 20) - max(r["y0"], y0 - 4) > 0 for y0, y1 in note_spans)

    if not rows:
        return []
    ends = sorted(r["x1"] for r in rows)
    right = ends[int(0.9 * (len(ends) - 1))]
    left = min(r["x0"] for r in rows)
    slack = max(30.0, 0.12 * (right - left))

    paras: list[str] = []
    tops: list[float] = []
    prev = None
    rule_x0 = None  # linke Kante des Fussnotenstrichs; Folgezeilen sind eingerueckt
    for r in rows:
        text = r["text"]
        if _FOOTNOTE_RULE_RE.match(text):
            rule_x0 = r["x0"]
        fn_start = (rule_x0 is not None and r["x0"] <= rule_x0 + 2
                    and _FOOTNOTE_START_RE.match(text))
        if fn_start:
            text = _FOOTNOTE_START_RE.sub(r"[\1] ", text, count=1)

        new = prev is None
        if prev is not None:
            height = min(prev["y1"] - prev["y0"], r["y1"] - r["y0"])
            # Silbentrennung oder umbrechende URL verbinden auch kurze Zeilen
            # (schmale Kaesten, Literaturverzeichnis)
            prev_full = (
                prev["x1"] >= right - slack
                or (re.search(r"[^\W\d_]-$", prev["text"]) is not None and text[:1].islower())
                or _url_continues(paras[-1], False)
            )
            wrapped = beside_note(prev) or beside_note(r)
            # Gleicher PyMuPDF-Block: Flattersatz-Zeilen enden oft frueh,
            # ohne dass ein Absatz endet
            same_block = bool(prev["blocks"] & r["blocks"])
            new = (
                r["y0"] - prev["y1"] > 0.75 * height     # Absatzabstand
                or abs(r["size"] - prev["size"]) > 0.5   # Ueberschrift/Fliesstext
                or (r["x0"] < prev["x0"] - 3 and not wrapped)  # Ausrueckung
                or (not prev_full and not wrapped and not same_block)  # Vorzeile endet frueh
                or r["bullet"] or r["sup"] or bool(fn_start)
                or _TOC_END_RE.search(prev["text"]) is not None  # Verzeichniseintrag
                or (" ... " in text and not text.startswith("..."))
                or bool(_FOOTNOTE_RULE_RE.match(text))
                or bool(_FOOTNOTE_RULE_RE.match(prev["text"]))
            )
        if new:
            paras.append(text)
            tops.append(r["y0"])
        else:
            paras[-1] = _join_lines(paras[-1], text, prev_full=True)
        prev = r
    return list(zip(tops, paras, strict=True))


def _text_column(pages_lines: list[list[dict[str, Any]]]) -> tuple[float, float]:
    """
    Satzspiegel (linke Kante, rechte Kante) ueber mehrere Seiten: haeufigster
    Zeilenanfang und 95. Perzentil der Zeilenenden. Fuer gerade und ungerade
    Seiten getrennt aufrufen, wenn das Layout spiegelt.
    """
    lines = [ln for page in pages_lines for ln in page]
    if not lines:
        return 0.0, float("inf")
    left = collections.Counter(round(ln["x0"]) for ln in lines).most_common(1)[0][0]
    ends = sorted(ln["x1"] for ln in lines)
    return left, ends[int(0.95 * (len(ends) - 1))]


_NOTE_FUNCTION_WORDS = {"und", "oder", "der", "die", "das", "des", "dem", "den", "für", "im",
                        "in", "mit", "von", "zu", "zur", "zum", "als", "ohne", "nach", "bei",
                        "über", "statt", "ein", "eine", "einer", "auf", "aus", "durch", "gegen"}


def _join_note_lines(prev: str, nxt: str) -> str:
    """
    Zeilen einer Randnotiz verbinden. In den schmalen Kaesten bricht Word Woerter
    auch ohne Trennstrich um ("Maschinenlesbarkei" / "t"); solche Bruchstuecke
    werden ueber den Wortschatz des Dokuments wieder zusammengesetzt.
    """
    if prev and nxt and not prev.endswith("-"):
        left = re.findall(r"[^\W\d_]+$", prev)
        right = re.match(r"[^\W\d_]+", nxt)
        if left and right and right.group(0)[0].islower():
            a, b = left[0].lower(), right.group(0).lower()
            # Ein Bruchstueck kommt im Dokument nur einmal vor (in der Notiz selbst)
            fragment = _WORD_COUNTS[a] <= 1
            if (len(b) <= 2
                    or (a + b in _PLAIN_WORDS | _JOINED_WORDS and fragment)
                    or (fragment and _WORD_COUNTS[b] <= 1 and b not in _NOTE_FUNCTION_WORDS)):
                return prev + nxt
    return _join_lines(prev, nxt, prev_full=False)


def _split_margin_notes(
    lines: list[dict[str, Any]], column: tuple[float, float]
) -> tuple[list[dict[str, Any]], list[tuple[float, float, str]]]:
    """
    Randnotizen (Marginalien, Word-Textfelder neben dem Satzspiegel) aus dem
    Fliesstext loesen. Kriterium: ein eigener, schmaler Textblock, der links
    oder rechts ueber den Satzspiegel des Dokuments hinausragt.

    Returns (Fliesstext-Zeilen, [(y0, y1, "[Randnotiz: ...]")]).
    """
    left, right = column

    blocks: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    for ln in lines:
        blocks[ln["block"]].append(ln)

    notes, note_blocks = [], set()
    for bid, blines in blocks.items():
        bx0 = min(ln["x0"] for ln in blines)
        bx1 = max(ln["x1"] for ln in blines)
        text = " ".join(ln["text"].strip() for ln in sorted(blines, key=lambda ln: ln["y0"]))
        if len(text) < 4 or _bullet(text) or _NUMBERING_RE.match(text):
            continue
        narrow = bx1 - bx0 < 0.4 * (right - left)
        if narrow and (bx0 < left - 10 or bx1 > right + 10):
            joined = ""
            for ln in sorted(blines, key=lambda ln: ln["y0"]):
                joined = _join_note_lines(joined, ln["text"].strip())
            notes.append((min(ln["y0"] for ln in blines), max(ln["y1"] for ln in blines),
                          f"[Randnotiz: {joined}]"))
            note_blocks.add(bid)
    return [ln for ln in lines if ln["block"] not in note_blocks], notes


def _pages_clean(
    pdf_path: Path, page_indices: list[int]
) -> tuple[list[str], dict[int, str | None]] | None:
    """
    Per-Seite bereinigter Text via PyMuPDF-Layoutdaten (siehe Abschnittskopf).

    Returns (auf page_indices ausgerichtete Texte, Seitenbezeichnung je Index)
    oder None ohne PyMuPDF. Die Bezeichnung ist das PDF-Page-Label oder die
    erkannte gedruckte Seitenzahl.
    """
    try:
        import fitz
    except ImportError:
        return None

    flags = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_LIGATURES & ~fitz.TEXT_PRESERVE_IMAGES
    try:
        pdf = fitz.open(str(pdf_path))
        total = len(pdf)
        valid = [i for i in page_indices if 0 <= i < total]

        # Kopfzeilen dokumentweit erkennen, nicht nur im angefragten Seitenbereich
        all_lines: list[list[dict[str, Any]]] = []
        heights: list[float] = []
        for page in pdf:
            lines = []
            for bid, block in enumerate(page.get_text("dict", flags=flags)["blocks"]):
                for line in block.get("lines", []):
                    text, sup, size = _line_text(line)
                    text = text.replace("­", "").replace(" ", " ")
                    if text.strip():
                        x0, y0, x1, y1 = line["bbox"]
                        lines.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1,
                                      "text": text, "sup": sup, "size": size,
                                      "block": bid})
            all_lines.append(lines)
            heights.append(page.rect.height)

        top_cut, bottom_cut, numbers = _detect_running_heads(all_lines, heights)
        body = [[ln for ln in lines
                 if not (top_cut is not None and ln["y1"] <= top_cut)
                 and not (bottom_cut is not None and ln["y0"] >= bottom_cut)]
                for lines in all_lines]
        columns = (_text_column(body[0::2]), _text_column(body[1::2]))
        _collect_vocabulary([ln["text"] for lines in all_lines for ln in lines])

        out_by_page: dict[int, str] = {}
        for i in valid:
            page = pdf[i]
            lines = body[i]

            # Tabellen: Zeilen im Tabellenbereich ersetzen durch Markdown-Block
            tables: list[tuple[Any, str]] = []
            if page.get_drawings():
                with contextlib.redirect_stdout(io.StringIO()):
                    found = page.find_tables().tables
                for t in found:
                    if t.row_count >= 2 and t.col_count >= 2:
                        md = _table_markdown(t)
                        if md:
                            tables.append((fitz.Rect(t.bbox), md))

            def in_table(ln: dict[str, Any], tables: list[tuple[Any, str]] = tables) -> bool:
                cx, cy = (ln["x0"] + ln["x1"]) / 2, (ln["y0"] + ln["y1"]) / 2
                return any(rect.contains(fitz.Point(cx, cy)) for rect, _ in tables)

            flow, notes = _split_margin_notes([ln for ln in lines if not in_table(ln)],
                                              columns[i % 2])
            note_spans = [(y0, y1) for y0, y1, _ in notes]

            # Fliesstext abschnittsweise zwischen den Tabellen setzen
            items: list[tuple[float, str]] = []
            cursor = float("-inf")
            for rect, md in [*sorted(tables, key=lambda t: t[0].y0), (None, None)]:
                y_end = rect.y0 if rect is not None else float("inf")
                chunk = [ln for ln in flow if cursor <= (ln["y0"] + ln["y1"]) / 2 < y_end]
                items += _paragraphs(_rows(chunk), note_spans)
                if rect is not None and md is not None:
                    items.append((rect.y0, md))
                    cursor = rect.y1

            # Randnotiz vor den Absatz, neben dessen Anfang oder Mitte sie steht
            for y, _, note in sorted(notes, reverse=True):
                pos = max((k for k, (top, _) in enumerate(items) if top <= y + 2), default=0)
                items.insert(pos, (y, note))
            out_by_page[i] = "\n\n".join(text for _, text in items)

        labels = {i: (pdf[i].get_label() or numbers[i]) for i in valid}
        pdf.close()
        return [out_by_page.get(i, "") for i in page_indices], labels
    except Exception as e:
        print(f"PyMuPDF (clean) error: {e}", file=sys.stderr)
        return None


def extract_text(
    pdf_path: Path,
    pages: list[int] | None = None,
    ocr: bool = True,
    lang: str = "eng",
    quiet: bool = False,
    clean: bool = False,
    page_markers: bool = False,
) -> str:
    """
    Extrahiert Text aus PDF — seitenweise, damit gescannte Seiten in sonst
    digitalen PDFs (Hybrid-Dokumente) nicht verloren gehen.

    Pro Seite:
      1. PyMuPDF  — schnell, praezise
      2. pypdf    — Fallback, nur fuer Seiten die PyMuPDF nicht lieferte
      3. Tesseract OCR — nur fuer weiterhin (nahezu) leere Seiten

    OCR-Text ersetzt eine Seite nur, wenn er mehr liefert als der Text-Layer —
    so verliert eine sparsam betextete, aber echte Seite nichts an schwaecheres OCR.

    clean=True ersetzt Stufe 1 durch die Layout-Rekonstruktion (_pages_clean),
    page_markers=True stellt jeder Seite eine Zeile "[Seite N]" voran.

    Raises:
        RuntimeError: Wenn keinerlei Text extrahiert werden konnte
    """
    total = get_total_pages(pdf_path)
    page_indices = pages if pages is not None else list(range(total))

    labels: dict[int, str | None] = {}
    per_page = None
    if clean:
        result = _pages_clean(pdf_path, page_indices)
        if result is not None:
            per_page, labels = result
    if per_page is None:
        per_page = _pages_pymupdf(pdf_path, page_indices)
    if per_page is None:
        per_page = [""] * len(page_indices)

    # pypdf-Fallback nur fuer duenne Seiten (uebernimmt nur, wenn es mehr liefert)
    if any(_page_is_thin(t) for t in per_page):
        pypdf_pages = _pages_pypdf(pdf_path, page_indices)
        if pypdf_pages is not None:
            for i, t in enumerate(per_page):
                if _page_is_thin(t) and len(pypdf_pages[i].strip()) > len(t.strip()):
                    per_page[i] = pypdf_pages[i]

    # OCR nur fuer weiterhin duenne Seiten (gescannt / ohne Text-Layer)
    if ocr:
        thin = [i for i, t in enumerate(per_page) if _page_is_thin(t)]
        if thin:
            ocr_pages = _pages_tesseract(
                pdf_path, [page_indices[i] for i in thin], lang=lang, quiet=quiet
            )
            if ocr_pages is not None:
                for slot, ocr_text in zip(thin, ocr_pages, strict=True):
                    if len(ocr_text.strip()) > len(per_page[slot].strip()):
                        per_page[slot] = ocr_text

    if page_markers:
        parts = []
        for idx, t in zip(page_indices, per_page, strict=True):
            label = labels.get(idx) or _page_label(pdf_path, idx)
            marker = f"[Seite {label}]" if label else f"[PDF-Seite {idx + 1}]"
            parts.append(f"{marker}\n\n{t.strip()}" if t.strip() else marker)
        if any(t.strip() for t in per_page):
            return "\n\n".join(parts)
    else:
        parts = [t for t in per_page if t.strip()]
        if parts:
            return "\n\n".join(parts)

    raise RuntimeError(
        "Alle PDF-Extraktoren fehlgeschlagen. "
        "Ist die Datei lesbar? Bei gescannten PDFs: brew install tesseract"
    )


def _page_label(pdf_path: Path, idx: int) -> str | None:
    """PDF-Page-Label einer Seite (z.B. "iv"), falls das Dokument welche definiert."""
    try:
        import fitz
        with fitz.open(str(pdf_path)) as pdf:
            return pdf[idx].get_label() or None
    except Exception:
        return None


def get_total_pages(pdf_path: Path) -> int:
    """Get total number of pages in PDF."""
    try:
        import fitz
        pdf = fitz.open(str(pdf_path))
        count = len(pdf)
        pdf.close()
        return count
    except ImportError:
        pass

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        return len(reader.pages)
    except ImportError:
        pass

    raise RuntimeError("Weder PyMuPDF noch pypdf installiert. Bitte venv aktivieren.")


def _resolve_output(pdf_path: Path, output: Path | None, batch: bool) -> Path | None:
    """
    Zielpfad fuer eine Datei bestimmen.

    Einzeldatei: -o (Datei) oder None (STDOUT).
    Batch: -o wird als Output-Verzeichnis interpretiert; ohne -o entsteht
    <name>.txt neben der Quelle.
    """
    if not batch:
        return output
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
        return output / (pdf_path.stem + ".txt")
    return pdf_path.with_suffix(".txt")


def process_pdf(pdf_path: Path, out_path: Path | None, args: argparse.Namespace) -> int:
    """Konvertiert eine einzelne PDF. Returns 0 bei Erfolg, sonst 1."""
    if not pdf_path.exists():
        print(f"Fehler: Datei nicht gefunden: {pdf_path}", file=sys.stderr)
        return 1

    if pdf_path.suffix.lower() != ".pdf":
        print(f"Warnung: Datei hat keine .pdf Endung: {pdf_path}", file=sys.stderr)

    label = f"[{pdf_path.name}] " if len(args.pdf_paths) > 1 else ""

    try:
        pages = None
        if args.pages:
            total_pages = get_total_pages(pdf_path)
            pages = parse_page_range(args.pages, total_pages)

            if not pages:
                print(f"Fehler: Ungültiger Seitenbereich: {args.pages}", file=sys.stderr)
                return 1

            if not args.quiet:
                print(f"{label}Extrahiere Seiten {min(pages)+1}-{max(pages)+1} "
                      f"von {total_pages}...", file=sys.stderr)
        elif not args.quiet:
            total_pages = get_total_pages(pdf_path)
            print(f"{label}Extrahiere {total_pages} Seiten...", file=sys.stderr)

        text = extract_text(
            pdf_path,
            pages,
            ocr=not args.no_ocr,
            lang=args.lang,
            quiet=args.quiet,
            clean=args.clean,
            page_markers=args.page_markers,
        )

        if out_path is not None:
            out_path.write_text(text, encoding="utf-8")
            if not args.quiet:
                print(f"Text geschrieben nach: {out_path}", file=sys.stderr)
        else:
            print(text)

        return 0

    except Exception as e:
        print(f"Fehler ({pdf_path.name}): {e}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PDF zu Text Konvertierung (mit automatischem OCR-Fallback)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  %(prog)s dokument.pdf                    # Ganzes PDF -> STDOUT
  %(prog)s dokument.pdf -o output.txt      # Ganzes PDF -> Datei
  %(prog)s *.pdf                           # Batch: je <name>.txt neben Quelle
  %(prog)s *.pdf -o txt/                   # Batch: nach Verzeichnis txt/
  %(prog)s dokument.pdf --pages 1-5        # Seiten 1-5
  %(prog)s dokument.pdf --pages 3          # Nur Seite 3
  %(prog)s dokument.pdf --pages 5-         # Ab Seite 5 bis Ende
  %(prog)s scan.pdf --lang deu             # OCR auf Deutsch
  %(prog)s dokument.pdf --no-ocr           # OCR-Fallback deaktivieren
  %(prog)s skript.pdf --clean -o skript.txt  # Fliesstext ohne Kopfzeilen/Trennungen
  %(prog)s skript.pdf --clean --page-markers # dazu [Seite N] vor jeder Seite
        """
    )

    parser.add_argument("pdf_paths", type=Path, nargs="+", metavar="pdf",
                        help="Pfad(e) zur/zu PDF-Datei(en)")
    parser.add_argument("-o", "--output", type=Path,
                        help="Einzeldatei: Output-Datei (default: STDOUT). "
                             "Mehrere Dateien: Output-Verzeichnis (default: neben Quelle).")
    parser.add_argument("--pages", type=str,
                        help='Seitenbereich (z.B. "1-5", "3", "5-")')
    parser.add_argument("--lang", type=str, default="eng",
                        help="Tesseract OCR Sprache (default: eng, z.B. deu, fra)")
    parser.add_argument("--no-ocr", action="store_true",
                        help="Tesseract OCR-Fallback deaktivieren")
    parser.add_argument("--clean", action="store_true",
                        help="Layout bereinigen: Kopf-/Fusszeilen entfernen, Absaetze "
                             "zusammenfuehren, Silbentrennung aufloesen, Fussnotenziffern "
                             "als [n], Tabellen als Markdown")
    parser.add_argument("--page-markers", action="store_true",
                        help='Jeder Seite eine Zeile "[Seite N]" voranstellen '
                             "(mit --clean: gedruckte Seitenzahl)")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Keine Status-Meldungen ausgeben")
    parser.add_argument("--version", action="version", version="%(prog)s 1.3.0")

    args = parser.parse_args()

    batch = len(args.pdf_paths) > 1
    exit_code = 0
    for pdf_path in args.pdf_paths:
        out_path = _resolve_output(pdf_path, args.output, batch)
        if process_pdf(pdf_path, out_path, args) != 0:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
