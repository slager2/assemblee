"""Edit decision list: the model edits this plain data; the compiler turns it into a FilmCraft timeline.

Keeping the edit as data (instead of mutating the NLE step by step) lets the model reorder, change and
delete shots freely, and lets the harness validate everything before anything is rendered.
"""
import difflib
import re
from dataclasses import asdict, dataclass, field

from .cards import CARD_STYLES
from .media import CAPTION_STYLES, POSITIONS

LOOKS = {  # Lumetri parameter sets
    "neutral": {},
    "retro_bright": {"saturation": 125, "contrast": 10, "faded_film": 15, "temperature": 8},
    "horror_cold": {"saturation": 55, "temperature": -35, "contrast": 30, "exposure": -0.5, "shadows": -25},
    "sickly_green": {"saturation": 70, "tint": -30, "contrast": 20, "exposure": -0.3},
    "cartoon_pop": {"saturation": 150, "vibrance": 30, "contrast": 15, "exposure": 0.15},
    "dark_cave": {"saturation": 90, "exposure": -0.6, "contrast": 35, "shadows": -30, "temperature": -10},
    "lava_warm": {"saturation": 130, "temperature": 40, "contrast": 25, "highlights": 10},
    "dreamy": {"saturation": 85, "faded_film": 35, "highlights": 20, "temperature": 10},
    "warm_memory": {"saturation": 90, "temperature": 25, "faded_film": 25, "contrast": -5},
    "black_white": {"saturation": 0, "contrast": 25},
}
MOTIONS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "punch_in", "still"]
TRANSITIONS = ["cut", "cross_dissolve", "dip_to_black", "dip_to_white", "flash", "glitch", "vhs_damage", "tv_power", "chaos",
               "cross_zoom", "whip", "push", "light_leak", "pop_motion", "film_dissolve", "zoom_blur"]
EFFECTS = {
    "rgb_split": ("rgb_split", {"amount": 10}),
    "camera_shake": ("camera_shake", {"amount": 20}),
    "film_noise": ("noise", {"amount": 15}),
    "vignette": ("vignette", {"amount": -55}),
    "digital_glitch": ("vr_digital_glitch", {"amplitude": 15}),
    "glow": ("wonder_glow", {"threshold": 55, "intensity": 120}),
    "light_leaks": ("light_leaks", {"intensity": 45}),
    "posterize": ("posterize", {"levels": 12}),
    "pixelate": ("mosaic", {"horizontal": 120, "vertical": 213, "sharp": True}),
}
MUSIC = {"dark_drone": "dark_drone.wav", "chiptune": "chiptune.wav", "epic": "epic.wav", "warm_pad": "warm_pad.wav", "none": None}
SFX = {"glitch": "sfx_glitch.wav", "whoosh": "sfx_whoosh.wav", "notify": "sfx_notify.wav", "boom": "sfx_boom.wav", "rise": "sfx_rise.wav"}

LIMITS = {"picture_seconds": (0.6, 8.0), "card_seconds": (1.2, 5.0), "transition_seconds": (0.2, 1.2), "music_db": (-24.0, 3.0)}


EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]")


def clean_text(text, limit):
    """Captions are drawn with DejaVu fonts, which have no emoji: strip them and tidy spaces."""
    return re.sub(r"[ \t]+", " ", EMOJI.sub("", str(text or ""))).strip()[:limit]


def pick(value, allowed, default, what, warnings):
    """Exact match, else closest allowed value (fuzzy), else default. Every correction is reported."""
    if value in allowed:
        return value
    if value in (None, ""):
        return default
    close = difflib.get_close_matches(str(value).lower(), list(allowed), n=1, cutoff=0.5)
    fixed = close[0] if close else default
    warnings.append(f"{what}: '{value}' is not allowed, used '{fixed}'")
    return fixed


def clamp(value, lo_hi, default, what, warnings):
    try:
        v = float(value)
    except (TypeError, ValueError):
        warnings.append(f"{what}: '{value}' is not a number, used {default}")
        return default
    lo, hi = lo_hi
    if not lo <= v <= hi:
        warnings.append(f"{what}: {v} out of range {lo}..{hi}, clamped")
    return round(min(hi, max(lo, v)), 2)


@dataclass
class Caption:
    text: str
    style: str = "subtitle"
    position: str = "bottom"


@dataclass
class Shot:
    section: str
    kind: str  # picture | card
    seconds: float
    asset: str = ""
    title: str = ""
    subtitle: str = ""
    card_style: str = "minimal"
    motion: str = "zoom_in"
    look: str = "neutral"
    caption: Caption | None = None
    effects: list = field(default_factory=list)
    transition_out: str = "cut"
    transition_seconds: float = 0.5

    def label(self):
        return self.title if self.kind == "card" else self.asset


@dataclass
class Section:
    name: str
    goal: str = ""
    target_seconds: float = 10.0
    music: str = "none"
    music_db: float = -10.0


class EDL:
    def __init__(self, catalog):
        self.catalog = catalog
        self.sections: list[Section] = []
        self.shots: list[Shot] = []
        self.sfx: list[dict] = []  # {"kind", "shot" (1-based), "at": start|end}

    # ---- validation ----
    def make_shot(self, raw: dict, section: str, warnings: list) -> Shot | None:
        if not isinstance(raw, dict):
            warnings.append(f"shot must be an object, got {type(raw).__name__}")
            return None
        title = clean_text(raw.get("card_title") or raw.get("title"), 40)
        asset = str(raw.get("asset") or "").strip()
        if title and not asset:
            return Shot(section=section, kind="card", title=title[:40], subtitle=clean_text(raw.get("card_subtitle") or raw.get("subtitle"), 80),
                        card_style=pick(raw.get("card_style") or raw.get("style"), CARD_STYLES, "minimal", "card_style", warnings),
                        seconds=clamp(raw.get("seconds", 2.5), LIMITS["card_seconds"], 2.5, "card seconds", warnings),
                        transition_out=pick(raw.get("transition_out"), TRANSITIONS, "cut", "transition_out", warnings))
        if asset not in self.catalog:
            close = difflib.get_close_matches(asset, list(self.catalog), n=1, cutoff=0.6)
            if not close:
                warnings.append(f"unknown asset '{asset}' (shot skipped); use ids from the asset list")
                return None
            warnings.append(f"asset '{asset}' not found, used '{close[0]}'")
            asset = close[0]
        cap = None
        if clean_text(raw.get("caption"), 120):
            cap = Caption(text=clean_text(str(raw["caption"]).replace("\\n", "\n"), 120),
                          style=pick(raw.get("caption_style"), CAPTION_STYLES, "subtitle", "caption_style", warnings),
                          position=pick(raw.get("caption_position"), POSITIONS, "bottom", "caption_position", warnings))
        effects = list(dict.fromkeys(e for e in (pick(e, EFFECTS, None, "effect", warnings) for e in (raw.get("effects") or [])) if e))[:2]
        return Shot(section=section, kind="picture", asset=asset,
                    seconds=clamp(raw.get("seconds", 3), LIMITS["picture_seconds"], 3.0, "seconds", warnings),
                    motion=pick(raw.get("motion"), MOTIONS, "zoom_in", "motion", warnings),
                    look=pick(raw.get("look"), LOOKS, "neutral", "look", warnings), caption=cap,
                    effects=[e for e in effects if e], transition_out=pick(raw.get("transition_out"), TRANSITIONS, "cut", "transition_out", warnings),
                    transition_seconds=clamp(raw.get("transition_seconds", 0.5), LIMITS["transition_seconds"], 0.5, "transition_seconds", warnings))

    # ---- queries ----
    def total(self):
        return round(sum(s.seconds for s in self.shots), 2)

    def times(self):
        t, out = 0.0, []
        for s in self.shots:
            out.append((round(t, 2), round(t + s.seconds, 2)))
            t += s.seconds
        return out

    def section_shots(self, name):
        return [i for i, s in enumerate(self.shots) if s.section == name]

    def summary(self):
        times = self.times()
        rows = []
        for i, (s, (a, b)) in enumerate(zip(self.shots, times), 1):
            row = {"shot": i, "section": s.section, "start": a, "end": b, "what": s.label()}
            if s.kind == "picture":
                row.update(motion=s.motion, look=s.look)
                if s.caption:
                    row["caption"] = f"[{s.caption.style}] {s.caption.text[:50]}"
                if s.effects:
                    row["effects"] = s.effects
            else:
                row["card_style"] = s.card_style
            if s.transition_out != "cut":
                row["transition_out"] = s.transition_out
            rows.append(row)
        return {"total_seconds": self.total(), "sections": [asdict(x) for x in self.sections], "shots": rows, "sfx": self.sfx}

    def to_dict(self):
        return {"sections": [asdict(x) for x in self.sections], "shots": [asdict(s) for s in self.shots], "sfx": self.sfx}
