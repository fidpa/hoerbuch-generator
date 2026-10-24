"""
atem.py - Atemgeraeusche erkennen und absenken (fuer qwen.py)

Qwen3-TTS atmet hoerbar ein, vor allem am Anfang jedes Textstuecks. Dieses Modul
findet die Atemzuege mit dem Modell Respiro-en und senkt sie um ATTENUATION_DB ab.
Nichts wird herausgeschnitten, die Laenge bleibt gleich; weiche Cosinus-Rampen
innerhalb des Atemzugs vermeiden Knackser.

Warum so: Ein Pegel-Gate (alles Leise absenken) traf im Hoertest auch leise
Wortenden, und Schneiden machte die Uebergaenge abgehackt. Eine Referenzstimme mit
stummgeschaltetem Atem verschlechterte den Klon hoerbar (Tests vom 24.10.2026).

Modell: Respiro-en (Dong Yang, MIT, https://huggingface.co/DongYANG/Respiro-en),
Netz und Merkmale nach breath-removal (Lukasz Liniewicz, MIT). Laeuft auf der CPU;
die Gewichte (35 MB) laedt der erste Aufruf nach ~/.cache/huggingface.

Usage (fuer vorhandene Dateien):
    .venv/bin/python werkzeuge/atem.py EIN.wav|.mp3 AUS.wav [--db 18]
"""

import argparse
import logging
import sys

import librosa
import numpy as np
import soundfile as sf
import torch
import torch.nn as nn
from torch.nn import functional as nnf
from torchaudio.models import Conformer

ATTENUATION_DB = 18.0
THRESHOLD = 0.064     # Schwelle aus dem Paper zu Respiro-en
MIN_FRAMES = 20       # kuerzester Atemzug: 20 Frames zu 10 ms
FADE = 0.03           # Rampe am Anfang und Ende eines Atemzugs (s)
WINDOW = 30.0         # lange Dateien in Fenstern dieser Laenge (s) ...
OVERLAP = 2.0         # ... mit dieser Ueberlappung erkennen

log = logging.getLogger("atem")
_net = None


def _zcr(wav: np.ndarray, win: int, hop: int) -> np.ndarray:
    wav = np.pad(wav, (win // 2, win // 2))
    n = 1 + (len(wav) - win) // hop
    return np.array([np.sum(np.abs(np.sign(wav[i * hop + 1:i * hop + win]) - np.sign(wav[i * hop:i * hop + win - 1])))
                     * 0.5 / win for i in range(n)], dtype=np.float32)


def _features(wav: np.ndarray, sr: int = 16000) -> tuple[torch.Tensor, torch.Tensor]:
    mel = librosa.power_to_db(librosa.feature.melspectrogram(
        y=wav, sr=sr, n_fft=int(sr * 0.025), hop_length=int(sr * 0.01), n_mels=128), ref=np.max)
    zcr = torch.tensor(_zcr(wav, int(sr * 0.025), int(sr * 0.01))).unsqueeze(0)
    mel = torch.tensor(mel).unsqueeze(0)
    zcr = zcr.unsqueeze(1).expand(-1, 128, -1)
    vms = torch.var(mel, dim=1).unsqueeze(1).expand(-1, mel.shape[1], -1)
    return torch.stack((mel, vms, zcr), dim=1), torch.tensor([zcr.shape[-1]])


class _Down(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.conv1 = nn.Sequential(nn.Conv2d(3, 1, 3, stride=2), nn.ReLU())
        self.conv2 = nn.Sequential(nn.Conv2d(1, 1, 3, stride=2), nn.ReLU())

    def forward(self, x, length):
        for conv in (self.conv1, self.conv2):
            pad = 1 - x.shape[-1] % 2
            x = conv(nnf.pad(x, (0, pad, 0, 0)))
            length = (length - 3 + pad) // 2 + 1
        return x, length


class _Up(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.deconv = nn.Sequential(nn.ConvTranspose1d(128, 128, 3, stride=2), nn.ReLU(),
                                    nn.ConvTranspose1d(128, 128, 3, stride=2), nn.ReLU())

    def forward(self, x):
        return self.deconv(x)


class _DetectionNet(nn.Module):
    """Respiro-en: Conformer und BiLSTM, eine Atem-Wahrscheinlichkeit je 10 ms."""

    def __init__(self) -> None:
        super().__init__()
        self.downsampling, self.upsampling = _Down(), _Up()
        self.linear, self.dropout = nn.Linear(31, 128), nn.Dropout(0.1)
        self.conformer = Conformer(input_dim=128, num_heads=4, ffn_dim=256, num_layers=8,
                                   depthwise_conv_kernel_size=31, dropout=0.1)
        self.lstm = nn.LSTM(128, 256, bidirectional=True, batch_first=True)
        self.fc, self.sigmoid = nn.Linear(512, 1), nn.Sigmoid()

    def forward(self, x, length):
        seq = x.shape[-1]
        x, length = self.downsampling(x, length)
        x = self.dropout(self.linear(x.squeeze(1).transpose(1, 2).contiguous()))
        x = self.conformer(x, length)[0].transpose(1, 2).contiguous()
        x = self.upsampling(x).transpose(1, 2).contiguous()
        return self.sigmoid(self.fc(self.lstm(x)[0]).squeeze(-1))[:, :seq]


def _model() -> _DetectionNet:
    global _net
    if _net is None:
        from huggingface_hub import hf_hub_download
        path = hf_hub_download("DongYANG/Respiro-en", "respiro-en.pt")
        _net = _DetectionNet()
        # weights_only: laedt nur Tensoren, fuehrt keinen Code aus der Datei aus
        _net.load_state_dict(torch.load(path, map_location="cpu", weights_only=True)["model"])
        _net.eval()
    return _net


def _detect_window(y16: np.ndarray) -> list[tuple[float, float]]:
    feat, length = _features(y16)
    with torch.no_grad():
        prob = _model()(feat, length)[0].numpy()
    idx = np.flatnonzero(prob > THRESHOLD)
    if not len(idx):
        return []
    runs = np.split(idx, np.flatnonzero(np.diff(idx) != 1) + 1)
    return [(r[0] * 0.01, (r[-1] + 1) * 0.01) for r in runs if len(r) > MIN_FRAMES]


def detect(y: np.ndarray, sr: int) -> list[tuple[float, float]]:
    """Atemzuege als (Start, Ende) in Sekunden."""
    y16 = librosa.resample(y, orig_sr=sr, target_sr=16000) if sr != 16000 else y
    step, win = int((WINDOW - OVERLAP) * 16000), int(WINDOW * 16000)
    segs: list[tuple[float, float]] = []
    for start in range(0, max(1, len(y16) - int(OVERLAP * 16000)), step):
        offset = start / 16000
        segs += [(offset + a, offset + b) for a, b in _detect_window(y16[start:start + win])]
    segs.sort()
    merged: list[tuple[float, float]] = []
    for a, b in segs:  # Treffer aus ueberlappenden Fenstern zusammenfassen
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def attenuate(y: np.ndarray, sr: int, db: float = ATTENUATION_DB) -> tuple[np.ndarray, int]:
    """Atemzuege um db absenken; liefert das Audio und die Zahl der Atemzuege."""
    segs = detect(y, sr)
    gain = np.ones(len(y), dtype=np.float32)
    target = 10 ** (-db / 20)
    fade = int(FADE * sr)
    ramp = (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, fade))).astype(np.float32)  # 1 -> 0
    for s, e in segs:
        a, b = int(s * sr), min(len(y), int(e * sr))
        if b - a < 2 * fade:
            continue
        gain[a:a + fade] = np.minimum(gain[a:a + fade], target + (1 - target) * ramp)
        gain[a + fade:b - fade] = target
        gain[b - fade:b] = np.minimum(gain[b - fade:b], target + (1 - target) * ramp[::-1])
    return y * gain, len(segs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Atemgeraeusche absenken (Respiro-en)")
    parser.add_argument("input", help="Audiodatei (WAV oder MP3)")
    parser.add_argument("output", help="Ausgabe-WAV")
    parser.add_argument("--db", type=float, default=ATTENUATION_DB,
                        help=f"Absenkung in dB (Default {ATTENUATION_DB:.0f})")
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(message)s")
    log.setLevel(logging.INFO)

    y, sr = librosa.load(args.input, sr=None, mono=True)
    out, n = attenuate(y, sr, args.db)
    sf.write(args.output, out, sr, subtype="PCM_16")
    log.info("%s: %d Atemzüge um %.0f dB abgesenkt", args.output, n, args.db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
