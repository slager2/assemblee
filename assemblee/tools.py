"""Polish-phase tools: small, enum-constrained edits of the EDL (never of the NLE directly)."""
from .cards import CARD_STYLES
from .edl import EDL, EFFECTS, LOOKS, MOTIONS, MUSIC, SFX, TRANSITIONS, Caption, clamp, pick, LIMITS
from .media import CAPTION_STYLES, POSITIONS


def _tool(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


INT = {"type": "integer"}
SHOT = {"type": "integer", "description": "shot number from the edit list"}
POLISH_TOOLS = [
    _tool("update_shot", "Change fields of one shot. Only pass the fields you change.",
          {"shot": SHOT, "seconds": {"type": "number"}, "motion": {"type": "string", "enum": MOTIONS}, "look": {"type": "string", "enum": list(LOOKS)},
           "caption": {"type": "string", "description": "new caption text; empty string removes the caption"},
           "caption_style": {"type": "string", "enum": CAPTION_STYLES}, "caption_position": {"type": "string", "enum": POSITIONS},
           "effects": {"type": "array", "items": {"type": "string", "enum": list(EFFECTS)}, "description": "replaces the effect list (max 2); [] removes all"},
           "transition_out": {"type": "string", "enum": TRANSITIONS}, "card_title": {"type": "string"}, "card_subtitle": {"type": "string"},
           "card_style": {"type": "string", "enum": CARD_STYLES}},
          ["shot"]),
    _tool("delete_shot", "Remove one shot.", {"shot": SHOT}, ["shot"]),
    _tool("move_shot", "Move a shot to a new position (1-based).", {"shot": SHOT, "to": INT}, ["shot", "to"]),
    _tool("set_section_music", "Music bed of a section.", {"section": {"type": "string"}, "mood": {"type": "string", "enum": list(MUSIC)},
                                                            "volume_db": {"type": "number", "description": "-18 quiet .. 0 loud"}}, ["section", "mood"]),
    _tool("add_sfx", "Sound effect at the start or end of a shot (max 8 in total).",
          {"kind": {"type": "string", "enum": list(SFX)}, "shot": SHOT, "at": {"type": "string", "enum": ["start", "end"]}}, ["kind", "shot"]),
    _tool("clear_sfx", "Remove all sound effects of a shot.", {"shot": SHOT}, ["shot"]),
    _tool("done", "Finish polishing.", {"note": {"type": "string"}}, []),
]


class PolishTools:
    def __init__(self, edl: EDL, on_change):
        self.edl, self.on_change = edl, on_change
        self.finished = False

    def _shot(self, n):
        n = int(n)
        if not 1 <= n <= len(self.edl.shots):
            raise ValueError(f"shot {n} does not exist; shots are 1..{len(self.edl.shots)}")
        return self.edl.shots[n - 1]

    def update_shot(self, shot, **f):
        s, w = self._shot(shot), []
        if "seconds" in f:
            lim = LIMITS["card_seconds"] if s.kind == "card" else LIMITS["picture_seconds"]
            s.seconds = clamp(f["seconds"], lim, s.seconds, "seconds", w)
        if s.kind == "picture":
            if "motion" in f:
                s.motion = pick(f["motion"], MOTIONS, s.motion, "motion", w)
            if "look" in f:
                s.look = pick(f["look"], LOOKS, s.look, "look", w)
            if "effects" in f:
                s.effects = [e for e in (pick(x, EFFECTS, None, "effect", w) for x in (f["effects"] or [])) if e][:2]
            if "caption" in f:
                s.caption = Caption(str(f["caption"]).replace("\\n", "\n")[:120]) if f["caption"] else None
            if s.caption and "caption_style" in f:
                s.caption.style = pick(f["caption_style"], CAPTION_STYLES, s.caption.style, "caption_style", w)
            if s.caption and "caption_position" in f:
                s.caption.position = pick(f["caption_position"], POSITIONS, s.caption.position, "caption_position", w)
        else:
            if "card_title" in f:
                s.title = str(f["card_title"])[:40]
            if "card_subtitle" in f:
                s.subtitle = str(f["card_subtitle"])[:80]
            if "card_style" in f:
                s.card_style = pick(f["card_style"], CARD_STYLES, s.card_style, "card_style", w)
        if "transition_out" in f:
            s.transition_out = pick(f["transition_out"], TRANSITIONS, s.transition_out, "transition_out", w)
        self.on_change()
        return {"ok": True, "shot": int(shot), "warnings": w} if w else {"ok": True, "shot": int(shot)}

    def delete_shot(self, shot):
        self._shot(shot)
        if len(self.edl.shots) <= 3:
            return {"error": "keep at least 3 shots"}
        del self.edl.shots[int(shot) - 1]
        self.edl.sfx = [x if x["shot"] < int(shot) else {**x, "shot": x["shot"] - 1} for x in self.edl.sfx if x["shot"] != int(shot)]
        self.on_change()
        return {"ok": True, "shots_now": len(self.edl.shots)}

    def move_shot(self, shot, to):
        s = self._shot(shot)
        to = max(1, min(len(self.edl.shots), int(to)))
        self.edl.shots.remove(s)
        self.edl.shots.insert(to - 1, s)
        self.on_change()
        return {"ok": True, "order": [x.label() for x in self.edl.shots]}

    def set_section_music(self, section, mood, volume_db=-10):
        sec = next((x for x in self.edl.sections if x.name == section), None)
        if not sec:
            return {"error": f"unknown section; sections: {[x.name for x in self.edl.sections]}"}
        w = []
        sec.music = pick(mood, MUSIC, sec.music, "mood", w)
        sec.music_db = clamp(volume_db, LIMITS["music_db"], -10.0, "volume_db", w)
        self.on_change()
        return {"ok": True, "warnings": w} if w else {"ok": True}

    def add_sfx(self, kind, shot, at="start"):
        self._shot(shot)
        if len(self.edl.sfx) >= 8:
            return {"error": "already 8 sound effects"}
        w = []
        self.edl.sfx.append({"kind": pick(kind, SFX, "whoosh", "kind", w), "shot": int(shot), "at": "end" if at == "end" else "start"})
        self.on_change()
        return {"ok": True}

    def clear_sfx(self, shot):
        before = len(self.edl.sfx)
        self.edl.sfx = [x for x in self.edl.sfx if x["shot"] != int(shot)]
        self.on_change()
        return {"ok": True, "removed": before - len(self.edl.sfx)}

    def done(self, note=""):
        self.finished = True
        return {"ok": True}

    def dispatch(self, name, args):
        if name not in {t["function"]["name"] for t in POLISH_TOOLS}:
            return {"error": f"unknown tool {name}; tools: {[t['function']['name'] for t in POLISH_TOOLS]}"}
        try:
            return getattr(self, name)(**args)
        except TypeError as e:
            return {"error": f"bad arguments: {e}"}
        except Exception as e:
            return {"error": str(e)[:300]}
