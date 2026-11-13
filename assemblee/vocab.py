"""Creative vocabulary: the small "strict" menus of edl.py, or the opt-in "rich" one built from the engines.

The rich vocabulary comes from vocab_data.json (scripts/build_vocab.py: every FilmCraft video transition and video
effect, with a one-line description, safe parameter ranges and exclusions). Everything the model writes is still
validated here: unknown names are fuzzy-matched, numbers are clamped, and every correction becomes a warning.

API used by the agent:
    prompt_section(mode)       -> compact text: one line per allowed item, grouped by category
    schema_fragments(mode)     -> {"picture": {...properties}, "card": {...properties}} to merge into the anyOf shot schema
    resolve_* functions        -> validation used by edl.EDL.make_shot (mode-aware)
"""
import difflib
import json
from pathlib import Path

from .config import H, W

DATA = json.loads((Path(__file__).with_name("vocab_data.json")).read_text())
MODES = ("strict", "rich")

RICH_TRANSITIONS = {r["id"]: r for r in DATA["transitions"] if "excluded" not in r}
RICH_EFFECTS = {r["id"]: r for r in DATA["effects"] if "excluded" not in r}
LUMETRI_LOOKS = [x for x in DATA["lumetri_looks"] if x != "None"]

GRADE = {  # Lumetri parameter -> safe range (verified on renders)
    "exposure": (-1.5, 1.5), "contrast": (-50, 60), "saturation": (0, 180), "temperature": (-60, 60), "tint": (-40, 40),
    "faded_film": (0, 60), "vibrance": (-40, 60), "highlights": (-60, 60), "shadows": (-60, 60), "whites": (-50, 50), "blacks": (-50, 50),
}
GRADE_EXTRA = {"creative_look": LUMETRI_LOOKS, "look_intensity": (0, 150), "shadow_tint": "color", "highlight_tint": "color"}
EASINGS = ["linear", "ease_in", "ease_out", "ease_in_out", "punch"]
CAMERA = {"scale": (100, 200), "xy": (0.0, 1.0)}
SPEED = (25, 300)  # percent, animated/video pictures only
MAX_EFFECTS = {"strict": 2, "rich": 3}
# measured render cost per frame (FilmCraft, 1080x1920, CPU): glint 1.3-1.5 s, volumetric rays + glow 0.8 s, most others <= 0.3 s
HEAVY_EFFECTS = {"glint", "volumetric_rays", "wonder_glow", "bokeh_blur", "lens_flare"}
MAX_HEAVY_SHOTS = 3  # per video: heavier edits export many minutes slower
TEXT_ANIMS = {  # implemented in cards.py with EffectCraft text animators
    "none": "the card style's own entrance",
    "typewriter": "letters appear one by one, like typing",
    "fade_letters": "letters fade in softly from left to right",
    "slide_up": "letters rise from below and fade in, one after another",
    "scale_pop": "each letter pops from zero size with a bounce",
    "blur_in": "letters come into focus from a heavy blur, left to right",
    "tracking_in": "wide letter spacing tightens into the word",
    "word_by_word": "whole words appear one at a time",
    "decode": "random symbols scramble and settle into the real letters",
    "glitch": "letters jitter sideways and flicker, then lock in place",
}


def _pick(value, allowed, default, what, warnings):
    allowed = list(allowed)
    if value in allowed:
        return value
    if value in (None, ""):
        return default
    low = {str(a).lower(): a for a in allowed}
    if str(value).lower() in low:
        return low[str(value).lower()]
    close = difflib.get_close_matches(str(value).lower(), list(low), n=1, cutoff=0.5)
    fixed = low[close[0]] if close else default
    warnings.append(f"{what}: '{value}' is not allowed, used '{fixed}'")
    return fixed


def _num(value, lo_hi, default, what, warnings):
    try:
        v = float(value)
    except (TypeError, ValueError):
        warnings.append(f"{what}: '{value}' is not a number, used {default}")
        return default
    lo, hi = lo_hi
    if not lo <= v <= hi:
        warnings.append(f"{what}: {v} out of range {lo}..{hi}, clamped")
    return round(min(hi, max(lo, v)), 3)


def _color(value, default, what, warnings):
    s = str(value or "").strip()
    if len(s) == 7 and s[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in s[1:]):
        return s.lower()
    named = {"red": "#e03030", "green": "#30c050", "blue": "#3070e0", "yellow": "#ffd23f", "orange": "#ff8a2b", "purple": "#8a3fd8",
             "pink": "#ff5fa8", "cyan": "#3fd8ff", "white": "#ffffff", "black": "#000000", "gold": "#e8b04a", "teal": "#1aa39a"}
    if s.lower() in named:
        return named[s.lower()]
    if s:
        warnings.append(f"{what}: '{value}' is not a #rrggbb colour, used {default}")
    return default


def _xy(value, what, warnings, lo=0.0, hi=1.0, default=(0.5, 0.5)):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        if value is not None:
            warnings.append(f"{what}: expected [x, y] fractions of the frame, used {list(default)}")
        return list(default)
    return [_num(value[0], (lo, hi), default[0], what + ".x", warnings), _num(value[1], (lo, hi), default[1], what + ".y", warnings)]


# ------------------------------------------------------------------ parameters (shared by effects and transitions)
def _param(row, pid, value, what, warnings):
    spec = row["params"][pid]
    t = spec["type"]
    if t == "number":
        if isinstance(value, (list, tuple)) and len(value) == 2:
            if spec.get("animatable"):
                return [_num(v, (spec["min"], spec["max"]), spec["min"], what, warnings) for v in value]
            warnings.append(f"{what}: cannot be animated, used the first value")
            value = value[0]
        return _num(value, (spec["min"], spec["max"]), spec["min"], what, warnings)
    if t == "choice":
        short = {o[5:].lower(): o for o in spec["options"] if o.startswith("From ")}
        if str(value).strip().lower() in short:
            return short[str(value).strip().lower()]
        return _pick(value, spec["options"], spec["options"][0], what, warnings)
    if t == "color":
        return _color(value, "#ffffff", what, warnings)
    if t == "bool":
        return bool(value)
    if t == "point":
        return _xy(value, what, warnings)
    return None


def _params(row, raw_params, amount, what, warnings):
    """Preset, then `amount` (0..1 along the main param's safe range), then explicit params; all validated."""
    out = dict(row.get("preset") or {})
    if amount is not None and row.get("main"):
        try:
            v = float(amount)
            if isinstance(amount, int) or v > 1:  # the schema asks for an integer percent 0..100 (grammar-enforced)
                if v > 100:
                    warnings.append(f"{what}.amount: {amount} is not a percent 0..100, used 50")
                    v = 50
                amount = max(0.0, v) / 100
        except (TypeError, ValueError):
            pass
        a = _num(amount, (0, 1), 0.5, f"{what}.amount", warnings)
        spec = row["params"][row["main"]]
        out[row["main"]] = round(spec["min"] + a * (spec["max"] - spec["min"]), 3)
    if isinstance(raw_params, dict):
        for k, v in raw_params.items():
            pid = k if k in row["params"] else None
            if pid is None and row["params"]:
                close = difflib.get_close_matches(str(k), list(row["params"]), n=1, cutoff=0.6)
                pid = close[0] if close else None
            if pid is None:
                warnings.append(f"{what}: unknown parameter '{k}' ignored" + (f" (allowed: {', '.join(row['params'])})" if row["params"] else ""))
                continue
            if pid != k:
                warnings.append(f"{what}: parameter '{k}' read as '{pid}'")
            val = _param(row, pid, v, f"{what}.{pid}", warnings)
            if val is not None:
                out[pid] = val
    return out


def engine_value(row, pid, value):
    """EDL value -> FilmCraft value (points are fractions of the frame in the EDL, pixels in the engine)."""
    spec = row["params"].get(pid, {})
    if spec.get("type") == "point" or (pid in ("center", "start", "end") and isinstance(value, list) and all(isinstance(v, float) and v <= 1 for v in value)):
        return [round(value[0] * W, 1), round(value[1] * H, 1)]
    return value


def effect_engine_params(fx):
    """[(param, value | [from, to], animated)] for a resolved rich effect, with engine-side companions filled in."""
    row = RICH_EFFECTS[fx["id"]]
    out = []
    for p, v in fx["params"].items():
        spec = row["params"].get(p, {})
        animated = spec.get("type") == "number" and isinstance(v, list)
        out.append((p, v if animated else engine_value(row, p, v), animated))
    vals = {p: (v, a) for p, v, a in out}
    if fx["id"] == "mosaic":  # square blocks on a vertical frame
        hz, a = vals.get("horizontal", (60, False))
        out.append(("vertical", [round(x * H / W) for x in hz] if a else round(hz * H / W), a))
    if fx["id"] == "clone":  # N x N tiles keep the 9:16 aspect, so the frame stays covered
        cols, a = vals.get("columns", (2, False))
        out.append(("rows", cols, a))
    return out


# ------------------------------------------------------------------ effects
def resolve_effect(raw, mode, strict_names, warnings):
    """Strict: a preset name from edl.EFFECTS (string). Rich: also any exposed FilmCraft effect id, as a string or
    {"id", "amount"?: 0..1, "params"?: {param: value | [from, to]}}. Returns a str (strict preset) or a dict."""
    if isinstance(raw, str) and raw in strict_names:
        return raw
    if mode != "rich":
        name = raw.get("id") if isinstance(raw, dict) else raw
        return _pick(name, strict_names, None, "effect", warnings)
    if isinstance(raw, str):
        raw = {"id": raw}
    if not isinstance(raw, dict):
        warnings.append(f"effect: expected a name or an object, got {type(raw).__name__}")
        return None
    eid = raw.get("id") or raw.get("effect") or raw.get("name")
    if eid in strict_names and not raw.get("params") and raw.get("amount") is None:
        return eid
    eid = _pick(eid, RICH_EFFECTS, None, "effect", warnings)
    if not eid:
        return None
    params = _params(RICH_EFFECTS[eid], raw.get("params"), raw.get("amount"), f"effect {eid}", warnings)
    out = {"id": eid, "params": params}
    if raw.get("amount") is not None:  # kept for the edit list: the model sees the effect the way it wrote it
        try:
            a = float(raw["amount"])
            out["amount"] = int(round(a if (isinstance(raw["amount"], int) or a > 1) and a <= 100 else (a * 100 if a <= 1 else 50)))
        except (TypeError, ValueError):
            pass
    return out


# ------------------------------------------------------------------ transitions
def resolve_transition(value, params, mode, strict_names, warnings):
    """-> (transition id, params dict). `value` may also be {"id", "amount", "params"} in rich mode."""
    amount = None
    if isinstance(value, dict):
        params, amount, value = value.get("params", params), value.get("amount"), value.get("id")
    allowed = strict_names if mode != "rich" else ["cut"] + list(RICH_TRANSITIONS)
    tid = _pick(value, allowed, "cut", "transition_out", warnings)
    if tid == "cut" or mode != "rich":
        if params and mode != "rich":
            warnings.append("transition_params: only available in rich mode, ignored")
        return tid, {}
    if isinstance(params, dict) and "amount" in params and amount is None:
        params = dict(params)
        amount = params.pop("amount")
    return tid, _params(RICH_TRANSITIONS[tid], params, amount, f"transition {tid}", warnings)


def transition_engine_params(tid, params):
    row = RICH_TRANSITIONS.get(tid)
    if not row or not params:
        return {}
    return {p: engine_value(row, p, v) for p, v in params.items()}


# ------------------------------------------------------------------ grade / camera / speed
def resolve_grade(raw, warnings):
    if not raw:
        return {}
    if not isinstance(raw, dict):
        warnings.append("grade: expected an object of Lumetri numbers, ignored")
        return {}
    out = {}
    for k, v in raw.items():
        key = k if (k in GRADE or k in GRADE_EXTRA) else _pick(k, list(GRADE) + list(GRADE_EXTRA), None, "grade parameter", warnings)
        if key is None:
            continue
        if key in GRADE:
            out[key] = _num(v, GRADE[key], 0.0 if key != "saturation" else 100.0, f"grade.{key}", warnings)
        elif key == "creative_look":
            out[key] = _pick(v, LUMETRI_LOOKS, LUMETRI_LOOKS[0], "grade.creative_look", warnings)
        elif key == "look_intensity":
            out[key] = _num(v, GRADE_EXTRA[key], 100, "grade.look_intensity", warnings)
        else:
            out[key] = _color(v, "#808080", f"grade.{key}", warnings)
    return out


def grade_engine_params(grade):
    """Lumetri setParam list. Split-tone colours are (mid-grey = neutral) colours; the creative look is a choice name."""
    out = []
    for k, v in grade.items():
        if k == "creative_look":
            out.append(("look", v))
        else:
            out.append((k, v))
    return out


def resolve_camera(raw, warnings):
    """{start_scale, end_scale (100..200 %), start_xy, end_xy (frame fractions of the view centre), easing}."""
    if not raw:
        return None
    if not isinstance(raw, dict):
        warnings.append("camera: expected an object, ignored")
        return None
    cam = {"start_scale": _num(raw.get("start_scale", 100), CAMERA["scale"], 100, "camera.start_scale", warnings),
           "end_scale": _num(raw.get("end_scale", raw.get("start_scale", 112)), CAMERA["scale"], 112, "camera.end_scale", warnings),
           "easing": _pick(raw.get("easing"), EASINGS, "ease_in_out", "camera.easing", warnings)}
    for k in ("start_xy", "end_xy"):
        xy = _xy(raw.get(k), f"camera.{k}", warnings)
        s = cam["start_scale" if k == "start_xy" else "end_scale"] / 100
        lim = 0.5 / s  # the view must stay inside the picture
        fixed = [round(min(1 - lim, max(lim, c)), 3) for c in xy]
        if fixed != xy:
            warnings.append(f"camera.{k}: {xy} would show the frame edge at {s * 100:.0f}% scale, moved to {fixed}")
        cam[k] = fixed
    return cam


def camera_keys(cam, s, e):
    """[(seconds, scale, [x, y] position in px)] plus per-key FilmCraft interpolation, for a shot from s to e."""
    def pos(xy, scale):
        return [round(W / 2 - (xy[0] - 0.5) * W * scale / 100, 1), round(H / 2 - (xy[1] - 0.5) * H * scale / 100, 1)]
    a, b = (cam["start_scale"], cam["start_xy"]), (cam["end_scale"], cam["end_xy"])
    if cam["easing"] == "punch":
        hit = s + min(0.3, (e - s) / 4)
        over = min(CAMERA["scale"][1] + 10, b[0] + (b[0] - a[0]) * 0.12 + 3)
        # punch: very fast move, small overshoot, settle, then a slow creep to the end
        creep = min(CAMERA["scale"][1], b[0] * 1.02)
        keys = [(s, a[0], pos(a[1], a[0])), (hit, over, pos(b[1], over)), (min(e - 0.05, hit + 0.15), b[0], pos(b[1], b[0])), (e, creep, pos(b[1], creep))]
        return keys, ["linear", "bezier", "bezier", "linear"]
    keys = [(s, a[0], pos(a[1], a[0])), (e, b[0], pos(b[1], b[0]))]
    first = {"linear": "linear", "ease_in": "easeOut", "ease_out": "linear", "ease_in_out": "easeOut"}[cam["easing"]]
    last = {"linear": "linear", "ease_in": "linear", "ease_out": "easeIn", "ease_in_out": "easeIn"}[cam["easing"]]
    return keys, [first, last]


def resolve_speed(value, animated, warnings):
    if value in (None, "", 100, 100.0):
        return 100.0
    if not animated:
        warnings.append("speed: only animated/video pictures have a speed, ignored")
        return 100.0
    return _num(value, SPEED, 100.0, "speed", warnings)


def resolve_text_anim(value, warnings):
    return _pick(value, TEXT_ANIMS, "none", "text_anim", warnings)


# ------------------------------------------------------------------ prompt + schema
def _short_params(row):
    out = []
    for pid, sp in row["params"].items():
        if sp["type"] == "number":
            out.append(f"{pid} {sp['min']:g}..{sp['max']:g}" + ("~" if sp.get("animatable") else ""))
        elif sp["type"] == "choice":
            out.append(f"{pid} " + "|".join(o.replace("From ", "").lower() if o.startswith("From ") else o for o in sp["options"]))
        else:
            out.append(f"{pid} {sp['type']}")
    return ", ".join(out)


def _group(rows):
    groups = {}
    for r in rows:
        groups.setdefault(r["category"], []).append(r)
    return groups


def prompt_section(mode="rich", with_params=True):
    """Compact vocabulary text for the model: one line per item, grouped by category."""
    from .edl import EFFECTS, LOOKS, MOTIONS, TRANSITIONS
    if mode != "rich":
        return ("Движения: " + ", ".join(MOTIONS) + "\nЛуки: " + ", ".join(LOOKS) + "\nЭффекты: " + ", ".join(EFFECTS)
                + "\nПереходы: " + ", ".join(TRANSITIONS))
    lines = ["ПЕРЕХОДЫ (transition_out; transition_params: amount 0..100 и/или параметры):"]
    for cat, rows in _group(RICH_TRANSITIONS.values()).items():
        lines.append(f"[{cat}]")
        for r in rows:
            p = _short_params(r) if with_params else ""
            lines.append(f"- {r['id']}: {r['desc']}" + (f" ({p})" if p else ""))
    lines.append("ЭФФЕКТЫ (effects: до 3 штук, {id, amount 0..100 (сила в процентах), params}; ~ = можно анимировать [от, до]):")
    for cat, rows in _group(RICH_EFFECTS.values()).items():
        lines.append(f"[{cat}]")
        for r in rows:
            p = _short_params(r) if with_params else ""
            lines.append(f"- {r['id']}: {r['desc']}" + (f" ({p})" if p else "") + (" [тяжёлый]" if r["id"] in HEAVY_EFFECTS else ""))
    lines.append(f"[тяжёлый] — медленно рендерится: не больше {MAX_HEAVY_SHOTS} кадров с такими эффектами на ролик.")
    lines.append("ЦВЕТ (grade): " + ", ".join(f"{k} {a:g}..{b:g}" for k, (a, b) in GRADE.items())
                 + "; creative_look " + "|".join(LUMETRI_LOOKS) + " + look_intensity 0..150; shadow_tint/highlight_tint #rrggbb")
    lines.append("КАМЕРА (camera): start_scale/end_scale 100..200, start_xy/end_xy [x,y] 0..1 — центр кадра на картинке, easing " + "|".join(EASINGS))
    lines.append(f"СКОРОСТЬ (speed, только анимированные картинки): {SPEED[0]}..{SPEED[1]} %")
    lines.append("АНИМАЦИЯ ТЕКСТА КАРТОЧКИ (text_anim): " + "; ".join(f"{k} — {v}" for k, v in TEXT_ANIMS.items()))
    return "\n".join(lines)


def _num_schema(lo, hi):
    return {"type": "number", "minimum": lo, "maximum": hi}


def _param_schema(sp):
    if sp["type"] == "number":
        one = _num_schema(sp["min"], sp["max"])
        if sp.get("animatable"):
            return {"anyOf": [one, {"type": "array", "items": one, "minItems": 2, "maxItems": 2}]}
        return one
    if sp["type"] == "choice":
        return {"type": "string", "enum": sp["options"]}
    if sp["type"] == "color":
        return {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}
    if sp["type"] == "bool":
        return {"type": "boolean"}
    return {"type": "array", "items": _num_schema(0, 1), "minItems": 2, "maxItems": 2}


def schema_fragments(mode="strict", effect_params=True):
    """Properties to merge into the picture/card objects of the anyOf shot schema.

    strict: the current enums. rich: every allowed transition/effect id, effects as objects with per-effect
    parameter ranges (effect_params=False keeps them as {id, amount} for a smaller grammar), grade, camera, speed,
    text_anim. Every property is optional for the grammar; the validator fills defaults.
    """
    from .cards import CARD_STYLES
    from .edl import EFFECTS, LOOKS, MOTIONS, TRANSITIONS
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if mode == "strict":
        return {"picture": {"motion": {"type": "string", "enum": MOTIONS}, "look": {"type": "string", "enum": list(LOOKS)},
                            "effects": {"type": "array", "maxItems": MAX_EFFECTS["strict"], "items": {"type": "string", "enum": list(EFFECTS)}},
                            "transition_out": {"type": "string", "enum": TRANSITIONS}},
                "card": {"card_style": {"type": "string", "enum": CARD_STYLES}, "transition_out": {"type": "string", "enum": TRANSITIONS}}}
    tids = ["cut"] + list(RICH_TRANSITIONS)
    amount = {"type": "integer", "minimum": 0, "maximum": 100}  # integer: llama.cpp grammars enforce integer ranges, not number ranges
    if effect_params:
        variants = []
        for r in RICH_EFFECTS.values():
            props = {"id": {"type": "string", "enum": [r["id"]]}, "amount": amount}
            if r["params"]:
                props["params"] = {"type": "object", "additionalProperties": False, "properties": {p: _param_schema(sp) for p, sp in r["params"].items()}}
            variants.append({"type": "object", "additionalProperties": False, "properties": props, "required": ["id"]})
        fx_item = {"anyOf": variants}
    else:
        fx_item = {"type": "object", "additionalProperties": False, "properties": {"id": {"type": "string", "enum": list(RICH_EFFECTS)}, "amount": amount}, "required": ["id"]}
    common_tparams = {"type": "object", "properties": {
        "amount": amount, "direction": {"type": "string", "enum": ["north", "east", "south", "west"]},
        "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}}}
    grade = {"type": "object", "additionalProperties": False, "properties": {
        **{k: _num_schema(a, b) for k, (a, b) in GRADE.items()},
        "creative_look": {"type": "string", "enum": LUMETRI_LOOKS}, "look_intensity": _num_schema(*GRADE_EXTRA["look_intensity"]),
        "shadow_tint": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}, "highlight_tint": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}}}
    xy = {"type": "array", "items": _num_schema(0, 1), "minItems": 2, "maxItems": 2}
    camera = {"type": "object", "additionalProperties": False, "properties": {
        "start_scale": _num_schema(*CAMERA["scale"]), "end_scale": _num_schema(*CAMERA["scale"]), "start_xy": xy, "end_xy": xy,
        "easing": {"type": "string", "enum": EASINGS}}, "required": ["start_scale", "end_scale", "easing"]}
    transition = {"transition_out": {"type": "string", "enum": tids}, "transition_params": common_tparams,
                  "transition_seconds": _num_schema(0.2, 1.2)}
    return {"picture": {"motion": {"type": "string", "enum": MOTIONS}, "look": {"type": "string", "enum": list(LOOKS)},
                        "grade": grade, "camera": camera, "speed": _num_schema(*SPEED),
                        "effects": {"type": "array", "maxItems": MAX_EFFECTS["rich"], "items": fx_item}, **transition},
            "card": {"card_style": {"type": "string", "enum": CARD_STYLES}, "text_anim": {"type": "string", "enum": list(TEXT_ANIMS)}, **transition}}


def counts():
    return {"transitions": (len(RICH_TRANSITIONS), len(DATA["transitions"])), "effects": (len(RICH_EFFECTS), len(DATA["effects"])),
            "grade_params": len(GRADE) + len(GRADE_EXTRA), "easings": len(EASINGS), "text_anims": len(TEXT_ANIMS) - 1}
