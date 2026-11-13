#!/usr/bin/env python3
"""Rebuild a run's final EDL from summary.json and render it again (no LLM).

Useful when a run failed at the very end (e.g. the export timed out) or to re-render with a new compiler.

usage: python3 scripts/reexport.py runs/<run_id> [out.mp4]
"""
import json
import sys
import time
from dataclasses import fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assemblee import music as music_mod  # noqa: E402
from assemblee.assets import load_or_build  # noqa: E402
from assemblee.compiler import compile_edl  # noqa: E402
from assemblee.edl import EDL, Caption, Section, Shot  # noqa: E402

run = Path(sys.argv[1]).resolve()
summary = json.loads((run / "summary.json").read_text())
task = json.loads((run / "task.json").read_text())
data = summary.get("edl") or sys.exit("summary.json has no EDL")
out = Path(sys.argv[2]) if len(sys.argv) > 2 else run / "output" / (task.get("name") or "reexport.mp4")
if out.suffix != ".mp4":
    out = out.with_suffix(".mp4")

catalog = load_or_build(Path(task["assets_dir"]))
mode = "rich" if any(s.get("grade") or s.get("camera") or isinstance((s.get("effects") or [None])[0], dict) for s in data["shots"]) \
    else task.get("vocab", "strict")
edl = EDL(catalog, mode=mode)
edl.music_library = music_mod.load_library(run)
sec_fields = {f.name for f in fields(Section)}
for s in data["sections"]:
    sec = Section(**{k: v for k, v in s.items() if k in sec_fields})
    for k, v in s.items():  # extra attributes the agent sets (visual_style, key_message...)
        if k not in sec_fields:
            setattr(sec, k, v)
    edl.sections.append(sec)
shot_fields = {f.name for f in fields(Shot)}
for s in data["shots"]:
    kw = {k: v for k, v in s.items() if k in shot_fields}
    if kw.get("caption"):
        kw["caption"] = Caption(**kw["caption"])
    edl.shots.append(Shot(**kw))
edl.sfx = data.get("sfx", [])
missing = [s.asset for s in edl.shots if s.kind == "picture" and s.asset not in catalog]
if missing:
    sys.exit(f"pictures missing from {task['assets_dir']}: {missing[:5]}")
t = time.time()
c = compile_edl(edl, on_progress=lambda m: print(" ", m, flush=True))
try:
    c.export(out)
finally:
    c.close()
print("exported", out, round(time.time() - t, 1), "s,", edl.total(), "s of video")
