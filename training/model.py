"""A small residual denoiser for Seestar stacks.

It predicts the NOISE, not the clean image. Two reasons, and the second is the
one that matters for an astrophotography tool:

* it gives Nocturne a real strength control for free —
  `result = noisy - strength * predicted_noise` — with strength 0 provably
  returning the input untouched;
* a network asked to output a finished picture can invent structure. Asked to
  output only what to REMOVE, inventing a star means predicting a negative
  blob, which the residual loss punishes directly. The recorded failure mode in
  this project is a process that looked good on a metric while quietly ruining
  every star, so the architecture should make that harder rather than rely on
  catching it later.
"""
from __future__ import annotations

import torch
import torch.nn as nn


def _block(cin: int, cout: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(cin, cout, 3, padding=1), nn.LeakyReLU(0.1, inplace=True),
        nn.Conv2d(cout, cout, 3, padding=1), nn.LeakyReLU(0.1, inplace=True),
    )


class DenoiseUNet(nn.Module):
    def __init__(self, base: int = 32, depth: int = 3, in_ch: int = 3):
        super().__init__()
        chans = [base * (2 ** i) for i in range(depth)]      # 32, 64, 128
        self.enc = nn.ModuleList()
        c_prev = in_ch
        for c in chans:
            self.enc.append(_block(c_prev, c)); c_prev = c
        self.pool = nn.MaxPool2d(2)
        self.mid = _block(chans[-1], chans[-1] * 2)
        self.ups = nn.ModuleList()
        self.dec = nn.ModuleList()
        c_prev = chans[-1] * 2
        for c in reversed(chans):
            self.ups.append(nn.ConvTranspose2d(c_prev, c, 2, stride=2))
            self.dec.append(_block(c * 2, c))
            c_prev = c
        # Zero-initialised final layer: the model starts as an EXACT identity
        # (predicted noise = 0), so epoch zero cannot damage an image and any
        # improvement is visibly earned rather than inherited from luck.
        self.out = nn.Conv2d(chans[0], in_ch, 1)
        nn.init.zeros_(self.out.weight); nn.init.zeros_(self.out.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        skips = []
        h = x
        for enc in self.enc:
            h = enc(h); skips.append(h); h = self.pool(h)
        h = self.mid(h)
        for up, dec, skip in zip(self.ups, self.dec, reversed(skips)):
            h = up(h)
            h = dec(torch.cat([h, skip], dim=1))
        return self.out(h)              # predicted NOISE

    def denoise(self, x: torch.Tensor, strength: float = 1.0) -> torch.Tensor:
        return x - strength * self.forward(x)
