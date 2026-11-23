#!/usr/bin/env python3
"""Original soundtrack generator for Akuna Matata reels — synthesized, so no licensing issues.

A light, playful marimba groove (ukulele-pop feel) + bass + soft drums, plus sound effects placed on cue
times (whoosh on scene wipes, pop when something lands, tick when text rises).

  python3 tools/soundtrack.py out.wav --dur 14 --cues '[{"t":2.8,"k":"whoosh"},{"t":0.25,"k":"pop"}]'
  --mood bright | chill | bouncy   (tempo + key + pattern; pick one that fits the reel, vary between posts)
  --seed N                          (melody variation so reels don't all sound identical)
render.py calls this automatically for every .mp4 and derives the cues from the page's animations.
"""
import argparse, json, numpy as np
from scipy.io import wavfile
from scipy.signal import butter, lfilter

SR = 44100
MOODS = {  # bpm, root midi, progression (scale degrees as chord roots), swing
    "bright": (112, 60, [0, 7, 9, 5], 0.0),     # C  G  Am F
    "bouncy": (124, 62, [0, 5, 7, 5], 0.08),    # D  G  A  G
    "chill":  (92,  57, [0, 8, 3, 10], 0.12),   # A  F  C  G  (relative-minor flavour)
}
MAJOR = [0, 2, 4, 5, 7, 9, 11]

def env(n, a=0.004, d=0.35):
    t = np.arange(n) / SR
    e = np.minimum(1, t / a) * np.exp(-t / d)
    return e

def marimba(f, dur, vel=1.0):
    n = int(dur * SR); t = np.arange(n) / SR
    s = np.sin(2*np.pi*f*t) + 0.25*np.sin(2*np.pi*f*3.93*t)*np.exp(-t/0.05) + 0.08*np.sin(2*np.pi*f*9.2*t)*np.exp(-t/0.02)
    return vel * s * env(n, 0.002, 0.32)

def pluck_bass(f, dur):
    n = int(dur * SR); t = np.arange(n) / SR
    s = np.sin(2*np.pi*f*t) + 0.3*np.sin(2*np.pi*2*f*t)
    return 0.9 * s * env(n, 0.006, 0.28)

def kick():
    n = int(0.22 * SR); t = np.arange(n) / SR
    f = 50 + 90*np.exp(-t/0.03)
    return np.sin(2*np.pi*np.cumsum(f)/SR) * np.exp(-t/0.12)

def noise_burst(dur, lo, hi, decay):
    n = int(dur * SR); t = np.arange(n) / SR
    b, a = butter(2, [lo/(SR/2), min(hi/(SR/2), .99)], btype="band")
    return lfilter(b, a, np.random.randn(n)) * np.exp(-t/decay)

def sfx(kind):
    if kind == "whoosh":
        n = int(0.5 * SR); t = np.arange(n) / SR
        x = np.random.randn(n); out = np.zeros(n); y = 0
        cut = 300 + 5000*(t/t[-1])**1.5                       # rising filter sweep
        alpha = 1 - np.exp(-2*np.pi*cut/SR)
        for i in range(n): y += alpha[i]*(x[i]-y); out[i] = y
        e = np.sin(np.pi*np.minimum(1, t/0.5))**2
        return 0.55 * out * e / (np.abs(out).max() + 1e-9)
    if kind == "pop":
        n = int(0.09 * SR); t = np.arange(n) / SR
        f = 500 + 700*(t/t[-1])
        return 0.6 * np.sin(2*np.pi*np.cumsum(f)/SR) * np.exp(-t/0.03)
    if kind == "tick":
        return 0.25 * noise_burst(0.03, 2500, 8000, 0.006)
    if kind == "ding":
        return 0.45 * (marimba(1568, 0.8) + 0.5*marimba(2093, 0.8))
    return np.zeros(1)

def midi(m): return 440 * 2 ** ((m - 69) / 12)

def track(dur, mood, seed):
    bpm, root, prog, swing = MOODS[mood]
    rng = np.random.default_rng(seed)
    beat = 60 / bpm; n = int((dur + 1) * SR)
    mus = np.zeros(n); drums = np.zeros(n)
    def put(buf, sig, t, g=1.0):
        i = int(t * SR); j = min(n, i + len(sig))
        if i < n: buf[i:j] += g * sig[:j-i]
    # melody pattern: 8 eighth-notes per bar, chord-tone indices (0 root,1 third,2 fifth,3 octave), -1 rest
    patterns = [[0,2,1,2,3,2,1,-1],[3,2,1,0,1,2,-1,2],[0,1,2,3,2,-1,1,2],[2,-1,3,2,1,0,1,-1]]
    pat = [patterns[k] for k in rng.permutation(4)]
    bars = int(np.ceil(dur / (4*beat))) + 1
    for b in range(bars):
        deg = prog[b % len(prog)]; t0 = b * 4 * beat
        third = 3 if deg in (9, 2, 4) else 4                 # minor chords on ii/iii/vi
        tones = [root+deg, root+deg+third, root+deg+7, root+deg+12]
        for k, idx in enumerate(pat[b % 4]):
            if idx < 0: continue
            sw = swing*beat if k % 2 else 0
            put(mus, marimba(midi(tones[idx]+12), 0.6, 0.55 + 0.15*rng.random()), t0 + k*beat/2 + sw, 0.5)
        for k in range(4):                                     # bass on every beat, root/fifth
            put(mus, pluck_bass(midi(root+deg-12 + (7 if k == 2 else 0)), beat*0.9), t0 + k*beat, 0.55)
            if k in (0, 2): put(drums, kick(), t0 + k*beat, 0.7)
            if k in (1, 3): put(drums, noise_burst(0.12, 900, 4000, 0.04), t0 + k*beat, 0.35)
            put(drums, noise_burst(0.04, 6000, 12000, 0.012), t0 + k*beat + beat/2, 0.18)
    out = mus + drums
    # final chord + fade
    fade = int(1.2 * SR); end = int(dur * SR)
    out[end-fade:end] *= np.linspace(1, 0, fade); out[end:] = 0
    return out[:end]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("--dur", type=float, required=True)
    ap.add_argument("--cues", default="[]"); ap.add_argument("--mood", default="bright", choices=list(MOODS))
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    np.random.seed(a.seed)
    music = track(a.dur, a.mood, a.seed)
    fx = np.zeros_like(music); last = {}
    for c in sorted(json.loads(a.cues), key=lambda c: c["t"]):
        k, t = c["k"], float(c["t"])
        if t >= a.dur or t - last.get(k, -9) < 0.12: continue   # no machine-gun duplicates
        last[k] = t; s = sfx(k); i = int(t * SR); j = min(len(fx), i + len(s)); fx[i:j] += s[:j-i]
    mix = 0.6 * music + 0.75 * fx
    mix = np.tanh(1.4 * mix) / np.tanh(1.4)                     # soft limiter
    mix *= 0.89 / (np.abs(mix).max() + 1e-9)                     # ~ -1 dBFS peak
    st = np.stack([mix, mix], 1)
    wavfile.write(a.out, SR, (st * 32767).astype(np.int16))
    print("OK", a.out)

if __name__ == "__main__":
    main()
