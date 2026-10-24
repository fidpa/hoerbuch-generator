# Fremde Bestandteile und ihre Lizenzen

Der Generator selbst steht unter der GNU Affero General Public License 3.0 oder neuer
(siehe [LICENSE](LICENSE)). Diese Datei nennt, was von anderen stammt, und ob es im Repo
liegt oder erst bei der Einrichtung geholt wird.

## Im Repo enthalten

### Die Stimmen `erzaehler` und `dozent`

`stimmen/erzaehler.wav` und `stimmen/dozent.wav` sind künstlich erzeugt, mit dem Modell
[`mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit`](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit)
(Qwen3-TTS, Apache 2.0) aus einer Textbeschreibung. Sie bilden keine echte Person nach.
Die Beschreibungen stehen im README unter „Eigene Stimme“.

### Netz und Merkmale der Atemerkennung

`werkzeuge/atem.py` baut das Netz und die Merkmalsberechnung von breath-removal nach,
um die Gewichte von Respiro-en laden zu können.

```
breath-removal, https://github.com/lukaszliniewicz/breath-removal

MIT License

Copyright (c) 2024 Lukasz Liniewicz

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Bei der Einrichtung oder beim ersten Lauf geholt

Diese Bestandteile liegen nicht im Repo und werden nicht mit ihm weitergegeben. Es
gelten die Bedingungen der jeweiligen Quelle.

### Modelle (von Hugging Face, nach `~/.cache/huggingface/`)

| Modell | Zweck | Lizenz |
|--------|-------|--------|
| [`mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit) | Sprachausgabe mit Stimmklon | Apache 2.0 |
| [`DongYANG/Respiro-en`](https://huggingface.co/DongYANG/Respiro-en) | Atemzüge erkennen | MIT |

### Python-Pakete (aus `requirements.txt`, über pip oder uv)

| Paket | Zweck | Lizenz |
|-------|-------|--------|
| [mlx-audio](https://github.com/Blaizzy/mlx-audio) | Qwen3-TTS auf MLX | MIT |
| [MLX](https://github.com/ml-explore/mlx) | Rechnen auf dem Grafikprozessor des Macs | MIT |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | Text aus PDFs | AGPL-3.0 oder kommerziell |
| [PyTorch](https://github.com/pytorch/pytorch) | Atemerkennung | Apache 2.0, mit Bestandteilen unter BSD und weiteren freien Lizenzen |
| [torchaudio](https://github.com/pytorch/audio) | Atemerkennung | BSD |
| [librosa](https://github.com/librosa/librosa) | Merkmale für die Atemerkennung | ISC |
| [transformers](https://github.com/huggingface/transformers), huggingface-hub | Modelle laden | Apache 2.0 |
| [NumPy](https://github.com/numpy/numpy) | Audiodaten | BSD-3-Clause, mit Bestandteilen unter weiteren freien Lizenzen |
| [soundfile](https://github.com/bastibe/python-soundfile) | WAV lesen und schreiben | BSD-3-Clause |

PyMuPDF ist der Grund für die AGPL dieses Repos. Die Lizenzangaben stammen aus den
Paketdaten der getesteten Versionen (24.10.2026).

### Programme (über Homebrew)

`ffmpeg` (LGPL oder GPL, je nach Build), `pandoc` (GPL-2.0 oder neuer), optional
`tesseract` (Apache 2.0). Der Generator ruft sie als eigene Programme auf.
