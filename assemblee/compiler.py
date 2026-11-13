"""Compile an EDL into a fresh FilmCraft sequence; render frames; export.

Each compile starts a new headless FilmCraft session, so the timeline always matches the EDL exactly.
"""
import base64
import math
import time
from pathlib import Path

from . import templates
from .config import AUDIO_DIR, FILMCRAFT_CLI, FPS, H, TICKS, W
from . import vocab
from .edl import EDL, EFFECTS, LOOKS, SFX
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
        old = self.fc.timeout
        self.fc.timeout = 1800  # a 60 s vertical edit with effects renders on the CPU for several minutes
        try:
            self.fc.run("file.exportMedia", {"path": str(path), "format": "h264", "bitrateKbps": bitrate_kbps, "wait": True,
                                             "hardwareEncoding": "auto"})  # NVENC when present, software otherwise
        finally:
            self.fc.timeout = old
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError("export produced no file")
        return path

    def close(self):
        self.fc.close()


def picture_media(entry, shot=None, catalog=None):
    """Prepared 1080x1920 media for a picture entry; with a shot that has a template layout, the layout is rendered
    (the shot's asset first, then its extra_assets)."""
    if entry.get("kind") == "animated" or str(entry["path"]).lower().endswith((".gif", ".mp4", ".webm", ".mov")):
        return animated_to_vertical_mp4(entry["path"])
    if shot is not None and shot.layout != "auto" and shot.layout in templates.REG["layout"]:
        paths = [entry["path"]] + [catalog[a]["path"] for a in shot.extra_assets if catalog and a in catalog]
        return templates.render_layout(shot.layout, paths, shot.layout_params)
    return fit_vertical(entry["path"], entry.get("fit", "auto"))


def compile_edl(edl: EDL, on_call=None, on_progress=None) -> Compiled:
    """Builds a fresh FilmCraft session; if anything fails mid-compile the headless engine is closed, not leaked."""
    fc = MCP([FILMCRAFT_CLI, "mcp"], timeout=300)
    try:
        return _compile_into(fc, edl, on_call, on_progress)
    except BaseException:
        fc.close()
        raise


def _compile_into(fc, edl: EDL, on_call=None, on_progress=None) -> Compiled:
    t0 = time.time()
    calls = {"filmcraft": 0, "effectcraft": 0}

    def note(engine, cid, params):
        calls[engine] += 1
        on_call and on_call(engine, cid, params)

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

    eases = []  # (clip, effect, param, sequence ticks, interpolation): set once all clips exist

    def set_param(clip, idx, p, v, s, e, what, animate=False):
        try:
            if animate:
                kf(clip, idx, p, [(s, v[0]), (e, v[1])])  # animated [from, to] over the shot
                eases.extend([(clip, idx, p, int(s * TICKS), "easeOut"), (clip, idx, p, int(e * TICKS), "easeIn")])
            else:
                run("effects.setParam", {"clip": clip, "effect": idx, "param": p, "value": v})
        except MCPError as err:
            warnings.append(f"{what}.{p}={v}: {str(err)[:120]}")

    warnings = []
    run("file.newSequence", {"name": "assemblee", "width": W, "height": H, "fps": FPS, "video": 3, "audio": 4})
    times = edl.times()
    clip_ids = []
    for i, (shot, (s, e)) in enumerate(zip(edl.shots, times), 1):
        on_progress and on_progress(f"shot {i}/{len(edl.shots)}")
        if shot.kind == "card":
            media = templates.render_card(shot.title, shot.subtitle, shot.card_style, shot.seconds, shot.card_params,
                                          on_call=lambda c, p: note("effectcraft", c, p), text_anim=shot.text_anim)
        else:
            media = picture_media(edl.catalog[shot.asset], shot, edl.catalog)
        speed = shot.speed if shot.kind == "picture" else 100.0
        src = shot.seconds * speed / 100  # source seconds, so the sped-up/slowed clip fills exactly shot.seconds
        cid = run("timeline.place", {"item": imp(media), "track": "V1", "seconds": s, "insert": False, "duration": {"seconds": src}, "audio": False})["clips"][0]
        clip_ids.append(cid)
        if speed != 100:
            run("clip.speedDuration", {"clips": [cid], "speed": speed, "ripple": False, "interpolation": "frameBlending"})
        if shot.kind == "picture":
            m = shot.motion
            if shot.camera:
                keys, interp = vocab.camera_keys(shot.camera, s, e)
                kf(cid, "motion", "scale", [(t, sc) for t, sc, _ in keys])
                kf(cid, "motion", "position", [(t, xy) for t, _, xy in keys])
                for (t, _, _), how in zip(keys, interp):
                    if how != "linear":
                        eases.extend([(cid, "motion", "scale", int(t * TICKS), how), (cid, "motion", "position", int(t * TICKS), how)])
            elif m == "zoom_in":
                kf(cid, "motion", "scale", [(s, 100), (e, 112)])
            elif m == "zoom_out":
                kf(cid, "motion", "scale", [(s, 114), (e, 101)])
            elif m == "punch_in":
                kf(cid, "motion", "scale", [(s, 100), (s + min(0.35, shot.seconds / 3), 118), (e, 122)])
            elif m in ("pan_left", "pan_right"):
                run("effects.setParam", {"clip": cid, "effect": "motion", "param": "scale", "value": 116})
                dx = 70 if m == "pan_left" else -70
                kf(cid, "motion", "position", [(s, [W / 2 + dx, H / 2]), (e, [W / 2 - dx, H / 2])])
            grade = {**LOOKS.get(shot.look, {}), **shot.grade}
            if grade:
                idx = run("effects.apply", {"clips": [cid], "effect": "lumetri"})["applied"][0]["index"]
                for p, v in vocab.grade_engine_params(grade):
                    set_param(cid, idx, p, v, s, e, f"shot {i} grade")
            for fx in shot.effects:
                if isinstance(fx, str):  # strict preset
                    eid, params = EFFECTS[fx]
                    params = [(p, v, False) for p, v in params.items()]
                else:
                    eid, params = fx["id"], vocab.effect_engine_params(fx)
                idx = run("effects.apply", {"clips": [cid], "effect": eid})["applied"][0]["index"]
                for p, v, animate in params:
                    set_param(cid, idx, p, v, s, e, f"shot {i} {eid}", animate)
            if shot.caption:
                cap = caption_png(shot.caption.text, shot.caption.style, shot.caption.position, shot.caption.params)
                ccid = run("timeline.place", {"item": imp(cap), "track": "V2", "seconds": s, "insert": False, "duration": {"seconds": shot.seconds}})["clips"][0]
                fade = min(0.25, shot.seconds / 4)
                kf(ccid, "opacity", "opacity", [(s, 0), (s + fade, 100), (e - fade, 100), (e, 0)])
    # transitions (after all clips exist)
    for i, shot in enumerate(edl.shots[:-1]):
        if shot.transition_out != "cut":
            frames = max(4, min(36, int(shot.transition_seconds * FPS)))
            tparams = vocab.transition_engine_params(shot.transition_out, shot.transition_params)
            for align in ("center", "start", "end"):
                try:
                    run("sequence.applyVideoTransition", {"clip": clip_ids[i + 1], "effect": shot.transition_out, "frames": frames, "edge": "in", "align": align,
                                                          **({"params": tparams} if tparams else {})})
                    break
                except MCPError as err:
                    if align == "end":
                        warnings.append(f"transition {shot.transition_out} after shot {i + 1}: {str(err)[:120]}")
                    continue
    # keyframe easing: FilmCraft addresses keyframes by media time, so read where each clip really sits
    if eases:
        layout = {it["clip"]: it for it in fc.run("sequence.inspect", {})["video"][0]["items"]}
        for clip, effect, param, t, how in eases:
            it = layout.get(clip)
            if not it:
                continue
            media_t = int(it["sourceIn"] + (t - it["start"]) * it.get("speed", 1.0))
            try:
                run("effects.setInterpolation", {"clip": clip, "effect": effect, "param": param, "mediaTime": media_t, "interpolation": how})
            except MCPError as err:
                warnings.append(f"easing {param}@{t / TICKS:.2f}s: {str(err)[:100]}")
    # music: merge consecutive sections with the same mood into one bed
    # a library track (or a mood with music_start) plays so that its music_start lands on the bed's first cut
    beds = edl.music_beds()
    for k, bed in enumerate(beds):
        path = edl.music_path(bed["mood"])
        track = bed.pop("track", None)
        start = max(0.0, bed["start"] - (0.4 if k else 0))
        length = media_duration(path) - 0.1
        dur = bed["end"] - start + (0.4 if k + 1 < len(beds) else 0)
        src = 0.0
        if bed["music_start"] is not None:
            src = max(0.0, bed["music_start"] - (bed["start"] - start))
            if src + dur > length:  # not enough track after the drop: start earlier, by whole beats if known
                need = src + dur - length
                beats = (track or {}).get("beats") or []
                period = (60.0 / track["bpm"]) if track and track.get("bpm") else 0
                if period:
                    need = math.ceil(need / period) * period
                src = max(0.0, src - need)
                bed["shifted_seconds"] = round(need, 3) if src else None
                if beats:
                    bed["on_beat"] = any(abs(b - (src + bed["start"] - start)) < 0.03 for b in beats)
        bed["source_in"] = round(src, 3)
        dur = min(dur, length - src)
        place = {"item": imp(path), "track": "A1" if k % 2 == 0 else "A2", "seconds": start, "insert": False, "video": False,
                 "duration": {"seconds": dur}}
        if src > 0:
            place["sourceIn"] = {"seconds": src}
        cid = run("timeline.place", place)["clips"][0]
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
    stats = {"calls": calls, "seconds": round(time.time() - t0, 1), "beds": beds, "warnings": warnings}
    return Compiled(fc, clip_ids, times, stats)
