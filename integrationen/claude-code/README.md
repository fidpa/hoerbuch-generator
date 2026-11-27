# Gesprächsmodus für Claude Code

Mit `/sprechen` liest Claude Code jede Antwort in einer kurzen, für das Ohr geschriebenen
Fassung vor, lokal mit den Stimmen dieses Repos und ohne Cloud. Die geschriebene Antwort mit
Tabellen, Code und Pfaden bleibt im Fenster stehen. Eine neue Eingabe bricht die Ausgabe ab.

## So arbeiten die Teile zusammen

| Teil | Datei | Aufgabe |
|---|---|---|
| Sprechdienst | `sprechen.sh`, `werkzeuge/sprechdienst.py` | hält das Modell geladen, spricht Satz für Satz, Stopp je Sitzung |
| Hook-Skript | `claude_sprechen.py` | Stop: Sprechmarke aus der Antwort an `sprechen.sh`, auf Wunsch über ssh und an das zuletzt benutzte Gerät; UserPromptSubmit: `--stopp`; SessionStart (optional): Modus von Anfang an |
| Command | `sprechen.md` | `/sprechen` schaltet den Modus ein, `/sprechen datei` auf Audiodateien in der Antwort um, `/sprechen aus` wieder aus |

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

**Optional: immer an.** Ein dritter Hook lässt jede Sitzung im Gesprächsmodus beginnen, ohne
`/sprechen`; `/sprechen aus` schaltet ihn für die Sitzung ab:

```json
"SessionStart": [{"hooks": [{"type": "command",
  "command": "<REPO>/.venv/bin/python <REPO>/integrationen/claude-code/claude_sprechen.py start"}]}]
```

Er gibt den Abschnitt „Modus einschalten“ aus `sprechen.md` als Kontext aus, rund 1 000 Tokens
je Sitzung. SessionStart feuert auch beim Fortsetzen einer Sitzung (`--resume`, `--continue`),
nach `/clear` und nach dem Kompaktieren; ein vorher abgeschalteter Modus ist danach wieder an.
Es spricht dann jede Sitzung, auch Sitzungen, die im Hintergrund arbeiten; der Hook erkennt sie
nicht.

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
| Audiodatei in der Antwort statt Ton, etwa am Handy | `/sprechen datei`; zurück mit `/sprechen` |
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
| `SPRECHEN_ENTFERNT`, `SPRECHEN_ENTFERNT_REPO`, `SPRECHEN_PLAYER` | leer | Fernbetrieb, siehe unten |
| `SPRECHEN_GERAETE`, `SPRECHEN_LEERLAUF` | leer, `1800` | Gerätewahl, siehe unten |

**Lautstärke:** Die Stimmen liegen bei rund −21 LUFS, Musik bei Streamingdiensten bei rund
−14 LUFS. Mit 8 dB lag `marketing.wav` bei −14,0 LUFS (gemessen am 26.11.2026). Geht die Stimme
neben lauter Musik trotzdem unter, `SPRECHEN_LAUTER` auf 12 setzen; darüber klingt sie zunehmend
gepresst, weil der Limiter mehr abfangen muss.

## Auf einem Gerät ohne MLX (Fernbetrieb)

Auf Linux oder einem Mac ohne Apple Silicon rechnet ein Mac im Netz, und das Gerät, an dem du
arbeitest, spielt den Ton selbst ab. Der Weg läuft über ssh, ein offener Port ist nicht nötig.

```
dieses Gerät: Stop-Hook ──ssh──► Mac: sprechen.sh --liefern ──► Sprechdienst
              Player    ◄── Ton Satz für Satz, 16-Bit-PCM, 24 kHz mono (48 KB/s)
```

**Voraussetzungen auf dem Mac:** dieses Repo mit `./einrichten.sh`, Anmeldung per ssh-Schlüssel
ohne Rückfrage (die Hooks nutzen `BatchMode=yes`). Ob MLX in einer ssh-Sitzung die GPU bekommt:

```bash
ssh <MAC> '<REPO>/.venv/bin/python -c "import mlx.core as mx; print(mx.default_device())"'
```

Erwartet wird `Device(gpu, 0)`.

**Auf diesem Gerät:**

1. Dieses Repo klonen, nur für das Hook-Skript; `./einrichten.sh` ist hier nicht nötig. Das
   Skript braucht Python ab 3.9 und nur die Standardbibliothek.
2. Einen Player bereithalten. Das Skript nimmt den ersten vorhandenen von `paplay`, `pw-play`,
   `aplay` und `ffplay`, oder den Befehl aus `SPRECHEN_PLAYER`, der 16-Bit-PCM mit 24 kHz mono
   von stdin spielt. `ffplay` braucht FFmpeg 5.1 oder neuer (Option `-ch_layout`). Geprüft
   sind `paplay` unter Linux und `ffplay` 9.1 unter macOS; `pw-play` und `aplay` sind
   ungeprüft (Stand 27.11.2026).
3. Die Hooks wie oben eintragen, mit `python3` statt `.venv/bin/python` und den Variablen davor:

   ```json
   "command": "SPRECHEN_ENTFERNT=<MAC> python3 <REPO>/integrationen/claude-code/claude_sprechen.py stop"
   ```

   Ebenso für `prompt`. Liegt das Repo auf dem Mac an einem anderen Ort als unter demselben
   Pfad in `~`, gibt `SPRECHEN_ENTFERNT_REPO` ihn an.
4. Optional in `~/.ssh/config` für den Mac `ControlMaster auto`, `ControlPath` und
   `ControlPersist 10m`: Jeder Aufruf nutzt dann die offene Verbindung und spart den Aufbau.

| Variable | Bedeutung |
|---|---|
| `SPRECHEN_ENTFERNT` | ssh-Ziel des Macs, etwa ein Host aus `~/.ssh/config`; ohne sie rechnet dieses Gerät selbst |
| `SPRECHEN_ENTFERNT_REPO` | Ort des Repos auf dem Mac (Standard: derselbe Pfad unter `~` wie hier) |
| `SPRECHEN_PLAYER` | eigener Player-Befehl, etwa `aplay -q -t raw -f S16_LE -r 24000 -c 1` |

**So verhält es sich:** Der Stop-Hook übergibt die Wiedergabe einem Hintergrundprozess und
kehrt sofort zurück. Mehrere Sitzungen dieses Geräts sprechen nacheinander, eine Sperre unter
`$XDG_RUNTIME_DIR/hoerbuch-generator/` (sonst `~/.cache/hoerbuch-generator/`) hält sie in der
Reihe. Eine Eingabe beendet die Wiedergabe der eigenen Sitzung hier sofort und stoppt den
Auftrag auf dem Mac. Läuft für die Sitzung nichts, baut die Eingabe keine Verbindung auf. Fehler der Wiedergabe stehen in `wiedergabe.log` im selben Ordner. Der Mac
muss wach und erreichbar sein; ist er es nicht, bleibt es still, und die Sitzung läuft weiter.

## Ton auf dem Gerät, an dem du gerade arbeitest

Läuft Claude Code auf einem Server oder einem anderen Mac und du arbeitest von einem Notebook
aus (Terminal per ssh, eine Oberfläche wie T3 Code), gehört der Ton auf das Notebook.
`SPRECHEN_GERAETE` nennt die Geräte, die ihn abspielen dürfen, als ssh-Ziele; `hier` steht für
das Gerät, auf dem Claude Code läuft:

```json
"command": "SPRECHEN_GERAETE='hier macbook' <REPO>/.venv/bin/python <REPO>/integrationen/claude-code/claude_sprechen.py stop"
```

Vor jeder Antwort fragt der Hook die Geräte parallel, wie lange die letzte Eingabe an Tastatur
oder Maus zurückliegt (macOS: `ioreg`, Linux mit GNOME: Mutter IdleMonitor über D-Bus), und
spielt auf dem zuletzt benutzten. Sind alle länger als `SPRECHEN_LEERLAUF` Sekunden unbenutzt
(Standard 1800), bleibt die Antwort stumm: Dann wird woanders gearbeitet, etwa am Handy, und
kein Rechner soll in einen leeren Raum sprechen. Ein schlafendes Gerät antwortet nicht und
verzögert die Antwort um höchstens sechs Sekunden.

| Fall | Einstellung |
|---|---|
| Claude Code auf dem Mac mit MLX, Ton auch auf einem Notebook | `SPRECHEN_GERAETE='hier macbook'` |
| Claude Code auf einem Server ohne Ton, ein Mac rechnet | `SPRECHEN_ENTFERNT=<MAC>` und `SPRECHEN_GERAETE='macbook <MAC>'` |

Auf dem gewählten Gerät spielt `paplay` oder `ffplay` (Homebrew), aufgerufen über ssh; ein
Repo-Klon ist dort nicht nötig. Fällt die Wahl auf `hier` und rechnet dieses Gerät selbst,
spielt der Dienst wie ohne Gerätewahl. Die Wahl steht mit den gemessenen Zeiten in
`wiedergabe.log` (Ordner wie oben). Die Eingabe der eigenen Sitzung bricht die Wiedergabe auch
auf dem anderen Gerät ab; was der Player dort schon gepuffert hat, klingt noch aus.

## Am Handy: Datei statt Ton (`/sprechen datei`)

Ein Handy erreicht der Hook nicht, es hat kein ssh. Manche Oberflächen spielen aber eine
Audiodatei ab, die in der Antwort eingebettet ist; T3 Code zeigt eine Markdown-Einbettung auf
eigener Zeile als Player, auf dem iPhone seit Version 2.2.0 (28.10.2026), gestartet per Tippen.
`/sprechen datei` schaltet dafür um: Claude ruft vor jeder Antwort `sprechen.sh --datei` auf,
das die gesprochene Fassung als MP3 unter `~/Library/Caches/hoerbuch-generator/dateien/` ablegt
und den Pfad ausgibt, und bettet die Datei am Ende der Antwort ein. Eine Sprechmarke gibt es in
diesem Modus nicht, der Stop-Hook bleibt still. Dateien älter als sieben Tage löscht der nächste
Aufruf; ältere Antworten zeigen dann keinen Player mehr.

Der Modus braucht den Sprechdienst auf dem Gerät, auf dem Claude Code läuft (Mac mit Apple
Silicon). In einer Sandbox braucht `sprechen.sh` eine Ausnahme, weil Metal dort fehlt; der feste
Ablageordner sorgt dafür, dass der Aufruf mit Ausnahme nirgendwo sonst schreibt. Gemessen am
27.11.2026: rund drei Sekunden für zwei Sätze bei geladenem Modell.

## Fehlerbilder

| Fehlerbild | Ursache | Lösung |
|---|---|---|
| Kein Ton, `./sprechen.sh --status` meldet `"zustand": "aus"` | Hooks fehlen oder greifen nicht | Hook-Einträge prüfen; Protokoll `~/Library/Logs/hoerbuch-generator/sprechdienst.log` |
| `Modell nicht ladbar: … No Metal device available` | Der Dienst wurde aus einer Sandbox gestartet | `./sprechen.sh --beenden` im Terminal; den nächsten Start übernimmt der Hook |
| Kein Ton, obwohl der Dienst läuft | Die Antwort trägt keine Sprechmarke | `/sprechen` erneut aufrufen |
| Ausgabe bricht mitten im Satz ab | Neue Eingabe oder Bericht eines Hintergrund-Agenten in derselben Sitzung | gewollt bei neuer Eingabe; bei Agenten-Berichten nicht abschaltbar |
| Die Sprechmarke steht sichtbar im Fenster | Die Oberfläche blendet HTML-Kommentare nicht aus | nur Darstellung |
| Fernbetrieb: kein Ton | Mac nicht erreichbar, ssh fragt nach einem Passwort, oder kein Player gefunden | `wiedergabe.log` lesen; `echo "Das ist ein Satz vom Mac." \| ssh <MAC> '<REPO>/sprechen.sh --liefern -' \| <Player>` von Hand |
| Gerätewahl: Ton auf dem falschen Gerät oder keiner | Leerlaufzeiten anders als gedacht, Gerät antwortet nicht, oder alle über `SPRECHEN_LEERLAUF` | Zeile `Gerätewahl:` in `wiedergabe.log` lesen |
| Gerätewahl: Gerät gewählt, aber nichts zu hören | Der Player nimmt die Standardausgabe des Geräts, etwa einen Monitor statt der eingebauten Lautsprecher | Ausgabe am Gerät umstellen (macOS: Systemeinstellungen > Ton > Ausgabe) |
| `/sprechen datei`: kein Player in der Antwort | Die Einbettung steht nicht allein auf ihrer Zeile, oder die Oberfläche spielt keine Einbettungen ab | Zeile prüfen; ältere T3-Code-Versionen auf dem iPhone zeigen „Image unavailable“ |

## Tests

```bash
.venv/bin/python -m unittest tests.test_claude_code -v
```

Die Tests starten den Dienst nicht. Sie ersetzen `sprechen.sh` durch ein Skript, das seine
Argumente mitschreibt, und laufen auch ohne MLX.
