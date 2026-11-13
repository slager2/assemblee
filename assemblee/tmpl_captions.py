"""Caption styles: transparent 1080x1920 overlays with one text block. Pillow only.
The first five are the original styles (drawn by media._legacy_caption); the others are new."""
import re

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .config import FONT_BOLD, FONT_BOOK, FONT_MONO, H, W
from .templates import (FONT_SERIF, FONT_SERIF_ITALIC, FONT_SERIF_REG, FONT_TYPE, FONT_UBUNTU, ink, fit_text, font, penum, pcolor,
                        pint, register, rgb, text_w, vgradient, wrap_words)

ANCHOR = {"top": 0.15, "center": 0.5, "bottom": 0.75}
COLOR = pcolor("color", "yellow", "основной цвет")
COLOR2 = pcolor("color2", "red", "второй цвет")
SIZE = pint("size", 60, 140, 100, "размер текста, % от обычного")


class Cap:
    def __init__(self, text, position, p, size, width=W - 140, max_lines=3, path=FONT_BOLD, upper=False, min_size=28):
        self.img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
        self.cy = H * ANCHOR.get(position, 0.75)
        self.p = p
        self.c = rgb(p.get("color", "white"))
        self.c2 = rgb(p.get("color2", "red"))
        self.f, self.lines, self.size = fit_text(text, path, size * p.get("size", 100) / 100, width, max_lines, min_size, upper)
        self.lh = int(self.size * 1.25)
        self.top = self.cy - self.lh * len(self.lines) / 2

    def widths(self):
        return [text_w(l, self.f) for l in self.lines]


def _split_tail(text, seps=(" — ", "|", " – ")):
    for s in seps:
        if s in text:
            a, b = text.rsplit(s, 1)
            return a.strip(), b.strip()
    return text, ""


def _legacy(style):
    def render(text, position, p):
        from .media import _legacy_caption
        return _legacy_caption(text, style, position)
    return render


for _id, _d, _m in [("subtitle", "белый текст с чёрной обводкой, классические субтитры", "neutral clean"),
                    ("cartoon", "жирный жёлто-белый мультяшный текст с толстой обводкой", "fun pop loud"),
                    ("retro2011", "белый текст в сером окошке с рамкой, как старый интерфейс", "retro nostalgic 2011"),
                    ("system", "синяя игровая рамка [СИСТЕМА] с моноширинным текстом", "game tech system"),
                    ("glitch", "заглавные буквы с красно-голубым сдвигом, глитч", "horror glitch loud")]:
    register("caption", _id, _d, _m)(_legacy(_id))


@register("caption", "karaoke", "караоке: все слова белые, одно слово подсвечено цветной плашкой (word — номер слова)", "music energetic social",
          (COLOR, pint("word", 0, 9, 1, "номер подсвеченного слова"), SIZE))
def karaoke(text, pos, p):
    c = Cap(text, pos, p, 78, max_lines=3)
    idx = 0
    for i, words in enumerate(wrap_words(" ".join(c.lines), c.f, W - 140)):
        line = " ".join(words)
        x = (W - text_w(line, c.f)) / 2
        y = c.top + i * c.lh
        for w in words:
            ww = text_w(w, c.f)
            if idx == min(p["word"], 99):
                c.d.rounded_rectangle((x - 14, y - 4, x + ww + 14, y + c.size * 1.15), 18, fill=c.c)
                c.d.text((x, y), w, font=c.f, fill=ink(c.c))
            else:
                c.d.text((x, y), w, font=c.f, fill=(255, 255, 255), stroke_width=6, stroke_fill=(0, 0, 0, 230))
            x += ww + text_w(" ", c.f)
            idx += 1
    return c.img


@register("caption", "block_box", "жирные строки на цветных плашках-лейблах", "bold social loud", (pcolor("color", "red", "цвет плашки"), SIZE))
def block_box(text, pos, p):
    c = Cap(text, pos, p, 74, max_lines=3, upper=False)
    for i, l in enumerate(c.lines):
        w = text_w(l, c.f)
        y = c.top + i * c.lh
        c.d.rounded_rectangle(((W - w) / 2 - 28, y - 2, (W + w) / 2 + 28, y + c.lh - 8), 14, fill=c.c)
        c.d.text((W / 2, y + 4), l, font=c.f, fill=ink(c.c), anchor="ma")
    return c.img


@register("caption", "handwritten", "рукописный курсив, слегка наклонён, с волнистым подчёркиванием", "personal warm diary",
          (COLOR, SIZE))
def handwritten(text, pos, p):
    c = Cap(text, pos, p, 96, width=W - 220, max_lines=3, path=FONT_SERIF_ITALIC)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i, l in enumerate(c.lines):
        y = c.top + i * c.lh
        d.text((W / 2 + 4, y + 5), l, font=c.f, fill=(0, 0, 0, 170), anchor="ma", stroke_width=4, stroke_fill=(0, 0, 0, 170))
        d.text((W / 2, y), l, font=c.f, fill=c.c + (255,), anchor="ma", stroke_width=1, stroke_fill=(30, 20, 10, 255))
    y = c.top + len(c.lines) * c.lh + 6
    w = max(c.widths())
    pts = [((W - w) / 2 + k * 24, y + (10 if k % 2 else 0)) for k in range(int(w // 24) + 1)]
    d.line(pts, fill=c.c + (255,), width=6, joint="curve")
    c.img.alpha_composite(layer.rotate(-3, resample=Image.BICUBIC, center=(W / 2, c.cy)))
    return c.img


@register("caption", "neon", "неоновая вывеска: светящийся контур цвета color", "night club glow synth", (pcolor("color", "pink", "цвет свечения"), SIZE))
def neon(text, pos, p):
    c = Cap(text, pos, p, 92, max_lines=3, path=FONT_UBUNTU)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for i, l in enumerate(c.lines):
        gd.text((W / 2, c.top + i * c.lh), l, font=c.f, fill=c.c + (255,), anchor="ma", stroke_width=10, stroke_fill=c.c + (255,))
    c.img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(26)))
    c.img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(9)))
    for i, l in enumerate(c.lines):
        c.d.text((W / 2, c.top + i * c.lh), l, font=c.f, fill=(255, 255, 255, 255), anchor="ma", stroke_width=3, stroke_fill=c.c + (255,))
    return c.img


@register("caption", "outline", "только контур букв, внутри пусто", "bold modern graphic", (pcolor("color", "white", "цвет контура"), SIZE))
def outline(text, pos, p):
    c = Cap(text, pos, p, 110, max_lines=3, upper=True)
    big, small = Image.new("L", (W, H), 0), Image.new("L", (W, H), 0)
    bd, sd = ImageDraw.Draw(big), ImageDraw.Draw(small)
    for i, l in enumerate(c.lines):
        xy = (W / 2, c.top + i * c.lh)
        bd.text(xy, l, font=c.f, fill=255, anchor="ma", stroke_width=6)
        sd.text(xy, l, font=c.f, fill=255, anchor="ma")
    ring = ImageChops.subtract(big, small)
    shadow = ring.filter(ImageFilter.GaussianBlur(5)).point(lambda v: int(v * 0.8))
    c.img.paste((0, 0, 0), (0, 0), shadow)
    c.img.paste(c.c + (255,), (0, 0), ring)
    return c.img


@register("caption", "stacked", "первое слово огромное цветное, остальные мелко под ним", "emphasis title bold", (COLOR, SIZE))
def stacked(text, pos, p):
    words = text.split()
    head, rest = (words[0], " ".join(words[1:])) if len(words) > 1 else (text, "")
    hf, hl, hs = fit_text(head, FONT_BOLD, 190 * p["size"] / 100, W - 140, 1, upper=True)
    rf, rl, rs = fit_text(rest, FONT_BOLD, 62 * p["size"] / 100, W - 160, 2) if rest else (None, [], 0)
    c = Cap("x", pos, p, 20)
    total = hs * 1.1 + len(rl) * rs * 1.25 + 14
    y = c.cy - total / 2
    c.d.text((W / 2, y + 6), hl[0], font=hf, fill=(0, 0, 0, 200), anchor="ma", stroke_width=12, stroke_fill=(0, 0, 0, 200))
    c.d.text((W / 2, y), hl[0], font=hf, fill=c.c + (255,), anchor="ma", stroke_width=8, stroke_fill=(20, 20, 30, 255))
    y += hs * 1.1 + 14
    for l in rl:
        c.d.text((W / 2, y), l, font=rf, fill=(255, 255, 255, 255), anchor="ma", stroke_width=5, stroke_fill=(0, 0, 0, 235))
        y += rs * 1.25
    return c.img


@register("caption", "quote", "цитата: большая кавычка, курсив, автор после « — » или «|»", "wisdom calm story", (COLOR, SIZE))
def quote(text, pos, p):
    body, author = _split_tail(text)
    c = Cap(body, pos, p, 88, width=W - 240, max_lines=4, path=FONT_SERIF_ITALIC)
    af = font(FONT_BOOK, 44)
    h_total = len(c.lines) * c.lh + (80 if author else 0) + 120
    y = c.cy - h_total / 2
    c.d.text((W / 2, y - 40), "“", font=font(FONT_SERIF, 380), fill=c.c + (255,), anchor="ma")
    y += 130
    for l in c.lines:
        c.d.text((W / 2, y), l, font=c.f, fill=(255, 255, 255, 255), anchor="ma", stroke_width=4, stroke_fill=(0, 0, 0, 230))
        y += c.lh
    if author:
        c.d.text((W / 2, y + 10), "— " + author, font=af, fill=c.c + (255,), anchor="ma", stroke_width=4, stroke_fill=(0, 0, 0, 230))
    return c.img


@register("caption", "lower_third", "плашка-титр внизу: цветной штрих слева, первая строка жирная (вторая — после переноса строки)", "news documentary clean",
          (COLOR, SIZE))
def lower_third(text, pos, p):
    parts = text.split("\n", 1)
    c = Cap(parts[0], pos, p, 64, width=W - 300, max_lines=2)
    sub = parts[1] if len(parts) > 1 else ""
    sf, sl, ss = fit_text(sub, FONT_BOOK, 40, W - 300, 2) if sub else (None, [], 0)
    bh = len(c.lines) * c.lh + (len(sl) * ss * 1.3 + 12 if sl else 0) + 40
    y0 = c.cy - bh / 2
    c.d.rectangle((50, y0, W - 50, y0 + bh), fill=(10, 12, 20, 215))
    c.d.rectangle((50, y0, 74, y0 + bh), fill=c.c + (255,))
    y = y0 + 20
    for l in c.lines:
        c.d.text((110, y), l, font=c.f, fill=(255, 255, 255, 255))
        y += c.lh
    for l in sl:
        c.d.text((110, y + 4), l, font=sf, fill=c.c + (255,))
        y += ss * 1.3
    return c.img


@register("caption", "sticker", "наклонённый стикер: белая плашка с чёрной рамкой и тенью", "fun social pop", (pcolor("color", "yellow", "цвет плашки"), pint("tilt", -10, 10, -5, "наклон"), SIZE))
def sticker(text, pos, p):
    c = Cap(text, pos, p, 80, width=W - 300, max_lines=3, upper=True)
    w = max(c.widths()) + 90
    hgt = len(c.lines) * c.lh + 50
    st = Image.new("RGBA", (int(w) + 40, int(hgt) + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(st)
    d.rounded_rectangle((20, 20, w + 20, hgt + 20), 30, fill=c.c + (255,), outline=(15, 15, 20, 255), width=9)
    for i, l in enumerate(c.lines):
        d.text((st.width / 2, 20 + 25 + i * c.lh), l, font=c.f, fill=ink(c.c) + (255,), anchor="ma")
    rot = st.rotate(p["tilt"], resample=Image.BICUBIC, expand=True)
    pos_xy = (int(W / 2 - rot.width / 2), int(c.cy - rot.height / 2))
    sh = rot.getchannel("A").filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.55))
    c.img.paste((0, 0, 0), (pos_xy[0] + 6, pos_xy[1] + 16), sh)
    c.img.alpha_composite(rot, pos_xy)
    return c.img


@register("caption", "speech_bubble", "белый облачок-реплика с хвостиком, чёрный текст", "comic dialogue fun", (SIZE, penum("corner", ["bl", "br"], "bl", "куда смотрит хвостик")))
def speech_bubble(text, pos, p):
    c = Cap(text, pos, p, 74, width=W - 300, max_lines=4, path=FONT_UBUNTU)
    w = max(c.widths()) + 100
    hgt = len(c.lines) * c.lh + 60
    x0, y0 = (W - w) / 2, c.cy - hgt / 2
    left = p["corner"] == "bl"
    tx = x0 + 90 if left else x0 + w - 90
    tail = [(tx - 30, y0 + hgt - 6), (tx + 40, y0 + hgt - 6), (tx + (-30 if left else 30), y0 + hgt + 80)]
    c.d.rounded_rectangle((x0, y0, x0 + w, y0 + hgt), 50, fill=(255, 255, 255, 255), outline=(15, 15, 20, 255), width=7)
    c.d.polygon(tail, fill=(255, 255, 255, 255), outline=(15, 15, 20, 255))
    c.d.line([tail[0], tail[1]], fill=(255, 255, 255, 255), width=10)
    for i, l in enumerate(c.lines):
        c.d.text((W / 2, y0 + 30 + i * c.lh), l, font=c.f, fill=(15, 15, 20, 255), anchor="ma")
    return c.img


@register("caption", "typewriter", "печатная машинка: моноширинный текст на тёмной бумаге с курсором", "mystery doc noir", (pcolor("color", "green", "цвет букв"), SIZE))
def typewriter(text, pos, p):
    c = Cap(text, pos, p, 66, width=W - 240, max_lines=5, path=FONT_TYPE)
    w = max(c.widths()) + 140
    hgt = len(c.lines) * c.lh + 70
    x0, y0 = (W - w) / 2, c.cy - hgt / 2
    c.d.rectangle((x0, y0, x0 + w, y0 + hgt), fill=(12, 12, 14, 225), outline=c.c + (255,), width=3)
    for i, l in enumerate(c.lines):
        c.d.text((x0 + 70, y0 + 35 + i * c.lh), l, font=c.f, fill=c.c + (255,))
    ex = x0 + 70 + text_w(c.lines[-1], c.f) + 8
    ey = y0 + 35 + (len(c.lines) - 1) * c.lh
    c.d.rectangle((ex, ey + 4, ex + c.size * 0.55, ey + c.size * 1.1), fill=c.c + (255,))
    return c.img


@register("caption", "newspaper", "газетный заголовок: засечки, капслок, двойные линейки на бумаге, метка СРОЧНО", "news serious retro", (pcolor("color", "red", "цвет метки"), SIZE))
def newspaper(text, pos, p):
    c = Cap(text, pos, p, 82, width=W - 200, max_lines=3, path=FONT_SERIF, upper=True)
    hgt = len(c.lines) * c.lh + 100
    y0 = c.cy - hgt / 2
    c.d.rectangle((40, y0, W - 40, y0 + hgt), fill=(244, 238, 222, 245))
    for dy in (8, 16):
        c.d.line((60, y0 + dy, W - 60, y0 + dy), fill=(20, 20, 20, 255), width=2 if dy == 16 else 5)
        c.d.line((60, y0 + hgt - dy, W - 60, y0 + hgt - dy), fill=(20, 20, 20, 255), width=2 if dy == 16 else 5)
    for i, l in enumerate(c.lines):
        c.d.text((W / 2, y0 + 50 + i * c.lh), l, font=c.f, fill=(20, 20, 20, 255), anchor="ma")
    tf = font(FONT_BOLD, 34)
    tw = text_w("СРОЧНО", tf) + 40
    c.d.rectangle((60, y0 - 26, 60 + tw, y0 + 28), fill=c.c + (255,))
    c.d.text((80, y0 - 20), "СРОЧНО", font=tf, fill=ink(c.c) + (255,))
    return c.img


@register("caption", "speaker_sub", "субтитры с именем говорящего: «Имя: текст» (без имени — РАССКАЗЧИК)", "dialogue film story", (COLOR, SIZE))
def speaker_sub(text, pos, p):
    m = re.match(r"^\s*([^:\n]{1,18}):\s*(.+)$", text, re.S)
    name, body = (m.group(1).strip(), m.group(2)) if m else ("Рассказчик", text)
    c = Cap(body, pos, p, 76, max_lines=3)
    nf = font(FONT_BOLD, 40)
    name = name.upper()
    nw = text_w(name, nf) + 50
    ny = c.top - 70
    c.d.rounded_rectangle(((W - nw) / 2, ny, (W + nw) / 2, ny + 58), 29, fill=c.c + (255,))
    c.d.text((W / 2, ny + 8), name, font=nf, fill=ink(c.c) + (255,), anchor="ma")
    for i, l in enumerate(c.lines):
        c.d.text((W / 2, c.top + i * c.lh), l, font=c.f, fill=(255, 255, 255, 255), anchor="ma", stroke_width=6, stroke_fill=(0, 0, 0, 235))
    return c.img


@register("caption", "gradient_text", "жирный текст с вертикальным градиентом из двух цветов и обводкой", "pop modern glam", (pcolor("color", "yellow", "верх"), pcolor("color2", "pink", "низ"), SIZE))
def gradient_text(text, pos, p):
    c = Cap(text, pos, p, 100, max_lines=3, upper=True)
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    for i, l in enumerate(c.lines):
        c.d.text((W / 2, c.top + i * c.lh + 6), l, font=c.f, fill=(0, 0, 0, 160), anchor="ma", stroke_width=14, stroke_fill=(0, 0, 0, 160))
        c.d.text((W / 2, c.top + i * c.lh), l, font=c.f, fill=(0, 0, 0, 255), anchor="ma", stroke_width=9, stroke_fill=(0, 0, 0, 255))
        md.text((W / 2, c.top + i * c.lh), l, font=c.f, fill=255, anchor="ma")
    top, bot = int(c.top), int(c.top + len(c.lines) * c.lh)
    g = Image.new("RGB", (W, H), c.c)
    band = vgradient(c.c, c.c2, (W, max(1, bot - top)))
    g.paste(band, (0, top))
    g.paste(c.c2, (0, bot, W, H))
    c.img.paste(g, (0, 0), mask)
    return c.img


@register("caption", "shadow3d", "объёмный текст: цветная «выдавленная» тень вниз-вправо", "game bold retro", (pcolor("color", "white", "лицо"), pcolor("color2", "blue", "объём"), SIZE))
def shadow3d(text, pos, p):
    c = Cap(text, pos, p, 100, max_lines=3, upper=True)
    dark = tuple(int(v * 0.7) for v in c.c2)
    for i, l in enumerate(c.lines):
        xy = (W / 2, c.top + i * c.lh)
        for k in range(22, 0, -1):
            c.d.text((xy[0] + k * 0.8, xy[1] + k), l, font=c.f, fill=dark + (255,), anchor="ma", stroke_width=6, stroke_fill=dark + (255,))
        c.d.text(xy, l, font=c.f, fill=c.c + (255,), anchor="ma", stroke_width=6, stroke_fill=(15, 15, 25, 255))
    return c.img


@register("caption", "corner_tiny", "мелкая подпись в углу кадра на тёмной плашке (не закрывает картинку)", "minimal quiet cinematic",
          (penum("corner", ["tl", "tr", "bl", "br"], "bl", "угол"), COLOR))
def corner_tiny(text, pos, p):
    c = Cap(text, "center", p, 40, width=520, max_lines=3, path=FONT_BOOK, min_size=28)
    w = max(c.widths()) + 44
    hgt = len(c.lines) * c.lh + 24
    x0 = 50 if p["corner"] in ("tl", "bl") else W - 50 - w
    y0 = 130 if p["corner"] in ("tl", "tr") else H - 330 - hgt
    c.d.rounded_rectangle((x0, y0, x0 + w, y0 + hgt), 14, fill=(0, 0, 0, 170))
    c.d.rectangle((x0, y0 + 8, x0 + 5, y0 + hgt - 8), fill=c.c + (255,))
    for i, l in enumerate(c.lines):
        c.d.text((x0 + 24, y0 + 12 + i * c.lh), l, font=c.f, fill=(255, 255, 255, 255))
    return c.img


@register("caption", "countdown", "гигантское число (первое слово) в кольце, остальной текст мелко под ним", "tension count list", (COLOR, SIZE))
def countdown(text, pos, p):
    words = text.split()
    num, rest = (words[0], " ".join(words[1:])) if words else ("", "")
    c = Cap("x", pos, p, 20)
    nf, nl, ns = fit_text(num[:6], FONT_BOLD, 420 * p["size"] / 100, 560, 1)
    cy = c.cy - (40 if rest else 0)
    r = max(260, int(max(text_w(nl[0], nf) / 2 + 70, ns * 0.75)))
    c.d.ellipse((W / 2 - r, cy - r, W / 2 + r, cy + r), fill=(0, 0, 0, 150), outline=c.c + (255,), width=14)
    c.d.text((W / 2, cy), nl[0], font=nf, fill=(255, 255, 255, 255), anchor="mm", stroke_width=8, stroke_fill=(0, 0, 0, 255))
    if rest:
        rf, rl, rs = fit_text(rest, FONT_BOLD, 58, W - 200, 2)
        for i, l in enumerate(rl):
            c.d.text((W / 2, cy + r + 40 + i * rs * 1.25), l, font=rf, fill=c.c + (255,), anchor="ma", stroke_width=5, stroke_fill=(0, 0, 0, 235))
    return c.img


@register("caption", "marker", "текст, выделенный жёлтым маркером поверх строк", "study note highlight", (pcolor("color", "yellow", "цвет маркера"), SIZE))
def marker(text, pos, p):
    c = Cap(text, pos, p, 86, max_lines=3, path=FONT_UBUNTU)
    for i, l in enumerate(c.lines):
        w = text_w(l, c.f)
        y = c.top + i * c.lh
        x0, x1 = (W - w) / 2 - 18, (W + w) / 2 + 18
        c.d.polygon([(x0, y + c.size * 0.2), (x1 + 6, y + c.size * 0.1), (x1, y + c.size * 1.15), (x0 - 6, y + c.size * 1.2)], fill=c.c + (235,))
        c.d.text((W / 2, y), l, font=c.f, fill=(15, 15, 20, 255), anchor="ma")
    return c.img
