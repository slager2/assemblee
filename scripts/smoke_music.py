#!/usr/bin/env python3
"""Real-music smoke test, no LLM needed (the model is used for query planning only with --llm):
  1. tempo analysis of the synthesized beds with known tempo (chiptune 120, epic 140 bpm)
  2. live search + download of CC music for "warm family" and "dark retro horror" (Openverse, ccMixter, Commons)
  3. analysis of every downloaded track (bpm vs ccMixter's own bpm tag when there is one)
  4. compile + export an EDL whose two sections use two downloaded tracks (music_start = the drop),
     beat-snapped cuts, then check the exported audio with ffmpeg volumedetect

usage: python3 scripts/smoke_music.py [dest_dir] [out.mp4] [--llm] [--no-compile]
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assemblee import music  # noqa: E402
from assemblee.config import AUDIO_DIR  # noqa: E402
from assemblee.edl import EDL, Section  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
dest = Path(args[0] if args else "/tmp/assemblee_music").expanduser()
out = Path(args[1] if len(args) > 1 else "/tmp/assemblee_music.mp4")
use_llm = "--llm" in sys.argv

print("== 1. tempo of the synthesized beds")
known = {"chiptune": (120.0, 0.5), "epic": (140.0, 60 / 140)}
for name, (bpm, period) in known.items():
    a = music.analyse(AUDIO_DIR / f"{name}.wav")
    phase = sum(min(b % period, period - b % period) for b in a["beats"]) / len(a["beats"])
    err = abs(a["bpm"] - bpm) / bpm * 100
    print(f"  {name}: {a['bpm']} bpm (true {bpm}, error {err:.2f}%), {len(a['beats'])} beats, mean phase error {phase * 1000:.0f} ms,"
          f" analysed in {a['seconds']} s")
    assert err < 2 and phase < 0.05, name

print("== 2. search + download")
llm = None
if use_llm:
    from assemblee.llm import LLM
    llm = LLM()
    if not llm.health():
        print("  model not running, keyword queries")
        llm = None
queries = None if llm else {"warm_family": ["warm family", "acoustic warm", "piano emotional"],
                            "dark_retro_horror": ["dark retro horror", "horror synth", "dark synthwave"]}


def ev(kind, d):
    if kind == "tool_result" and d.get("name") in ("search_music", "download_music", "plan_music_queries"):
        print("  ", d["name"], "ok" if d["ok"] else "FAIL", json.dumps(d["result"], ensure_ascii=False)[:160])
    elif kind == "warning":
        print("   warning:", d["message"][:160])


t0 = time.time()
lib = music.gather_music("ролик про тёплые семейные воспоминания, а потом тёмный ретро-хоррор", llm, dest,
                         {"warm_family": "тёплые семейные воспоминания", "dark_retro_horror": "тёмный ретро-хоррор, синтезаторы 80-х"},
                         per_mood=3, queries=queries, on_event=ev)
print(f"  {len(lib)} tracks in {time.time() - t0:.0f} s")

print("== 3. analysis")
credits = json.loads((dest / "credits.json").read_text())
for t in lib:
    hint = t.get("bpm_hint")
    rel = ""
    if hint:
        r = t["bpm"] / hint
        rel = f" ccMixter says {hint:g} ({'match' if abs(r - 1) < 0.04 else 'octave' if min(abs(r - 2), abs(r - 0.5)) < 0.08 else 'MISS'})"
    print(f"  {t['id']}: {t['bpm']} bpm (conf {t['tempo_confidence']}){rel}, {t['duration']} s, drop at {t['best_start']} s,"
          f" {t['license']} [{t['provider']}] {t['title'][:40]} / {t['artist'][:24]}")
    c = credits[t["id"]]
    assert c["kind"] == "music" and c["license_clear"] and c["license_url"] and c["page_url"], c
print("  licences:", sorted({t["license"] for t in lib}))

if "--no-compile" in sys.argv or len({t["mood"] for t in lib}) < 2:
    sys.exit(0)

print("== 4. compile with downloaded tracks")
from assemblee.assets import load_or_build  # noqa: E402
from assemblee.compiler import compile_edl  # noqa: E402

refs = Path("/home/slager/Рабочий стол/refs")
cat = load_or_build(refs)
ids = list(cat)
warm = next(t for t in lib if t["mood"] == "warm_family")
dark = next(t for t in lib if t["mood"] == "dark_retro_horror")
edl = EDL(cat)
edl.music_library = {t["id"]: t for t in lib}
w = []
edl.sections = [Section("warm", music=edl.resolve_music(warm["id"], w), music_db=-8),
                Section("dark", music=edl.resolve_music(dark["id"], w), music_db=-8)]
raw = [("warm", {"card_title": "Семья", "card_style": "minimal", "seconds": 2.2}),
       ("warm", {"asset": ids[0], "seconds": 2.7, "motion": "zoom_in", "look": "warm_memory", "transition_out": "cross_dissolve"}),
       ("warm", {"asset": ids[1 % len(ids)], "seconds": 3.1, "motion": "pan_left", "look": "warm_memory"}),
       ("dark", {"asset": ids[-1], "seconds": 1.9, "motion": "punch_in", "look": "horror_cold", "effects": ["rgb_split"]}),
       ("dark", {"asset": ids[-2], "seconds": 2.6, "motion": "zoom_out", "look": "dark_cave"}),
       ("dark", {"card_title": "Конец", "card_style": "final", "seconds": 2.0})]
for sec, r in raw:
    s = edl.make_shot(r, sec, w)
    if s:
        edl.shots.append(s)
before = [s.seconds for s in edl.shots]
reports = music.snap_edl(edl)
print("  warnings:", w)
print("  beat snap:", json.dumps(reports), "\n   ", before, "->", [s.seconds for s in edl.shots])
for name in ("warm", "dark"):
    bed, at = edl.section_track_time(name)
    beats = edl.music_library[bed["mood"]]["beats"]
    print(f"  section {name}: track {bed['mood']} from {at:.2f} s (nearest beat {min(beats, key=lambda b: abs(b - at)):.2f})")
t = time.time()
c = compile_edl(edl, on_progress=lambda m: None)
print("  compiled:", json.dumps({k: c.stats[k] for k in ("beds", "warnings", "seconds")}, ensure_ascii=False))
c.export(out)
c.close()
print("  exported", out, round(time.time() - t, 1), "s")


def volume(path, start=None, dur=None):
    cmd = ["ffmpeg", "-v", "info", "-nostdin"] + (["-ss", str(start), "-t", str(dur)] if start is not None else []) + \
          ["-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    mean = float(re.search(r"mean_volume: (-?[\d.]+) dB", err)[1])
    peak = float(re.search(r"max_volume: (-?[\d.]+) dB", err)[1])
    return mean, peak


mean, peak = volume(out)
print(f"  export audio: mean {mean} dB, peak {peak} dB")
times = edl.times()
for name in ("warm", "dark"):
    idx = edl.section_shots(name)
    a, b = times[idx[0]][0], times[idx[-1]][1]
    m, p = volume(out, a + 0.5, max(0.5, b - a - 1.0))
    print(f"  section {name} ({a:.1f}-{b:.1f} s): mean {m} dB, peak {p} dB")
    assert m > -40, f"section {name} is silent"
assert mean > -35 and peak < 0.5, "exported audio is silent or clipping"
print("OK")
