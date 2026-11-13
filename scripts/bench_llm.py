#!/usr/bin/env python3
"""Benchmark a running llama-server for the assemblee agent workload.

Starts nothing itself: point it at a port where llama-server already listens.

Measures (all numbers come from the server's own `timings` where possible):
  pp      prompt processing t/s on a ~20k token realistic prompt
          (tools JSON + agent history), cold (unique prefix, nothing cached)
  warm    time-to-first-token when the same prompt is sent again
          (prefix cache hit) and for the realistic "next agent turn" case:
          previous prompt + assistant tool call + tool result + new user msg
  tg      generation t/s while producing a ~400 token tool-call answer
          at ~20k depth (also draft acceptance if speculative decoding is on)
  vision  latency of one 540x960 PNG + short question, JSON-schema answer
  conc    (--concurrent) vision request fired while the tool-call answer
          is being generated; reports both streams

Python stdlib only.  Example:
  python3 scripts/bench_llm.py --port 8011 --label baseline --out .cache/bench.jsonl
"""
import argparse
import base64
import json
import random
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib

# --------------------------------------------------------------------------
# realistic agent prompt
# --------------------------------------------------------------------------

def _p(desc, **props):
    return {"type": "string", "description": desc, **props}


def make_tools():
    num = {"type": "number"}
    tools = [
        ("list_assets", "List media files in the assets directory with duration, resolution, fps, audio presence.",
         {"kind": {"type": "string", "enum": ["video", "image", "audio", "all"]}}, []),
        ("probe_clip", "Return ffprobe metadata, scene cuts, loudness and a transcript for one asset.",
         {"path": _p("asset path relative to assets_dir"), "transcript": {"type": "boolean"}}, ["path"]),
        ("render_frame", "Render one frame of the current timeline (or of a raw asset) to PNG for visual checking.",
         {"at": {**num, "description": "seconds on the timeline"}, "asset": _p("optional raw asset"),
          "width": {"type": "integer"}}, ["at"]),
        ("look_at_frame", "Ask the vision model a question about a rendered frame. Returns JSON verdict.",
         {"path": _p("frames/....png"), "question": _p("what to check")}, ["path", "question"]),
        ("add_clip", "Append a clip to the timeline.",
         {"asset": _p("asset path"), "in": num, "out": num, "label": _p("short label"),
          "look": {"type": "string", "enum": ["none", "warm", "cold", "film", "bw", "vivid", "teal_orange"]},
          "motion": {"type": "string", "enum": ["none", "ken_burns_in", "ken_burns_out", "pan_left", "pan_right", "shake"]},
          "speed": num}, ["asset", "in", "out"]),
        ("add_card", "Insert a title card (solid/gradient background + text).",
         {"text": _p("card text"), "seconds": num, "style": {"type": "string", "enum": ["bold", "minimal", "glitch", "neon"]},
          "after": {"type": "integer"}}, ["text", "seconds"]),
        ("set_caption", "Burn a caption onto clip n.",
         {"n": {"type": "integer"}, "text": _p("caption"), "position": {"type": "string", "enum": ["top", "center", "bottom"]},
          "size": {"type": "integer"}}, ["n", "text"]),
        ("set_transition", "Set the transition after clip n.",
         {"after": {"type": "integer"}, "kind": {"type": "string", "enum": ["cut", "fade", "dissolve", "wipe", "zoom", "whip"]},
          "seconds": num}, ["after", "kind"]),
        ("add_effect", "Add an effect to clip n.",
         {"n": {"type": "integer"}, "effect": {"type": "string", "enum": ["vignette", "grain", "blur_bg", "flash", "rgb_split", "slowmo", "freeze"]},
          "strength": num}, ["n", "effect"]),
        ("add_music", "Lay a music bed between two timeline points.",
         {"mood": {"type": "string", "enum": ["epic", "chill", "funny", "tense", "sad"]}, "from": num, "to": num, "db": num},
         ["mood", "from", "to"]),
        ("add_sfx", "Add a sound effect at a time inside clip n.",
         {"kind": {"type": "string", "enum": ["whoosh", "boom", "click", "ding", "scratch", "laugh"]}, "clip": {"type": "integer"}, "at": num},
         ["kind", "clip", "at"]),
        ("set_timeline", "Replace the whole timeline at once. Use for (re)building the edit in one go.",
         {"clips": {"type": "array", "items": {"type": "object", "properties": {
             "asset": {"type": "string"}, "in": num, "out": num, "label": {"type": "string"},
             "look": {"type": "string"}, "motion": {"type": "string"}, "caption": {"type": "string"},
             "transition": {"type": "string"}}, "required": ["asset", "in", "out", "label"]}},
          "music": {"type": "array", "items": {"type": "object"}}}, ["clips"]),
        ("remove_clip", "Remove clip n.", {"n": {"type": "integer"}}, ["n"]),
        ("move_clip", "Move clip n to position m.", {"n": {"type": "integer"}, "to": {"type": "integer"}}, ["n", "to"]),
        ("trim_clip", "Change in/out points of clip n.", {"n": {"type": "integer"}, "in": num, "out": num}, ["n"]),
        ("get_timeline", "Return the current timeline as JSON.", {}, []),
        ("export", "Export the timeline to output/<name>.mp4.",
         {"name": _p("file name"), "preset": {"type": "string", "enum": ["draft", "final", "shorts"]}}, ["name"]),
        ("note", "Write a planning note to yourself (not shown to the user).", {"text": _p("note")}, ["text"]),
    ]
    out = []
    for name, desc, props, req in tools:
        out.append({"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": req}}})
    return out


SYSTEM = """You are Assemblee, an autonomous video editor for short gaming videos (Roblox, 9:16 shorts and 16:9 trailers).
You work ONLY through tools. Every reply must contain exactly one tool call; never answer with plain prose.
Workflow phases: explore (list and probe assets) -> plan (write a note with the story beats) -> build (timeline)
-> polish (captions, transitions, sfx, music) -> review (render frames and look at them) -> export.
Rules:
- Keep the total duration within the requested target (+-10%).
- Hook in the first 2 seconds: the most exciting moment goes first, then context.
- Captions: short (max 6 words), bottom position for gameplay, center for reaction moments.
- Never cut in the middle of a spoken sentence: use transcript word timings from probe_clip.
- After every 3-4 timeline edits render a frame and check it with look_at_frame.
- Prefer set_timeline when rebuilding more than 3 clips at once.
- Music bed at -18 dB under speech, -10 dB otherwise. SFX on impacts only.
- When the review passes, export with preset "final". If something fails, fix it and re-check.
"""

WORDS = ("ok so we spawn in the lobby and the server is literally on fire look at this guy he has the "
         "admin sword no way bro jumped off the tower we need to get the key before the timer runs out "
         "wait wait wait press the button now yes we did it gg chat that was insane let us try the obby again").split()


def fake_probe(rng, i):
    dur = round(rng.uniform(12, 95), 2)
    scenes = sorted(round(rng.uniform(0, dur), 2) for _ in range(rng.randint(5, 14)))
    words = []
    t = 0.3
    for _ in range(rng.randint(40, 90)):
        w = rng.choice(WORDS)
        d = round(rng.uniform(0.12, 0.45), 2)
        words.append({"w": w, "s": round(t, 2), "e": round(t + d, 2)})
        t += d + rng.uniform(0.02, 0.3)
    return {"path": f"raw/clip{i:02d}.mp4", "duration": dur, "width": 1920, "height": 1080, "fps": 60,
            "audio": True, "loudness_lufs": round(rng.uniform(-28, -12), 1),
            "scene_cuts": scenes, "peaks": [round(rng.uniform(0, dur), 2) for _ in range(6)],
            "transcript": " ".join(x["w"] for x in words), "words": words}


def build_messages(rounds, nonce, seed=7):
    rng = random.Random(seed)
    msgs = [{"role": "system", "content": f"[session {nonce}]\n" + SYSTEM},
            {"role": "user", "content": "Task: make a 45 second 9:16 short from the Server Beast gameplay in raw/. "
                                        "Funny tone, big captions, end with a 'subscribe' card."}]
    cid = 0
    for i in range(rounds):
        cid += 1
        call = {"id": f"call_{cid}", "type": "function",
                "function": {"name": "probe_clip", "arguments": json.dumps({"path": f"raw/clip{i:02d}.mp4", "transcript": True})}}
        msgs.append({"role": "assistant", "content": "", "tool_calls": [call]})
        msgs.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(fake_probe(rng, i))})
    return msgs


NEXT_USER = ("All clips are probed. Now call set_timeline ONCE with the full 45 second edit: 5 clips, each with "
             "asset, in, out, label, look, motion, caption and transition. Put the best moment first.")


def turn_extension(msgs, user_msg=False):
    """Next agent turn: assistant tool call + tool result carrying the next instruction.

    With user_msg=True the instruction comes as a new *user* message instead.  The Qwen3.5
    chat template then re-renders every earlier assistant turn without the empty
    <think></think> block, so the prompt diverges right after the first user message and
    almost the whole history has to be re-processed (hybrid model => no partial reuse).
    """
    call = {"id": "call_x1", "type": "function",
            "function": {"name": "note", "arguments": json.dumps({"text": "Beats: hook=admin sword, fail=tower jump, win=key."})}}
    out = msgs + [{"role": "assistant", "content": "", "tool_calls": [call]}]
    if user_msg:
        return out + [{"role": "tool", "tool_call_id": "call_x1", "content": json.dumps({"ok": True})},
                      {"role": "user", "content": NEXT_USER}]
    return out + [{"role": "tool", "tool_call_id": "call_x1", "content": json.dumps({"ok": True, "next": NEXT_USER})}]


# --------------------------------------------------------------------------
# synthetic 540x960 PNG (stdlib only)
# --------------------------------------------------------------------------

def make_png(w=540, h=960):
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            if 380 < y < 560 and 40 < x < 500:          # yellow caption box
                c = (250, 220, 40) if ((x // 23 + y // 31) % 3) else (20, 20, 20)
            elif y > 700:                                  # green ground
                c = (40, 150 + (x * 7 + y) % 40, 60)
            else:                                          # sky gradient + blocky "character"
                c = (90, 140 + y // 10, 230)
                if 200 < x < 330 and 580 < y < 700:
                    c = (200, 60, 50)
            row += bytes(c)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


VISION_SCHEMA = {"type": "object", "properties": {
    "text_readable": {"type": "boolean"}, "seen": {"type": "string", "maxLength": 120}},
    "required": ["text_readable", "seen"]}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class Client:
    def __init__(self, port, host="127.0.0.1"):
        self.base = f"http://{host}:{port}"

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=30) as r:
            return json.loads(r.read())

    def chat_stream(self, body, timeout=900):
        """POST /v1/chat/completions with stream=True; returns dict with ttft, wall, timings, text."""
        body = dict(body, stream=True, timings_per_token=False)
        req = urllib.request.Request(self.base + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        t0 = time.perf_counter()
        ttft = None
        timings = None
        text = []
        n_chunks = 0
        usage = None
        calls = {}
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}") from None
        with resp as r:
            for line in r:
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if data == b"[DONE]":
                    break
                ev = json.loads(data)
                if ev.get("timings"):
                    timings = ev["timings"]
                if ev.get("usage"):
                    usage = ev["usage"]
                for ch in ev.get("choices", []):
                    d = ch.get("delta") or {}
                    piece = d.get("content") or ""
                    for tc in d.get("tool_calls") or []:
                        fn = tc.get("function") or {}
                        piece += (fn.get("name") or "") + (fn.get("arguments") or "")
                        slot = calls.setdefault(tc.get("index", 0), {"id": None, "name": "", "arguments": ""})
                        slot["id"] = tc.get("id") or slot["id"]
                        slot["name"] += fn.get("name") or ""
                        slot["arguments"] += fn.get("arguments") or ""
                    if piece:
                        n_chunks += 1
                        if ttft is None:
                            ttft = time.perf_counter() - t0
                        text.append(piece)
        wall = time.perf_counter() - t0
        return {"ttft": ttft if ttft is not None else wall, "wall": wall, "timings": timings or {},
                "usage": usage or {}, "text": "".join(text),
                "tool_calls": [calls[k] for k in sorted(calls)]}


def r1(x):
    return None if x is None else round(x, 1)


def r3(x):
    return None if x is None else round(x, 3)


# --------------------------------------------------------------------------
# benchmark steps
# --------------------------------------------------------------------------

def bench(args):
    cl = Client(args.port)
    nonce = f"{time.time():.6f}"
    tools = make_tools()
    msgs = build_messages(args.rounds, nonce)
    common = {"model": "x", "temperature": 0.0, "seed": 1, "tools": tools,
              "chat_template_kwargs": {"enable_thinking": False}}
    res = {"label": args.label, "port": args.port}

    # 1. cold prompt processing (unique nonce at the very start => no cache hit)
    r = cl.chat_stream(dict(common, messages=msgs, max_tokens=1))
    t = r["timings"]
    res["prompt_tokens"] = t.get("prompt_n")
    res["pp_tps"] = r1(t.get("prompt_per_second"))
    res["pp_wall_s"] = r3(r["wall"])
    print(f"[{args.label}] cold pp: {t.get('prompt_n')} tok @ {res['pp_tps']} t/s ({r['wall']:.2f}s)", file=sys.stderr)

    # 2. identical prompt again -> warm TTFT
    r = cl.chat_stream(dict(common, messages=msgs, max_tokens=1))
    res["ttft_warm_same_s"] = r3(r["ttft"])
    res["warm_same_prompt_n"] = r["timings"].get("prompt_n")
    print(f"[{args.label}] warm same: ttft {r['ttft']:.3f}s, reprocessed {res['warm_same_prompt_n']} tok", file=sys.stderr)

    # 3. next agent turn (prefix + tool call + tool result) -> warm TTFT + tool-call generation
    ext = turn_extension(msgs)
    gen_body = dict(common, messages=ext, max_tokens=args.gen_tokens, tool_choice="required")

    vision_out = {}
    vth = None
    if args.concurrent and not args.no_vision:
        png = make_png()

        def vis():
            time.sleep(args.concurrent_delay)
            vision_out.update(vision_request(cl, png))
        vth = threading.Thread(target=vis)
        vth.start()

    best = None
    first = None
    for i in range(1 if args.concurrent else args.gen_repeats):
        r = cl.chat_stream(gen_body)
        t = r["timings"]
        if i == 0:
            first = r
            res["ttft_warm_turn_s"] = r3(r["ttft"])
            res["warm_turn_prompt_n"] = t.get("prompt_n")
        if best is None or (t.get("predicted_per_second") or 0) > (best["timings"].get("predicted_per_second") or 0):
            best = r
    t = best["timings"]
    res["gen_tokens"] = t.get("predicted_n")
    res["tg_tps"] = r1(t.get("predicted_per_second"))
    res["gen_wall_s"] = r3(best["wall"])
    if t.get("draft_n"):
        res["draft_n"] = t.get("draft_n")
        res["draft_accepted"] = t.get("draft_n_accepted")
        res["accept_rate"] = r3(t["draft_n_accepted"] / t["draft_n"])
    res["gen_sample"] = best["text"][:160]
    print(f"[{args.label}] turn ttft {res['ttft_warm_turn_s']}s (reprocessed {res['warm_turn_prompt_n']}), "
          f"tg {res['tg_tps']} t/s over {res['gen_tokens']} tok"
          + (f", accept {res.get('accept_rate')}" if "accept_rate" in res else ""), file=sys.stderr)

    nxt = None
    # 3b. the turn after that: history + the call the model really generated + its result.
    #     Shows whether generated tokens are reused (re-rendered template == generated text).
    if first["tool_calls"] and not args.concurrent:
        tc = first["tool_calls"][0]
        call = {"id": tc["id"] or "call_g1", "type": "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"]}}
        nxt = ext + [{"role": "assistant", "content": "", "tool_calls": [call]},
                     {"role": "tool", "tool_call_id": call["id"], "content": json.dumps({"ok": True, "clips": 5})}]
        try:
            r = cl.chat_stream(dict(common, messages=nxt, max_tokens=1))
            res["ttft_after_gen_s"] = r3(r["ttft"])
            res["after_gen_prompt_n"] = r["timings"].get("prompt_n")
            print(f"[{args.label}] turn after gen: ttft {r['ttft']:.3f}s (reprocessed {res['after_gen_prompt_n']})", file=sys.stderr)
        except RuntimeError as e:
            print(f"[{args.label}] turn after gen failed: {e}", file=sys.stderr)

    # 3c. optional: instruction as a new user message (template re-renders history)
    if args.user_turn:
        r = cl.chat_stream(dict(common, messages=turn_extension(msgs, user_msg=True), max_tokens=1))
        res["ttft_new_user_s"] = r3(r["ttft"])
        res["new_user_prompt_n"] = r["timings"].get("prompt_n")
        print(f"[{args.label}] new user msg: ttft {r['ttft']:.3f}s (reprocessed {res['new_user_prompt_n']})", file=sys.stderr)

    # 4. vision
    if not args.no_vision:
        if vth:
            vth.join()
            res["conc_vision_s"] = r3(vision_out.get("wall"))
            res["conc_vision_ok"] = vision_out.get("ok")
            res["conc_vision_err"] = vision_out.get("err")
            print(f"[{args.label}] concurrent vision {res['conc_vision_s']}s ok={res['conc_vision_ok']}", file=sys.stderr)
        else:
            png = make_png()
            v = vision_request(cl, png)
            res["vision_s"] = r3(v.get("wall"))
            res["vision_ok"] = v.get("ok")
            res["vision_answer"] = v.get("text", "")[:120]
            if v.get("err"):
                res["vision_err"] = v["err"]
            print(f"[{args.label}] vision {res['vision_s']}s ok={v.get('ok')} {res['vision_answer']!r}", file=sys.stderr)
            # 5. agent turn right after the vision request: with one slot the agent's KV was
            #    swapped out to the RAM prompt cache (or dropped if it did not fit --cache-ram)
            if nxt is not None and v.get("ok"):
                r = cl.chat_stream(dict(common, messages=nxt, max_tokens=1))
                res["ttft_after_vision_s"] = r3(r["ttft"])
                res["after_vision_prompt_n"] = r["timings"].get("prompt_n")
                print(f"[{args.label}] agent turn after vision: ttft {r['ttft']:.3f}s "
                      f"(reprocessed {res['after_vision_prompt_n']})", file=sys.stderr)

    try:
        props = cl.get("/props")
        res["n_ctx"] = (props.get("default_generation_settings") or {}).get("n_ctx")
    except Exception:
        pass
    return res


def vision_request(cl, png):
    url = "data:image/png;base64," + base64.b64encode(png).decode()
    body = {"model": "x", "temperature": 0.0, "max_tokens": 80,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {"name": "verdict", "schema": VISION_SCHEMA}},
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": url}},
                {"type": "text", "text": "Is the caption text in this frame readable? Answer JSON: text_readable, seen (what you see, short)."}]}]}
    try:
        r = cl.chat_stream(body)
        ok = True
        try:
            json.loads(r["text"])
        except Exception:
            ok = False
        return {"wall": r["wall"], "ttft": r["ttft"], "text": r["text"], "ok": ok, "timings": r["timings"]}
    except Exception as e:  # keep the bench going, report the failure
        return {"wall": None, "ok": False, "err": str(e)[:200]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--label", default="run")
    ap.add_argument("--rounds", type=int, default=10, help="probe_clip rounds in history (10 ~= 20k tokens)")
    ap.add_argument("--gen-tokens", type=int, default=800, help="max_tokens cap; the answer itself is ~400 tokens")
    ap.add_argument("--gen-repeats", type=int, default=2)
    ap.add_argument("--concurrent", action="store_true", help="fire the vision request during generation")
    ap.add_argument("--concurrent-delay", type=float, default=1.5, help="seconds after gen start")
    ap.add_argument("--no-vision", action="store_true")
    ap.add_argument("--user-turn", action="store_true", help="also time a turn that appends a user message")
    ap.add_argument("--out", help="append the JSON result line to this file")
    args = ap.parse_args()

    res = bench(args)
    line = json.dumps(res, ensure_ascii=False)
    print(line)
    if args.out:
        with open(args.out, "a") as f:
            f.write(line + "\n")


if __name__ == "__main__":
    main()
