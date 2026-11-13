"""Local Russian voice-over (CPU only; the LLM owns the GPU).

Engines run as subprocesses in their own venvs (scripts/setup_tts.sh), see tts_worker.py:
  silero v5_ru  (default; torch; aidar xenia baya kseniya eugene; models are CC BY-NC-SA 4.0, non-commercial use)
  piper ru_RU   (fallback; onnx; irina denis dmitri ruslan; the piper-tts package is GPL-3, ruslan data is non-commercial)

synthesize(text, voice, rate) -> Voice(path, seconds, phrases): 48 kHz stereo wav, loudnorm I=-16, cached by hash.
"""
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import CACHE, TTS_MODELS, TTS_PY

VOICES = {"aidar": "silero", "xenia": "silero", "baya": "silero", "kseniya": "silero", "eugene": "silero",
          "irina": "piper", "denis": "piper", "dmitri": "piper", "ruslan": "piper"}
DEFAULT_VOICE = "aidar"
VOICE_DIR = CACHE / "voice"
RATE = (0.7, 1.4)
LEAD = 0.05  # the narration starts this long after its shot starts
TAIL = 0.3  # a shot with narration lasts at least spoken length + this
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")
ONES = "ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать".split()
TENS = "_ _ двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто".split()
HUNDREDS = "_ сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот".split()


def number_words(n):
    """Nominative cardinal (no gender/case agreement), enough for a fallback: the prompt asks the model to spell numbers out."""
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + (" " + ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return HUNDREDS[n // 100] + (" " + number_words(n % 100) if n % 100 else "")
    if n < 10000:
        k = n // 1000
        head = {1: "одна тысяча", 2: "две тысячи", 3: "три тысячи", 4: "четыре тысячи"}.get(k, ONES[k] + " тысяч")
        return head + (" " + number_words(n % 1000) if n % 1000 else "")
    return " ".join(ONES[int(c)] for c in str(n))


def clean(text):
    t = EMOJI.sub("", str(text or "")).replace("«", "").replace("»", "").replace("—", ", ").replace("–", ", ")
    t = re.sub(r"\d+", lambda m: number_words(int(m.group())), t)
    return re.sub(r"\s+", " ", t).strip()


def list_voices():
    out = []
    for v, eng in VOICES.items():
        ok = Path(TTS_PY[eng]).is_file() and any(Path(TTS_MODELS).glob("silero_v5_ru.pt" if eng == "silero" else f"ru_RU-{v}-medium.onnx"))
        out.append({"voice": v, "engine": eng, "installed": ok, "default": v == DEFAULT_VOICE})
    return out


def pick_voice(name):
    """Exact voice, else the closest known one, else the default."""
    import difflib
    if name in VOICES:
        return name
    close = difflib.get_close_matches(str(name or "").lower(), list(VOICES), n=1, cutoff=0.5)
    return close[0] if close else DEFAULT_VOICE


@dataclass
class Voice:
    path: Path
    seconds: float
    phrases: list  # [(text, seconds)] sentences, durations include the short pause after each
    voice: str
    rate: float

    def timeline(self):
        """[(text, start, end)] of every phrase from the start of the clip."""
        t, out = 0.0, []
        for text, d in self.phrases:
            out.append((text, round(t, 3), round(t + d, 3)))
            t += d
        return out


def key(text, voice, rate):
    return hashlib.sha1(json.dumps([clean(text), voice, round(rate, 3), 3], ensure_ascii=False).encode()).hexdigest()[:16]


def probe_seconds(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def synthesize_many(items, on_status=None):
    """items: [(text, voice, rate)] -> [Voice]. One worker process per engine (the model loads once)."""
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    result, todo = [None] * len(items), {}
    for i, (text, voice, rate) in enumerate(items):
        voice, rate = pick_voice(voice), min(RATE[1], max(RATE[0], float(rate or 1.0)))
        k = key(text, voice, rate)
        wav, meta = VOICE_DIR / f"{k}.wav", VOICE_DIR / f"{k}.json"
        if wav.is_file() and meta.is_file():
            m = json.loads(meta.read_text())
            result[i] = Voice(wav, m["seconds"], m["phrases"], voice, rate)
        else:
            todo.setdefault(VOICES[voice], []).append((i, clean(text), voice, rate, k))
    for engine, jobs in todo.items():
        py = TTS_PY[engine]
        if not Path(py).is_file():
            raise RuntimeError(f"TTS engine '{engine}' is not installed: run scripts/setup_tts.sh")
        on_status and on_status(f"tts {engine}: {len(jobs)} line(s)")
        raw = [{"engine": engine, "voice": v, "text": t, "out": str(VOICE_DIR / f"{k}.raw.wav"), "models": str(TTS_MODELS)} for _, t, v, _, k in jobs]
        p = subprocess.run([str(py), "-I", str(Path(__file__).with_name("tts_worker.py"))], input=json.dumps(raw), capture_output=True, text=True, timeout=900)
        if p.returncode:
            raise RuntimeError(f"TTS worker failed: {p.stderr[-400:]}")
        for (i, text, voice, rate, k), r in zip(jobs, json.loads(p.stdout)):
            wav = VOICE_DIR / f"{k}.wav"
            # rate (pitch-preserving), mono -> 48 kHz stereo, loudness; the pause keeps its length share
            af = (f"atempo={rate}," if abs(rate - 1) > 0.01 else "") + "loudnorm=I=-16:TP=-1.5:LRA=7"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", r["out"], "-af", af, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(wav)], check=True)
            Path(r["out"]).unlink(missing_ok=True)
            phrases = [[t, round(d / rate, 3)] for t, d in r["phrases"]]
            seconds = round(probe_seconds(wav), 3)
            (VOICE_DIR / f"{k}.json").write_text(json.dumps({"seconds": seconds, "phrases": phrases, "text": text, "voice": voice, "rate": rate}, ensure_ascii=False))
            result[i] = Voice(wav, seconds, phrases, voice, rate)
    return result


def synthesize(text, voice=DEFAULT_VOICE, rate=1.0) -> Path:
    """The narration as a 48 kHz stereo wav (loudnorm I=-16), cached by hash of (text, voice, rate)."""
    return synthesize_many([(text, voice, rate)])[0].path


def spoken_seconds(text, voice=DEFAULT_VOICE, rate=1.0):
    return synthesize_many([(text, voice, rate)])[0].seconds


def estimate_seconds(text, rate=1.0):
    """Pure arithmetic when no audio exists yet: ~13 characters per second at rate 1 (measured on aidar/xenia)."""
    return round(max(0.5, len(clean(text)) / 13.0 / (rate or 1.0)), 2)


if __name__ == "__main__":  # python3 -m assemblee.voice "text" [voice] [rate]
    a = sys.argv[1:]
    if not a:
        print(json.dumps(list_voices(), ensure_ascii=False, indent=1))
    else:
        v = synthesize_many([(a[0], a[1] if len(a) > 1 else DEFAULT_VOICE, float(a[2]) if len(a) > 2 else 1.0)])[0]
        print(v.path, v.seconds, v.timeline())
