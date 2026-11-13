"""Picture preparation and caption rendering (Pillow + ffmpeg). Pure functions, cached on disk."""
import hashlib
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import CACHE, FONT_BOLD, FONT_MONO, FONT_SANS, FPS, H, RENDER_VERSION, W

CAPTION_STYLES = ["subtitle", "cartoon", "retro2011", "system", "glitch"]
POSITIONS = ["top", "center", "bottom"]


def h(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12]


def cache_dir(sub):
    d = CACHE / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def font(path, size):
    return ImageFont.truetype(path, size)


def wrap(draw, text, f, width):
    lines = []
    for para in text.split("\n"):
        words, line = para.split(), ""
        for w in words:
            test = (line + " " + w).strip()
            if draw.textlength(test, font=f) <= width or not line:
                line = test
            else:
                lines.append(line)
                line = w
        lines.append(line)
    return lines


def fit_vertical(src, mode="auto") -> Path:
    """Any picture -> 1080x1920 PNG. fill: crop to cover; blur: whole picture over a blurred, darkened copy."""
    im = Image.open(src)
    im.seek(0)
    im = im.convert("RGB")
    if mode == "auto":
        mode = "fill" if im.width / im.height < 0.8 else "blur"
    out = cache_dir("pictures") / f"{h(src, os.path.getmtime(src), mode, RENDER_VERSION)}.png"
    if out.exists():
        return out
    scale = max(W / im.width, H / im.height)
    cover = im.resize((int(im.width * scale) + 1, int(im.height * scale) + 1), Image.LANCZOS)
    cx, cy = (cover.width - W) // 2, (cover.height - H) // 2
    cover = cover.crop((cx, cy, cx + W, cy + H))
    if mode == "fill":
        cover.save(out)
        return out
    bg = cover.filter(ImageFilter.GaussianBlur(40)).point(lambda v: int(v * 0.45))
    fw, fh = W, int(im.height * W / im.width)
    if fh > int(H * 0.8):
        fh = int(H * 0.8)
        fw = int(im.width * fh / im.height)
    fg = im.resize((fw, fh), Image.LANCZOS)
    shadow = Image.new("L", (fw + 60, fh + 60), 0)
    ImageDraw.Draw(shadow).rectangle((30, 30, fw + 30, fh + 30), fill=170)
    bg.paste((0, 0, 0), ((W - fw) // 2 - 30, (H - fh) // 2 - 18), shadow.filter(ImageFilter.GaussianBlur(18)))
    bg.paste(fg, ((W - fw) // 2, (H - fh) // 2))
    bg.save(out)
    return out


def animated_to_vertical_mp4(src, seconds=12) -> Path:
    out = cache_dir("pictures") / f"{h(src, os.path.getmtime(src), RENDER_VERSION)}.mp4"
    if not out.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-stream_loop", "3", "-i", str(src), "-filter_complex",
                        f"[0]fps={FPS},split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=25,eq=brightness=-0.3[bg];"
                        f"[b]scale={W}:-2:flags=neighbor[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p",
                        "-t", str(seconds), "-an", "-c:v", "libx264", "-crf", "20", str(out)], check=True)
    return out


def thumb(src, size=(144, 256)) -> Path:
    """Small JPEG for the UI timeline (first frame for videos)."""
    out = cache_dir("thumbs") / f"{h(src, os.path.getmtime(src))}.jpg"
    if out.exists():
        return out
    src = Path(src)
    if src.suffix.lower() in (".mp4", ".mov", ".webm"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", str(src), "-frames:v", "1",
                        "-vf", f"scale={size[0]}:{size[1]}:force_original_aspect_ratio=decrease", str(out)], check=False)
    else:
        im = Image.open(src)
        im.seek(0)
        im = im.convert("RGB")
        im.thumbnail(size)
        im.save(out, quality=82)
    return out


def caption_png(text, style, position) -> Path:
    out = cache_dir("captions") / f"{h(text, style, position, RENDER_VERSION)}.png"
    if out.exists():
        return out
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y_anchor = {"top": 0.15, "center": 0.5, "bottom": 0.75}.get(position, 0.75)  # inside the Reels/Shorts safe zone

    def fit(path, size, txt, width, max_lines):
        while True:
            f = font(path, size)
            lines = wrap(d, txt, f, width)
            if size <= 30 or (len(lines) <= max_lines and max(d.textlength(l, font=f) for l in lines) <= width):
                return f, lines, size
            size -= 4

    if style == "retro2011":
        f, lines, sz = fit(FONT_SANS, 60, text, W - 220, 3)
        lh = int(sz * 1.25)
        bw = max(d.textlength(l, font=f) for l in lines) + 70
        bh = lh * len(lines) + 44
        x0, y0 = (W - bw) / 2, H * y_anchor - bh / 2
        d.rectangle((x0, y0, x0 + bw, y0 + bh), fill=(40, 40, 40, 190), outline=(200, 200, 200, 210), width=3)
        for i, l in enumerate(lines):
            d.text((W / 2, y0 + 22 + i * lh), l, font=f, fill=(255, 255, 255, 255), anchor="ma")
    elif style == "cartoon":
        f, lines, sz = fit(FONT_BOLD, 92, text.upper(), W - 120, 3)
        lh = int(sz * 1.22)
        y0 = H * y_anchor - lh * len(lines) / 2
        for i, l in enumerate(lines):
            tw = d.textlength(l, font=f)
            d.text(((W - tw) / 2, y0 + i * lh + 8), l, font=f, fill=(0, 0, 0, 160), stroke_width=12, stroke_fill=(0, 0, 0, 160))
            d.text(((W - tw) / 2, y0 + i * lh), l, font=f, fill=(255, 214, 63, 255) if i == 0 else (255, 255, 255, 255),
                   stroke_width=10, stroke_fill=(20, 20, 30, 255))
    elif style == "system":
        body = "\n".join(f"[{l.strip('[] ')}]" for l in text.split("\n") if l.strip())
        f, lines, sz = fit(FONT_MONO, 52, body, W - 230, 5)
        lh = int(sz * 1.35)
        bw, bh = W - 140, lh * len(lines) + 120
        x0, y0 = 70, H * y_anchor - bh / 2
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle((x0, y0, x0 + bw, y0 + bh), 18, outline=(80, 200, 255, 255), width=14)
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)))
        d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), 18, fill=(8, 20, 60, 230), outline=(110, 215, 255, 255), width=4)
        d.text((x0 + 40, y0 + 22), "[ СИСТЕМА ]", font=font(FONT_MONO, 34), fill=(110, 215, 255, 255))
        for i, l in enumerate(lines):
            d.text((x0 + 40, y0 + 80 + i * lh), l, font=f, fill=(225, 245, 255, 255))
    elif style == "glitch":
        f, lines, sz = fit(FONT_BOLD, 110, text.upper(), W - 120, 3)
        lh = int(sz * 1.16)
        y0 = H * y_anchor - lh * len(lines) / 2
        for i, l in enumerate(lines):
            tw = d.textlength(l, font=f)
            x, y = (W - tw) / 2, y0 + i * lh
            d.text((x - 9, y), l, font=f, fill=(255, 40, 70, 200))
            d.text((x + 9, y + 3), l, font=f, fill=(40, 230, 255, 200))
            d.text((x, y), l, font=f, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 160))
    else:  # subtitle
        f, lines, sz = fit(FONT_BOLD, 66, text, W - 140, 3)
        lh = int(sz * 1.25)
        y0 = H * y_anchor - lh * len(lines) / 2
        for i, l in enumerate(lines):
            tw = d.textlength(l, font=f)
            d.text(((W - tw) / 2, y0 + i * lh), l, font=f, fill=(255, 255, 255, 255), stroke_width=6, stroke_fill=(0, 0, 0, 235))
    img.save(out)
    return out


def media_duration(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0
