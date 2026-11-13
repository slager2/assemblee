"""Template registry: the FORM of a shot is chosen by the model from many templates, not hard-coded.

Three categories, each a dict id -> Template (id, Russian one-line description, mood tags, validated parameters, render):
    layout   a picture placed into the 1080x1920 frame            render(images: [PIL.Image], params) -> RGB image
    caption  an overlay text on a transparent frame               render(text, position, params)      -> RGBA image
    card     a full-screen title card                             render(title, subtitle, params)     -> RGB image (+ ffmpeg fade)
             (the first seven cards are the old EffectCraft ones: engine="effectcraft", rendered by cards.py)

Parameters are grammar-safe: integers with ranges (llama.cpp grammars ignore number min/max) and enums (colours are
names, not hex). Unknown or out-of-range values are fixed, never raised. The model-facing pieces are generated here:
    prompt_section(cats)      compact listing, one line per template
    schema_props(kind)        properties to merge into the picture/card shot schema
    resolve_*                 validation used by edl.make_shot / tools
Renders are cached on disk by (inputs, id, params, RENDER_VERSION, TEMPLATES_VERSION). Pillow only (no numpy).
"""
import difflib
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .config import FONT_BOLD, FONT_BOOK, FONT_MONO, H, RENDER_VERSION, W
from .media import cache_dir, h

TEMPLATES_VERSION = 1
FONT_SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
FONT_SERIF_ITALIC = "/usr/share/fonts/truetype/freefont/FreeSerifBoldItalic.ttf"
FONT_SERIF_REG = "/usr/share/fonts/truetype/freefont/FreeSerif.ttf"
FONT_UBUNTU = "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf"
FONT_TYPE = "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"

COLORS = {"white": (255, 255, 255), "yellow": (255, 214, 63), "red": (255, 64, 64), "cyan": (110, 215, 255),
          "pink": (255, 80, 160), "green": (90, 230, 120), "orange": (255, 150, 50), "purple": (170, 110, 255),
          "blue": (50, 110, 255), "black": (15, 15, 20)}
POSITIONS = ["top", "center", "bottom"]
CORNERS = ["tl", "tr", "bl", "br"]


# ------------------------------------------------------------------ parameters
@dataclass
class Param:
    name: str
    kind: str  # int | enum
    default: object
    lo: int = 0
    hi: int = 0
    options: tuple = ()
    desc: str = ""

    def short(self):
        if self.kind == "int":
            return f"{self.name} {self.lo}..{self.hi}"
        if self.options == tuple(COLORS):
            return f"{self.name} цвет"
        return f"{self.name} " + "|".join(self.options)


def pint(name, lo, hi, default, desc=""):
    return Param(name, "int", default, lo, hi, (), desc)


def penum(name, options, default, desc=""):
    return Param(name, "enum", default, 0, 0, tuple(options), desc)


def pcolor(name, default, desc=""):
    return Param(name, "enum", default, 0, 0, tuple(COLORS), desc)


@dataclass
class Template:
    id: str
    cat: str
    desc: str
    mood: tuple
    params: tuple
    render: object
    assets: int = 1  # layouts: how many pictures it shows (extra ones come from Shot.extra_assets)
    engine: str = "pillow"  # cards: "effectcraft" renders through cards.py

    def resolve(self, raw, warnings=None):
        """Validated parameter dict: every declared parameter present, ranges clamped, enums fuzzy-matched."""
        raw = raw if isinstance(raw, dict) else {}
        out = {}
        for p in self.params:
            v = raw.get(p.name, p.default)
            if p.kind == "int":
                try:
                    n = int(round(float(v)))
                except (TypeError, ValueError):
                    n = p.default
                if not p.lo <= n <= p.hi and warnings is not None:
                    warnings.append(f"{self.id}.{p.name}: {v} out of range {p.lo}..{p.hi}, clamped")
                out[p.name] = min(p.hi, max(p.lo, n))
            else:
                if v not in p.options:
                    close = difflib.get_close_matches(str(v).lower(), p.options, n=1, cutoff=0.5)
                    if warnings is not None and raw.get(p.name) is not None:
                        warnings.append(f"{self.id}.{p.name}: '{v}' is not allowed, used '{close[0] if close else p.default}'")
                    v = close[0] if close else p.default
                out[p.name] = v
        return out


REG = {"layout": {}, "caption": {}, "card": {}}


def register(cat, id, desc, mood="", params=(), assets=1, engine="pillow"):
    def deco(fn):
        REG[cat][id] = Template(id, cat, desc, tuple(mood.split()), tuple(params), fn, assets, engine)
        return fn
    return deco


def ids(cat):
    return list(REG[cat])


def get(cat, id):
    return REG[cat].get(id)


def resolve_id(cat, value, default, what, warnings):
    """Exact id, else the closest one (fuzzy), else the default. Corrections are reported."""
    if value in REG[cat]:
        return value
    if value in (None, ""):
        return default
    close = difflib.get_close_matches(str(value).lower(), list(REG[cat]), n=1, cutoff=0.5)
    fixed = close[0] if close else default
    warnings.append(f"{what}: '{value}' is not allowed, used '{fixed}'")
    return fixed


def resolve_params(cat, id, raw, warnings):
    t = REG[cat].get(id)
    return t.resolve(raw, warnings) if t else {}


# ------------------------------------------------------------------ model-facing text and schema
CAT_TITLES = {"layout": "РАСКЛАДКИ КАРТИНКИ (layout; extra_assets — доп. картинки для split_screen/triptych/pip/film_strip; layout_params)",
              "caption": "СТИЛИ ПОДПИСЕЙ (caption_style; caption_params: color, size и т.д.)",
              "card": "КАРТОЧКИ (card_style; card_params; текст карточки: card_title, card_subtitle)"}
CAT_PARAM_KEY = {"layout": "layout_params", "caption": "caption_params", "card": "card_params"}


def prompt_section(cats=("layout", "caption", "card"), with_params=True):
    """One line per template, grouped by category: `- id: описание [настроение] (параметры)`."""
    lines = ["Цвета в параметрах (color, color2, bg...): " + ", ".join(COLORS) + ". Числа в параметрах — целые."]
    for cat in cats:
        lines.append(CAT_TITLES[cat] + ":")
        for t in REG[cat].values():
            ps = ", ".join(p.short() for p in t.params) if with_params else ""
            extra = f" [{t.assets} карт.]" if t.assets > 1 else ""
            lines.append(f"- {t.id}: {t.desc}{extra} [{' '.join(t.mood)}]" + (f" ({ps})" if ps else ""))
    return "\n".join(lines)


def param_schema(cat):
    """Object schema of the union of parameters of a category (same name -> widest range / union of options)."""
    props = {}
    for t in REG[cat].values():
        for p in t.params:
            cur = props.get(p.name)
            if p.kind == "int":
                lo, hi = (min(cur["minimum"], p.lo), max(cur["maximum"], p.hi)) if cur else (p.lo, p.hi)
                props[p.name] = {"type": "integer", "minimum": lo, "maximum": hi}
            else:
                opts = list(dict.fromkeys((cur["enum"] if cur else []) + list(p.options)))
                props[p.name] = {"type": "string", "enum": opts}
    return {"type": "object", "additionalProperties": False, "properties": props}


def schema_props(kind):
    """Properties to merge into the model's picture ("picture") or card ("card") shot schema; all optional."""
    if kind == "picture":
        return {"layout": {"type": "string", "enum": ["auto"] + ids("layout")}, "layout_params": param_schema("layout"),
                "extra_assets": {"type": "array", "maxItems": 2, "items": {"type": "string"}},
                "caption_style": {"type": "string", "enum": ids("caption")}, "caption_params": param_schema("caption")}
    return {"card_style": {"type": "string", "enum": ids("card")}, "card_params": param_schema("card")}


# ------------------------------------------------------------------ drawing helpers (shared by the template modules)
def rgb(name, default="white"):
    return COLORS.get(name) or COLORS[default]


def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def ink(c):
    """Readable text colour on top of c."""
    return (15, 15, 20) if lum(c) > 140 else (255, 255, 255)


def font(path, size):
    return ImageFont.truetype(path, max(8, int(size)))


_MEASURE = ImageDraw.Draw(Image.new("L", (8, 8)))


def wrap_words(text, f, width):
    """Lines as lists of words (keeps word identity for per-word styling)."""
    lines = []
    for para in text.split("\n"):
        line = []
        for w in para.split():
            test = " ".join(line + [w])
            if _MEASURE.textlength(test, font=f) <= width or not line:
                line.append(w)
            else:
                lines.append(line)
                line = [w]
        lines.append(line)
    return lines


def fit_text(text, path, size, width, max_lines, min_size=26, upper=False, step=4):
    """(font, lines, size) with the largest size <= `size` so that text wraps in <= max_lines lines no wider than `width`."""
    text = text.upper() if upper else text
    size = int(size)
    while True:
        f = font(path, size)
        lines = [" ".join(l) for l in wrap_words(text, f, width)]
        ok = len(lines) <= max_lines and max(_MEASURE.textlength(l, font=f) for l in lines) <= width
        if ok or size <= min_size:
            return f, lines, size
        size -= step


def text_w(s, f):
    return _MEASURE.textlength(s, font=f)


def cover(im, w, h_, fx=0.5, fy=0.5):
    """Crop-to-fill into w x h_; (fx, fy) in 0..1 is the point of the picture that stays as close to the middle as the crop allows."""
    s = max(w / im.width, h_ / im.height)
    nw, nh = max(w, int(im.width * s + 0.5)), max(h_, int(im.height * s + 0.5))
    r = im.resize((nw, nh), Image.LANCZOS)
    x = min(max(0, int(fx * nw - w / 2)), nw - w)
    y = min(max(0, int(fy * nh - h_ / 2)), nh - h_)
    return r.crop((x, y, x + w, y + h_))


def contain(im, w, h_):
    s = min(w / im.width, h_ / im.height)
    return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)


def blur_bg(im, dim=0.45):
    """Cheap blurred, darkened full-frame background (blurs a small copy)."""
    small = cover(im, W // 8, H // 8).filter(ImageFilter.GaussianBlur(5)).resize((W, H), Image.BILINEAR)
    return small.point(lambda v: int(v * dim))


def vgradient(c1, c2, size=(W, H)):
    mask = Image.linear_gradient("L").resize(size)
    return Image.composite(Image.new("RGB", size, c2), Image.new("RGB", size, c1), mask)


def rounded_mask(size, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), r, fill=255)
    return m


def drop_shadow(canvas, box, r=0, blur=24, alpha=150, offset=(0, 14)):
    sh = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle((box[0] + offset[0], box[1] + offset[1], box[2] + offset[0], box[3] + offset[1]), r, fill=alpha)
    canvas.paste((0, 0, 0), (0, 0), sh.filter(ImageFilter.GaussianBlur(blur)))


def paste_rotated(canvas, layer, angle, center, shadow=True):
    """layer: RGBA; rotated around its centre and pasted so its centre lands on `center`."""
    rot = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
    x, y = int(center[0] - rot.width / 2), int(center[1] - rot.height / 2)
    if shadow:
        a = rot.getchannel("A").point(lambda v: int(v * 0.6)).filter(ImageFilter.GaussianBlur(16))
        canvas.paste((0, 0, 0), (x + 6, y + 18), a)
    canvas.paste(rot, (x, y), rot)


# ------------------------------------------------------------------ render entry points (cached)
def _pkey(params):
    return json.dumps(params, sort_keys=True, ensure_ascii=False)


def load_picture(src):
    im = Image.open(src)
    im.seek(0)
    return im.convert("RGB")


def render_layout(layout, sources, params=None):
    """sources: picture paths (the shot's asset first, then extra_assets; padded by repeating). -> cached 1080x1920 PNG path."""
    t = REG["layout"][layout]
    params = t.resolve(params)
    srcs = [sources[i % len(sources)] for i in range(t.assets)]
    out = cache_dir("layouts") / f"{h(*[(s, os.path.getmtime(s)) for s in srcs], layout, _pkey(params), RENDER_VERSION, TEMPLATES_VERSION)}.png"
    if out.exists():
        return out
    img = t.render([load_picture(s) for s in srcs], params)
    assert img.size == (W, H), (layout, img.size)
    img.convert("RGB").save(out)
    return out


def render_caption(text, style, position="bottom", params=None):
    t = REG["caption"][style]
    params = t.resolve(params)
    out = cache_dir("captions") / f"{h(text, style, position, _pkey(params), RENDER_VERSION, TEMPLATES_VERSION)}.png"
    if out.exists():
        return out
    img = t.render(text, position, params)
    assert img.size == (W, H), (style, img.size)
    img.save(out)
    return out


CARD_FPS = 30


def render_card(title, subtitle, style, seconds, params=None, on_call=None, text_anim="none"):
    """Cached H.264 card clip. EffectCraft styles go through cards.py; the others are Pillow stills + a short fade (ffmpeg)."""
    t = REG["card"].get(style) or REG["card"]["minimal"]
    if t.engine == "effectcraft":
        from . import cards
        return cards.render_card(title, subtitle, t.id, seconds, on_call=on_call, text_anim=text_anim)
    params = t.resolve(params)
    title, subtitle = title.strip()[:60], (subtitle or "").strip()[:140]
    out = cache_dir("cards") / f"{h(title, subtitle, t.id, _pkey(params), round(seconds, 2), RENDER_VERSION, TEMPLATES_VERSION)}.mp4"
    if out.exists():
        return out
    png = cache_dir("cards") / f"{out.stem}.png"
    t.render(title, subtitle, params).convert("RGB").save(png)
    fade = min(0.25, seconds / 4)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", str(CARD_FPS), "-i", str(png), "-t", str(seconds),
                    "-vf", f"fade=t=in:st=0:d={fade},fade=t=out:st={max(0, seconds - fade):.2f}:d={fade},format=yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", str(out)], check=True)
    png.unlink(missing_ok=True)
    return out


def counts():
    return {c: len(v) for c, v in REG.items()}


from . import tmpl_layouts, tmpl_captions, tmpl_cards  # noqa: E402,F401  (register the templates)

LAYOUT_IDS = ["auto"] + ids("layout")
CAPTION_IDS = ids("caption")
CARD_IDS = ids("card")
