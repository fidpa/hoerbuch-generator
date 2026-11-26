# Gesprächsmodus für Claude Code

Mit `/sprechen` liest Claude Code jede Antwort in einer kurzen, für das Ohr geschriebenen
Fassung vor, lokal mit den Stimmen dieses Repos und ohne Cloud. Die geschriebene Antwort mit
Tabellen, Code und Pfaden bleibt im Fenster stehen. Eine neue Eingabe bricht die Ausgabe ab.

## So arbeiten die Teile zusammen

| Teil | Datei | Aufgabe |
|---|---|---|
| Sprechdienst | `sprechen.sh`, `werkzeuge/sprechdienst.py` | hält das Modell geladen, spricht Satz für Satz, Stopp je Sitzung |
| Hook-Skript | `claude_sprechen.py` | Stop: Sprechmarke aus der Antwort an `sprechen.sh`; UserPromptSubmit: `--stopp` |
| Command | `sprechen.md` | `/sprechen` schaltet den Modus ein, `/sprechen aus` wieder aus |

Im Gesprächsmodus schreibt Claude ans Ende jeder Antwort einen HTML-Kommentar
`<!-- sprechen: … -->`. Nur dieser Text wird gesprochen. Ohne `/sprechen` gibt es keine Marke,
und die Hooks tun nichts. Die Regeln für die gesprochene Fassung (Länge, Satzbau, Zahlen
ausschreiben) stehen in `sprechen.md`.

## Voraussetzungen

- Mac mit Apple Silicon und macOS, wie für den Rest des Repos
- `./einrichten.sh` einmal ausgeführt
- Claude Code mit Hooks (Stop-Hooks bekommen den Antworttext im Feld `last_assistant_message`)

## Einrichten

**1. Dienst prüfen**, im Repo-Ordner:

```bash
./sprechen.sh --warten -v marketing -t 1.1 --lauter 8 "Der Sprechdienst funktioniert."
```

Der erste Aufruf lädt das Modell und braucht deshalb länger.

**2. Hooks eintragen** in `~/.claude/settings.json` unter `hooks`; bestehende Einträge bleiben.
`<REPO>` durch den absoluten Pfad dieses Repos ersetzen:

```json
"hooks": {
  "Stop": [{"hooks": [{"type": "command", "async": true,
    "command": "<REPO>/.venv/bin/python <REPO>/integrationen/claude-code/claude_sprechen.py stop"}]}],
  "UserPromptSubmit": [{"hooks": [{"type": "command", "timeout": 10,
    "command": "<REPO>/.venv/bin/python <REPO>/integrationen/claude-code/claude_sprechen.py prompt"}]}]
}
```

`async` beim Stop-Hook hält Claude Code nicht auf, während der Auftrag abgegeben wird.

**3. Command verlinken**, für alle Projekte oder nur für eines:

```bash
ln -s <REPO>/integrationen/claude-code/sprechen.md ~/.claude/commands/sprechen.md
ln -s <REPO>/integrationen/claude-code/sprechen.md <PROJEKT>/.claude/commands/sprechen.md
```

Ein Link statt einer Kopie: Ein `git pull` in diesem Repo bringt dann Hook-Skript und Command
auf denselben Stand. Ein laufender Dienst behält den alten Stand, bis `./sprechen.sh --beenden`
ihn beendet; den nächsten Start übernimmt der Hook.

## Benutzen

| Was | Wie |
|---|---|
| Gesprächsmodus an | `/sprechen` |
| Gesprächsmodus aus | `/sprechen aus` |
| Ausgabe abbrechen | etwas Neues eingeben, oder `./sprechen.sh --stopp` |
| Dienst beenden | `./sprechen.sh --beenden`; sonst endet er 20 Minuten nach dem letzten Auftrag (Eingaben ohne gesprochene Antwort zählen nicht) |

Der Modus gilt je Sitzung.

**Mehrere Sitzungen:** Antworten aus verschiedenen Sitzungen spricht der Dienst nacheinander.
Eine Eingabe bricht nur die Ausgabe der eigenen Sitzung ab. Wechselt die sprechende Sitzung,
beginnt die Antwort mit dem Namen des Projektordners, etwa „Aus Notizen.“ für einen Ordner
`notizen`.

## Einstellungen

Über Umgebungsvariablen, etwa vor dem Befehl im Hook (`SPRECHEN_LAUTER=12 <REPO>/.venv/bin/python …`)
oder unter `env` in den Einstellungen von Claude Code:

| Variable | Standard | Bedeutung |
|---|---|---|
| `SPRECHEN_STIMME` | `marketing` | Stimme aus `stimmen/`, ruhiger Gesprächston |
| `SPRECHEN_TEMPO` | `1.1` | Sprechtempo, 0.5 bis 2.0 |
| `SPRECHEN_LAUTER` | `8` | Anhebung in dB, 0 bis 15, mit Limiter |

**Lautstärke:** Die Stimmen liegen bei rund −21 LUFS, Musik bei Streamingdiensten bei rund
−14 LUFS. Mit 8 dB lag `marketing.wav` bei −14,0 LUFS (gemessen am 26.11.2026). Geht die Stimme
neben lauter Musik trotzdem unter, `SPRECHEN_LAUTER` auf 12 setzen; darüber klingt sie zunehmend
gepresst, weil der Limiter mehr abfangen muss.

## Fehlerbilder

| Fehlerbild | Ursache | Lösung |
|---|---|---|
| Kein Ton, `./sprechen.sh --status` meldet `"zustand": "aus"` | Hooks fehlen oder greifen nicht | Hook-Einträge prüfen; Protokoll `~/Library/Logs/hoerbuch-generator/sprechdienst.log` |
| `Modell nicht ladbar: … No Metal device available` | Der Dienst wurde aus einer Sandbox gestartet | `./sprechen.sh --beenden` im Terminal; den nächsten Start übernimmt der Hook |
| Kein Ton, obwohl der Dienst läuft | Die Antwort trägt keine Sprechmarke | `/sprechen` erneut aufrufen |
| Ausgabe bricht mitten im Satz ab | Neue Eingabe oder Bericht eines Hintergrund-Agenten in derselben Sitzung | gewollt bei neuer Eingabe; bei Agenten-Berichten nicht abschaltbar |
| Die Sprechmarke steht sichtbar im Fenster | Die Oberfläche blendet HTML-Kommentare nicht aus | nur Darstellung |

## Tests

```bash
.venv/bin/python -m unittest tests.test_claude_code -v
```

Die Tests starten den Dienst nicht. Sie ersetzen `sprechen.sh` durch ein Skript, das seine
Argumente mitschreibt, und laufen auch ohne MLX.
