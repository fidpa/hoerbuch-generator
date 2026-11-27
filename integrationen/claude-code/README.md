# Gesprächsmodus für Claude Code

Mit `/sprechen` liest Claude Code jede Antwort in einer kurzen, für das Ohr geschriebenen
Fassung vor, lokal mit den Stimmen dieses Repos und ohne Cloud. Die geschriebene Antwort mit
Tabellen, Code und Pfaden bleibt im Fenster stehen. Eine neue Eingabe lässt die laufende Antwort
zu Ende sprechen; „Psst“ als einzige Eingabe bricht sie ab.

## So arbeiten die Teile zusammen

| Teil | Datei | Aufgabe |
|---|---|---|
| Sprechdienst | `sprechen.sh`, `werkzeuge/sprechdienst.py` | hält das Modell geladen, spricht Satz für Satz, Stopp je Sitzung |
| Hook-Skript | `claude_sprechen.py` | Stop: Sprechmarke aus der Antwort an `sprechen.sh`, auf Wunsch über ssh und an das zuletzt benutzte Gerät; UserPromptSubmit: `--stopp` bei einem Stoppwort; SessionStart (optional): Modus von Anfang an; Notification (optional): Ansage, wenn Claude auf eine Freigabe wartet; `pruefen`: Einrichtung prüfen |
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
nicht. Startet ein Dienst Claude ohne Nutzer und lädt dabei die Einstellungen des Nutzers (ein Bot
über das Agent SDK mit `settingSources: ["user", …]`, ein zeitgesteuertes `claude -p` ohne
`--setting-sources`), setzt er `SPRECHEN_AUS=1`. Dann tun alle Hooks dieses Skripts nichts, etwa
in einer systemd-Unit mit `Environment=SPRECHEN_AUS=1`. Claude Code reicht seine Umgebung an die
Hooks weiter ([Hook-Doku](https://code.claude.com/docs/en/hooks.md#common-input-fields)). Setzt ein
Bot im Agent SDK die Option `env` selbst, ersetzt sie die Umgebung ganz; dann muss `SPRECHEN_AUS`
dort stehen. Lädt der Dienst die Einstellungen des Nutzers gar nicht (`--setting-sources project`),
erreicht ihn kein Hook des Nutzers, er verliert dann aber auch dessen Berechtigungen und MCP-Server.

**Optional: Ansage, wenn Claude wartet.** Wartet Claude auf eine Freigabe, gibt es keine Antwort
und damit nichts zu sprechen. Ein Notification-Hook sagt dann „Claude wartet auf deine
Freigabe.“, bei einem Formular eines MCP-Servers „Claude wartet auf deine Eingabe.“:

```json
"Notification": [{"matcher": "permission_prompt|elicitation_dialog|elicitation_url_dialog",
  "hooks": [{"type": "command", "async": true,
    "command": "<REPO>/.venv/bin/python <REPO>/integrationen/claude-code/claude_sprechen.py notification"}]}]
```

Im Fernbetrieb und mit Gerätewahl (unten) stehen dieselben Variablen davor wie beim Stop-Hook.
Claude Code löst ihn aus, wenn eine Freigabe rund sechs Sekunden wartet; im Terminal schiebt jede
Taste die Frist auf, in Oberflächen auf Basis des Agent SDK nicht
([Hook-Doku](https://code.claude.com/docs/en/hooks.md#notification)). Der Hook spricht nur, wenn
die Sitzung im Gesprächsmodus ist. Das liest er aus ihrem Transkript: Es zählt der letzte Aufruf
von `/sprechen` oder der Kontext des SessionStart-Hooks. Nach `/sprechen aus` und `/sprechen
datei` bleibt er still. Grenzen: Das Format des Transkripts ist nicht dokumentiert, und ändert es
sich, bleibt die Ansage stumm. Den Hinweis nach 60 Sekunden ohne Eingabe (`idle_prompt`) spricht
der Hook nicht, er folgte sonst auf jede gesprochene Antwort. Eine Rückfrage von Claude selbst
(Werkzeug `AskUserQuestion`) kam in T3 Code als `permission_prompt` mit der Meldung „Claude needs
your permission to use AskUserQuestion“, sechs Sekunden nach der Frage (gemessen am 27.11.2026);
dafür sagt der Hook „Claude hat eine Frage an dich.“ Im Terminal ist das ungeprüft.

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
| Ausgabe abbrechen | nur ein Stoppwort eingeben: „Psst“, „Pst“, „Still“ oder „Ruhe“, Satzzeichen egal; Claude bekommt es nicht. Oder `./sprechen.sh --stopp` |
| Weiterfragen | einfach eingeben: Die laufende Antwort spricht zu Ende, die nächste folgt danach |
| Dienst beenden | `./sprechen.sh --beenden`; sonst endet er 20 Minuten nach dem letzten Auftrag (Eingaben ohne gesprochene Antwort zählen nicht) |

Der Modus gilt je Sitzung.

**Mehrere Sitzungen:** Antworten aus verschiedenen Sitzungen spricht der Dienst nacheinander.
Ein Stoppwort bricht nur die Ausgabe der eigenen Sitzung ab. Wechselt die sprechende Sitzung,
beginnt die Antwort mit dem Namen des Projektordners, etwa „Aus Notizen.“ für einen Ordner
`notizen`.

**Warum „Stopp“ kein Stoppwort ist:** Mit „Stopp“ hält man oft Claude selbst an, etwa in einer
Oberfläche, die Eingaben während einer laufenden Antwort weiterreicht. Das Wort soll dann bei
Claude ankommen und nicht vom Hook abgefangen werden. Bis v0.6.1 brach jede neue Eingabe die
Ausgabe ab; `SPRECHEN_UNTERBRECHEN=1` stellt das wieder her.

## Einstellungen

Über Umgebungsvariablen, etwa vor dem Befehl im Hook (`SPRECHEN_LAUTER=12 <REPO>/.venv/bin/python …`)
oder unter `env` in den Einstellungen von Claude Code:

| Variable | Standard | Bedeutung |
|---|---|---|
| `SPRECHEN_STIMME` | `marketing` | Stimme aus `stimmen/`, ruhiger Gesprächston |
| `SPRECHEN_TEMPO` | `1.1` | Sprechtempo, 0.5 bis 2.0 |
| `SPRECHEN_LAUTER` | `8` | Anhebung in dB, 0 bis 15, mit Limiter |
| `SPRECHEN_UNTERBRECHEN` | leer | `1`: jede neue Eingabe bricht die laufende Ausgabe ab, wie bis v0.6.1 |
| `SPRECHEN_AUS` | leer | `1`: alle Hooks tun nichts, für Dienste ohne Nutzer: kein Modus von Anfang an, kein Ton, kein Stoppwort |
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
   `aplay`, `ffmpeg` (nur unter macOS, Ausgabe über AudioToolbox) und `ffplay`, oder den
   Befehl aus `SPRECHEN_PLAYER`, der 16-Bit-PCM mit 24 kHz mono von stdin spielt. `ffplay`
   braucht FFmpeg 5.1 oder neuer (Option `-ch_layout`) und verwirft unter macOS die ersten
   Sekunden eines Stroms, der erst nach und nach ankommt; deshalb dort zuerst `ffmpeg`. Geprüft
   sind `paplay` unter Linux und `ffmpeg` 9.1 unter macOS; `pw-play` und `aplay` sind
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
Reihe. Ein Stoppwort beendet die Wiedergabe der eigenen Sitzung hier sofort und stoppt den
Auftrag auf dem Mac. Läuft für die Sitzung nichts, baut es keine Verbindung auf. Fehler der Wiedergabe stehen in `wiedergabe.log` im selben Ordner, jede Zeile mit Datum und Uhrzeit, dazu Auftrag, Beginn und Ende jeder Wiedergabe. Der Mac
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

Auf dem gewählten Gerät spielt `paplay`, unter macOS `ffmpeg` aus Homebrew über AudioToolbox
(sonst `ffplay`), aufgerufen über ssh; ein Repo-Klon ist dort nicht nötig. Fällt die Wahl auf
`hier` und rechnet dieses Gerät selbst, spielt der Dienst wie ohne Gerätewahl. Die Wahl steht
mit den gemessenen Zeiten in `wiedergabe.log` (Ordner wie oben). Ein Stoppwort der eigenen
Sitzung bricht die Wiedergabe auch auf dem anderen Gerät ab; was der Player dort schon
gepuffert hat, klingt noch aus, bei `ffmpeg` unter macOS rund drei Sekunden, bei `ffplay` rund
fünf (gemessen am 27.11.2026).

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

## Einrichtung prüfen

```bash
python3 <REPO>/integrationen/claude-code/claude_sprechen.py pruefen
```

Auf jedem Gerät im Terminal, nicht aus einer Sandbox (dort scheitern ssh und der Socket des
Dienstes). Der Befehl liest die Hook-Einträge aus `~/.claude/settings.json` und rechnet mit den
Variablen, die der Stop-Hook sieht: die Umgebung des Terminals, darüber die `SPRECHEN_*`-Variablen
unter `env`, darüber die vor dem Befehl des Stop-Hooks. Je Zeile meldet er:

| Bereich | Inhalt |
|---|---|
| `Hooks` | welche Ereignisse dieses Skript aufrufen, Stop und UserPromptSubmit sind Pflicht; dazu Variablen, die zwischen den Hooks abweichen (siehe unten) |
| `Variable` | die Einstellungen, mit denen der Stop-Hook läuft |
| `Version` | Stand dieses Klons (`git describe`) |
| `Rechnen` | mit `SPRECHEN_ENTFERNT`: ob ssh antwortet, Stand des Klons dort und Zustand des Dienstes; sonst der Dienst hier. `aus` ist kein Fehler, der erste Auftrag startet ihn |
| `Player` | im Fernbetrieb der Player hier |
| `Gerät` | je Gerät aus `SPRECHEN_GERAETE`: Leerlaufzeit und Player, oder dass ssh nicht antwortet. Ein schlafendes Gerät ist nur ein Hinweis, solange ein anderes antwortet |

Verglichen wird je Variable zwischen den Hooks, die sie nutzen: `SPRECHEN_ENTFERNT` und
`SPRECHEN_ENTFERNT_REPO` zwischen Stop, UserPromptSubmit und Notification (der Prompt-Hook braucht
sie für den Stopp auf dem Mac), `SPRECHEN_GERAETE` und `SPRECHEN_LEERLAUF` zwischen Stop und
Notification. Weichen sie ab, ist das ein Fehler. Weichen Stimme, Tempo oder Lautstärke zwischen
Stop und Notification ab, ist das nur ein Hinweis.

Fehlt etwas, steht `FEHLER:` in der Zeile, und der Befehl endet mit Exit 1; `Hinweis:` ändert den
Exit-Code nicht. Grenze: Hooks in den Einstellungen eines Projekts (`.claude/settings.json`) und in
`settings.local.json` liest der Befehl nicht; stehen sie nur dort, meldet er sie als fehlend.

## Fehlerbilder

| Fehlerbild | Ursache | Lösung |
|---|---|---|
| Keine Ansage, wenn Claude auf eine Freigabe wartet | Notification-Hook fehlt, die Sitzung ist nicht im Gesprächsmodus, oder die Freigabe kam vor Ablauf von rund sechs Sekunden | `pruefen`; den Grund nennt die Zeile `Hinweis … ohne Ton` auf stderr des Hooks. Im Fernbetrieb braucht der Hook dieselben Variablen wie der Stop-Hook |
| Ein Bot oder ein zeitgesteuerter Lauf spricht, oder seine Antworten enden mit `<!-- sprechen: … -->` | Der Dienst lädt die Einstellungen des Nutzers, und der SessionStart-Hook schaltet den Modus ein | `SPRECHEN_AUS=1` in der Umgebung des Dienstes, etwa `Environment=` in seiner systemd-Unit; danach den Dienst neu starten |
| Kein Ton, `./sprechen.sh --status` meldet `"zustand": "aus"` | Hooks fehlen oder greifen nicht | Hook-Einträge prüfen; Protokoll `~/Library/Logs/hoerbuch-generator/sprechdienst.log` |
| `Modell nicht ladbar: … No Metal device available` | Der Dienst wurde aus einer Sandbox gestartet | `./sprechen.sh --beenden` im Terminal; den nächsten Start übernimmt der Hook |
| Kein Ton, obwohl der Dienst läuft | Die Antwort trägt keine Sprechmarke | `/sprechen` erneut aufrufen |
| Ausgabe bricht mitten im Satz ab | Stoppwort, oder `SPRECHEN_UNTERBRECHEN=1` und eine neue Eingabe oder der Bericht eines Hintergrund-Agenten in derselben Sitzung | gewollt beim Stoppwort; sonst `SPRECHEN_UNTERBRECHEN` entfernen |
| Die Stimme hängt dem Text hinterher | Mehrere Eingaben kurz hintereinander, die Antworten stehen in der Reihe | „Psst“ leert die Reihe der Sitzung |
| Die Sprechmarke steht sichtbar im Fenster | Die Oberfläche blendet HTML-Kommentare nicht aus | nur Darstellung |
| Fernbetrieb: kein Ton | Mac nicht erreichbar, ssh fragt nach einem Passwort, oder kein Player gefunden | `wiedergabe.log` lesen; `echo "Das ist ein Satz vom Mac." \| ssh <MAC> '<REPO>/sprechen.sh --liefern -' \| <Player>` von Hand |
| Gerätewahl: Ton auf dem falschen Gerät oder keiner | Leerlaufzeiten anders als gedacht, Gerät antwortet nicht, oder alle über `SPRECHEN_LEERLAUF` | Zeile `Gerätewahl:` in `wiedergabe.log` lesen |
| `wiedergabe.log`: `Wiedergabe auf … abgebrochen (Obergrenze)`, `Player ssh endete mit 255` oder `sprechen.sh auf … nach dem Player nicht, beendet` | Das Gerät schlief während der Wiedergabe ein, oder die Verbindung brach ab. ssh gibt nach etwa 15 s auf, sonst endet die Wiedergabe spätestens an der Obergrenze (zwei Minuten plus eine Viertelsekunde je Zeichen) | nichts zu tun, die nächste Antwort spielt wieder; tritt es oft auf, Schlafeinstellungen des Geräts prüfen |
| Gerätewahl: Gerät gewählt, aber nichts zu hören | Der Player nimmt die Standardausgabe des Geräts, etwa einen Monitor statt der eingebauten Lautsprecher | Ausgabe am Gerät umstellen (macOS: Systemeinstellungen > Ton > Ausgabe) |
| `/sprechen datei`: kein Player in der Antwort | Die Einbettung steht nicht allein auf ihrer Zeile, oder die Oberfläche spielt keine Einbettungen ab | Zeile prüfen; ältere T3-Code-Versionen auf dem iPhone zeigen „Image unavailable“ |

## Tests

```bash
.venv/bin/python -m unittest tests.test_claude_code -v
```

Die Tests starten den Dienst nicht. Sie ersetzen `sprechen.sh` durch ein Skript, das seine
Argumente mitschreibt, und laufen auch ohne MLX.
