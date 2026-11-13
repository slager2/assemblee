"""Compile an EDL into a fresh FilmCraft sequence; render frames; export.

Each compile starts a new headless FilmCraft session, so the timeline always matches the EDL exactly.
"""
import base64
import time
from pathlib import Path

from .cards import render_card
from .config import AUDIO_DIR, FILMCRAFT_CLI, FPS, H, TICKS, W
from .edl import EDL, EFFECTS, LOOKS, MUSIC, SFX
from .mcp import MCP, MCPError
from .media import animated_to_vertical_mp4, caption_png, fit_vertical, media_duration


class Compiled:
    def __init__(self, fc, clip_ids, times, stats):
        self.fc, self.clip_ids, self.times, self.stats = fc, clip_ids, times, stats

    def frame_png(self, seconds) -> bytes:
        r = self.fc.call("render_frame", {"seconds": float(seconds)})
        img = r["image_png_b64"] if isinstance(r, dict) else next(x for x in r if isinstance(x, dict) and "image_png_b64" in x)["image_png_b64"]
        return base64.b64decode(img)

    def export(self, path: Path, bitrate_kbps=12000):
        path = Path(path)
        if path.exists():
            path.unlink()
        self.fc.run("file.exportMedia", {"path": str(path), "format": "h264", "bitrateKbps": bitrate_kbps, "wait": True})
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError("export produced no file")
        return path

    def close(self):
        self.fc.close()


def picture_media(entry):
    if entry.get("kind") == "animated" or str(entry["path"]).lower().endswith((".gif", ".mp4", ".webm", ".mov")):
        return animated_to_vertical_mp4(entry["path"])
    return fit_vertical(entry["path"], entry.get("fit", "auto"))


def compile_edl(edl: EDL, on_call=None, on_progress=None) -> Compiled:
    t0 = time.time()
    calls = {"filmcraft": 0, "effectcraft": 0}

    def note(engine, cid, params):
        calls[engine] += 1
        on_call and on_call(engine, cid, params)

    fc = MCP([FILMCRAFT_CLI, "mcp"], timeout=300)
    items = {}

    def run(cid, params):
        note("filmcraft", cid, params)
        return fc.run(cid, params)

    def imp(path):
        path = str(path)
        if path not in items:
            note("filmcraft", "media_import", {"paths": [path]})
            r = fc.call("media_import", {"paths": [path]})
            if r.get("errors"):
                raise RuntimeError(f"import failed: {r['errors']}")
            items[path] = r["items"][0]
        return items[path]

    def kf(clip, effect, param, pairs):
        for t, v in pairs:
            run("effects.setParam", {"clip": clip, "effect": effect, "param": param, "value": v, "time": int(t * TICKS), "keyframe": True})

    run("file.newSequence", {"name": "assemblee", "width": W, "height": H, "fps": FPS, "video": 3, "audio": 4})
    times = edl.times()
    clip_ids = []
    for i, (shot, (s, e)) in enumerate(zip(edl.shots, times), 1):
        on_progress and on_progress(f"shot {i}/{len(edl.shots)}")
        if shot.kind == "card":
            media = render_card(shot.title, shot.subtitle, shot.card_style, shot.seconds, on_call=lambda c, p: note("effectcraft", c, p))
        else:
            media = picture_media(edl.catalog[shot.asset])
        cid = run("timeline.place", {"item": imp(media), "track": "V1", "seconds": s, "insert": False, "duration": {"seconds": shot.seconds}, "audio": False})["clips"][0]
        clip_ids.append(cid)
        if shot.kind == "picture":
            m = shot.motion
            if m == "zoom_in":
                kf(cid, "motion", "scale", [(s, 100), (e, 112)])
            elif m == "zoom_out":
                kf(cid, "motion", "scale", [(s, 114), (e, 101)])
            elif m == "punch_in":
                kf(cid, "motion", "scale", [(s, 100), (s + min(0.35, shot.seconds / 3), 118), (e, 122)])
            elif m in ("pan_left", "pan_right"):
                run("effects.setParam", {"clip": cid, "effect": "motion", "param": "scale", "value": 116})
                dx = 70 if m == "pan_left" else -70
                kf(cid, "motion", "position", [(s, [W / 2 + dx, H / 2]), (e, [W / 2 - dx, H / 2])])
            if LOOKS.get(shot.look):
                idx = run("effects.apply", {"clips": [cid], "effect": "lumetri"})["applied"][0]["index"]
                for p, v in LOOKS[shot.look].items():
                    run("effects.setParam", {"clip": cid, "effect": idx, "param": p, "value": v})
            for name in shot.effects:
                eid, params = EFFECTS[name]
                idx = run("effects.apply", {"clips": [cid], "effect": eid})["applied"][0]["index"]
                for p, v in params.items():
                    try:
                        run("effects.setParam", {"clip": cid, "effect": idx, "param": p, "value": v})
                    except MCPError:
                        pass
            if shot.caption:
                cap = caption_png(shot.caption.text, shot.caption.style, shot.caption.position)
                ccid = run("timeline.place", {"item": imp(cap), "track": "V2", "seconds": s, "insert": False, "duration": {"seconds": shot.seconds}})["clips"][0]
                fade = min(0.25, shot.seconds / 4)
                kf(ccid, "opacity", "opacity", [(s, 0), (s + fade, 100), (e - fade, 100), (e, 0)])
    # transitions (after all clips exist)
    for i, shot in enumerate(edl.shots[:-1]):
        if shot.transition_out != "cut":
            frames = max(4, min(36, int(shot.transition_seconds * FPS)))
            for align in ("center", "start", "end"):
                try:
                    run("sequence.applyVideoTransition", {"clip": clip_ids[i + 1], "effect": shot.transition_out, "frames": frames, "edge": "in", "align": align})
                    break
                except MCPError:
                    continue
    # music: merge consecutive sections with the same mood into one bed
    beds = []
    for sec in edl.sections:
        idx = edl.section_shots(sec.name)
        if not idx or sec.music in ("none", None):
            continue
        a, b = times[idx[0]][0], times[idx[-1]][1]
        if beds and beds[-1]["mood"] == sec.music and abs(beds[-1]["end"] - a) < 0.05:
            beds[-1]["end"] = b
        else:
            beds.append({"mood": sec.music, "start": a, "end": b, "db": sec.music_db})
    for k, bed in enumerate(beds):
        path = AUDIO_DIR / MUSIC[bed["mood"]]
        start = max(0.0, bed["start"] - (0.4 if k else 0))
        dur = min(bed["end"] - start + (0.4 if k + 1 < len(beds) else 0), media_duration(path) - 0.1)
        cid = run("timeline.place", {"item": imp(path), "track": "A1" if k % 2 == 0 else "A2", "seconds": start, "insert": False, "video": False,
                                     "duration": {"seconds": dur}})["clips"][0]
        run("clip.audioGain", {"clips": [cid], "mode": "set", "db": float(bed["db"])})
        for edge in ("in", "out"):
            try:
                run("sequence.applyAudioTransition", {"clip": cid, "effect": "constant_power", "frames": 18, "edge": edge, "align": "start" if edge == "in" else "end"})
            except MCPError:
                pass
    for k, fx in enumerate(edl.sfx):
        n = fx["shot"] - 1
        if not 0 <= n < len(times):
            continue
        path = AUDIO_DIR / SFX[fx["kind"]]
        d = media_duration(path)
        t = times[n][0] if fx.get("at", "start") == "start" else max(0.0, times[n][1] - d / 2)
        run("timeline.place", {"item": imp(path), "track": "A3" if k % 2 == 0 else "A4", "seconds": t, "insert": False, "video": False, "duration": {"seconds": d}})
    stats = {"calls": calls, "seconds": round(time.time() - t0, 1), "beds": beds}
    return Compiled(fc, clip_ids, times, stats)
