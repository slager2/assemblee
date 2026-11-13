"""Polish-phase tools: small, enum-constrained edits of the EDL (never of the NLE directly)."""
from . import vocab
from .cards import CARD_STYLES
from .edl import EDL, is_animated, EFFECTS, LOOKS, MOTIONS, MUSIC, SFX, TRANSITIONS, Caption, clamp, pick, LIMITS
from .media import CAPTION_STYLES, POSITIONS


def _tool(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


INT = {"type": "integer"}
SHOT = {"type": "integer", "description": "shot number from the edit list"}
def polish_tools(mode="strict", music=None):
    """Polish tools for a vocabulary mode: in rich mode update_shot also edits grade, camera, speed, text_anim,
    effects with amounts and transition params (same validation as the build phase).
    music: extra allowed music ids (downloaded library tracks) for set_section_music, which then also takes
    "start" (seconds into the track at the section's first cut)."""
    tools = [dict(t, function=dict(t["function"], parameters=dict(t["function"]["parameters"], properties=dict(t["function"]["parameters"]["properties"]))))
             for t in _BASE]
    frag = vocab.schema_fragments(mode, effect_params=False)
    props = tools[0]["function"]["parameters"]["properties"]
    props["effects"] = dict(frag["picture"]["effects"], description="replaces the effect list; [] removes all")
    props["transition_out"] = frag["picture"]["transition_out"]
    props["card_style"] = frag["card"]["card_style"]
    if mode == "rich":
        for k in ("grade", "camera", "speed", "transition_params", "transition_seconds"):
            props[k] = frag["picture"][k]
        props["text_anim"] = frag["card"]["text_anim"]
    if music:
        fn = next(t for t in tools if t["function"]["name"] == "set_section_music")["function"]
        mp = fn["parameters"]["properties"]
        mp["mood"] = {"type": "string", "enum": list(MUSIC) + [m for m in music if m not in MUSIC],
                      "description": "built-in mood or a downloaded track id"}
        mp["start"] = {"type": "number", "description": "seconds into a downloaded track at the section's first cut; omit = its drop"}
    return tools


_BASE = [
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
                                                            "volume_db": {"type": "integer", "minimum": -24, "maximum": 3, "description": "-18 quiet .. 0 loud"}}, ["section", "mood"]),
    _tool("retime_section", "Make a section last about this many seconds: every shot of the section is scaled proportionally.",
          {"section": {"type": "string"}, "seconds": {"type": "number"}}, ["section", "seconds"]),
    _tool("add_sfx", "Sound effect at the start or end of a shot (max 8 in total).",
          {"kind": {"type": "string", "enum": list(SFX)}, "shot": SHOT, "at": {"type": "string", "enum": ["start", "end"]}}, ["kind", "shot"]),
    _tool("clear_sfx", "Remove all sound effects of a shot.", {"shot": SHOT}, ["shot"]),
    _tool("done", "Finish polishing.", {"note": {"type": "string"}}, []),
]
POLISH_TOOLS = polish_tools("strict")


class PolishTools:
    def __init__(self, edl: EDL, on_change, guardrails="full"):
        """guardrails != "full": sound-variety rules are warnings, not refusals (the model decides)."""
        self.edl, self.on_change, self.guardrails = edl, on_change, guardrails
        self.finished = False
        self.tools = polish_tools(edl.mode, music=list(edl.music_library))

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
                s.effects = self.edl.effects(f["effects"] or [], w)  # same resolver as the build phase (strict names or rich objects)
            rich = self.edl.mode == "rich"
            if rich and "grade" in f:
                s.grade = vocab.resolve_grade(f["grade"], w)
            if rich and "camera" in f:
                s.camera = vocab.resolve_camera(f["camera"], w)
            if rich and "speed" in f:
                s.speed = self.edl.fit_speed(vocab.resolve_speed(f["speed"], is_animated(self.edl.catalog[s.asset]), w), s.seconds, w)
            if not rich and any(k in f for k in ("grade", "camera", "speed", "text_anim")):
                w.append("grade/camera/speed/text_anim need rich mode, ignored")
            if "caption" in f:
                text = str(f["caption"]).replace("\\n", "\n")[:120]
                if not text:
                    s.caption = None
                elif s.caption:  # new text keeps the style and position the shot already had
                    s.caption.text = text
                else:
                    s.caption = Caption(text)
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
            if "text_anim" in f and self.edl.mode == "rich":
                s.text_anim = vocab.resolve_text_anim(f["text_anim"], w)
        if "transition_out" in f or "transition_params" in f:
            s.transition_out, s.transition_params = self.edl.transition(
                {"transition_out": f.get("transition_out", s.transition_out), "transition_params": f.get("transition_params", s.transition_params)}, w)
        if "transition_seconds" in f:
            s.transition_seconds = clamp(f["transition_seconds"], LIMITS["transition_seconds"], s.transition_seconds, "transition_seconds", w)
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
        frm, to = int(shot), max(1, min(len(self.edl.shots), int(to)))
        order = list(range(1, len(self.edl.shots) + 1))
        order.insert(to - 1, order.pop(frm - 1))
        new_pos = {old: new for new, old in enumerate(order, 1)}
        self.edl.shots.remove(s)
        self.edl.shots.insert(to - 1, s)
        self.edl.sfx = [{**x, "shot": new_pos[x["shot"]]} for x in self.edl.sfx if x["shot"] in new_pos]  # sounds follow their shots
        # the moved shot joins the section it lands in, so sections stay contiguous (music beds, beat snapping)
        nb = self.edl.shots[to - 2] if to > 1 else (self.edl.shots[1] if len(self.edl.shots) > 1 else s)
        s.section = nb.section
        self.on_change()
        return {"ok": True, "order": [x.label() for x in self.edl.shots]}

    def set_section_music(self, section, mood, volume_db=None, start=None):
        sec = next((x for x in self.edl.sections if x.name == section), None)
        if not sec:
            return {"error": f"unknown section; sections: {[x.name for x in self.edl.sections]}"}
        w = []
        sec.music = self.edl.resolve_music(mood, w, default=sec.music)
        if volume_db is not None:  # changing only the mood keeps the volume set earlier
            sec.music_db = clamp(volume_db, LIMITS["music_db"], sec.music_db, "volume_db", w)
        track = self.edl.music_library.get(sec.music)
        if start is not None and track:
            sec.music_start = clamp(start, (0.0, max(0.0, float(track.get("duration") or 0) - 5)), track.get("best_start") or 0.0, "start", w)
        elif track:
            sec.music_start = None
        self.on_change()
        return {"ok": True, "warnings": w} if w else {"ok": True}

    def retime_section(self, section, seconds):
        idx = self.edl.section_shots(section)
        if not idx:
            return {"error": f"section has no shots; sections: {[x.name for x in self.edl.sections]}"}
        w = []
        want = clamp(seconds, (1.0, 60.0), 0, "seconds", w)
        have = sum(self.edl.shots[i].seconds for i in idx)
        for i in idx:
            s = self.edl.shots[i]
            lim = LIMITS["card_seconds"] if s.kind == "card" else LIMITS["picture_seconds"]
            s.seconds = round(min(lim[1], max(lim[0], s.seconds * want / have)), 2)
        got = round(sum(self.edl.shots[i].seconds for i in idx), 2)
        if abs(got - want) > 0.3:
            w.append(f"shot limits allow {got}s here; add or remove shots for {want}s")
        self.on_change()
        return {"ok": True, "section_seconds": got, "total_seconds": self.edl.total(), **({"warnings": w} if w else {})}

    def add_sfx(self, kind, shot, at="start"):
        self._shot(shot)
        if len(self.edl.sfx) >= 8:
            return {"error": "already 8 sound effects"}
        w = []
        kind = pick(kind, SFX, "whoosh", "kind", w)
        strict = self.guardrails == "full"
        if any(x["shot"] == int(shot) for x in self.edl.sfx):
            if strict:
                return {"error": f"shot {shot} already has a sound effect; pick another strong moment"}
            w.append(f"shot {shot} now has more than one sound effect")
        if sum(1 for x in self.edl.sfx if x["kind"] == kind) >= 2:
            if strict:
                return {"error": f"'{kind}' already used twice; vary the sounds: {[k for k in SFX if k != kind]}"}
            w.append(f"'{kind}' is used {sum(1 for x in self.edl.sfx if x['kind'] == kind) + 1} times now")
        self.edl.sfx.append({"kind": kind, "shot": int(shot), "at": "end" if at == "end" else "start"})
        self.on_change()
        return {"ok": True, "warnings": w} if w else {"ok": True}

    def clear_sfx(self, shot):
        before = len(self.edl.sfx)
        self.edl.sfx = [x for x in self.edl.sfx if x["shot"] != int(shot)]
        self.on_change()
        return {"ok": True, "removed": before - len(self.edl.sfx)}

    def done(self, note=""):
        self.finished = True
        return {"ok": True}

    def dispatch(self, name, args):
        spec = next((t["function"] for t in self.tools if t["function"]["name"] == name), None)
        if spec is None:
            return {"error": f"unknown tool {name}; tools: {[t['function']['name'] for t in self.tools]}"}
        allowed = spec["parameters"]["properties"]
        args = {k: v for k, v in (args or {}).items() if k in allowed}  # the flat action schema lets the model fill unrelated fields
        missing = [k for k in spec["parameters"]["required"] if k not in args]
        if missing:
            return {"error": f"{name}: missing {missing}"}
        try:
            return getattr(self, name)(**args)
        except TypeError as e:
            return {"error": f"bad arguments: {e}"}
        except Exception as e:
            return {"error": str(e)[:300]}
