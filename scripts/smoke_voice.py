#!/usr/bin/env python3
"""Voice-over smoke test without the LLM: an EDL with a section narration and a per-shot narration, music ducked under
the speech; exports and checks levels per time window with ffmpeg (the voice must be audible above the music).

usage: python3 scripts/smoke_voice.py [assets_dir] [out.mp4] [voice] [--no-duck]
"""
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assemblee.assets import load_or_build  # noqa: E402
from assemblee.compiler import compile_edl  # noqa: E402
from assemblee.edl import EDL, Section  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
root = Path(args[0] if args else "/home/slager/Рабочий стол/refs")
out = Path(args[1] if len(args) > 1 else "/tmp/assemblee_voice.mp4")
voice = args[2] if len(args) > 2 else "aidar"
LOUD = 3 if "--loud" in sys.argv else -10  # loud music makes the ducking itself measurable
cat = load_or_build(root)
ids = list(cat)
edl = EDL(cat)
edl.voice = voice
if "--no-duck" in sys.argv:
    edl.duck_db = 0
edl.sections = [Section("intro", music="epic", music_db=LOUD, narration="Добро пожаловать на сервер, где каждый блок может оказаться ловушкой. Здесь никто не уходит прежним."),
                Section("mid", music="epic", music_db=LOUD),
                Section("end", music="epic", music_db=LOUD)]
w = []
raw = [("intro", {"card_title": "Server Beast", "card_style": "glitch", "seconds": 1.5}),
       ("intro", {"asset": ids[0], "seconds": 1.5, "motion": "zoom_in"}),
       ("mid", {"asset": ids[min(10, len(ids) - 1)], "seconds": 3, "motion": "punch_in"}),
       ("mid", {"asset": ids[min(20, len(ids) - 1)], "seconds": 3, "motion": "pan_left"}),
       ("end", {"asset": ids[-1], "seconds": 1.0, "motion": "zoom_out"}),
       ("end", {"card_title": "Заходи", "card_style": "final", "seconds": 2})]
for sec, r in raw:
    s = edl.make_shot(r, sec, w)
    if s:
        edl.shots.append(s)
edl.shots[4].narration = "Не оглядывайся. Они уже считают твои шаги!"
t = time.time()
c = compile_edl(edl, on_progress=lambda m: print(" ", m))
print("warnings:", c.stats["warnings"])
print("narration:", [(n["shot"], n["start"], n["end"], n["voice"]) for n in edl.narration_clips])
print("shot times:", edl.times())
c.export(out)
c.close()
print("exported", out, round(time.time() - t, 1), "s")


def level(a, b):
    """Mean volume (dB) of the exported audio in [a, b]."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-ss", str(a), "-t", str(b - a), "-i", str(out), "-vn", "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else float("nan")


total = edl.total()
clips = edl.narration_clips
rows = [("music before speech", 0.0, min(0.04, clips[0]["start"]) if clips[0]["start"] > 0.05 else 0.05)]
for i, n in enumerate(clips):
    rows.append((f"speech {i + 1}", n["start"] + 0.2, n["end"] - 0.2))
    nxt = clips[i + 1]["start"] if i + 1 < len(clips) else total
    if nxt - n["end"] > 1.6:
        rows.append((f"gap after {i + 1} (music back)", n["end"] + 0.9, nxt - 0.5))
for name, a, b in rows:
    print(f"  {name:28s} {a:6.2f}-{b:6.2f} s  mean {level(a, b):6.1f} dB")
sp = [level(n["start"] + 0.2, n["end"] - 0.2) for n in clips]
gaps = [level(n["end"] + 0.9, (clips[i + 1]["start"] if i + 1 < len(clips) else total) - 0.5) for i, n in enumerate(clips)
        if (clips[i + 1]["start"] if i + 1 < len(clips) else total) - n["end"] > 1.6]
if gaps:
    print("voice vs music-only gap:", round(min(sp) - max(gaps), 1), "dB", "(voice louder)" if min(sp) > max(gaps) else "(VOICE NOT ABOVE MUSIC)")
