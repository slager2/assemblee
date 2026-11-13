"""Edit decision list: the model edits this plain data; the compiler turns it into a FilmCraft timeline.

Keeping the edit as data (instead of mutating the NLE step by step) lets the model reorder, change and
delete shots freely, and lets the harness validate everything before anything is rendered.
"""
import difflib
import re
from dataclasses import asdict, dataclass, field

from pathlib import Path

from . import vocab
from .cards import CARD_STYLES
from .config import AUDIO_DIR
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


STYLE_TAG = re.compile(r"^\s*\[(subtitle|cartoon|retro2011|system|glitch|minimal|final|joining_server)\]\s*", re.I)


def clean_text(text, limit):
    """Captions are drawn with DejaVu fonts, which have no emoji: strip them and tidy spaces. A leading style tag
    like "[glitch] " is metadata the model copied from an edit list, never caption text."""
    t = STYLE_TAG.sub("", EMOJI.sub("", str(text or "")))
    return re.sub(r"[ \t]+", " ", t).strip()[:limit]


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
    # rich vocabulary (vocab.py); the defaults mean "not used", so strict EDLs compile exactly as before
    grade: dict = field(default_factory=dict)  # numeric Lumetri values, applied on top of `look`
    camera: dict | None = None  # replaces `motion` when set
    speed: float = 100.0  # animated/video pictures only
    transition_params: dict = field(default_factory=dict)
    text_anim: str = "none"  # cards only
    narration: str = ""  # voice-over spoken from this shot's start (own line, besides the section narration); "" = none

    def label(self):
        return self.title if self.kind == "card" else self.asset


@dataclass
class Section:
    name: str
    goal: str = ""
    target_seconds: float = 10.0
    music: str = "none"  # a built-in mood (MUSIC) or a downloaded track id from EDL.music_library ("music/<slug>")
    music_db: float = -10.0
    music_start: float | None = None  # track time at the section's first cut; None = the track's best_start (0 for moods)
    narration: str = ""  # voice-over spoken from the section's first cut (Russian, spoken style); "" = silent
    narration_voice: str = ""  # "" = the EDL's voice


def is_animated(entry):
    return entry.get("kind") == "animated" or str(entry.get("path", "")).lower().endswith((".gif", ".mp4", ".webm", ".mov"))


ANIMATED_SOURCE_SECONDS = 11.5  # media.animated_to_vertical_mp4 makes 12 s clips


class EDL:
    def __init__(self, catalog, mode="strict"):
        """mode: "strict" (small menus of this module) or "rich" (vocab.py: every engine transition/effect, grade, camera...)."""
        if mode not in vocab.MODES:
            raise ValueError(f"mode must be one of {vocab.MODES}")
        self.catalog = catalog
        self.mode = mode
        self.sections: list[Section] = []
        self.shots: list[Shot] = []
        self.sfx: list[dict] = []  # {"kind", "shot" (1-based), "at": start|end}
        self.music_library: dict = {}  # track id -> music.gather_music entry (path, bpm, beats, best_start, duration...)
        self.voice: str | None = None  # voice-over voice (voice.VOICES) or None = no voice-over
        self.voice_rate: float = 1.0
        self.duck_db: float = 12.0  # the music goes this much quieter under speech
        self.narration_clips: list[dict] = []  # filled by fit_narration

    # ---- validation ----
    def transition(self, raw, warnings):
        return vocab.resolve_transition(raw.get("transition_out"), raw.get("transition_params"), self.mode, TRANSITIONS, warnings)

    def effects(self, items, warnings):
        out, seen = [], set()
        for e in items or []:
            fx = vocab.resolve_effect(e, self.mode, EFFECTS, warnings)
            key = fx if isinstance(fx, str) else fx and fx["id"]
            if fx and key not in seen:
                seen.add(key)
                out.append(fx)
        limit = vocab.MAX_EFFECTS[self.mode]
        if len(out) > limit:
            warnings.append(f"effects: at most {limit}, kept the first {limit}")
        return out[:limit]

    def make_shot(self, raw: dict, section: str, warnings: list) -> Shot | None:
        if not isinstance(raw, dict):
            warnings.append(f"shot must be an object, got {type(raw).__name__}")
            return None
        title = clean_text(raw.get("card_title") or raw.get("title"), 40)
        asset = str(raw.get("asset") or "").strip()
        rich = self.mode == "rich"
        if title and not asset:
            tid, tparams = self.transition(raw, warnings)
            return Shot(section=section, kind="card", title=title[:40], subtitle=clean_text(raw.get("card_subtitle") or raw.get("subtitle"), 80),
                        card_style=pick(raw.get("card_style") or raw.get("style"), CARD_STYLES, "minimal", "card_style", warnings),
                        seconds=clamp(raw.get("seconds", 2.5), LIMITS["card_seconds"], 2.5, "card seconds", warnings),
                        transition_out=tid, transition_params=tparams,
                        transition_seconds=clamp(raw.get("transition_seconds", 0.5), LIMITS["transition_seconds"], 0.5, "transition_seconds", warnings),
                        text_anim=vocab.resolve_text_anim(raw.get("text_anim"), warnings) if rich else "none")
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
        tid, tparams = self.transition(raw, warnings)
        seconds = clamp(raw.get("seconds", 3), LIMITS["picture_seconds"], 3.0, "seconds", warnings)
        shot = Shot(section=section, kind="picture", asset=asset, seconds=seconds,
                    motion=pick(raw.get("motion"), MOTIONS, "zoom_in", "motion", warnings),
                    look=pick(raw.get("look"), LOOKS, "neutral", "look", warnings), caption=cap,
                    effects=self.effects(raw.get("effects"), warnings), transition_out=tid, transition_params=tparams,
                    transition_seconds=clamp(raw.get("transition_seconds", 0.5), LIMITS["transition_seconds"], 0.5, "transition_seconds", warnings))
        if rich:
            shot.grade = vocab.resolve_grade(raw.get("grade"), warnings)
            shot.camera = vocab.resolve_camera(raw.get("camera"), warnings)
            shot.speed = self.fit_speed(vocab.resolve_speed(raw.get("speed"), is_animated(self.catalog[asset]), warnings), seconds, warnings)
        elif any(raw.get(k) for k in ("grade", "camera", "speed", "text_anim")):
            warnings.append("grade/camera/speed/text_anim are only available in rich mode, ignored")
        return shot

    @staticmethod
    def fit_speed(speed, seconds, warnings):
        """A fast clip needs seconds * speed of source; the prepared animated clip is about 12 s long."""
        top = round(ANIMATED_SOURCE_SECONDS / seconds * 100, 1)
        if speed > top:
            warnings.append(f"speed: {speed}% needs more source than the clip has for a {seconds}s shot, used {top}%")
            return top
        return speed

    # ---- music ----
    def music_choices(self):
        return list(MUSIC) + [k for k in self.music_library if k not in MUSIC]

    def resolve_music(self, value, warnings, default="none"):
        return pick(value, self.music_choices(), default, "music", warnings)

    def music_path(self, music):
        """File of a mood or library track (a plain existing path also works); None for "none"/unknown."""
        if music in MUSIC:
            f = AUDIO_DIR / MUSIC[music] if MUSIC[music] else None
            return f if f and f.is_file() else None  # built-in beds missing (make_audio.sh not run): no music, not a crash
        if music in self.music_library:
            return Path(self.music_library[music]["path"])
        return Path(music) if music and Path(music).is_file() else None

    def music_beds(self):
        """Consecutive sections with the same music merge into one bed. Each bed: music, start/end (timeline s),
        db, sections, music_start = track time at the bed start (None = legacy: the file plays from 0 at the
        crossfade pre-roll), track = the library entry or None."""
        times, beds = self.times(), []
        for sec in self.sections:
            idx = self.section_shots(sec.name)
            if not idx or sec.music in ("none", None) or self.music_path(sec.music) is None:
                continue
            a, b = times[idx[0]][0], times[idx[-1]][1]
            if beds and beds[-1]["mood"] == sec.music and abs(beds[-1]["end"] - a) < 0.05:
                beds[-1]["end"] = b
                beds[-1]["sections"].append(sec.name)
                continue
            track = self.music_library.get(sec.music)
            start = sec.music_start
            if start is None and track:
                start = float(track.get("best_start") or 0.0)
            beds.append({"mood": sec.music, "start": a, "end": b, "db": sec.music_db, "sections": [sec.name],
                         "music_start": None if start is None else round(max(0.0, float(start)), 3), "track": track})
        return beds

    def section_track_time(self, name):
        """(bed, track time at the section's first cut) or (None, None) when the section has no music."""
        times = self.times()
        idx = self.section_shots(name)
        for bed in self.music_beds():
            if name in bed["sections"] and idx:
                return bed, (bed["music_start"] or 0.0) + times[idx[0]][0] - bed["start"]
        return None, None

    # ---- voice-over ----
    def fit_narration(self, synth=None, on_status=None):
        """Synthesizes every narration line and lengthens the shots it covers so the line fits: a narrated shot (or
        section) lasts at least the spoken length + voice.LEAD + voice.TAIL. Pure arithmetic on the audio length,
        idempotent (shots only grow). Fills self.narration_clips: shot, text, voice, path, seconds, phrases, start, end."""
        from . import voice as voice_mod
        self.narration_clips = []
        if not self.voice:
            return []
        lines = []  # (first shot, last shot, text, voice)
        for sec in self.sections:
            idx = self.section_shots(sec.name)
            if idx and sec.narration.strip():
                lines.append((idx[0], idx[-1], sec.narration, sec.narration_voice or self.voice))
        for i, s in enumerate(self.shots):
            if s.narration.strip():
                lines.append((i, i, s.narration, self.voice))
        lines.sort(key=lambda x: x[0])
        got = (synth or voice_mod.synthesize_many)([(t, v, self.voice_rate) for _, _, t, v in lines], on_status) if lines else []
        for (a, b, text, v), vo in zip(lines, got):
            extra = vo.seconds + voice_mod.LEAD + voice_mod.TAIL - sum(x.seconds for x in self.shots[a:b + 1])
            for _ in range(4):  # even share per shot, the remainder goes to shots that still have room under their limit
                room = [x for x in self.shots[a:b + 1] if x.seconds < (LIMITS["card_seconds"][1] if x.kind == "card" else LIMITS["picture_seconds"][1]) - 0.01]
                if extra <= 0.005 or not room:
                    break
                share = extra / len(room)
                for x in room:
                    top = LIMITS["card_seconds"][1] if x.kind == "card" else LIMITS["picture_seconds"][1]
                    add = min(share, top - x.seconds)
                    x.seconds = round(x.seconds + add + 0.004, 2)
                    extra -= add + 0.004
            self.narration_clips.append({"shot": a + 1, "text": text, "voice": v, "path": str(vo.path), "seconds": vo.seconds, "phrases": vo.phrases})
        times = self.times()
        for c in self.narration_clips:
            c["start"] = round(times[c["shot"] - 1][0] + voice_mod.LEAD, 2)
            c["end"] = round(c["start"] + c["seconds"], 2)
        for prev, cur in zip(self.narration_clips, self.narration_clips[1:]):  # lines never overlap
            if cur["start"] < prev["end"] + 0.1:
                shift = round(prev["end"] + 0.1 - cur["start"], 2)
                cur["start"], cur["end"] = round(cur["start"] + shift, 2), round(cur["end"] + shift, 2)
        return self.narration_clips

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
                row.update(motion=s.motion if not s.camera else "camera", look=s.look)
                if s.grade:
                    row["grade"] = s.grade
                if s.camera:
                    row["camera"] = s.camera
                if s.speed != 100:
                    row["speed"] = s.speed
                if s.caption:
                    row["caption"] = s.caption.text[:60]
                    row["caption_style"] = s.caption.style
                if s.effects:
                    row["effects"] = [({"id": e["id"], **({"amount": e["amount"]} if "amount" in e else {})} if isinstance(e, dict) else e)
                                      for e in s.effects]  # the form the model writes, not engine parameters
            else:
                row["card_style"] = s.card_style
                if s.text_anim != "none":
                    row["text_anim"] = s.text_anim
            if s.transition_out != "cut":
                row["transition_out"] = s.transition_out
                if s.transition_params:
                    row["transition_params"] = s.transition_params
            rows.append(row)
        out = {"total_seconds": self.total(), "mode": self.mode, "sections": [asdict(x) for x in self.sections], "shots": rows, "sfx": self.sfx}
        if self.voice:
            out["voice"] = self.voice
        return out

    def to_dict(self):
        return {"sections": [asdict(x) for x in self.sections], "shots": [asdict(s) for s in self.shots], "sfx": self.sfx}
