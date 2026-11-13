"""Runs INSIDE an engine venv (torch for silero, onnxruntime for piper): stdin = JSON list of jobs
{"engine","voice","text","out","models"}, stdout = JSON list of {"out","sr","phrases":[[text, seconds]...]}.
Each phrase (sentence) is synthesized on its own and joined with a short pause, so the harness knows phrase timings.
Standalone on purpose: it must not import assemblee (the venv has none of its dependencies)."""
import json
import re
import sys
import wave

import numpy as np

PAUSE = 0.14
SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")


def phrases(text):
    return [p.strip() for p in SPLIT.split(text) if re.search(r"\w", p)]


def load(engine, voice, models, cache):
    key = (engine, voice if engine == "piper" else "")
    if key in cache:
        return cache[key]
    if engine == "piper":
        from piper import PiperVoice
        m = PiperVoice.load(f"{models}/ru_RU-{voice}-medium.onnx")
    else:
        import torch
        torch.set_num_threads(6)
        m = torch.package.PackageImporter(f"{models}/silero_v5_ru.pt").load_pickle("tts_models", "model")
        m.to("cpu")
    cache[key] = m
    return m


def say(engine, model, voice, text):
    if engine == "piper":
        ch = list(model.synthesize(text))
        return np.concatenate([c.audio_float_array for c in ch]), ch[0].sample_rate
    a = model.apply_tts(text=text, speaker=voice, sample_rate=48000, put_accent=True, put_yo=True)
    return a.numpy(), 48000


def main():
    cache, res = {}, []
    for job in json.load(sys.stdin):
        model = load(job["engine"], job["voice"], job["models"], cache)
        parts, info, sr = [], [], 0
        for p in phrases(job["text"]):
            a, sr = say(job["engine"], model, job["voice"], p)
            a = np.concatenate([a, np.zeros(int(PAUSE * sr), dtype=a.dtype)])
            parts.append(a)
            info.append([p, round(len(a) / sr, 3)])
        a = np.concatenate(parts) if parts else np.zeros(int(0.2 * (sr or 22050)))
        with wave.open(job["out"], "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr or 22050)
            w.writeframes((np.clip(a, -1, 1) * 32767).astype("<i2").tobytes())
        res.append({"out": job["out"], "sr": sr, "phrases": info})
    json.dump(res, sys.stdout)


main()
