#!/usr/bin/env python3
"""Compile a hand-written EDL without any LLM and export it: checks the engine side end to end.

usage: python3 scripts/smoke_compile.py [assets_dir] [out.mp4]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assemblee.assets import load_or_build  # noqa: E402
from assemblee.compiler import compile_edl  # noqa: E402
from assemblee.edl import EDL, Section  # noqa: E402

root = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/slager/Рабочий стол/refs")
out = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/assemblee_smoke.mp4")
cat = load_or_build(root)
ids = list(cat)
edl = EDL(cat)
edl.sections = [Section("intro", music="dark_drone", music_db=-10), Section("body", music="chiptune", music_db=-10)]
w = []
raw = [("intro", {"card_title": "Smoke test", "card_subtitle": "Проверка компилятора", "card_style": "glitch", "seconds": 2, "transition_out": "glitch"}),
       ("intro", {"asset": ids[0], "seconds": 2, "motion": "zoom_in", "look": "horror_cold", "caption": "Подпись снизу", "caption_style": "retro2011"}),
       ("body", {"asset": ids[min(10, len(ids) - 1)], "seconds": 2, "motion": "punch_in", "look": "cartoon_pop", "caption": "Мульт", "caption_style": "cartoon",
                 "effects": ["glow"], "transition_out": "whip"}),
       ("body", {"asset": ids[-1], "seconds": 2, "motion": "pan_left", "look": "dark_cave", "caption": "Ур.1\nНавык", "caption_style": "system", "caption_position": "center"}),
       ("body", {"card_title": "Конец", "card_style": "final", "seconds": 2})]
for sec, r in raw:
    s = edl.make_shot(r, sec, w)
    if s:
        edl.shots.append(s)
edl.sfx = [{"kind": "whoosh", "shot": 3, "at": "start"}]
print("warnings:", w)
t = time.time()
c = compile_edl(edl, on_progress=lambda m: print(" ", m))
print("compiled:", c.stats)
Path("/tmp/assemblee_smoke_frame.png").write_bytes(c.frame_png(5.0))
c.export(out)
c.close()
print("exported", out, round(time.time() - t, 1), "s")
