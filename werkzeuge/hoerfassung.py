#!/usr/bin/env python3
"""
hoerfassung.py - Text (Buch, Artikel, Skript) fuer vorlesen.sh aufbereiten

Erzeugt aus einem PDF oder aus der Ausgabe von `pdf_zu_text.py --clean --page-markers`
eine Hoerfassung <name>_hoerfassung.txt, die vorlesen.sh sauber vorliest. vorlesen.sh
ruft das bei PDFs selbst auf; einzeln nur, um die Hoerfassung vorher zu pruefen.

Usage:
    .venv/bin/python werkzeuge/hoerfassung.py skript.pdf            # -> skript_hoerfassung.txt
    .venv/bin/python werkzeuge/hoerfassung.py skript.pdf -o hoer.txt
    ./vorlesen.sh skript_hoerfassung.txt                             # danach vertonen

Erprobt an deutschen Sachtexten mit Gliederung. Entstanden fuer zwei
Sprachausgaben: Piper (espeak, braucht Lautschrift) und Qwen3-TTS. Dieser Ordner nutzt
nur Qwen, deshalb ist --engine qwen der Default; der Piper-Zweig bleibt fuer Vergleiche.

Was passiert:
    - Eine Zeile je Abschnitt: Piper synthetisiert jede Zeile einzeln und setzt die
      Satzpause (--sentence-silence) nur zwischen Saetzen INNERHALB einer Zeile;
      Ueberschriften und Absaetze enden deshalb mit Satzzeichen.
    - Weggelassen: Verzeichnisse, Glossar, Literaturverzeichnis, Fussnoten,
      Seitenmarken, URLs. Vom Deckblatt bleiben Titelzeilen.
    - Ausgeschrieben: Abkuerzungen ("z. B.", "vgl.", "sog.", "i. V. m.",
      "§ 2 Abs. 1"), Daten und Ordnungszahlen, Genderstern,
      Schraegstriche, Pfeile. Jeder Abkuerzungspunkt waere sonst eine Satzpause.
    - Buchstabiert: Akronyme, die espeak als Wort liest ("KI" -> "Kii", "EU" -> "Eu").
    - Umschrieben: englische Fachbegriffe, die espeak nach deutschen Regeln liest
      ("Chatbot", "Bias", "Compliance"); weitere Woerter deckte fuer Piper ein eigenes
      Lexikon ab, das hier nicht enthalten ist.
    - Tabellen als Saetze ("Frage: ... Loesung: ..."), Randnotizen als "Stichwort: ...".
    - Aufzaehlungspunkte enden mit Satzpause; ein Bindewort am Ende ("…, und")
      wandert an den Anfang des naechsten Punkts. Nach jedem Satzende steht ein
      Grossbuchstabe, sonst wertet espeak den Punkt nicht als Satzende.
    - Zahlenbereiche mit "bis" ("Randnummer 8 bis 15", "Buchstabe a bis m").
    - Englische Zitatbloecke werden durch einen Hinweis ersetzt (die deutsche
      Stimme liest sie unverstaendlich); die Uebersetzung im Skript bleibt. Ein
      englisches Originalzitat in Klammern hinter der deutschen Fassung entfaellt.
    - Saetze ueber 220 Zeichen werden an Satzzeichen geteilt: Piper wird bei langen
      Saetzen undeutlich (gemessen, siehe _MAX_SENTENCE).
    - Bindestrich vor "gesetz", "geheim", "gericht", "gebiet" im Kompositum: espeak
      liest dort sonst "geh" ("Datenschutz-geh-setz", "Geschäfts-geh-eimnis").
    - Roemische Zahlen nach "Anhang", "Kapitel", "Teil", "Klasse", "München" und im
      Aktenzeichen ("X ZR") als Zahlwort: espeak liest "Anhang I" als Buchstaben und
      "Anhang III" als "roemisch drei". "Art. 6 III" wird "Artikel 6 Absatz drei".
    - Gesetzeskuerzel in gemischter Schreibung ("OWiG", "KSchG", "BVerfG") ausgeschrieben.

Mit --engine qwen entfaellt alles, was nur espeak (Piper) braucht: Lautschrift fuer
englische Begriffe ("Tschättbot", "Koppirait"), Bindestriche vor "gesetz" und Co.,
"K-I " vor Vokal und "Verordnung", das Teilen von Saetzen ueber 220 Zeichen
(qwen.py teilt selbst, ohne Kommas zu Punkten zu machen) und der Hinweis statt
englischer Zitatbloecke: Qwen liest sie verstaendlich vor. Ein englisches Original in
Klammern hinter der deutschen Fassung entfaellt weiter, es wuerde den Inhalt doppeln.
Qwen spricht englische Begriffe richtig aus; in der Ruecktranskription verfehlte es nur
die Lautschrift ("äs-ä-Sörwis" wurde "SR-Service"), Test vom 24.10.2026.

Pruefung des Ergebnisses: MP3 mit einem deutschen Whisper-Modell UND parakeet-mlx
(Chunks 15/5) zuruecktranskribieren und gegen den gesprochenen Text abgleichen; Fehler,
die beide Modelle an derselben Stelle machen, liegen im Audio.

Alle Ersatzschreibungen sind mit `espeak-ng -v de -q -x "Wort"` geprueft, die
wichtigsten zusaetzlich per Synthese und Ruecktranskription (Whisper).

Version: 1.2.1
Date: 2026-10-24

Changelog:
    v1.2.1 (2026-10-24): Ordnungszahl vor dem Monat mit Endung nach dem Wort davor
                         ("Stand: erster Oktober", "der erste Januar"), bisher immer "-en"
    v1.2.0 (2026-10-24): --engine qwen ohne espeak-Lautschrift, Satzteilung und
                         Zitat-Hinweis (englische Zitate werden vorgelesen); fuer beide
                         Engines: Aufzaehlungszeichen mitten im Absatz, "19. Jh.",
                         "TWh", Grafik-Beschriftungen vor Bildunterschriften entfallen,
                         doppelte Bildunterschrift
    v1.1.0 (2026-10-07): Roemische Zahlen, weitere Gesetzeskuerzel, "i.V.m"/"i.S.d"
                         ohne Schlusspunkt, "Art 7" ohne Punkt, GEMA, Charta
    v1.0.0 (2026-10-07): Initial version
"""

import argparse
import re
import subprocess
import sys
import tempfile
from functools import partial
from pathlib import Path
from typing import Any

PDF_TO_TXT = Path(__file__).resolve().parent / "pdf_zu_text.py"

# --- Zahlwoerter -------------------------------------------------------------

_ORD = {1: "erst", 2: "zweit", 3: "dritt", 4: "viert", 5: "fünft", 6: "sechst",
        7: "siebt", 8: "acht", 9: "neunt", 10: "zehnt", 11: "elft", 12: "zwölft",
        13: "dreizehnt", 14: "vierzehnt", 15: "fünfzehnt", 16: "sechzehnt",
        17: "siebzehnt", 18: "achtzehnt", 19: "neunzehnt", 20: "zwanzigst",
        21: "einundzwanzigst", 22: "zweiundzwanzigst", 23: "dreiundzwanzigst",
        24: "vierundzwanzigst", 25: "fünfundzwanzigst", 26: "sechsundzwanzigst",
        27: "siebenundzwanzigst", 28: "achtundzwanzigst", 29: "neunundzwanzigst",
        30: "dreißigst", 31: "einunddreißigst"}
_ADVERB = {1: "Erstens", 2: "Zweitens", 3: "Drittens", 4: "Viertens", 5: "Fünftens",
           6: "Sechstens", 7: "Siebtens", 8: "Achtens", 9: "Neuntens", 10: "Zehntens"}
_MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
           "September", "Oktober", "November", "Dezember"]
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
          "ix": 9, "x": 10}
_NUMWORD = {1: "eins", 2: "zwei", 3: "drei", 4: "vier", 5: "fünf", 6: "sechs",
            7: "sieben", 8: "acht", 9: "neun", 10: "zehn"}

# Artikel/Praepositionen, nach denen eine Ordnungszahl die Endung -en traegt
_DATIVE = {"am", "vom", "zum", "im", "beim", "dem", "den", "des", "der", "einem",
           "einer", "eines", "seit", "bis", "ab", "Am", "Vom", "Zum", "Im", "Seit", "Bis", "Ab"}
_NOMINATIVE = {"die", "das", "eine", "Die", "Das", "Eine"}


def ordinal(n: int, ending: str) -> str:
    return _ORD[n] + ending if n in _ORD else f"{n}."


# --- Ersetzungen ---------------------------------------------------------------

# Abkuerzungen mit Punkt: Der Punkt wuerde sonst als Satzende eine Pause erzeugen.
# Reihenfolge: mehrteilige vor einteiligen.
_ABBREVIATIONS = [
    (r"i\.\s?V\.\s?m\.?(?!\w)", "in Verbindung mit"),  # auch "i.V.m Art."
    (r"i\.\s?S\.\s?d\.?(?!\w)", "im Sinne des"),
    (r"i\.\s?R\.\s?d\.?(?!\w)", "im Rahmen von"),
    (r"i\.\s?S\.\s?v\.", "im Sinne von"),
    (r"i\.\s?S\.\s?e\.", "im Sinne eines"),
    (r"i\.\s?d\.\s?R\.", "in der Regel"),
    (r"i\.\s?E\.", "im Ergebnis"),
    (r"i\.\s?Ü\.", "im Übrigen"),
    (r"z\.\s?B\.", "zum Beispiel"),
    (r"engl\.", "englisch"),
    (r"z\.\s?T\.", "zum Teil"),
    (r"u\.\s?a\.", "unter anderem"),
    (r"u\.\s?U\.", "unter Umständen"),
    (r"v\.\s?a\.", "vor allem"),
    (r"d\.\s?h\.", "das heißt"),
    (r"o\.\s?ä\.", "oder Ähnliches"),
    (r"o\.\s?g\.", "oben genannte"),
    (r"s\.\s?o\.", "siehe oben"),
    (r"s\.\s?u\.", "siehe unten"),
    (r"m\.\s?E\.", "meines Erachtens"),
    (r"h\.\s?M\.", "herrschende Meinung"),
    (r"a\.\s?A\.", "anderer Ansicht"),
    (r"a\.\s?M\.", "anderer Meinung"),
    (r"n\.\s?F\.", "in neuer Fassung"),
    (r"a\.\s?F\.", "in alter Fassung"),
    (r"Urt\.\s?v\.", "Urteil vom"),
    (r"Beschl\.\s?v\.", "Beschluss vom"),
    (r"bzw\.", "beziehungsweise"),
    (r"bzgl\.", "bezüglich"),
    (r"bspw\.", "beispielsweise"),
    (r"ggf\.", "gegebenenfalls"),
    (r"Ggf\.", "Gegebenenfalls"),
    (r"usw\.", "und so weiter"),
    (r"etc\.", "et cetera"),
    (r"vgl\.", "vergleiche"),
    (r"Vgl\.", "Vergleiche"),
    (r"gem\.", "gemäß"),
    (r"einschl\.", "einschließlich"),
    (r"insb\.", "insbesondere"),
    (r"evtl\.", "eventuell"),
    (r"ca\.", "circa"),
    (r"vs\.", "versus"),
    (r"Mio\.", "Millionen"),
    (r"Mrd\.", "Milliarden"),
    (r"Hrsg\.", "Herausgeber"),
    (r"Aufl\.", "Auflage"),
    (r"Kap\.", "Kapitel"),
    (r"Abb\.", "Abbildung"),
    (r"Tab\.", "Tabelle"),
    (r"Ziff\.", "Ziffer"),
    (r"Anh\.", "Anhang"),
    (r"Abschn\.", "Abschnitt"),
    (r"UAbs\.", "Unterabsatz"),
    (r"Abs\.", "Absatz"),
    (r"Artt?\.", "Artikel"),
    (r"lit\.", "Buchstabe"),
    (r"Buchst\.", "Buchstabe"),
    (r"Nrn?\.", "Nummer"),
    (r"Rn\.", "Randnummer"),
    (r"Hs\.", "Halbsatz"),
    (r"Halbs\.", "Halbsatz"),
    (r"Alt\.", "Alternative"),
    (r"Var\.", "Variante"),
    (r"Dr\.", "Doktor"),
    (r"Prof\.", "Professor"),
    (r"[sS]og\.", "SOG"),  # Endung haengt vom Artikel ab, siehe _sogenannt
    (r"ff\.", "fortfolgende"),
]

# Akronyme, die espeak als Wort liest ("EU" -> "Eu", "KI" -> "Kii"): buchstabieren.
# Gepruef mit `espeak-ng -v de -q -x`; Bindestriche erzwingen Buchstabennamen.
_SPELL = {"KI", "EU", "IT", "EG", "AGG", "UWG", "IEC", "OLG", "AEUV", "US", "USA",
          "EUV", "EWR", "KUG", "CE", "BAG", "SAE", "EDSA", "EDSB", "TIA", "JI",
          "CRA", "API", "RAG", "KIR", "LG", "DE", "AI", "MIG", "BSIG", "AGI",
          "GPAI", "IP", "WHO", "IEA", "FAQ", "RED", "PED", "MED", "GAR", "PSA", "AEU",
          "IWF", "IVDR", "IKT", "ICSMS", "IAB", "EHDS", "EGBGB", "AGB", "OWIG", "KMU"}
# Qwen liest "AI" in englischem Zusammenhang ("AI Act", "Stability AI") selbst richtig
_QWEN_NO_SPELL = {"AI"}
# Bewusst als Wort gelesen (so auch gesprochen): LAION, ISO, NIS, FLOP, SCHUFA, GEMA,
# BRAO, DORA, ENISA, EASA, FIFA, UNESCO, ELIZA, ATEX, EMFA

# Zusammengesetzte Kuerzel, die ausgeschrieben besser klingen
_EXPAND = [
    (r"\bKI-VO\b", "KI-Verordnung"),
    (r"\bKIVO\b", "KI-Verordnung"),
    (r"\bMÜ-VO\b", "Marktüberwachungsverordnung"),
    (r"\bDSGVO-E\b", "DSGVO-Entwurf"),
    (r"\b(DSM|JI|NIS-?2|PH)-?RL\b", r"\1-Richtlinie"),
    (r"\bVO\b", "Verordnung"),
    (r"\bRL\b", "Richtlinie"),
    (r"\bEUR\b", "Euro"),
    (r"\b(\d{1,2})\. Jh\.", r"\1. Jahrhundert"),
    (r"\bTWh\b", "Terawattstunden"),
    (r"\bF&E\b", "Forschung und Entwicklung"),
    (r"\bS&P\b", "S-und-P"),
    (r"\bErwG\b", "Erwägungsgrund"),
    (r"\bErwGr\.?", "Erwägungsgrund"),
    (r"\bUrhG\b", "Urheberrechtsgesetz"),
    (r"\b(?:EuGH|EUGH)\b", "E-U-G-H"),
    (r"\bIIb\b", "2 b"),
    (r"\bKI-VOI\b", "KI-VO"),  # Tippfehler in der Quelle
    (r"\bAG(?= [A-ZÄÖÜ][a-zäöü]+\b)", "Amtsgericht"),  # "AG München"
    (r"\bBetrVG\b", "Betriebsverfassungsgesetz"),
    (r"\bKUG\b", "Kunsturhebergesetz"),
    # Gesetzeskuerzel in gemischter Schreibung liest espeak silbenweise ("Prod Haft G")
    (r"\bProdHaftG-E\b", "Produkthaftungsgesetz-Entwurf"),
    (r"\bProdHaftG\b", "Produkthaftungsgesetz"),
    (r"\bProdHaft-?(RL|Richtlinie)\b", "Produkthaftungsrichtlinie"),
    (r"\bGeschGehG\b", "Geschäftsgeheimnisgesetz"),
    (r"\bAktG\b", "Aktiengesetz"),
    (r"\bGewO\b", "Gewerbeordnung"),
    (r"\bBNetzA\b", "Bundesnetzagentur"),
    (r"\bUKlaG\b", "Unterlassungsklagengesetz"),
    (r"\bMStV\b", "Medienstaatsvertrag"),
    (r"\bSaaS\b", "Software-as-a-Service"),
    (r"\bSchulG Bln\b", "Schulgesetz Berlin"),
    (r"\bBlnDSG\b", "Berliner Datenschutzgesetz"),
    (r"\bBayDSG\b", "Bayerisches Datenschutzgesetz"),
    (r"\bDSG NRW\b", "Datenschutzgesetz N-R-W"),
    (r"\bJoerg\b", "Jörg"),
    (r"\bBRAO\b", "B-R-A-O"),  # espeak: "Brao"
    (r"\bOWiG\b", "Ordnungswidrigkeitengesetz"),
    (r"\bUnionsmarkenVO\b", "Unionsmarkenverordnung"),
    (r"\bMüG\b", "Marktüberwachungsgesetz"),
    (r"\bVDuG\b", "Verbraucherrechtedurchsetzungsgesetz"),
    (r"\bVwVfG\b", "Verwaltungsverfahrensgesetz"),
    (r"\bStVG\b", "Straßenverkehrsgesetz"),
    (r"\bKSchG\b", "Kündigungsschutzgesetz"),
    (r"\bHinSchG\b", "Hinweisgeberschutzgesetz"),
    (r"\bArbSchG\b", "Arbeitsschutzgesetz"),
    (r"\bPostG\b", "Postgesetz"),
    (r"\bBVerfG\b", "Bundesverfassungsgericht"),
    (r"\biVm\b", "in Verbindung mit"),
    (r"\bArt (?=\d)", "Art. "),  # Punkt fehlt in der Quelle
]

# Nur fuer espeak (Piper): Lautschrift und Bindestriche, die Qwen nicht braucht
_ESPEAK_EXPAND = [
    (r"\bChatGPT\b", "Tschätt-G-P-T"),
    (r"\bOpenAI\b", "Ohpen-Ei-Ai"),
    (r"\bAI GENERA-?TED\b", "Ei-Ai Dschenerejtet"),
    (r"\bAI MODIFIED\b", "Ei-Ai Moddifaid"),
    (r"(?i)\bKnow-?how\b", "Nohau"),
    (r"\bGEMA\b", "Gähma"),  # espeak: "Ge-MA" mit Schwa
    # espeak liest "Bußgeld" mit kurzem u und im Kompositum "-gəld-beh-wehrt"
    (r"\b([Bb])ußgeld(?=[a-zäöü])", r"\1uhsgeld-"),
    (r"\b([Bb])ußgeld", r"\1uhsgeld"),
    (r"\bon Transparency of AI-?generated Content\b", "on Tränspärenssi off Ei-Ai-Dschenerejtet Kontent"),
    (r"\bCivil Resolution Tribunal\b", "Siwwl Resoluschen Traibjunal"),
    (r"\bBusiness Judgm?ent Rule\b", "Bisness Dschadschment Ruhl"),
    (r"\bAutocomplete\b", "Autokompliet"),
    (r"\bDesignG\b", "Desain-Gesetz"),
    (r"\bG[Rr]C[Hh]\b", "Grundrechte-Karta"),  # "Charta" liest espeak mit sch
    (r"\bCharta\b", "Karta"),
    (r"\bePrivacy\b", "Ih-Praiwessi"),
]
# Gegenstueck fuer --engine qwen, wo die Piper-Fassung keine normale Schreibung ist
_QWEN_EXPAND = [
    (r"\bAI GENERA-?TED\b", "AI-generated"),
    (r"\bAI MODIFIED\b", "AI-modified"),
    (r"\bDesignG\b", "Designgesetz"),
    (r"\bG[Rr]C[Hh]\b", "Grundrechtecharta"),
]
_ENGINE = "piper"  # setzt main() aus --engine

# Genderstern: Doppelnennung (Formen aus den Skripten, weitere bei Bedarf ergaenzen)
_GENDER = {
    "Kund*innen": "Kundinnen und Kunden",
    "Schüler*innen": "Schülerinnen und Schüler",
    "Mandatsträger*innen": "Mandatsträgerinnen und Mandatsträger",
    "Schriftsteller*innen": "Schriftstellerinnen und Schriftsteller",
    "Bürger*innen": "Bürgerinnen und Bürger",
    "Leser*innen": "Leserinnen und Leser",
    "Adressat*innen": "Adressatinnen und Adressaten",
    "Kolleg*innen": "Kolleginnen und Kollegen",
    "Hersteller*innen": "Herstellerinnen und Hersteller",
    "jede*r": "jede und jeder",
}

# Englische Fachbegriffe, die espeak nach deutschen Regeln liest ("Chatbot" ->
# "Schatbot", "Bias" -> "Bi-as") oder auf englische Laute umschaltet, die das
# deutsche Stimm-Modell nicht kennt. Ersatz geprueft mit `espeak-ng -v de -x`.
# Haeufige Woerter wie Software, Update, Cloud fehlen hier bewusst: Fuer Piper
# ersetzte sie ein eigenes Lexikon, das nicht Teil dieses Repos ist.
_PHRASES = [
    (r"\bCode of Practice\b", "Kohd off Präktiss"),
    (r"\bGeneral[- ]Purpose\b", "Dschenerell-Pörpes"),
    (r"\bHuman-in-the-Loop\b", "Juhmen-in-de-Luhp"),
    (r"\bHuman-on-the-Loop\b", "Juhmen-on-de-Luhp"),
    (r"\bOpen[- ]Source\b", "Ohpen-Sohrs"),
    (r"\bBlack[- ]Box\b", "Bläck-Box"),
    (r"\bUse[- ]Cases?\b", "Juhs-Keis"),
    (r"\bas-a-Service\b", "äs-ä-Sörwis"),
    (r"\bAnalytical Engine\b", "Ännelittikl Endschin"),
    (r"\bBrute[- ]Force\b", "Bruht-Fohrs"),
    (r"\bA-I\b(?=[- ]Act|[- ]Office|\)|$)", "Ei-Ai"),
    (r"(?<=Pörpes )A-I\b", "Ei-Ai"),
]
_ANGLICISMS = {
    "Babbage": "Bäbbidsch", "Babbages": "Bäbbidschs", "Lovelace": "Lawlejs",
    "Dartmouth": "Dahrtmuss", "Blue": "Bluh", "Mary": "Mähri", "Shelley": "Schelli",
    "Shelleys": "Schellis",
    "Bias": "Baias", "Chats": "Tschätts", "Code": "Kohd", "Copyright": "Koppirait",
    "Cybersecurity": "Saibersekjuriti", "Data": "Dejta", "Deep": "Diep",
    "Deepfake": "Diepfeik", "Deepfakes": "Diepfeiks", "Download": "Daunlohd",
    "Downloads": "Daunlohds", "Downstream": "Daunstriem", "Fairness": "Fernes",
    "Framework": "Fräimwörk", "Google": "Guhgel", "Guide": "Gaid", "Human": "Juhmen",
    "Input": "Inputt", "Label": "Lejbel", "Labels": "Lejbels", "Language": "Längwitsch",
    "Large": "Lahrdsch", "Learning": "Lörning", "Loop": "Luhp", "Machine": "Mäschien",
    "Microsoft": "Maikrosoft", "Mining": "Maining", "Office": "Offis", "Output": "Autputt",
    "Practice": "Präktiss", "Provider": "Prowaider", "Resilience": "Risilienz",
    "Service": "Sörwis", "Teams": "Tiems", "Tools": "Tuhls", "Website": "Wäbsait",
}
# Stamm auch in geschlossenen Komposita ("Bürosoftware", "Onlineshop", "KI-Chatbots")
_STEMS = [("compliance", "Kompleiens"), ("governance", "Gawernens"),
          ("online", "Onlain"), ("chatbot", "Tschättbot"), ("e-mail", "Iemejl"),
          ("software", "Softwär"), ("hardware", "Hardwär")]


def _anglicisms(t: str) -> str:
    for pat, rep in _PHRASES:
        t = re.sub(pat, rep, t)
    t = re.sub(r"\b(" + "|".join(_ANGLICISMS) + r")\b", lambda m: _ANGLICISMS[m.group(1)], t)

    def stem(m: re.Match[str], rep: str) -> str:
        return rep if m.group(0)[0].isupper() else rep.lower()
    for s, rep in _STEMS:
        t = re.sub(s, partial(stem, rep=rep), t, flags=re.IGNORECASE)
    return t


_URL_RE = re.compile(r"(?:https?://|www\.)\S+")
_FOOTREF_RE = re.compile(r"\[\d{1,4}(?:\s*[,–-]\s*\d{1,4})*\]")
_HEADING_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)\s+([A-ZÄÖÜ„\"].*)$")
_BACK_MATTER_RE = re.compile(
    r"^(Glossar.*|Literaturverzeichnis|Abkürzungsverzeichnis|Quellenverzeichnis|"
    r"Stichwortverzeichnis|Rechtsprechungsverzeichnis)$")


def _spell_if_listed(word: str) -> str:
    """Akronym buchstabieren, wenn es in _SPELL steht (bei Qwen ohne _QWEN_NO_SPELL)."""
    if word not in _SPELL or (_ENGINE == "qwen" and word in _QWEN_NO_SPELL):
        return word
    return _spell(word)


def _spell(word: str) -> str:
    return "-".join(word)


def _sogenannt(m: re.Match[str]) -> str:
    """Endung von "sog." am folgenden Adjektiv oder am Artikel ausrichten."""
    prev, nxt = m.group(1), m.group(2)
    adj = re.match(r"[a-zäöü]\w*?(en|em|er|es|e)$", nxt)
    # Ohne Adjektiv entscheidet der Artikel; "der" ist mehrdeutig und bekommt -e
    article_ending = "en" if prev in _DATIVE - {"der"} else "e"
    ending = adj.group(1) if adj else article_ending
    return f"{prev} sogenannt{ending} {nxt}"


def _date(m: re.Match[str]) -> str:
    day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return m.group(0)
    return f"{day}. {_MONTHS[month - 1]} {year}"


def _ordinals(text: str) -> str:
    """Ordnungszahlen vor Monaten, "Auflage" und nach Artikeln ausschreiben."""
    months = "|".join(_MONTHS)

    def month_ord(m: re.Match[str]) -> str:
        # Endung nach dem Wort davor: "am ersten", "der erste", ohne Artikel "erster"
        # ("Stand: erster Oktober"); vor dem Monat ist "der" Nominativ, nicht Dativ
        prev, n = m.group(1), int(m.group(2))
        if prev in _DATIVE - {"der"}:
            ending = "en"
        elif prev in _NOMINATIVE | {"der", "Der"}:
            ending = "e"
        else:
            ending = "er"
        return f"{m.group(0)[:m.start(2) - m.start(0)]}{ordinal(n, ending)} {m.group(3)}"
    text = re.sub(rf"(?:(?<![\w.])(\w+)\s+)?(?<!\S)(\d{{1,2}})\. ({months})\b", month_ord, text)
    # "seit 2.2.2025" -> "seit dem zweiten Februar"
    text = re.sub(rf"\b([Ss]eit|[Aa]b) (?=\w+en (?:{months})\b)", r"\1 dem ", text)

    def edition(m: re.Match[str]) -> str:
        n = int(m.group(1))
        return f"{ordinal(n, 'e')} Auflage"
    text = re.sub(r"\b(\d{1,2})\. Auflage\b", edition, text)

    def after_article(m: re.Match[str]) -> str:
        art, n, word = m.group(1), int(m.group(2)), m.group(3)
        ending = "en" if art in _DATIVE else "e"
        if art.lower() in ("seit", "ab"):
            art += " dem"
        return f"{art} {ordinal(n, ending)} {word}"
    articles = "|".join(sorted(_DATIVE | _NOMINATIVE))
    return re.sub(rf"\b({articles}) (\d{{1,2}})\. ([A-ZÄÖÜa-zäöü]\w+)", after_article, text)


_ROMAN_DIGITS = {"I": 1, "V": 5, "X": 10}
_NUMWORD_TEENS = {11: "elf", 12: "zwölf", 13: "dreizehn", 14: "vierzehn", 15: "fünfzehn",
                  16: "sechzehn", 17: "siebzehn", 18: "achtzehn", 19: "neunzehn", 20: "zwanzig"}
_ROMAN_UNIT = r"(?=[IVX])(?:XX|X?(?:IX|IV|V?I{0,3}))(?![\wäöüß-])"
_ROMAN_AFTER = re.compile(
    r"\b(Anh(?:ang|angs|änge|ängen)|Kapitels?|Teils?|Titels?|Abschnitts?|Bandes|Band|Buch"
    r"|Klassen?|München|Artikel \d+[a-z]?)"
    rf"((?:\s*(?:,|und|bis|oder)?\s+{_ROMAN_UNIT})+)")


def _roman_value(r: str) -> int:
    vals = [_ROMAN_DIGITS[c] for c in r]
    return sum(-v if i + 1 < len(vals) and v < vals[i + 1] else v for i, v in enumerate(vals))


def _roman_numerals(text: str) -> str:
    """Roemische Zahl nach "Anhang", "Kapitel" usw. als Zahlwort: espeak liest "Anhang I"
    als Buchstaben und "Anhang III" als "roemisch drei"."""
    def numword(m: re.Match[str]) -> str:
        n = _roman_value(m.group(0))
        return _NUMWORD.get(n) or _NUMWORD_TEENS.get(n) or m.group(0)

    def repl(m: re.Match[str]) -> str:
        nums = re.sub(rf"(?<!\w){_ROMAN_UNIT}", numword, m.group(2))
        # "Art. 6 III" ist die Kurzschreibweise fuer Absatz 3
        return m.group(1) + (" Absatz" if m.group(1).startswith("Artikel") else "") + nums
    text = _ROMAN_AFTER.sub(repl, text)
    # Unterpunkte klein: "Buchstabe h Ziffer iii"
    text = re.sub(r"\b(Ziffern?|Ziff\.) ((?:i{1,3}|iv|vi{0,3}|ix|x)(?![\w-]))",
                  lambda m: f"Ziffer {_NUMWORD[_ROMAN[m.group(2)]]}", text)
    # Senat im Aktenzeichen: "X ZR 37/11", "VI ZB 39/18"
    return re.sub(rf"(?<![\w-]){_ROMAN_UNIT}(?= (?:[A-Z]?Z[RB]|StR|AZR)\b)", numword, text)


def _arrows(text: str) -> str:
    text = text.replace("\uf0e8", " → ").replace("\uf0e7", " gegenüber ")
    # Pfeil nach Satzende ist ein Gliederungszeichen: weglassen
    text = re.sub(r"([.!?][“\"”)]?)\s*→\s*", r"\1 ", text)
    # Zwischen zwei Einzelwoertern: "Eingabe → Ausgabe" -> "Eingabe zu Ausgabe"
    text = re.sub(r"(?<=\w) → (?=\w+[\s),.;:])(?=(\w+)(?![\w-]))", " zu ", text)
    text = re.sub(r"(^|[.!?:]\s+)→\s*", r"\1Daraus folgt: ", text)
    return re.sub(r"\s*→\s*", ", also ", text)


def speakable(text: str) -> str:
    """Einen Absatz in vorlesbaren Text umsetzen."""
    t = _FOOTREF_RE.sub("", text)
    t = re.sub(r"(\d)(lit\.|Abs\.|Nr\.)", r"\1 \2", t)  # Tippfehler "Abs. 1lit. h"
    t = re.sub(r"\b(Abs|Art|Nr|Rn|S)\.(\d)", r"\1. \2", t)  # "Abs.1"
    t = re.sub(r"(\d)([A-ZÄÖÜ][a-zäöü])", r"\1 \2", t)  # "Abs. 3ProdHaftG"
    t = _URL_RE.sub("", t)
    t = re.sub(r"\b(abrufbar|verfügbar)\s+(unter|hier)?\s*:?\s*(?=[,.;)]|$)", "", t)
    for k, v in _GENDER.items():
        t = t.replace(k, v)
    # Aufzaehlungszeichen mitten im Absatz: wie ein Komma lesen, nach Satzende und
    # Bindewort ("… Aufsicht sowie • eine …") entfallen
    t = re.sub(r"(?<=[.:;!?])\s*[•◦▪➢►✓]\s+", " ", t)
    t = re.sub(r"\b(und|oder|sowie)\s+[•◦▪➢►✓]\s+", r"\1 ", t)
    t = re.sub(r",?\s*[•◦▪➢►✓]\s+", ", ", t)
    t = t.replace("*", "")
    t = re.sub(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", _date, t)
    for pat, rep in _EXPAND + (_ESPEAK_EXPAND if _ENGINE == "piper" else _QWEN_EXPAND):
        t = re.sub(pat, rep, t)
    # Satz nach Absatz/Unterabsatz ("Abs. 1 S. 2"), sonst Seite
    t = re.sub(r"\b((?:U?Abs\.|Absatz|Unterabsatz)\s+\d+\w?)\s+S\.\s+(?=\d)", r"\1 Satz ", t)
    t = re.sub(r"\bS\.\s+(?=\d)", "Seite ", t)
    # "Art. 26ff.", "Rn. 5 f.": auch ohne Leerzeichen an der Zahl
    t = re.sub(r"(?<=\d)\s?ff\.", " fortfolgende", t)
    t = re.sub(r"(?<=\d)\s?f\.(?=[\s,;)]|$)", " folgende", t)
    for pat, rep in _ABBREVIATIONS:
        t = re.sub(rf"(?<![\w.]){pat}", rep, t)
    t = re.sub(r"(\w+) SOG (\S+)", _sogenannt, t)
    t = re.sub(r"^SOG\b", "Sogenannte", t)
    t = re.sub(r"\bSOG\b", "sogenannte", t)
    t = re.sub(r"\blit\s+(?=[a-z]{1,2}\b)", "Buchstabe ", t)
    t = re.sub(r"\b(UND|ODER|NICHT|ODER AUCH)\b", lambda m: m.group(1).lower(), t)
    t = t.replace("\u2011", "-")
    t = re.sub(r"§§\s*", "Paragrafen ", t)
    t = re.sub(r"§\s*", "Paragraf ", t)
    # Akronyme buchstabieren, auch als Glied von Komposita ("EU-KI-Verordnung")
    t = re.sub(r"(?<![\w-])([A-ZÄÖÜ]{2,5})(?=$|[^\wäöüß])",
               lambda m: _spell_if_listed(m.group(1)), t)
    t = re.sub(r"(?<![\w])([A-ZÄÖÜ]{2,5})(?=-[\wÄÖÜ])",
               lambda m: _spell_if_listed(m.group(1)), t)
    t = re.sub(r"(?<=-)([A-ZÄÖÜ]{2,5})(?=$|[^\wäöüß])",
               lambda m: _spell_if_listed(m.group(1)), t)
    if _ENGINE == "piper":
        t = _anglicisms(t)
        # "K-I-Verordnung": espeak bindet "I" an das folgende "V" ("kaː iːfɛɾ…"), beide  # noqa: RUF003 (IPA-Längenzeichen)
        # Pruefmodelle hoerten in jedem vierten Fall "KF-Verordnung"; mit Wortgrenze nicht
        t = re.sub(r"\bK-I-(?=Verordnung|[aeiouäöüAEIOUÄÖÜ])", "K-I ", t)
        # espeak liest unbetontes "ge" im Kompositum als langes "geh" und zerreisst
        # "geheim" ("Geschäfts-geh-eimnis"); ein Bindestrich vor dem Wortteil hilft
        t = re.sub(r"(?<=[a-zäöüß])(gesetz(?!t)|geheim|gericht(?!et)|gebiet)", r"-\1", t)  # nicht "eingesetzt"
    # Ordnungszahlen, Formeln, Zeichen
    t = _roman_numerals(t)
    t = _ordinals(t)
    t = re.sub(r"\(?10\^\{?(\d+)\}?\)?", r"10 hoch \1", t)
    t = re.sub(r"10([⁰¹²³⁴⁵⁶⁷⁸⁹]+)",
               lambda m: "10 hoch " + m.group(1).translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")), t)
    t = re.sub(r"(?<=\d) / (?=\d)", " von ", t)  # "Wissenstest 1 / 4"
    # Bereiche mit Binde- oder Halbgeviertstrich: "Randnummer 8-15", "Buchstabe a-m"
    t = re.sub(r"(?<=\d)\s?[–-]\s?(?=\d)", " bis ", t)
    t = re.sub(r"\b(Buchstaben?) ([a-z])\s?[–-]\s?([a-z])\b", r"\1 \2 bis \3", t)
    t = re.sub(r"(?<=\d)\s*/\s*(?=\d)", " Strich ", t)
    t = re.sub(r"\bModul (\d+)", lambda m: "Modul " + " ".join(m.group(1)), t)
    t = re.sub(r"(\w)/n\b", r"\1n", t)
    t = re.sub(r"(\w)-\s*/\s*(\w)", r"\1- oder \2", t)
    t = re.sub(r"(\w)\s*/\s*-(\w)", r"\1 oder -\2", t)
    t = re.sub(r"\bund\s*/\s*oder\b", "und oder", t)
    t = re.sub(r"\b([A-ZÄÖÜ][\wäöüß-]*)\s*/\s*(?=[A-ZÄÖÜ])", r"\1 und ", t)  # "Russell/Norvig"
    t = re.sub(r"(?<=\w)\s*/\s*(?=\w)", " oder ", t)
    t = re.sub(r"\s/\s", " oder ", t)
    # Aufzaehlung im Fliesstext: "oder b. bekannten" -> "oder Buchstabe b: bekannten"
    t = re.sub(r"(\b(?:und|oder)|[,;])\s+([a-z])\.\s", r"\1 Buchstabe \2: ", t)
    t = _arrows(t)
    t = re.sub(r"\s+=\s+", " bedeutet ", t)
    t = re.sub(r"\s+\+\s+", " plus ", t)
    t = t.replace("&", " und ").replace("€", " Euro").replace("™", "")
    t = re.sub(r"\[([^\]]*)\]", r"\1", t)  # Einfuegungen in Zitaten
    t = re.sub(r"[\x00-\x1f|#~^{}\uf000-\uf0ff…]", " ", t)
    t = re.sub(r"\(\s*\)", "", t)
    t = re.sub(r"\s+([,.;:!?)])", r"\1", t)
    t = re.sub(r"([,;:])\1+", r"\1", t)
    t = re.sub(r",\s*\.", ".", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _list_marker(p: str) -> str:
    """Aufzaehlungszeichen und Gliederungsmarken am Absatzanfang sprechbar machen."""
    p = re.sub(r"^[•◦▪➢►✓–-]\s+", "", p)
    m = re.match(r"^(\d{1,2})\.\s+(?=\S)(?!Jh\.)", p)  # "19. Jh." ist keine Aufzaehlung
    if m:
        n = int(m.group(1))
        return f"{_ADVERB.get(n, f'Nummer {n}')}: " + p[m.end():]
    m = re.match(r"^\(?([ivx]{1,4})\)\s+", p)
    if m and m.group(1) in _ROMAN:
        return f"Ziffer {_NUMWORD[_ROMAN[m.group(1)]]}: " + p[m.end():]
    m = re.match(r"^\(?([a-z]{1,2})[.)]\s+", p)
    if m:
        return f"Buchstabe {m.group(1)}: " + p[m.end():]
    return p


def _item_end(text: str) -> tuple[str, str]:
    """
    Aufzaehlungspunkte enden im Hoertext mit Satzpause. Ein Bindewort am Ende
    ("…, und") wandert an den Anfang des naechsten Punkts ("Und die …"),
    sonst entstuende ein Satz aus Hunderten Woertern ohne Pause.
    Returns (text_mit_satzende, bindewort_fuer_naechsten_punkt).
    """
    m = re.search(r"[,;]?\s+(und|oder|sowie)$", text)
    if m and m.start() > 0 and not re.match(r"^(\w+: )?(und|oder|sowie)$", text, re.IGNORECASE):
        return text[:m.start()].rstrip(",; ") + ".", m.group(1).capitalize()
    return re.sub(r"[,;]$", ".", text), ""


def _ends_sentence(p: str) -> bool:
    return bool(re.search(r"[.!?:;“\"”)]$", p))


def _terminate(p: str) -> str:
    p = p.rstrip()
    if not p:
        return p
    if p.endswith(":"):
        return p[:-1] + "."
    # Aufzaehlungsglied mitten im Satz ("…, und" / "…;"): ohne Punkt weiterlesen
    if re.search(r"([,;]|\b(und|oder|sowie|beziehungsweise))$", p):
        return p
    return p if re.search(r"[.!?]$", p) or re.search(r"[.!?][“\"”)]$", p) else p + "."


# --- Tabellen ------------------------------------------------------------------

def _parse_table(block: str) -> tuple[list[str], list[list[str]]]:
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")]
            for ln in block.splitlines() if ln.strip() and not re.match(r"^\|[-|]+\|$", ln)]
    header, body = rows[0], rows[1:]
    # Kopfzeile, die die Tabellenerkennung getrennt hat ("Auslegungsme-" / "thode")
    if body and any(re.search(r"[^\W\d_]-$", h) for h in header):
        header = [_join_hyphenated(h, c) for h, c in zip(header, body[0], strict=False)]
        body = body[1:]
    return header, body


def _join_hyphenated(left: str, right: str) -> str:
    """Silbentrennung zwischen zwei Zellfragmenten aufloesen ("KI-" + "Verordnung" bleibt)."""
    if not right:
        return left
    if re.search(r"[^\W\d_]-$", left):
        return left[:-1] + right if right[:1].islower() else left + right
    return f"{left} {right}".strip()


def _table_text(header: list[str], rows: list[list[str]]) -> str:
    sentences = []
    for row in rows:
        parts = []
        for h, c in zip(header, row, strict=False):
            if not c:
                continue
            c = _terminate(speakable(c))
            parts.append(f"{speakable(h)}: {c}" if h else c)
        if parts:
            sentences.append(" ".join(parts))
    return " ".join(sentences)


# --- Englische Zitate -----------------------------------------------------------

_EN_WORDS = {"the", "of", "and", "to", "for", "is", "are", "which", "that", "with", "by",
             "it", "be", "as", "or", "at", "from", "this", "we", "their", "means", "an"}
_DE_WORDS = {"der", "die", "das", "und", "ist", "sind", "nicht", "mit", "von", "zu", "den",
             "dem", "des", "ein", "eine", "auf", "für", "sich", "auch", "wird", "werden"}
_EN_NOTE = "Es folgt ein englisches Originalzitat, das hier nicht vorgelesen wird."


def _is_english(sentence: str) -> bool:
    words = re.findall(r"[a-zäöüß]+", sentence.lower())
    en = sum(w in _EN_WORDS for w in words)
    de = sum(w in _DE_WORDS for w in words)
    return en >= 3 and en > 2 * de


# Piper (VITS) wird bei langen Saetzen undeutlich. Gemessen an einem Sachtext per
# Ruecktranskription mit Whisper und Parakeet (Anteil der Woerter, die beide Modelle
# verfehlen): 2,2 % unter 150 Zeichen, 5,4 % bei 250 bis 350, 14,4 % bei 350 bis 450,
# 23,7 % ueber 600. Lange Saetze werden deshalb an Satzzeichen in Teilsaetze zerlegt.
_MAX_SENTENCE = 220
_SPLIT_MARKS = [r"; ", r": ", r" (?=\()", r"(?<=\)),? ", r", ",
                # letzte Wahl: vor Zitat oder Bindewort (das Bindewort bleibt im neuen Satz)
                r" (?=„)", r" (?=sowie )", r"(?<!-) (?=und )", r"(?<!-) (?=oder )"]


def _split_long(sentence: str) -> list[str]:
    """Satz ueber _MAX_SENTENCE Zeichen an der besten Stelle teilen, rekursiv."""
    if _ENGINE == "qwen" or len(sentence) <= _MAX_SENTENCE:
        return [sentence]
    for mark in _SPLIT_MARKS:
        cands = [m for m in re.finditer(mark, sentence) if 60 <= m.start() <= len(sentence) - 40]
        if cands:
            # Teilstelle moeglichst nah an der Mitte, damit beide Teile kurz werden
            m = min(cands, key=lambda m: abs(m.start() - len(sentence) / 2))
            head = sentence[:m.start()].rstrip(" ,;:") + "."
            tail = sentence[m.end():].lstrip()
            return _split_long(head) + _split_long(tail)
    return [sentence]


def _drop_english_quotes(line: str) -> str:
    """
    Englische Zitatbloecke durch einen Hinweis ersetzen: Die deutsche Stimme liest
    Englisch weitgehend unverstaendlich (Ruecktranskription: "More than half of SMEs"
    wird "Mauritan half aufs Mess"). Die Skripte liefern meist eine Uebersetzung oder
    Paraphrase direkt dahinter; englische Einsprengsel in deutschen Saetzen bleiben.
    """
    # englisches Originalzitat in Klammern hinter der deutschen Wiedergabe: entfaellt
    line = re.sub(r"\s*\(„([^“”\"]+)[“”\"]\)", lambda m: "" if _is_english(m.group(1)) else m.group(0), line)
    out: list[str] = []
    for sent in re.split(r"(?<=[.!?])\s+", line):
        if _ENGINE == "piper" and _is_english(sent):  # Qwen liest Englisch verstaendlich
            if not out or out[-1] != _EN_NOTE:
                out.append(_EN_NOTE)
            continue
        if out and out[-1] == _EN_NOTE and re.fullmatch(r"\([^)]*\)\.?", sent):
            continue  # Klammerzusatz zum Zitat, etwa die franzoesische Fassung
        out.extend(_split_long(sent))
    # espeak wertet einen Punkt vor Kleinbuchstaben nicht als Satzende (keine Pause,
    # Saetze verschmelzen); Aufzaehlungspunkte beginnen oft klein
    return " ".join(s[:1].upper() + s[1:] for s in out)


# --- Dokument ------------------------------------------------------------------

def convert(source: str) -> str:
    """Text aus `pdf_zu_text.py --clean --page-markers` in die Hoerfassung umsetzen."""
    has_markers = re.search(r"^\[(?:PDF-)?Seite [^\]]+\]\s*$", source, flags=re.M) is not None
    pages = re.split(r"^\[(?:PDF-)?Seite [^\]]+\]\s*$", source, flags=re.M)
    pages = [[p.strip() for p in pg.split("\n\n") if p.strip()] for pg in pages]
    if has_markers and not pages[0]:
        pages = pages[1:]

    # Fussnoten abschneiden (ab dem Fussnotenstrich)
    bodies = []
    for pg in pages:
        cut = next((k for k, p in enumerate(pg) if re.match(r"^_{5,}$", p)), len(pg))
        bodies.append(pg[:cut])

    def toc_line(p: str) -> bool:
        return bool(re.search(r"(\.{2,}|…)\s*[\dIVXivx]+$|\s\d+$", p))

    flat = [(pi, p) for pi, pg in enumerate(bodies) for p in pg]
    # Hauptteil beginnt mit Kapitel "1 Titel" (nicht der Eintrag im Inhaltsverzeichnis);
    # ohne Seitenmarker oder Gliederung: ganzer Text, kein Deckblatt
    start = next((k for k, (pi, p) in enumerate(flat)
                  if pi > 0 and re.match(r"^1\s+[A-ZÄÖÜ]", p) and not toc_line(p)), None)
    cover = bodies[0] if has_markers and start is not None else []
    start = start or 0
    end = next((k for k, (_, p) in enumerate(flat) if k > start and _BACK_MATTER_RE.match(p)),
               len(flat))
    body = flat[start:end]

    # Absaetze, Tabellen, Randnotizen ueber Seitengrenzen zusammenfuehren
    items: list[dict[str, Any]] = []
    for pi, p in body:
        if p.startswith("|"):
            header, rows = _parse_table(p)
            prev = items[-1] if items else None
            if prev and prev["kind"] == "table" and prev["header"] == header:
                for row in rows:  # Fortsetzung auf neuer Seite
                    if row and not row[0] and prev["rows"]:
                        prev["rows"][-1] = [f"{a} {b}".strip()
                                            for a, b in zip(prev["rows"][-1], row, strict=False)]
                    else:
                        prev["rows"].append(row)
            else:
                items.append({"kind": "table", "header": header, "rows": rows, "page": pi})
            continue
        if re.match(r"^(Abbildung|Tabelle) \d+:?\s", p):
            # Beschriftungen aus der Grafik selbst ("Deep", "Input Layer"): kurze Absaetze
            # ohne Satzzeichen direkt vor der Bildunterschrift entfallen
            while (items and items[-1]["kind"] == "para" and items[-1]["page"] == pi
                   and len(items[-1]["text"]) <= 60
                   and not re.search(r"[.!?:;“\")]$", items[-1]["text"])
                   and _list_marker(items[-1]["text"]) == items[-1]["text"]):
                items.pop()
            p = re.sub(r"^(.{10,}?)\s+\1$", r"\1", p)  # doppelt extrahierte Bildunterschrift
            items.append({"kind": "caption", "text": p, "page": pi})
            continue
        if p.startswith("[Randnotiz:"):
            items.append({"kind": "note", "text": p[len("[Randnotiz:"):-1].strip(), "page": pi})
            continue
        m = _HEADING_RE.match(p)
        if m and len(p) < 220 and not re.search(r"[.!?]$", p) and int(m.group(1).split(".")[0]) <= 20:
            items.append({"kind": "heading", "num": m.group(1), "text": m.group(2), "page": pi})
            continue
        # Seitenuebergreifender Absatz: Vorgaenger ohne Satzende auf voriger Seite
        last_para = next((it for it in reversed(items) if it["kind"] == "para"), None)
        between = items[items.index(last_para) + 1:] if last_para else []
        if (last_para and last_para["page"] < pi and not _ends_sentence(last_para["text"])
                and all(it["kind"] in ("note", "caption") for it in between)):
            prev = last_para["text"]
            if re.search(r"[^\W\d_]-$", prev) and p[:1].islower() and \
                    not re.match(r"(und|oder|bzw\.|sowie)\b", p):
                last_para["text"] = prev[:-1] + p
            else:
                last_para["text"] = prev + " " + p
            last_para["page"] = pi
            continue
        items.append({"kind": "para", "text": p, "page": pi})

    # Ausgabe: eine Zeile je Abschnitt
    carry = ""  # Bindewort vom Ende eines Aufzaehlungspunkts fuer den naechsten
    lines: list[list[str]] = [[_terminate(". ".join(speakable(c) for c in cover))] if cover else []]
    for it in items:
        if it["kind"] == "heading":
            level = it["num"].count(".")
            label = "Kapitel" if level == 0 else "Abschnitt"
            title = _terminate(speakable(_FOOTREF_RE.sub("", it["text"])))
            lines.append([f"{label} {it['num']}: {title}"])
        elif it["kind"] == "caption":
            lines[-1].append(_terminate(speakable(it["text"])))
        elif it["kind"] == "note":
            lines[-1].append(_terminate(f"Stichwort: {speakable(it['text'])}"))
        elif it["kind"] == "table":
            lines[-1].append(_table_text(it["header"], it["rows"]))
        else:
            is_item = _list_marker(it["text"]) != it["text"]
            text = speakable(_list_marker(it["text"]))
            if carry and text:
                text = f"{carry} {text[0].lower()}{text[1:]}"
                carry = ""
            if not text:
                continue
            if is_item:
                text, carry = _item_end(text)
                if not carry and text.lower().endswith((" und", " oder", " sowie")):
                    lines[-1].append(text)  # Gliederungspunkt nur "Und": weiterlesen
                    continue
            lines[-1].append(_terminate(text))
    return "\n".join(_drop_english_quotes(" ".join(x for x in ln if x))
                     for ln in lines if ln) + "\n"


def _source_text(path: Path) -> str:
    """Eingabetext; PDFs laufen zuerst durch pdf_zu_text.py --clean --page-markers."""
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / (path.stem + ".txt")
        subprocess.run([sys.executable, str(PDF_TO_TXT), str(path), "--clean", "--page-markers", "-q",
                        "--lang", "deu",  # Texterkennung bei Scans auf Deutsch
                        "-o", str(out)], check=True)
        return out.read_text(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Text (PDF oder pdf_zu_text --clean) fuer vorlesen.sh aufbereiten",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  %(prog)s skript.pdf                 # -> skript_hoerfassung.txt
  %(prog)s skript.txt                 # Eingabe aus pdf_zu_text.py --clean --page-markers
  %(prog)s skript.pdf -o hoer.txt     # eigener Ausgabepfad
  %(prog)s Skripte/*/*.pdf            # Batch
  ./vorlesen.sh skript_hoerfassung.txt   # danach vertonen
""")
    ap.add_argument("sources", type=Path, nargs="+", metavar="datei",
                    help="PDF oder Text aus pdf_zu_text.py --clean --page-markers")
    ap.add_argument("-o", "--output", type=Path,
                    help="Ausgabedatei (nur bei genau einer Eingabe; Default <name>_hoerfassung.txt)")
    ap.add_argument("--engine", choices=["piper", "qwen"], default="qwen",
                    help="Ziel-Sprachausgabe (Default qwen); piper mit espeak-Lautschrift")
    ap.add_argument("--version", action="version", version="%(prog)s 1.2.1")
    args = ap.parse_args()
    global _ENGINE
    _ENGINE = args.engine

    if args.output and len(args.sources) > 1:
        ap.error("-o/--output ist nur bei genau einer Eingabedatei erlaubt")

    rc = 0
    for source in args.sources:
        if not source.is_file():
            print(f"Fehler: Datei nicht gefunden: {source}", file=sys.stderr)
            rc = 1
            continue
        try:
            out = convert(_source_text(source))
        except (subprocess.CalledProcessError, OSError, UnicodeDecodeError) as e:
            print(f"Fehler ({source.name}): {e}", file=sys.stderr)
            rc = 1
            continue
        suffix = "_tts.txt" if args.engine == "piper" else "_hoerfassung.txt"
        target = args.output or source.with_name(source.stem + suffix)
        target.write_text(out, encoding="utf-8")
        print(f"{target}: {len(out.splitlines())} Zeilen, {len(out.split())} Wörter",
              file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
