"""Picture layouts: how a picture (or two or three) sits in the 1080x1920 frame. Pillow only."""
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from .config import H, W
from .templates import (COLORS, FONT_MONO, blur_bg, contain, cover, drop_shadow, font, paste_rotated, pcolor, pint, penum, register,
                        rgb, rounded_mask, vgradient)

FOCUS = (pint("focus_x", 0, 100, 50, "точка интереса по горизонтали, %"), pint("focus_y", 0, 100, 50, "точка интереса по вертикали, %"))


def _f(p):
    return p.get("focus_x", 50) / 100, p.get("focus_y", 50) / 100


@register("layout", "fill_focus", "на весь кадр с обрезкой; focus_x/focus_y — что должно остаться в кадре", "action bold full", FOCUS)
def fill_focus(ims, p):
    return cover(ims[0], W, H, *_f(p))


@register("layout", "blur_letterbox", "вся картинка по центру на размытом тёмном фоне из неё же", "calm wide soft", (pint("dim", 20, 80, 45, "яркость фона, %"),))
def blur_letterbox(ims, p):
    im = ims[0]
    bg = blur_bg(im, p["dim"] / 100)
    fg = contain(im, W, int(H * 0.8))
    box = ((W - fg.width) // 2, (H - fg.height) // 2)
    drop_shadow(bg, (box[0], box[1], box[0] + fg.width, box[1] + fg.height), 0, 20, 170, (0, 10))
    bg.paste(fg, box)
    return bg


@register("layout", "contain_solid", "картинка целиком на однотонном фоне с полями", "clean minimal calm",
          (pcolor("bg", "black", "цвет фона"), pint("pad", 0, 120, 40, "поля, px")))
def contain_solid(ims, p):
    c = Image.new("RGB", (W, H), rgb(p["bg"]))
    fg = contain(ims[0], W - 2 * p["pad"], int(H * 0.8))
    c.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    return c


@register("layout", "contain_gradient", "картинка целиком на вертикальном градиенте из двух цветов", "dreamy soft pop",
          (pcolor("bg", "purple", "верх"), pcolor("bg2", "black", "низ"), pint("pad", 0, 120, 50, "поля, px")))
def contain_gradient(ims, p):
    c = vgradient(rgb(p["bg"]), rgb(p["bg2"]))
    fg = contain(ims[0], W - 2 * p["pad"], int(H * 0.8))
    box = ((W - fg.width) // 2, (H - fg.height) // 2)
    drop_shadow(c, (box[0], box[1], box[0] + fg.width, box[1] + fg.height), 0, 24, 140)
    c.paste(fg, box)
    return c


@register("layout", "polaroid", "белая рамка-полароид, чуть наклонена, на фоне стены", "nostalgic warm memory",
          (pcolor("bg", "orange", "цвет стены"), pint("tilt", -10, 10, -4, "наклон, градусы")) + FOCUS)
def polaroid(ims, p):
    bgc = rgb(p["bg"])
    c = vgradient(tuple(int(v * 0.55) for v in bgc), tuple(int(v * 0.25) for v in bgc))
    fw, fh = 900, 1130
    card = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    ImageDraw.Draw(card).rectangle((0, 0, fw - 1, fh - 1), fill=(246, 244, 236, 255))
    card.paste(cover(ims[0], 800, 800, *_f(p)), (50, 50))
    ImageDraw.Draw(card).rectangle((50, 50, 849, 849), outline=(200, 198, 190), width=2)
    paste_rotated(c, card, p["tilt"], (W / 2, H / 2 - 40))
    return c


@register("layout", "phone_mockup", "картинка на экране смартфона (рамка, вырез), фон размыт", "tech modern social",
          (pint("bezel", 14, 40, 26, "толщина рамки"),) + FOCUS)
def phone_mockup(ims, p):
    c = blur_bg(ims[0], 0.35)
    sw, sh = 700, 1450
    b = p["bezel"]
    bw, bh = sw + 2 * b, sh + 2 * b
    x, y = (W - bw) // 2, (H - bh) // 2
    drop_shadow(c, (x, y, x + bw, y + bh), 90, 30, 190, (0, 20))
    d = ImageDraw.Draw(c)
    d.rounded_rectangle((x, y, x + bw, y + bh), 90, fill=(18, 18, 22), outline=(70, 70, 78), width=4)
    scr = cover(ims[0], sw, sh, *_f(p))
    c.paste(scr, (x + b, y + b), rounded_mask((sw, sh), 70))
    d.rounded_rectangle((W // 2 - 90, y + b + 18, W // 2 + 90, y + b + 56), 20, fill=(10, 10, 12))
    d.rounded_rectangle((W // 2 - 130, y + bh - b - 30, W // 2 + 130, y + bh - b - 22), 4, fill=(235, 235, 240))
    return c


@register("layout", "split_screen", "две картинки: верхняя и нижняя половины, разделитель", "versus contrast compare",
          (pcolor("bg", "white", "цвет разделителя"), pint("gap", 0, 40, 12, "ширина разделителя")) + FOCUS, assets=2)
def split_screen(ims, p):
    c = Image.new("RGB", (W, H), rgb(p["bg"]))
    hh = (H - p["gap"]) // 2
    c.paste(cover(ims[0], W, hh, *_f(p)), (0, 0))
    c.paste(cover(ims[1], W, hh), (0, hh + p["gap"]))
    return c


@register("layout", "triptych", "три картинки: три полосы (rows — строки, cols — колонки)", "rhythm collection series",
          (penum("dir", ["rows", "cols"], "rows", "направление"), pcolor("bg", "black", "разделитель"), pint("gap", 0, 30, 10, "ширина разделителя")), assets=3)
def triptych(ims, p):
    c = Image.new("RGB", (W, H), rgb(p["bg"]))
    g = p["gap"]
    if p["dir"] == "rows":
        hh = (H - 2 * g) // 3
        for i, im in enumerate(ims):
            c.paste(cover(im, W, hh), (0, i * (hh + g)))
    else:
        ww = (W - 2 * g) // 3
        for i, im in enumerate(ims):
            c.paste(cover(im, ww, H), (i * (ww + g), 0))
    return c


@register("layout", "pip", "картинка-картинка: большая на весь кадр и маленькая в углу в рамке", "reaction commentary social",
          (penum("corner", ["tl", "tr", "bl", "br"], "br", "угол"), pint("pip_size", 25, 50, 38, "ширина врезки, % кадра"), pcolor("bg", "white", "цвет рамки")), assets=2)
def pip(ims, p):
    c = cover(ims[0], W, H)
    pw = int(W * p["pip_size"] / 100)
    ph = int(pw * 1.25)
    m = 50
    x = m if p["corner"] in ("tl", "bl") else W - pw - m
    y = 260 if p["corner"] in ("tl", "tr") else H - ph - 360
    drop_shadow(c, (x - 8, y - 8, x + pw + 8, y + ph + 8), 24, 18, 190)
    d = ImageDraw.Draw(c)
    d.rounded_rectangle((x - 8, y - 8, x + pw + 8, y + ph + 8), 24, fill=rgb(p["bg"]))
    c.paste(cover(ims[1], pw, ph), (x, y), rounded_mask((pw, ph), 18))
    return c


@register("layout", "film_strip", "плёнка с перфорацией, несколько кадров друг под другом", "retro cinema nostalgic",
          (pint("frames", 2, 4, 3, "кадров"), pcolor("bg", "black", "цвет плёнки")), assets=3)
def film_strip(ims, p):
    c = Image.new("RGB", (W, H), tuple(int(v * 0.9) for v in rgb(p["bg"])))
    d = ImageDraw.Draw(c)
    n = p["frames"]
    sx, sw = 150, W - 300
    gap = 36
    fh = (H - 200 - gap * (n - 1)) // n
    for i in range(n):
        y = 100 + i * (fh + gap)
        c.paste(cover(ims[i % len(ims)], sw, fh), (sx, y))
    for side in (40, W - 40 - 56):  # sprocket holes
        for y in range(10, H, 84):
            d.rounded_rectangle((side, y, side + 56, y + 48), 10, fill=(235, 232, 220))
    d.rectangle((sx - 8, 0, sx - 4, H), fill=(60, 60, 60))
    d.rectangle((sx + sw + 4, 0, sx + sw + 8, H), fill=(60, 60, 60))
    return c


@register("layout", "torn_paper", "картинка с рваным краем на бумажном фоне", "handmade scrapbook warm",
          (pcolor("bg", "orange", "цвет бумаги"), pint("seed", 0, 20, 3, "форма разрыва")) + FOCUS)
def torn_paper(ims, p):
    rnd = random.Random(p["seed"])
    base = tuple(min(255, int(v * 0.35 + 150)) for v in rgb(p["bg"]))
    c = Image.new("RGB", (W, H), base)
    noise = Image.effect_noise((W // 4, H // 4), 18).resize((W, H)).convert("RGB")
    c = ImageChops.blend(c, ImageChops.multiply(c, noise), 0.25)
    pw, ph = 940, 1300
    x0, y0 = (W - pw) // 2, 240
    m = Image.new("L", (pw, ph), 0)

    def edge(n, length):
        return [rnd.randint(0, 26) for _ in range(n)]
    pts = [(i * 20, e) for i, e in enumerate(edge(pw // 20 + 1, pw))]
    pts += [(pw - e, i * 24) for i, e in enumerate(edge(ph // 24 + 1, ph))]
    pts += [(pw - i * 20, ph - e) for i, e in enumerate(edge(pw // 20 + 1, pw))]
    pts += [(e, ph - i * 24) for i, e in enumerate(edge(ph // 24 + 1, ph))]
    ImageDraw.Draw(m).polygon(pts, fill=255)
    paper = Image.new("RGBA", (pw + 40, ph + 40), (0, 0, 0, 0))
    white = Image.new("RGBA", (pw, ph), (245, 241, 230, 255))
    white.putalpha(m)
    paper.alpha_composite(white, (20, 20))
    img = cover(ims[0], pw - 60, ph - 60, *_f(p)).convert("RGBA")
    inner = Image.new("L", (pw - 60, ph - 60), 0)
    ImageDraw.Draw(inner).polygon([(max(0, min(pw - 61, x - 30)), max(0, min(ph - 61, y - 30))) for x, y in pts], fill=255)
    img.putalpha(inner)
    paper.alpha_composite(img, (50, 50))
    paste_rotated(c, paper, -2, (W / 2, y0 + ph / 2))
    return c


@register("layout", "rounded_card", "скруглённая карточка с тенью на размытом фоне", "soft modern app",
          (pint("radius", 20, 120, 60, "радиус углов"),) + FOCUS)
def rounded_card(ims, p):
    c = blur_bg(ims[0], 0.5)
    cw, ch = 940, 1420
    x, y = (W - cw) // 2, (H - ch) // 2
    drop_shadow(c, (x, y, x + cw, y + ch), p["radius"], 30, 190, (0, 24))
    c.paste(cover(ims[0], cw, ch, *_f(p)), (x, y), rounded_mask((cw, ch), p["radius"]))
    return c


@register("layout", "circle_mask", "картинка в большом круге с обводкой", "focus portrait calm",
          (pcolor("bg", "purple", "фон"), pcolor("ring", "white", "обводка"), pint("ring_w", 0, 30, 14, "толщина обводки")) + FOCUS)
def circle_mask(ims, p):
    bgc = rgb(p["bg"])
    c = vgradient(tuple(int(v * 0.8) for v in bgc), tuple(int(v * 0.25) for v in bgc))
    dia = 960
    x, y = (W - dia) // 2, (H - dia) // 2
    d = ImageDraw.Draw(c)
    if p["ring_w"]:
        d.ellipse((x - p["ring_w"], y - p["ring_w"], x + dia + p["ring_w"], y + dia + p["ring_w"]), fill=rgb(p["ring"]))
    m = Image.new("L", (dia * 2, dia * 2), 0)
    ImageDraw.Draw(m).ellipse((0, 0, dia * 2 - 1, dia * 2 - 1), fill=255)
    c.paste(cover(ims[0], dia, dia, *_f(p)), (x, y), m.resize((dia, dia), Image.LANCZOS))
    return c


@register("layout", "duotone_poster", "двухцветный постер: тень и свет из двух цветов, рамка", "bold poster graphic",
          (pcolor("bg", "purple", "тени"), pcolor("bg2", "yellow", "света"), pint("frame", 0, 60, 30, "рамка, px")) + FOCUS)
def duotone_poster(ims, p):
    g = ImageOps.autocontrast(ImageOps.grayscale(cover(ims[0], W, H, *_f(p))), cutoff=2)
    c = ImageOps.colorize(g, rgb(p["bg"]), rgb(p["bg2"]))
    if p["frame"]:
        ImageDraw.Draw(c).rectangle((0, 0, W - 1, H - 1), outline=rgb(p["bg2"]), width=p["frame"])
    return c


@register("layout", "comic_panel", "панель комикса: косые края, чёрная рамка, точки-растр на бумаге", "comic pop fun",
          (pcolor("bg", "yellow", "бумага"), pint("border", 6, 30, 16, "рамка")) + FOCUS)
def comic_panel(ims, p):
    c = Image.new("RGB", (W, H), tuple(min(255, int(v * 0.3 + 180)) for v in rgb(p["bg"])))
    d = ImageDraw.Draw(c)
    for y in range(0, H, 36):  # halftone dots, fading to the bottom
        for x in range(0, W, 36):
            r = int(11 * (1 - y / H))
            if r > 1:
                ox = 18 if (y // 36) % 2 else 0
                d.ellipse((x + ox - r, y - r, x + ox + r, y + r), fill=tuple(int(v * 0.75) for v in rgb(p["bg"])))
    poly = [(70, 150), (W - 50, 100), (W - 70, 1500), (50, 1560)]
    pm = Image.new("L", (W, H), 0)
    ImageDraw.Draw(pm).polygon(poly, fill=255)
    c.paste(cover(ims[0], W, H, *_f(p)), (0, 0), pm)
    d.polygon(poly, outline=(10, 10, 12), width=p["border"])
    small = [(60, 1600), (W // 2 - 20, 1620), (W // 2 - 40, 1850), (80, 1840)]
    d.polygon(small, fill=(255, 255, 255), outline=(10, 10, 12), width=p["border"])
    return c


@register("layout", "vhs_crt", "экран старого ТВ: сдвиг каналов, строки развёртки, скруглённый кинескоп, PLAY", "retro glitch horror 90s",
          (pint("shift", 0, 24, 9, "сдвиг цветов"), pint("scan", 0, 100, 45, "сила строк, %")) + FOCUS)
def vhs_crt(ims, p):
    im = cover(ims[0], W, H, *_f(p))
    r, g, b = im.split()
    s = p["shift"]
    im = Image.merge("RGB", (ImageChops.offset(r, s, 0), g, ImageChops.offset(b, -s, 0)))
    ov = Image.new("L", (W, H), 0)
    od = ImageDraw.Draw(ov)
    for y in range(0, H, 6):
        od.rectangle((0, y, W, y + 2), fill=int(160 * p["scan"] / 100))
    im.paste((0, 0, 0), (0, 0), ov)
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).rounded_rectangle((20, 20, W - 20, H - 20), 110, fill=255)
    im = Image.composite(im, Image.new("RGB", (W, H), (6, 6, 8)), vig.filter(ImageFilter.GaussianBlur(3)))
    d = ImageDraw.Draw(im)
    d.text((90, 110), "PLAY ▶", font=font(FONT_MONO, 54), fill=(240, 240, 240), stroke_width=2, stroke_fill=(0, 0, 0))
    d.text((W - 90, 110), "SP 0:00:12", font=font(FONT_MONO, 44), fill=(240, 240, 240), anchor="ra", stroke_width=2, stroke_fill=(0, 0, 0))
    return im
