#!/usr/bin/env python3
"""Build a rich-mode EDL from a few ideas.py recipes (no LLM), compile, export, and write contact sheets.

usage: python3 scripts/demo_ideas.py [--assets DIR] [--out DIR] [--no-export] [recipe_id ...]
default recipes: error_screen_hook zoom_through_chain before_after_wipe
"""
import argparse
import io
import json
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assemblee import ideas  # noqa: E402
from assemblee.assets import load_or_build  # noqa: E402
from assemblee.compiler import compile_edl  # noqa: E402
from assemblee.edl import EDL, Section  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("recipes", nargs="*", default=["error_screen_hook", "zoom_through_chain", "before_after_wipe"])
ap.add_argument("--assets", default="/home/slager/Рабочий стол/refs")
ap.add_argument("--out", default="/tmp/assemblee_ideas")
ap.add_argument("--no-export", action="store_true")
args = ap.parse_args()
out_dir = Path(args.out)
out_dir.mkdir(parents=True, exist_ok=True)
cat = load_or_build(Path(args.assets))

# hand-picked pictures and captions per recipe (the agent would let the model choose these)
PICKS = {
    "error_screen_hook": (["last-online/no-players-online"], ["ОШИБКА: ИГРОКОВ НЕТ", "Сервер пуст уже 3 года"], ["код 0 из 0", None]),
    "zoom_through_chain": (["spider/02-upper-1", "spider/03-lower-2", "spider/04-lava-1"], ["Верхний ярус", "Ниже", "Туда никто не спускался"], None),
    "before_after_wipe": (["server-beast/slime-rancher-1"], ["ДО", "ПОСЛЕ"], None),
    "freeze_callout": (["server-beast/slime-rancher-2"], [None, "Да. Это я.\nСейчас объясню, как так вышло", "3 дня назад"], [None, None, ""]),
    "vhs_memory": (["last-online/classic-1", "last-online/classic-maps"], ["2011", "Сервер был полон", "Мы строили тут всё лето", "Теперь тут тихо"], ["Последний онлайн", None, None, ""]),
    "countdown_top3": (["spider/03-lower-1", "spider/04-lava-2", "spider/01-mother"], ["ТОП-3 жутких мест", "3", None, "2", None, "1", None],
                       ["№1 вас удивит", "Нижние пещеры", None, "Лавовое озеро", None, "Логово Матери", None]),
    "hero_flare_reveal": (["spider/01-mother"], ["Мать", "Королева пауков"], None),
    "pop_art_grid": (["server-beast/slime-rancher-3"], [None, "Четыре — уже проблема"], None),
    "neon_outline": (["last-online/backrooms", "last-online/crossroads"], ["СКАНИРОВАНИЕ...", None], None),
    "movie_trailer": (["server-beast/dragon-adventures-1", "server-beast/dragon-adventures-2"],
                      ["В мире, где драконы правят...", "...один игрок решил их приручить", "SERVER BEAST"], [None, None, "скоро"]),
    "glitch_reveal": (["last-online/just-act-natural"], [None, "СИГНАЛ ВОССТАНОВЛЕН"], None),
    "horror_strobe": (["last-online/backrooms", "spider/01-mother"], ["Ты слышал шаги?", None, "ОНО ЗДЕСЬ"], None),
    "sketch_to_colour": (["server-beast/dragon-adventures-2"], ["Это был просто набросок", "Теперь в это играют тысячи"], None),
    "portal_twist": (["last-online/classic-2", "server-beast/slime-rancher2-1"], ["Закрой глаза...", "Ты в другой игре"], None),
    "single_colour_accent": (["spider/04-lava-3", "spider/04-lava-4"], ["Видишь красное? Не наступай", None], None),
    "dream_float": (["server-beast/grow-a-garden-2", "server-beast/slime-rancher2-2"], [None, "Представь свой сад", None], [None, "", None]),
    "calm_then_chaos": (["server-beast/grow-a-garden-1", "spider/04-lava-1", "spider/05-evo-3"], ["Обычный день на сервере", None, None, "Никто не ожидал"], None),
    "tilted_cards": (["server-beast/spore-1", "server-beast/grow-a-garden-1"], ["Spore — эволюция", "Grow a Garden"], None),
}


def picks(rid):
    pick = PICKS.get(rid)
    if pick:
        return pick
    pics = [k for k, v in cat.items() if v.get("kind") != "animated"]
    return pics[:4], None, None


edl = EDL(cat, mode="rich")
labels, warnings = [], []
for rid in args.recipes:
    r = ideas.BY_ID[rid]
    edl.sections.append(Section(rid, music=r["music_hint"], music_db=-14))
    assets, caps, subs = picks(rid)
    raw, sfx = ideas.to_shots(r, [a for a in assets if a in cat] or list(cat)[:1], caps)
    base = len(edl.shots)
    for i, (shot_raw, st) in enumerate(zip(raw, r["structure"])):
        if subs and i < len(subs) and subs[i] is not None and st["kind"] == "card":
            shot_raw["card_subtitle"] = subs[i]
        if not shot_raw.get("card_title") and st["kind"] == "card":
            shot_raw["card_title"] = r["name_ru"]
        if "{" in str(shot_raw.get("caption", "")):
            shot_raw.pop("caption")  # unfilled template
        s = edl.make_shot(shot_raw, rid, warnings)
        if s:
            edl.shots.append(s)
            labels.append(f"{rid}[{i}] {st['role']}")
    for x in sfx:
        edl.sfx.append({"kind": x["kind"], "shot": base + x["offset"] + 1, "at": "start"})
print("warnings:", warnings or "none")
print("total", edl.total(), "s,", len(edl.shots), "shots")

t0 = time.time()
c = compile_edl(edl, on_progress=lambda m: print(" ", m))
print("compiled:", json.dumps({k: v for k, v in c.stats.items() if k != "beds"}, ensure_ascii=False))
tw, th = 216, 384
rows = []
for i, ((s, e), shot, label) in enumerate(zip(c.times, edl.shots, labels)):
    ts = [s + 0.12, (s + e) / 2, e - 0.12]
    frames = [Image.open(io.BytesIO(c.frame_png(t))).convert("RGB") for t in ts]
    if i + 1 < len(edl.shots) and shot.transition_out != "cut":
        frames.append(Image.open(io.BytesIO(c.frame_png(e))).convert("RGB"))
    rows.append((f"{i + 1}. {label} -> {shot.transition_out}", frames))
per = 4
for n in range(0, len(rows), per):
    chunk = rows[n:n + per]
    img = Image.new("RGB", (4 * tw, len(chunk) * (th + 18)), "#222")
    d = ImageDraw.Draw(img)
    for k, (label, frames) in enumerate(chunk):
        d.text((4, k * (th + 18) + 3), label[:150], fill="yellow")
        for j, f in enumerate(frames):
            img.paste(f.resize((tw, th)), (j * tw, k * (th + 18) + 18))
    img.save(out_dir / f"sheet_{n // per + 1}.png")
if not args.no_export:
    print("exported", c.export(out_dir / "ideas.mp4"))
c.close()
print(round(time.time() - t0, 1), "s; sheets in", out_dir)
