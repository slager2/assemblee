#!/usr/bin/env python3
"""Render EVERY template of assemblee/templates.py into contact sheets (no LLM needed).
usage: scripts/template_gallery.py [--out DIR] [--refs DIR] [--ec]   (--ec also renders the 7 EffectCraft cards, slow)"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from assemblee import templates as T  # noqa: E402
from assemblee.config import FONT_BOLD, H, W  # noqa: E402

TW, TH, COLS = 270, 480, 6
TEXTS = ["Он слышал каждый шаг", "Никто не заходил сюда 10 лет"]
CARD_SAMPLES = {"big_number": ("37 млн", "игроков за месяц"), "vs_card": ("Слайм vs Дракон", "кто сильнее?"),
                "checklist": ("Что нужно", "собрать ресурсы; построить базу; приручить зверя; не умереть"),
                "timeline": ("Путь игры", "2019: идея; 2021: релиз; 2023: хит"), "poll_card": ("Кого бы ты выбрал?", "Слайма; Дракона; Паука"),
                "quote_card": ("Мир не ждёт тех, кто боится шагнуть", "неизвестный игрок"), "chapter": ("Пустой сервер", "где все?"),
                "end_cta": ("Это только начало", "Подписывайся"), "sticky_note": ("Не забыть", "выключить свет перед сном"),
                "headline_news": ("Сервер опустел за одну ночь", "Игроки не могут объяснить, куда все пропали"),
                "split_two": ("Было страшно", "Стало смешно")}


def sheet(tiles, path):
    rows = (len(tiles) + COLS - 1) // COLS
    s = Image.new("RGB", (COLS * (TW + 8) + 8, rows * (TH + 34) + 8), (30, 30, 34))
    d = ImageDraw.Draw(s)
    f = ImageFont.truetype(FONT_BOLD, 18)
    for i, (label, im) in enumerate(tiles):
        x, y = 8 + (i % COLS) * (TW + 8), 8 + (i // COLS) * (TH + 34)
        s.paste(im.convert("RGB").resize((TW, TH), Image.LANCZOS), (x, y + 28))
        d.text((x, y + 2), label, font=f, fill=(255, 255, 255))
    s.save(path)
    print(path, len(tiles))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="gallery")
    ap.add_argument("--refs", default="/home/slager/Рабочий стол/refs")
    ap.add_argument("--ec", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pics = sorted(Path(a.refs).rglob("*.jpg"))
    pics = [pics[0], pics[len(pics) // 2], pics[-1]]
    print("pictures:", [p.name for p in pics])
    for k in range(2):
        tiles = []
        for lid in T.ids("layout"):
            tiles.append((lid, Image.open(T.render_layout(lid, [pics[(k + j) % 3] for j in range(3)], {}))))
        sheet(tiles, out / f"layouts_{k + 1}.png")
    for k in range(2):
        tiles = []
        base = T.cover(T.load_picture(pics[k]), W, H)
        for sid in T.ids("caption"):
            text = "3 секунды" if sid == "countdown" else ("Иван: это точно был он" if sid == "speaker_sub" else TEXTS[k])
            cap = Image.open(T.render_caption(text, sid, "bottom" if sid == "corner_tiny" else "center", {}))
            bg = base.copy()
            bg.paste(cap, (0, 0), cap)
            tiles.append((sid, bg))
        sheet(tiles, out / f"captions_{k + 1}.png")
    tiles = []
    for cid in T.ids("card"):
        t = T.get("card", cid)
        if t.engine == "effectcraft":
            if not a.ec:
                im = Image.new("RGB", (W, H), (60, 60, 70))
                ImageDraw.Draw(im).text((100, 900), "EffectCraft\n(--ec)", font=ImageFont.truetype(FONT_BOLD, 100), fill=(255, 255, 255))
            else:
                mp4 = T.render_card("Заголовок карточки", "подзаголовок", cid, 2.0)
                png = out / f"_{cid}.png"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.2", "-i", str(mp4), "-frames:v", "1", str(png)], check=True)
                im = Image.open(png)
        else:
            ti, su = CARD_SAMPLES.get(cid, ("Заголовок карточки", "подзаголовок"))
            im = t.render(ti, su, t.resolve({}))
        tiles.append((cid, im))
    sheet(tiles, out / "cards.png")
    mp4 = T.render_card("Сервер опустел", "никто не знает почему", "big_number", 2.0)  # ffmpeg path smoke test
    print("card clip:", mp4, mp4.stat().st_size)
    print(T.counts())


main()
