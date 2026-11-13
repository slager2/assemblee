"""Card styles. The first seven are the EffectCraft cards of cards.py (animated); the rest are Pillow stills with a fade."""
import re

from PIL import Image, ImageDraw, ImageFilter

from .config import FONT_BOLD, FONT_BOOK, H, W
from .templates import (FONT_SERIF, FONT_SERIF_ITALIC, FONT_UBUNTU, ink, fit_text, font, pcolor, penum, pint, register, rgb, text_w,
                        vgradient)

PALETTES = {"night": ((12, 14, 28), (30, 20, 60), (240, 240, 250)), "paper": ((244, 238, 224), (230, 220, 200), (30, 28, 26)),
            "sunset": ((255, 120, 70), (120, 40, 110), (255, 255, 255)), "ocean": ((10, 60, 100), (4, 20, 50), (235, 248, 255)),
            "neon": ((20, 6, 40), (4, 4, 14), (250, 245, 255)), "mono": ((235, 235, 235), (200, 200, 205), (20, 20, 24))}
PAL = penum("palette", list(PALETTES), "night", "палитра фона")
ACC = pcolor("color", "yellow", "акцентный цвет")

for _id, _d, _m in [("joining_server", "тёмная заставка «Joining server...» с глитчем (анимация)", "game horror tech"),
                    ("glitch", "глитч-карточка с красным акцентом (анимация)", "horror loud"),
                    ("retro2011", "синяя карточка в духе 2011, желтый акцент (анимация)", "retro nostalgic"),
                    ("cartoon", "оранжевая мультяшная карточка с обводкой (анимация)", "fun pop"),
                    ("system", "синее окно [СИСТЕМА] (анимация)", "game system tech"),
                    ("minimal", "тёмная минималистичная карточка с золотой чертой (анимация)", "calm elegant"),
                    ("final", "чёрный финал с плавным уходом в темноту (анимация)", "ending calm")]:
    register("card", _id, _d, _m, engine="effectcraft")(None)


class Canvas:
    def __init__(self, p, w=W, h_=H):
        a, b, self.fg = PALETTES[p.get("palette", "night")]
        self.img = vgradient(a, b, (w, h_))
        self.d = ImageDraw.Draw(self.img)
        self.acc = rgb(p.get("color", "yellow"))
        self.dim = tuple(int(v * 0.6 + (255 - v) * 0.0) if sum(self.fg) > 400 else int(v * 0.5) for v in self.fg)

    def text(self, s, path, size, y, width=W - 140, max_lines=3, fill=None, upper=False, x=W / 2, anchor="ma", lh=1.2, min_size=30):
        f, lines, sz = fit_text(s, path, size, width, max_lines, min_size, upper)
        for i, l in enumerate(lines):
            self.d.text((x, y + i * sz * lh), l, font=f, fill=fill or self.fg, anchor=anchor)
        return y + len(lines) * sz * lh, f, lines, sz


def _items(s):
    return [x.strip() for x in re.split(r"[;|\n]", s) if x.strip()]


def _center_block(heights, total=H):
    return (total - heights) / 2


@register("card", "big_number", "огромное число или слово-удар (card_title), подпись под ним", "stat shock bold", (PAL, ACC))
def big_number(title, sub, p):
    c = Canvas(p)
    f, lines, sz = fit_text(title, FONT_BOLD, 420, W - 120, 1, 60)
    hb = len(lines) * sz * 1.1 + (160 if sub else 0)
    y = _center_block(hb) + 20
    for i, l in enumerate(lines):
        c.d.text((W / 2, y + i * sz * 1.1), l, font=f, fill=c.acc, anchor="ma")
    y += len(lines) * sz * 1.1 + 30
    c.d.rectangle((W / 2 - 110, y, W / 2 + 110, y + 10), fill=c.fg)
    if sub:
        c.text(sub, FONT_BOOK, 56, y + 50, width=W - 200, max_lines=3)
    return c.img


@register("card", "split_two", "экран из двух цветов: сверху заголовок, снизу подпись на цветной половине", "contrast bold modern", (PAL, ACC))
def split_two(title, sub, p):
    c = Canvas(p)
    c.d.rectangle((0, H // 2, W, H), fill=c.acc)
    c.d.polygon([(0, H // 2 - 70), (W, H // 2 + 70), (W, H // 2 + 80), (0, H // 2 - 60)], fill=c.fg)
    f, lines, sz = fit_text(title, FONT_BOLD, 150, W - 160, 4, 60)
    y = H // 4 - len(lines) * sz * 1.18 / 2 - 30
    for i, l in enumerate(lines):
        c.d.text((W / 2, y + i * sz * 1.18), l, font=f, fill=c.fg, anchor="ma")
    if sub:
        f, lines, sz = fit_text(sub, FONT_BOLD, 90, W - 160, 4, 40)
        y = H * 3 // 4 - len(lines) * sz * 1.2 / 2 + 40
        for i, l in enumerate(lines):
            c.d.text((W / 2, y + i * sz * 1.2), l, font=f, fill=ink(c.acc), anchor="ma")
    return c.img


@register("card", "quote_card", "цитата крупным курсивом (card_title), автор — card_subtitle", "wisdom calm story", (PAL, ACC))
def quote_card(title, sub, p):
    c = Canvas(p)
    f, lines, sz = fit_text(title, FONT_SERIF_ITALIC, 110, W - 220, 7, 50)
    hb = len(lines) * sz * 1.25 + 300 + (110 if sub else 0)
    y = _center_block(hb)
    c.d.text((W / 2, y - 30), "“", font=font(FONT_SERIF, 420), fill=c.acc, anchor="ma")
    y += 260
    for i, l in enumerate(lines):
        c.d.text((W / 2, y + i * sz * 1.25), l, font=f, fill=c.fg, anchor="ma")
    y += len(lines) * sz * 1.25 + 40
    if sub:
        c.d.line((W / 2 - 60, y, W / 2 + 60, y), fill=c.acc, width=6)
        c.text("— " + sub, FONT_BOOK, 52, y + 30, width=W - 240, max_lines=2, fill=c.acc)
    return c.img


@register("card", "checklist", "список с галочками: заголовок card_title, пункты в card_subtitle через «;»", "list tips useful", (PAL, ACC))
def checklist(title, sub, p):
    c = Canvas(p)
    items = _items(sub)[:6] or ["…"]
    row = 210
    f, tl, tsz = fit_text(title, FONT_BOLD, 120, W - 160, 2)
    y = _center_block(len(tl) * tsz * 1.2 + 70 + row * len(items))
    for i, l in enumerate(tl):
        c.d.text((W / 2, y + i * tsz * 1.2), l, font=f, fill=c.fg, anchor="ma")
    y += len(tl) * tsz * 1.2 + 70
    for it in items:
        bf, bl, bs = fit_text(it, FONT_BOOK, 76, W - 340, 2, 34)
        c.d.rounded_rectangle((100, y, 100 + 90, y + 90), 18, fill=c.acc)
        c.d.line([(122, y + 46), (143, y + 68), (178, y + 24)], fill=ink(c.acc), width=12, joint="curve")
        for i, l in enumerate(bl):
            c.d.text((230, y + 45 - len(bl) * bs * 1.2 / 2 + i * bs * 1.2), l, font=bf, fill=c.fg)
        y += row
    return c.img


@register("card", "vs_card", "два соперника «А vs Б» (card_title) по половинам, VS-значок в центре", "versus compare battle", (PAL, pcolor("color", "red", "цвет значка")))
def vs_card(title, sub, p):
    c = Canvas(p)
    parts = [x.strip() for x in re.split(r"\s+(?:vs|VS|Vs|против)\s+|\|", title) if x.strip()]
    a, b = (parts + ["?", "?"])[:2] if len(parts) >= 2 else (title, "?")
    c.d.rectangle((0, H // 2, W, H), fill=tuple(int(v * 0.8) for v in PALETTES[p["palette"]][1]))
    for txt, cy in ((a, H // 4 - 60), (b, H * 3 // 4 + 60)):
        f, lines, sz = fit_text(txt, FONT_BOLD, 150, W - 160, 3, 50)
        y = cy - len(lines) * sz * 1.15 / 2
        for i, l in enumerate(lines):
            c.d.text((W / 2, y + i * sz * 1.15), l, font=f, fill=c.fg, anchor="ma")
    r = 150
    c.d.ellipse((W / 2 - r, H / 2 - r, W / 2 + r, H / 2 + r), fill=c.acc, outline=c.fg, width=12)
    c.d.text((W / 2, H / 2), "VS", font=font(FONT_BOLD, 150), fill=ink(c.acc), anchor="mm")
    if sub:
        c.text(sub, FONT_BOOK, 46, H / 2 + 190, width=W - 240, max_lines=2, fill=c.fg)
    return c.img


@register("card", "timeline", "вертикальная шкала времени: пункты в card_subtitle через «;» (например «2019: старт; 2021: успех»)", "history progress story", (PAL, ACC))
def timeline(title, sub, p):
    c = Canvas(p)
    items = _items(sub)[:5] or ["…"]
    step = 300
    f, tl, tsz = fit_text(title, FONT_BOLD, 120, W - 160, 2)
    y = _center_block(len(tl) * tsz * 1.2 + 110 + step * (len(items) - 1)) - 20
    for i, l in enumerate(tl):
        c.d.text((W / 2, y + i * tsz * 1.2), l, font=f, fill=c.fg, anchor="ma")
    top = y + len(tl) * tsz * 1.2 + 130
    x = 200
    c.d.line((x, top, x, top + step * (len(items) - 1)), fill=c.acc, width=10)
    for i, it in enumerate(items):
        cy = top + i * step
        c.d.ellipse((x - 30, cy - 30, x + 30, cy + 30), fill=c.acc, outline=c.fg, width=8)
        label, _, rest = it.partition(":")
        if not rest:
            label, rest = "", it
        if label:
            c.d.text((x + 70, cy - 84), label.strip()[:12], font=font(FONT_BOLD, 64), fill=c.acc)
        f, lines, sz = fit_text(rest.strip(), FONT_BOOK, 68, W - x - 140, 2, 32)
        for k, l in enumerate(lines):
            c.d.text((x + 70, cy - (8 if label else 30) + k * sz * 1.2), l, font=f, fill=c.fg)
    return c.img


@register("card", "poll_card", "вопрос-опрос: вопрос в card_title, варианты в card_subtitle через «;»", "interactive question social", (PAL, ACC))
def poll_card(title, sub, p):
    c = Canvas(p)
    opts = _items(sub)[:4] or ["Да", "Нет"]
    f, lines, sz = fit_text(title, FONT_BOLD, 100, W - 220, 4, 48)
    bh = len(lines) * sz * 1.2 + 90
    y0 = 300
    c.d.rounded_rectangle((60, y0, W - 60, y0 + bh), 44, fill=c.acc)
    for i, l in enumerate(lines):
        c.d.text((W / 2, y0 + 45 + i * sz * 1.2), l, font=f, fill=ink(c.acc), anchor="ma")
    y = y0 + bh + 90
    fills = [0.62, 0.38, 0.2, 0.1]
    for i, o in enumerate(opts):
        c.d.rounded_rectangle((80, y, W - 80, y + 150), 36, fill=tuple(int(v * 0.55 + 20) for v in PALETTES[p["palette"]][1]), outline=c.fg, width=4)
        c.d.rounded_rectangle((110, y + 112, 110 + int((W - 220) * fills[i]), y + 126), 7, fill=c.acc)
        bf, bl, bs = fit_text(o, FONT_BOLD, 70, W - 300, 1, 32)
        c.d.text((120, y + 52), f"{chr(65 + i)}  {bl[0]}", font=bf, fill=c.fg, anchor="lm")
        y += 200
    return c.img


@register("card", "chapter", "заставка главы: «ГЛАВА N» мелко, название крупно, тонкая линия", "story cinematic calm", (PAL, ACC, pint("number", 1, 20, 1, "номер главы")))
def chapter(title, sub, p):
    c = Canvas(p)
    f, lines, sz = fit_text(title, FONT_SERIF, 130, W - 200, 3, 60)
    hb = 120 + len(lines) * sz * 1.2 + (110 if sub else 0)
    y = _center_block(hb)
    c.d.text((W / 2, y), f"ГЛАВА {p['number']}", font=font(FONT_BOLD, 60), fill=c.acc, anchor="ma")
    c.d.line((W / 2 - 90, y + 85, W / 2 + 90, y + 85), fill=c.acc, width=4)
    y += 130
    for i, l in enumerate(lines):
        c.d.text((W / 2, y + i * sz * 1.2), l, font=f, fill=c.fg, anchor="ma")
    if sub:
        c.text(sub, FONT_BOOK, 62, y + len(lines) * sz * 1.2 + 30, width=W - 260, max_lines=2, fill=c.fg)
    return c.img


@register("card", "end_cta", "финальный экран с призывом: заголовок и кнопка-пилюля с текстом card_subtitle", "ending social call", (PAL, ACC))
def end_cta(title, sub, p):
    c = Canvas(p)
    y, f, lines, sz = c.text(title, FONT_BOLD, 130, 560, width=W - 160, max_lines=3)
    y += 80
    label = sub or "Подпишись"
    bf, bl, bs = fit_text(label, FONT_BOLD, 66, W - 380, 1, 34)
    w = text_w(bl[0], bf) + 150
    c.d.rounded_rectangle(((W - w) / 2, y, (W + w) / 2, y + 150), 75, fill=c.acc)
    c.d.text((W / 2 - 30, y + 75), bl[0], font=bf, fill=ink(c.acc), anchor="mm")
    ax = (W + w) / 2 - 80
    c.d.polygon([(ax - 12, y + 45), (ax + 28, y + 75), (ax - 12, y + 105)], fill=ink(c.acc))
    for cx, cy, r in ((160, 300, 90), (W - 140, 1560, 130), (W - 220, 380, 40), (190, 1500, 50)):
        c.d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=c.acc, width=8)
    return c.img


@register("card", "sticky_note", "жёлтая бумажка-стикер с наклоном и скотчем: заметка (card_title + card_subtitle)", "personal fun notes", (PAL, pcolor("color", "yellow", "цвет бумажки")))
def sticky_note(title, sub, p):
    c = Canvas(p)
    note = Image.new("RGBA", (860, 960), (0, 0, 0, 0))
    d = ImageDraw.Draw(note)
    d.rectangle((0, 0, 859, 959), fill=tuple(min(255, v) for v in rgb(p["color"])) + (255,))
    d.polygon([(860, 900), (860, 960), (800, 960)], fill=tuple(int(v * 0.8) for v in rgb(p["color"])) + (255,))
    f, lines, sz = fit_text(title, FONT_SERIF_ITALIC, 124, 700, 4, 46)
    y = 130
    for i, l in enumerate(lines):
        d.text((430, y + i * sz * 1.2), l, font=f, fill=(30, 25, 20), anchor="ma")
    y += len(lines) * sz * 1.2 + 40
    if sub:
        sf, sl, ss = fit_text(sub, FONT_SERIF_ITALIC, 76, 700, 4, 34)
        for i, l in enumerate(sl):
            d.text((430, y + i * ss * 1.25), l, font=sf, fill=(70, 55, 40), anchor="ma")
    d.rectangle((300, -16, 560, 56), fill=(235, 235, 225, 200))
    rot = note.rotate(4, resample=Image.BICUBIC, expand=True)
    sh = rot.getchannel("A").filter(ImageFilter.GaussianBlur(20)).point(lambda v: int(v * 0.6))
    x, yy = (W - rot.width) // 2, (H - rot.height) // 2
    c.img.paste((0, 0, 0), (x + 10, yy + 24), sh)
    c.img.paste(rot, (x, yy), rot)
    return c.img


@register("card", "headline_news", "первая полоса газеты: шапка, огромный заголовок, колонки-«текст» под ним", "news retro serious", (pcolor("color", "red", "цвет метки"),))
def headline_news(title, sub, p):
    img = Image.new("RGB", (W, H), (240, 234, 218))
    d = ImageDraw.Draw(img)
    ink_c = (25, 22, 20)
    d.text((W / 2, 110), "ВЕЧЕРНИЙ ВЕСТНИК", font=font(FONT_SERIF, 78), fill=ink_c, anchor="ma")
    for dy, wd in ((220, 8), (238, 3), (H - 150, 3), (H - 134, 8)):
        d.line((50, dy, W - 50, dy), fill=ink_c, width=wd)
    tf = font(FONT_BOLD, 38)
    d.rectangle((50, 270, 50 + text_w("СРОЧНО", tf) + 40, 328), fill=rgb(p["color"]))
    d.text((70, 276), "СРОЧНО", font=tf, fill=ink(rgb(p["color"])))
    f, lines, sz = fit_text(title, FONT_SERIF, 150, W - 120, 5, 56, upper=True)
    y = 380
    for i, l in enumerate(lines):
        d.text((60, y + i * sz * 1.12), l, font=f, fill=ink_c)
    y += len(lines) * sz * 1.12 + 40
    if sub:
        sf, sl, ss = fit_text(sub, FONT_SERIF_ITALIC, 56, W - 120, 3, 32)
        for i, l in enumerate(sl):
            d.text((60, y + i * ss * 1.25), l, font=sf, fill=(70, 66, 60))
        y += len(sl) * ss * 1.25 + 40
    d.line((50, y, W - 50, y), fill=ink_c, width=3)
    y += 30
    colw = (W - 140) // 2
    for cx in (50, 90 + colw):
        for k, yy in enumerate(range(int(y), H - 190, 34)):
            wdt = colw - (80 if k % 7 == 6 else 0)
            d.rectangle((cx, yy, cx + wdt, yy + 14), fill=(150, 144, 132))
    return img
