---
description: "Gesprächsmodus an oder aus: Claude hängt jeder Antwort eine gesprochene Fassung an, die der Stop-Hook über den lokalen Sprechdienst (Qwen3-TTS) vorliest."
argument-hint: "[aus]"
disable-model-invocation: true
---

# Gesprächsmodus

Argument: `$ARGUMENTS`

## Bei `aus`

Ab sofort keine Sprechmarken mehr anhängen. Antworte nur mit „Der Gesprächsmodus ist aus.“, ohne Marke. Sonst nichts tun.

## Sonst: Modus einschalten

Für den Rest dieser Sitzung endet **jede** Antwort mit genau einer Sprechmarke als HTML-Kommentar:

```
<!-- sprechen: Gesprochene Fassung in ganzen Sätzen. -->
```

Der Stop-Hook (`claude_sprechen.py` im Hörbuch-Generator) liest nur den Inhalt dieser Marke vor.
Die geschriebene Antwort davor bleibt, wie sie wäre: mit Tabellen, Code und Pfaden. Was zum
Kopieren oder Nachlesen gebraucht wird, steht dort und nicht in der Marke.

### Knapp

Wer zuhört, tut meist nebenbei etwas anderes. Jede Sekunde Sprechzeit kostet Aufmerksamkeit.

- **Meist ein bis drei Sätze, höchstens rund 60 Wörter**, das ist etwa eine halbe Minute. Mehr
  nur, wenn ausdrücklich eine ausführliche Erklärung gewünscht ist.
- **Das Ergebnis zuerst.** Danach nur, was jetzt zu wissen oder zu entscheiden ist. Herleitung,
  Einzelheiten und Belege bleiben im geschriebenen Teil; ein Hinweis wie „Die Einzelheiten
  stehen im Text“ genügt.
- **Nicht vorlesen, was schon bekannt ist:** keine Wiederholung der Frage, keine Ankündigung,
  kein Rückblick auf die Arbeitsschritte, keine Zusammenfassung am Schluss.
- **Höchstens eine Frage pro Antwort**, und die am Ende, damit die Antwort gleich folgen kann.
- **Nie nur ein Wort.** „Erledigt.“ allein erzeugt die Stimme oft nicht; ein ganzer Satz wie
  „Ich bin fertig, die Tests laufen.“ kommt an.

### Natürlich

Die Marke ist gesprochene Sprache, kein vorgelesener Text. Maßstab: so, wie ein Kollege am
Schreibtisch nebenan es sagen würde.

- **Kurze Sätze**, ein Gedanke je Satz, keine Schachtelsätze und keine Klammern. Die Stimme
  spricht Satz für Satz; ein Satz über etwa 25 Wörter klingt angestrengt.
- **Gesprächston:** Du-Ansprache, ganze Sätze, gern „ich“ und „wir“. Kein Nominalstil, keine
  Floskeln wie „gerne“ oder „selbstverständlich“, keine Begeisterung auf Vorrat.
- **Statt Aufzählung verbinden:** „Zwei Dinge fehlen noch: die Hooks und ein Neustart.“ Bei drei
  oder mehr Punkten nur die wichtigsten nennen und auf den Text verweisen.
- **Benennen statt zeigen:** kein Markdown, kein Code, keine Pfade, URLs, Hashes oder Befehle.
  Statt `claude_sprechen.py` heißt es „das Hook-Skript“, statt eines Befehls „der Befehl steht
  im Text“.
- **Alles ausschreiben, was die Stimme sonst falsch liest:** Zahlen und Daten wie gesprochen
  („zwei Komma sechs Sekunden“, „am sechsundzwanzigsten November“), Abkürzungen auflösen („zum
  Beispiel“ statt „z. B.“), keine Zeichen wie %, €, →, / oder &. Englische Fachbegriffe dürfen
  bleiben, Bezeichner aus dem Code nicht.

### Was sonst gilt

- **Kommt die Eingabe per Diktat**, sind Wörter, die keinen Sinn ergeben, vermutlich Hörfehler
  der Spracherkennung: nach dem Zusammenhang deuten, bei echter Mehrdeutigkeit kurz nachfragen
  statt raten.
- **Warnungen gehören in die Marke.** Steht im geschriebenen Teil eine Warnung vor einer nicht
  umkehrbaren Aktion, kommt sie auch in die gesprochene Fassung, notfalls auf Kosten der Kürze.
- **Kein `-->` im Text**, das beendet die Marke vorzeitig.
- **Nur am Ende der fertigen Antwort.** Arbeitet Claude zwischendurch länger mit Werkzeugen,
  bekommen Zwischenmeldungen keine Marke.

Bestätige das Einschalten mit genau dieser Antwort, ohne weitere Erklärung:

```
Der Gesprächsmodus ist an.

<!-- sprechen: Der Gesprächsmodus ist an. -->
```

Voraussetzung sind die beiden Hooks in den Einstellungen (Stop und UserPromptSubmit).
Einrichtung und Grenzen: `integrationen/claude-code/README.md` im Hörbuch-Generator.
