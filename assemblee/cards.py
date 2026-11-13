"""Full-screen animated text cards rendered by EffectCraft (MCP to build the comp, CLI to render)."""
import subprocess

from PIL import Image, ImageDraw

from .config import EFFECTCRAFT_CLI, FONT_BOLD, FONT_BOOK, FPS, H, RENDER_VERSION, W
from .mcp import MCP
from .media import cache_dir, font, h

CARD_STYLES = ["joining_server", "glitch", "retro2011", "cartoon", "system", "minimal", "final"]
PALETTES = {"joining_server": ("#0b0b0e", "#e8e8e8", "#7fdcf0"), "retro2011": ("#0d69ac", "#ffffff", "#f5cd30"),
            "cartoon": ("#ff6a2b", "#ffffff", "#ffd23f"), "system": ("#06102e", "#e1f5ff", "#6ed7ff"),
            "glitch": ("#050505", "#ffffff", "#ff2e4d"), "minimal": ("#111114", "#f2f2f2", "#c9a96e"),
            "final": ("#000000", "#ffffff", "#9aa5b1")}


def _fit_text(text, path, max_size, min_size, width, tracking=0, max_lines=2, shrink_first=0.62):
    """Largest size at which text wraps into <= max_lines lines of <= width px (same DejaVu font EffectCraft renders)."""
    d = ImageDraw.Draw(Image.new("L", (8, 8)))

    def w_of(line, f, size):
        return d.textlength(line, font=f) + tracking / 1000 * size * max(0, len(line) - 1)

    def wrap(f, size):
        lines, line = [], ""
        for word in text.split():
            test = (line + " " + word).strip()
            if w_of(test, f, size) <= width or not line:
                line = test
            else:
                lines.append(line)
                line = word
        lines.append(line)
        return lines

    for n in range(1, max_lines + 1):
        floor = min_size if n == max_lines else max(min_size, int(max_size * shrink_first))
        for size in range(max_size, floor - 1, -4):
            f = font(path, size)
            lines = wrap(f, size)
            if len(lines) <= n and max(w_of(l, f, size) for l in lines) <= width:
                return size, lines
    return min_size, wrap(font(path, min_size), min_size)


TEXT_ANIM_VERSION = 3  # bump when the text animations change (part of the card cache key)
SEL = "text/animators/animator/selectors/rangeSelector/"
PROP = "text/animators/animator/properties/"
SHAPES = {"square": 0, "ramp_up": 1, "ramp_down": 2, "triangle": 3, "round": 4, "smooth": 5}
# text_anim -> (animator properties, their "hidden" values, selector settings).
# square shape: the range selector's `start` sweeps 0 -> 100, so the hidden state leaves the characters one by one.
# ramp shapes: a 0..50 % ramp slides (`offset` -50 -> 100) from before the first character to past the last one, so each
# character goes smoothly from hidden (after the ramp) to shown (before it), several at a time.
TEXT_ANIMS = {
    "typewriter": (["opacity"], {"opacity": 0}, {"shape": "square", "smoothness": 0}),
    "word_by_word": (["opacity"], {"opacity": 0}, {"shape": "square", "smoothness": 0, "basedOn": 2}),
    "fade_letters": (["opacity"], {"opacity": 0}, {"shape": "ramp_up"}),
    "slide_up": (["opacity", "position"], {"opacity": 0, "position": [0, 160, 0]}, {"shape": "ramp_up"}),
    "scale_pop": (["scale", "opacity"], {"scale": [0, 0, 100], "opacity": 0}, {"shape": "ramp_up"}),
    "blur_in": (["blur", "opacity"], {"blur": [40, 40], "opacity": 0}, {"shape": "ramp_up"}),
    "decode": (["characterOffset"], {"characterRange": 1, "characterOffset": 12}, {"shape": "square", "smoothness": 0, "randomize": True, "basedOn": 1}),
}


def text_anim_keys(seconds):
    """Reveal window: starts right away, takes about 40% of the card (0.5..1.4 s)."""
    return 0.05, 0.05 + min(1.4, max(0.5, seconds * 0.4))


def animate_text(call, run, layer, kind, seconds):
    """Per-character entrance with EffectCraft text animators (After Effects-style range/wiggly selectors)."""
    a, b = text_anim_keys(seconds)
    if kind == "tracking_in":
        run("layer.addTextAnimator", {"layer": layer, "properties": ["tracking", "opacity"]})
        call("add_keyframe", {"layer": layer, "path": PROP + "tracking", "interpolation": "easyEaseOut", "keys": [{"time": a, "value": 140}, {"time": b, "value": 0}]})
        call("add_keyframe", {"layer": layer, "path": PROP + "opacity", "keys": [{"time": a, "value": 0}, {"time": a + (b - a) * 0.6, "value": 100}]})
        return
    if kind == "glitch":
        run("layer.addTextAnimator", {"layer": layer, "properties": ["position", "fillHue", "opacity"]})
        run("layer.addTextSelector", {"layer": layer, "animator": 1, "kind": "wiggly"})
        call("set_property", {"layer": layer, "path": PROP + "position", "value": [70, 0, 0]})
        call("set_property", {"layer": layer, "path": PROP + "fillHue", "value": 120})
        call("set_property", {"layer": layer, "path": PROP + "opacity", "value": -100})
        w = "text/animators/animator/selectors/wigglySelector/"
        call("set_property", {"layer": layer, "path": w + "wigglesPerSecond", "value": 14})
        call("set_property", {"layer": layer, "path": w + "correlation", "value": 0})
        call("add_keyframe", {"layer": layer, "path": SEL + "advanced/amount", "interpolation": "hold",
                              "keys": [{"time": 0, "value": 100}, {"time": b, "value": 35}, {"time": b + 0.15, "value": 0}]})
        return
    props, hidden, sel = TEXT_ANIMS[kind]
    run("layer.addTextAnimator", {"layer": layer, "properties": props})
    for p, v in hidden.items():
        call("set_property", {"layer": layer, "path": PROP + p, "value": v})
    for k, v in sel.items():
        call("set_property", {"layer": layer, "path": SEL + "advanced/" + k, "value": SHAPES.get(v, v) if k == "shape" else v})
    if sel.get("shape") == "square":
        call("add_keyframe", {"layer": layer, "path": SEL + "start", "interpolation": "linear", "keys": [{"time": a, "value": 0}, {"time": b, "value": 100}]})
    else:
        call("set_property", {"layer": layer, "path": SEL + "end", "value": 50})
        call("add_keyframe", {"layer": layer, "path": SEL + "offset", "interpolation": "easyEaseOut", "keys": [{"time": a, "value": -50}, {"time": b, "value": 100}]})


def render_card(title, subtitle, style, seconds, on_call=None, text_anim="none"):
    """Returns the path of a cached H.264 card clip. on_call(tool, params) is called for every MCP call.
    text_anim: "none" (the style's own entrance) or a per-character animation from vocab.TEXT_ANIMS."""
    style = style if style in PALETTES else "minimal"
    text_anim = text_anim if text_anim in TEXT_ANIMS or text_anim in ("tracking_in", "glitch") else "none"
    title, subtitle = title.strip()[:40], (subtitle or "").strip()[:80]
    out = cache_dir("cards") / f"{h(title, subtitle, style, round(seconds, 2), RENDER_VERSION, *([text_anim, TEXT_ANIM_VERSION] if text_anim != 'none' else []))}.mp4"
    if out.exists():
        return out
    bg, fg, accent = PALETTES[style]
    if style in ("cartoon", "glitch", "retro2011"):
        title = title.upper()
    tw = 760 if style == "system" else 940
    tsize, tlines = _fit_text(title, FONT_BOLD, 150 if style != "system" else 104, 60, tw, tracking=20, max_lines=3)
    ssize, slines = (_fit_text(subtitle, FONT_BOOK, 52, 34, tw, tracking=20, max_lines=3, shrink_first=0.9) if subtitle else (0, []))
    tlead, slead = int(tsize * 1.18), int(ssize * 1.3)
    gap = max(70, int(tsize * 0.6)) if slines else 0
    block = int(tsize * 0.75) + tlead * (len(tlines) - 1) + (gap + int(ssize * 0.75) + slead * (len(slines) - 1) if slines else 0)
    t_base = H * 0.47 - block / 2 + tsize * 0.75
    s_base = t_base + tlead * (len(tlines) - 1) + gap + ssize * 0.95
    bottom = (s_base + slead * (len(slines) - 1)) if slines else t_base + tlead * (len(tlines) - 1)
    proj = cache_dir("cards") / f"{out.stem}.ecproj"
    ec = MCP([EFFECTCRAFT_CLI, "mcp"])
    try:
        def run(i, p):
            on_call and on_call(i, p)
            return ec.call("execute_command", {"id": i, "params": p})

        def call(n, a):
            on_call and on_call(n, a)
            return ec.call(n, a)

        call("open_project", {"new": True})
        run("comp.new", {"name": "Card", "width": W, "height": H, "frameRate": FPS, "duration": seconds, "background": bg})
        top = t_base - tsize * 0.75
        if style == "system":
            btop, bbot = top - 130, bottom + max(ssize, tsize // 2) * 0.3 + 60
            box = run("layer.newShape", {"kind": "rounded", "size": [940, int(bbot - btop)], "fill": "#0a1a4a", "stroke": accent, "strokeWidth": 6,
                                         "position": [W / 2, (btop + bbot) / 2]})["layer"]
            call("add_keyframe", {"layer": box, "path": "transform/scale", "keys": [{"time": 0, "value": [0, 0]}, {"time": 0.25, "value": [104, 104]}, {"time": 0.4, "value": [100, 100]}]})
            run("layer.newText", {"text": "[ СИСТЕМА ]", "position": [W / 2, top - 62], "size": 34, "fill": accent, "font": "DejaVu Sans Mono", "style": "Bold",
                                  "justify": "center", "tracking": 200})
        elif style != "final":
            last = t_base + tlead * (len(tlines) - 1) + tsize * 0.22
            bar_y = (last + s_base - ssize * 0.78) / 2 if slines else last + 40
            bar = run("layer.newShape", {"kind": "rect", "size": [220, 10], "fill": accent, "position": [W / 2, bar_y]})["layer"]
            call("add_keyframe", {"layer": bar, "path": "transform/scale", "keys": [{"time": 0.1, "value": [0, 100]}, {"time": 0.5, "value": [100, 100]}]})
        tparams = {"text": "\n".join(tlines), "position": [W / 2, t_base], "size": tsize, "fill": fg, "font": "DejaVu Sans", "style": "Bold",
                   "justify": "center", "tracking": 20}
        if style == "cartoon":
            tparams.update({"stroke": "#1a1a2a", "strokeWidth": max(6, tsize // 11), "applyStroke": True, "strokeOverFill": False})
        t = run("layer.newText", tparams)["layer"]
        if slines:
            sparams = {"text": "\n".join(slines), "position": [W / 2, s_base], "size": ssize, "fill": accent, "font": "DejaVu Sans",
                       "style": "Book", "justify": "center", "tracking": 20}
            st = run("layer.newText", sparams)["layer"]
            call("add_keyframe", {"layer": st, "path": "transform/opacity", "keys": [{"time": seconds * 0.25, "value": 0}, {"time": seconds * 0.45, "value": 100}]})
        if style == "joining_server":
            j = run("layer.newText", {"text": "Joining server...", "position": [W / 2, bottom + 150], "size": 40, "fill": "#8a8a8a",
                                      "font": "DejaVu Sans", "style": "Book", "justify": "center", "tracking": 120})["layer"]
            call("add_keyframe", {"layer": j, "path": "transform/opacity", "interpolation": "hold",
                                  "keys": [{"time": k * 0.25, "value": 100 if k % 2 == 0 else 35} for k in range(int(seconds * 4) + 1)]})
        if style in ("joining_server", "glitch", "retro2011"):
            call("add_effect", {"layer": t, "effect": "ec.vr.digitalglitch", "values": {"masterAmplitude": 200}})
            call("add_keyframe", {"layer": t, "path": "effects/#1/masterAmplitude", "keys": [
                {"time": 0, "value": 280}, {"time": seconds * 0.35, "value": 0}, {"time": seconds * 0.85, "value": 0}, {"time": seconds, "value": 300}]})
        if text_anim != "none":
            animate_text(call, run, t, text_anim, seconds)
        elif style in ("cartoon", "final", "minimal"):
            call("add_keyframe", {"layer": t, "path": "transform/scale", "interpolation": "easyEase",
                                  "keys": [{"time": 0, "value": [80 if style == "minimal" else 60] * 2}, {"time": 0.3, "value": [106 if style == "minimal" else 112] * 2},
                                           {"time": 0.5, "value": [100, 100]}]})
        call("add_keyframe", {"layer": t, "path": "transform/opacity", "keys": [{"time": 0, "value": 0 if text_anim == "none" else 100}, {"time": 0.2, "value": 100},
                                                                               {"time": seconds - 0.2, "value": 100}, {"time": seconds, "value": 0 if style == "final" else 100}]})
        call("save_project", {"path": str(proj)})
    finally:
        ec.close()
    r = subprocess.run([str(EFFECTCRAFT_CLI), "--project", str(proj), "render", "--comp", "Card", "--out", str(out), "--format", "h264"], capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"EffectCraft render failed: {r.stderr[-300:]}")
    return out
