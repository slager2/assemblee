#!/usr/bin/env python3
"""Compile a hand-written EDL in RICH mode (vocab.py) without any LLM, export it and dump labelled frames.

Every rich feature appears at least once: numeric grade + creative look + split toning, camera moves with each easing,
speed on an animated picture, effects with params and animated [from, to] values, transitions with params, card
text_anim. Also feeds deliberately wrong values to show the validator's warnings. Look at the contact sheets it writes.

usage: python3 scripts/smoke_rich.py [assets_dir] [out_dir]
"""
import io
import json
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assemblee import vocab  # noqa: E402
from assemblee.assets import load_or_build  # noqa: E402
from assemblee.compiler import compile_edl  # noqa: E402
from assemblee.edl import EDL, Section  # noqa: E402

root = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/slager/Рабочий стол/refs")
out_dir = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/assemblee_rich")
out_dir.mkdir(parents=True, exist_ok=True)
cat = load_or_build(root)


def asset(prefix, kind=None):
    for k, v in cat.items():
        if k.startswith(prefix) and (kind is None or v.get("kind") == kind):
            return k
    return next(iter(cat))


edl = EDL(cat, mode="rich")
edl.sections = [Section("intro", music="dark_drone", music_db=-12), Section("body", music="chiptune", music_db=-12), Section("outro", music="none")]
raw = [
    ("intro", {"card_title": "Сервер живой", "card_subtitle": "typewriter + page_peel", "card_style": "minimal", "seconds": 2.4,
               "text_anim": "typewriter", "transition_out": "page_peel", "transition_params": {"corner": "Bottom Right"}, "transition_seconds": 0.8},
     "card typewriter -> page_peel"),
    ("intro", {"asset": asset("server-beast/slime-rancher-1"), "seconds": 3,
               "grade": {"creative_look": "Teal & Orange", "look_intensity": 140, "contrast": 30, "saturation": 140, "shadow_tint": "#2050a0", "highlight_tint": "#ffb060"},
               "camera": {"start_scale": 150, "end_scale": 110, "start_xy": [0.3, 0.35], "end_xy": [0.6, 0.55], "easing": "ease_in_out"},
               "effects": [{"id": "lens_flare", "params": {"center": [0.8, 0.15], "brightness": 170}}, "light_leaks"],
               "transition_out": "shape_flow", "transition_params": {"shape": "Heart"}, "transition_seconds": 1.0},
     "grade teal&orange + split tone, camera ease_in_out, lens_flare, light_leaks -> shape_flow heart"),
    ("body", {"asset": asset("spider/04-lava-1"), "seconds": 2.5,
              "grade": {"exposure": 0.4, "temperature": 55, "saturation": 160, "highlights": -30},
              "camera": {"start_scale": 100, "end_scale": 140, "end_xy": [0.5, 0.45], "easing": "punch"},
              "effects": [{"id": "gaussian_blur", "params": {"blurriness": [50, 0]}}, {"id": "volumetric_rays", "amount": 0.8}],
              "transition_out": "glitch", "transition_params": {"amount": 1}},
     "grade warm, camera punch, focus pull (blur 50->0), volumetric_rays -> glitch amount 1"),
    ("body", {"asset": asset("last-online/no-players-online", "animated"), "seconds": 2.5, "speed": 50,
              "effects": [{"id": "rgb_split", "amount": 0.7}, {"id": "posterize_time", "params": {"rate": 6}}],
              "transition_out": "whip", "transition_params": {"direction": "west"}},
     "animated gif at speed 50%, rgb_split, posterize_time -> whip west"),
    ("body", {"asset": asset("spider/02-upper-1"), "seconds": 2.5,
              "grade": {"exposure": -0.8, "temperature": -55, "tint": -30, "faded_film": 45, "vibrance": -30},
              "camera": {"start_scale": 120, "end_scale": 120, "start_xy": [0.3, 0.5], "end_xy": [0.7, 0.5], "easing": "linear"},
              "effects": [{"id": "edge_glow", "params": {"color": "#40ff80"}}, {"id": "vr_digital_glitch", "amount": 0.9}],
              "transition_out": "kaleidoscope", "transition_params": {"segments": 8}},
     "grade cold/faded, camera linear pan, edge_glow green, digital glitch -> kaleidoscope"),
    ("body", {"asset": asset("server-beast/grow-a-garden-1"), "seconds": 2.5,
              "camera": {"start_scale": 100, "end_scale": 125, "easing": "ease_out"},
              "effects": [{"id": "mosaic", "params": {"horizontal": [10, 80]}}, {"id": "rounded_crop", "params": {"border_color": "#ffd23f"}}],
              "transition_out": "cross_zoom", "transition_params": {"amount": 0.9}},
     "camera ease_out, mosaic animated 10->80 (de-pixelate), rounded_crop gold border -> cross_zoom"),
    ("body", {"asset": asset("server-beast/spore-1"), "seconds": 2.5,
              "grade": {"creative_look": "Bleach Bypass", "contrast": 40},
              "camera": {"start_scale": 130, "end_scale": 100, "easing": "ease_in"},
              "effects": [{"id": "clone", "params": {"columns": 3}}, {"id": "tint", "params": {"black": "#301040", "white": "#80ffe0"}}],
              "transition_out": "spin_motion", "transition_params": {"spin": "Counter-clockwise", "rotation": 360}},
     "camera ease_in zoom out, clone 3x3, duotone tint -> spin_motion"),
    ("outro", {"card_title": "Glitch-карточка", "card_subtitle": "text_anim glitch", "card_style": "glitch", "seconds": 2.2, "text_anim": "glitch",
               "transition_out": "flash"}, "card glitch text_anim -> flash"),
    ("outro", {"card_title": "Конец", "card_subtitle": "scale_pop", "card_style": "final", "seconds": 2.2, "text_anim": "scale_pop"}, "card final scale_pop"),
]
# wrong values the validator must fix (and report)
bad = {"asset": asset("spider/01-mother"), "seconds": 2, "grade": {"exposure": 9, "saturaton": 300, "creative_look": "teal orange"},
       "camera": {"start_scale": 60, "end_scale": 260, "start_xy": [0.0, 0.0], "easing": "bounce"}, "speed": 200,
       "effects": ["gausian_blur", {"id": "rgb_split", "params": {"amount": 5000, "colour": 1}}, "glow", "vignette", "noise"],
       "transition_out": "page_curl", "transition_params": {"amount": 3}}
w = []
labels = []
for sec, r, label in raw:
    s = edl.make_shot(r, sec, w)
    if s:
        edl.shots.append(s)
        labels.append(label)
wbad = []
edl.make_shot(bad, "body", wbad)
print("warnings on the good EDL:", w)
print("warnings on the bad shot:\n  " + "\n  ".join(wbad))
edl.sfx = [{"kind": "whoosh", "shot": 4, "at": "start"}]
print("vocab:", vocab.counts())

t0 = time.time()
c = compile_edl(edl, on_progress=lambda m: print(" ", m))
print("compiled:", json.dumps({k: v for k, v in c.stats.items() if k != "beds"}, ensure_ascii=False))
if c.stats["warnings"]:
    print("COMPILER WARNINGS:", c.stats["warnings"])

tw, th = 216, 384
sheet_rows = []
for i, ((s, e), shot, label) in enumerate(zip(c.times, edl.shots, labels)):
    ts = [s + 0.12, (s + e) / 2, e - 0.12]
    frames = [Image.open(io.BytesIO(c.frame_png(t))).convert("RGB") for t in ts]
    if i + 1 < len(edl.shots) and shot.transition_out != "cut":
        frames.append(Image.open(io.BytesIO(c.frame_png(e))).convert("RGB"))  # transition midpoint (centered)
    for k, f in enumerate(frames):
        f.save(out_dir / f"shot{i + 1:02d}_{k}.png")
    sheet_rows.append((f"{i + 1}. {label}", frames))
per = 3
for n in range(0, len(sheet_rows), per):
    rows = sheet_rows[n:n + per]
    img = Image.new("RGB", (4 * tw, len(rows) * (th + 18)), "#222")
    d = ImageDraw.Draw(img)
    for r, (label, frames) in enumerate(rows):
        d.text((4, r * (th + 18) + 3), label[:150], fill="yellow")
        for k, f in enumerate(frames):
            img.paste(f.resize((tw, th)), (k * tw, r * (th + 18) + 18))
    img.save(out_dir / f"sheet_{n // per + 1}.png")
mp4 = c.export(out_dir / "rich.mp4")
c.close()
# the exported file must match the preview: grab two frames from it
for t in (c.times[3][0] + 0.5, c.times[3][0] + 2.0):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(mp4), "-frames:v", "1", str(out_dir / f"export_{t:.2f}.png")], check=True)
print("exported", mp4, round(time.time() - t0, 1), "s; sheets in", out_dir)
