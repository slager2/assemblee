#!/usr/bin/env python3
"""Generate a realistic fake editing run for developing/demoing the web UI.

Writes runs/fake-<timestamp>/ (task.json, events.jsonl, frames/*.png,
output/trailer.mp4, summary.json) following docs/events.md, appending events
over about --duration seconds so the monitor can be watched live.

    python3 scripts/fake_run.py                 # ~60 s, into ./runs
    python3 scripts/fake_run.py --duration 10   # quicker
    python3 scripts/fake_run.py --fail          # ends with run_end ok=false
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MODEL = "qwen3-4b-instruct-q4_k_m"
TOOLS = [
    "list_assets", "probe_media", "read_gdd", "plan_edit", "add_clip", "add_card",
    "set_caption", "add_effect", "add_transition", "add_music", "add_sfx",
    "render_frame", "check_frame", "export_video",
]

LOOKS = {
    "teal_orange": ((18, 52, 64), (214, 120, 52)),
    "noir": ((14, 14, 18), (90, 90, 100)),
    "neon": ((40, 10, 70), (20, 200, 220)),
    "warm": ((70, 30, 20), (230, 180, 90)),
    "cold": ((10, 30, 60), (120, 170, 220)),
    "card_dark": ((12, 12, 16), (30, 30, 40)),
}

# (kind, label, seconds, look, motion, effects, caption)
PLAN = [
    ("card", "SERVER BEAST", 3.0, "card_dark", "fade_in", ["glow"], "SERVER BEAST"),
    ("clip", "Серверная ночью", 4.5, "cold", "slow_push", ["vignette"], None),
    ("clip", "Мигают диоды", 3.0, "neon", "handheld", ["grain"], None),
    ("clip", "Игрок входит", 4.0, "teal_orange", "dolly_left", [], "Ты думал, это просто работа"),
    ("card", "Ночная смена", 2.5, "card_dark", "static", [], "НОЧНАЯ СМЕНА"),
    ("clip", "Коридор стоек", 5.0, "noir", "slow_push", ["vignette", "grain"], None),
    ("clip", "Тень за стойкой", 3.5, "noir", "shake", ["chromatic"], "Что-то живёт в серверах"),
    ("clip", "Перегрев", 3.0, "warm", "zoom_in", ["heat_haze"], None),
    ("clip", "Погоня", 4.0, "teal_orange", "handheld", ["motion_blur", "shake"], None),
    ("card", "Не дай ему уйти в сеть", 2.5, "card_dark", "static", ["glitch"], "НЕ ДАЙ ЕМУ УЙТИ В СЕТЬ"),
    ("clip", "Кабели как щупальца", 4.0, "neon", "orbit", ["glitch"], None),
    ("clip", "Финальная схватка", 5.0, "warm", "zoom_in", ["flash", "shake"], "Перезагрузи его. Или он перезагрузит тебя"),
    ("clip", "Тишина", 3.0, "cold", "static", ["vignette"], None),
    ("card", "Скоро в Roblox", 3.0, "card_dark", "fade_in", ["glow"], "СКОРО В ROBLOX"),
    ("card", "Логотип", 2.5, "card_dark", "static", [], None),
]

TRANSITIONS = ["cut", "crossfade", "dip_black", "whip", "glitch"]


class Run:
    def __init__(self, root: Path, duration: float, seed: int):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.id = f"fake-{stamp}"
        self.dir = root / self.id
        (self.dir / "frames").mkdir(parents=True, exist_ok=True)
        (self.dir / "output").mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "events.jsonl"
        self.seq = 0
        self.rng = random.Random(seed)
        self.duration = duration
        self.t0 = time.time()
        self.call_n = 0
        self.turn = 0
        self.stats = {"turns": 0, "tool_calls": 0, "errors": 0, "completion_tokens": 0, "llm_seconds": 0.0}
        self.timeline = {"total_seconds": 0.0, "clips": [], "transitions": [], "music": [], "sfx": []}

    # ------------------------------------------------------------ plumbing

    def emit(self, type_: str, **data):
        self.seq += 1
        ev = {"seq": self.seq, "ts": round(time.time(), 3), "type": type_, "data": data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    def wait(self, units: float):
        """Sleep a share of the total duration (the script has ~135 units)."""
        time.sleep(max(0.0, units * self.duration / 135.0))

    def llm(self, content: str, calls: list[tuple[str, dict]], think: float = 3.0):
        self.turn += 1
        self.emit("llm_request", turn=self.turn, messages=2 + self.turn * 2,
                  prompt_tokens_est=1800 + self.turn * 420 + self.rng.randint(0, 300))
        self.wait(think)
        tps = round(self.rng.uniform(38, 62), 1)
        completion = max(12, len(content) // 3 + 40 * len(calls) + self.rng.randint(0, 40))
        secs = round(completion / tps, 2)
        self.stats["turns"] += 1
        self.stats["completion_tokens"] += completion
        self.stats["llm_seconds"] += secs
        self.emit("llm_response", turn=self.turn, content=content,
                  tool_calls=[{"name": n, "arguments": a} for n, a in calls],
                  usage={"prompt_tokens": 1800 + self.turn * 430, "completion_tokens": completion},
                  seconds=secs, tokens_per_second=tps)
        if self.rng.random() < 0.6:
            self.emit("llm_stats", tokens_per_second=tps,
                      kv_used=round(min(0.95, 0.08 + self.turn * 0.025), 3),
                      slots_busy=1, vram_mb=self.rng.choice([5210, 5234, 5260, None]))

    def tool(self, name: str, args: dict, result: dict | None = None, ok: bool = True,
             secs: float | None = None, units: float = 1.0):
        self.call_n += 1
        cid = f"call_{self.call_n:03d}"
        self.stats["tool_calls"] += 1
        self.emit("tool_call", id=cid, name=name, args=args)
        self.wait(units)
        if not ok:
            self.stats["errors"] += 1
        self.emit("tool_result", id=cid, name=name, ok=ok, result=result or {"ok": True},
                  seconds=round(secs if secs is not None else self.rng.uniform(0.05, 1.8), 3))

    def push_timeline(self):
        self.emit("timeline", **copy.deepcopy(self.timeline))

    # ------------------------------------------------------------ assets

    def draw_frame(self, name: str, look: str, title: str, caption: str | None,
                   card: bool, small_text: bool = False) -> str:
        w, h = 640, 360
        a, b = LOOKS.get(look, LOOKS["noir"])
        small = Image.new("RGB", (32, 18))
        px = small.load()
        for y in range(18):
            for x in range(32):
                t = (x / 31) * 0.7 + (y / 17) * 0.3
                px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
        img = small.resize((w, h), Image.BILINEAR)
        d = ImageDraw.Draw(img)
        if not card:  # fake "racks"
            for i in range(6):
                x = 40 + i * 100 + self.rng.randint(-8, 8)
                d.rectangle([x, 70, x + 60, 320], outline=(0, 0, 0), width=3)
                for j in range(8):
                    c = self.rng.choice([(40, 255, 120), (255, 80, 60), (80, 160, 255)])
                    d.ellipse([x + 8, 85 + j * 28, x + 14, 91 + j * 28], fill=c)
        try:
            big = ImageFont.truetype("DejaVuSans-Bold.ttf", 44 if card else 22)
            cap = ImageFont.truetype("DejaVuSans-Bold.ttf", 12 if small_text else 22)
        except OSError:
            big = cap = ImageFont.load_default()
        text = caption if (card and caption) else title
        if card:
            d.text((w / 2, h / 2), text, font=big, fill=(240, 240, 240), anchor="mm")
        else:
            d.text((16, 16), title, font=big, fill=(255, 255, 255, 200))
            if caption:
                d.rectangle([0, h - 60, w, h], fill=(0, 0, 0))
                d.text((w / 2, h - 30), caption, font=cap,
                       fill=(90, 90, 90) if small_text else (255, 255, 255), anchor="mm")
        rel = f"frames/{name}"
        img.save(self.dir / rel)
        return rel

    def make_video(self, seconds: float) -> Path:
        out = self.dir / "output" / "trailer.mp4"
        if shutil.which("ffmpeg"):
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=25:duration={seconds}",
                 "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}",
                 "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(out)],
                check=False,
            )
        if not out.exists():
            out.write_bytes(b"")
        return out


def play(run: Run, fail: bool):
    r = run
    task = ("Смонтируй 60-секундный тизер игры Server Beast из ассетов в assets/server_beast: "
            "карточки с текстом, мрачная музыка, звуки серверов, финальная карточка с призывом.")
    (r.dir / "task.json").write_text(json.dumps({
        "run_id": r.id, "task": task, "assets_dir": "assets/server_beast",
        "gdds": ["Desktop/GDD_Server_Beast.md"], "model": MODEL,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    r.emit("run_start", task=task, model=MODEL, tools=TOOLS)
    r.wait(2)

    # ---- explore
    r.emit("phase", name="explore", note="Смотрю ассеты и GDD")
    r.llm("Начну с того, что посмотрю, какие ассеты есть, и прочитаю GDD, чтобы понять тон игры.",
          [("list_assets", {"dir": "assets/server_beast"}), ("read_gdd", {"name": "Server Beast"})])
    r.tool("list_assets", {"dir": "assets/server_beast"},
           {"videos": [f"sb_{i:02d}.mp4" for i in range(1, 12)], "music": ["dark_pulse.mp3", "tension_rise.mp3", "epic_drop.mp3"],
            "sfx": ["hum.wav", "beep.wav", "boom.wav", "glitch.wav"], "images": ["logo.png"]}, units=2)
    r.tool("read_gdd", {"name": "Server Beast"},
           {"title": "Server Beast", "genre": "хоррор", "pitch": "Ночная смена в дата-центре, где в серверах живёт существо.",
            "tone": ["мрачно", "напряжённо", "кульминация"], "chars": 4120}, units=2)
    r.llm("Тон мрачный, хоррор. Проверю длительности нескольких клипов.",
          [("probe_media", {"path": "assets/server_beast/sb_01.mp4"})])
    for i in (1, 4, 7):
        r.tool("probe_media", {"path": f"assets/server_beast/sb_{i:02d}.mp4"},
               {"duration": round(r.rng.uniform(6, 14), 2), "width": 1920, "height": 1080, "fps": 30, "has_audio": i != 4},
               units=1.2)
    r.tool("probe_media", {"path": "assets/server_beast/sb_99.mp4"},
           {"error": "file not found: assets/server_beast/sb_99.mp4"}, ok=False, secs=0.02)
    r.emit("warning", message="Модель запросила несуществующий файл sb_99.mp4")

    # ---- plan
    r.emit("phase", name="plan", note="Структура тизера: 15 сцен, ~55 с")
    r.llm("План: открывающая карточка, нарастание в серверной, три текстовые карточки, кульминация, "
          "финальная карточка «Скоро в Roblox». Музыка: dark_pulse → tension_rise → epic_drop.",
          [("plan_edit", {"scenes": len(PLAN), "target_seconds": 55})], think=5)
    r.tool("plan_edit", {"scenes": len(PLAN), "target_seconds": 55,
                         "beats": ["intro", "build", "reveal", "climax", "cta"]},
           {"accepted": True, "scenes": len(PLAN)}, units=2)

    # ---- build
    r.emit("phase", name="build", note="Собираю таймлайн")
    t = 0.0
    for n, (kind, label, secs, look, motion, effects, caption) in enumerate(PLAN, start=1):
        tool = "add_card" if kind == "card" else "add_clip"
        args = ({"text": caption or label, "seconds": secs, "style": look} if kind == "card"
                else {"src": f"assets/server_beast/sb_{(n % 11) + 1:02d}.mp4", "in": round(r.rng.uniform(0, 4), 2),
                      "seconds": secs, "look": look, "motion": motion})
        if n == 1 or n % 3 == 0:
            r.llm(f"Добавляю сцену {n}: «{label}» ({secs:.1f} с, {look}, {motion}).", [(tool, args)], think=2)
        r.tool(tool, args, {"n": n, "start": round(t, 2), "end": round(t + secs, 2)}, units=1.0)
        thumb = r.draw_frame(f"clip{n:02d}.png", look, label, caption, kind == "card",
                             small_text=(n == 7))
        r.timeline["clips"].append({
            "n": n, "kind": kind, "label": label, "start": round(t, 2), "end": round(t + secs, 2),
            "look": look, "motion": motion, "effects": [], "caption": None, "thumb": thumb,
        })
        clip = r.timeline["clips"][-1]
        t += secs
        r.timeline["total_seconds"] = round(t, 2)
        if n > 1:
            kind_t = "cut" if n % 4 == 1 else TRANSITIONS[n % len(TRANSITIONS)]
            r.timeline["transitions"].append([n - 1, kind_t, 0.0 if kind_t == "cut" else round(r.rng.choice([0.3, 0.5, 0.8]), 1)])
        if caption and kind == "clip":
            r.tool("set_caption", {"clip": n, "text": caption, "position": "bottom"}, {"ok": True}, units=0.6)
        clip["caption"] = caption
        if effects:
            r.tool("add_effect", {"clip": n, "effects": effects}, {"applied": effects}, units=0.6)
            clip["effects"] = list(effects)
        if n == 9:
            r.tool("add_effect", {"clip": n, "effects": ["datamosh"]},
                   {"error": "unknown effect 'datamosh'", "available": ["glitch", "grain", "shake", "flash"]}, ok=False, secs=0.04)
            r.emit("error", message="EffectCraft: unknown effect 'datamosh'", where="tool:add_effect")
        r.push_timeline()
        if n in (3, 7, 12):
            r.emit("frame", path=thumb, clip=n, seconds=round(clip["start"] + 0.5, 2), verdict=None)
        r.wait(1.2)

    # music + sfx
    r.llm("Видеоряд собран. Кладу музыку по трём частям и звуки серверов.",
          [("add_music", {"track": "dark_pulse.mp3"}), ("add_sfx", {"kind": "hum"})], think=3)
    total = r.timeline["total_seconds"]
    music = [
        ("мрачно", "dark_pulse.mp3", 0.0, 17.0, -16),
        ("напряжённо", "tension_rise.mp3", 17.0, 36.5, -14),
        ("кульминация", "epic_drop.mp3", 36.5, total, -11),
    ]
    for mood, track, a, b, db in music:
        r.tool("add_music", {"track": track, "from": a, "to": b, "db": db, "mood": mood},
               {"ok": True, "duration": round(b - a, 2)}, units=1)
        r.timeline["music"].append({"mood": mood, "from": a, "to": round(b, 2), "db": db})
        r.push_timeline()
    sfx = [("hum", 2), ("beep", 3), ("glitch", 7), ("boom", 9), ("glitch", 10), ("boom", 12), ("beep", 15)]
    for kind, n in sfx:
        c = r.timeline["clips"][n - 1]
        at = round(c["start"] + r.rng.uniform(0.2, 0.6) * (c["end"] - c["start"]), 2)
        r.tool("add_sfx", {"kind": kind, "clip": n, "at": at}, {"ok": True}, units=0.5)
        r.timeline["sfx"].append({"kind": kind, "clip": n, "at": at})
    r.push_timeline()

    # ---- polish
    r.emit("phase", name="polish", note="Проверка читаемости текста на кадрах")
    r.llm("Проверю кадры с текстом: карточки и титры на клипах 4, 7, 12.",
          [("render_frame", {"clip": 4}), ("check_frame", {"path": "frames/clip04.png"})], think=3)
    for n in (1, 4, 7, 10, 12):
        c = r.timeline["clips"][n - 1]
        sec = round((c["start"] + c["end"]) / 2, 2)
        r.tool("render_frame", {"clip": n, "at": sec}, {"path": c["thumb"]}, units=1, secs=r.rng.uniform(0.4, 1.2))
        r.tool("check_frame", {"path": c["thumb"], "expect_text": c["caption"]}, units=2.5,
               secs=r.rng.uniform(1.5, 3.5),
               result={"text_readable": n != 7, "seen": (f"Виден текст «{c['caption']}»" if n != 7
                       else "Подпись внизу почти не видна: серый мелкий текст на тёмном фоне")})
        r.emit("frame", path=c["thumb"], clip=n, seconds=sec, verdict={
            "text_readable": n != 7,
            "seen": (f"Чётко читается «{c['caption']}», контраст хороший" if n != 7
                     else "Подпись внизу почти не видна: серый мелкий текст на тёмном фоне"),
        })
    r.llm("На клипе 7 титр не читается. Увеличу размер и сделаю текст белым с подложкой.",
          [("set_caption", {"clip": 7, "size": 34, "color": "#ffffff", "box": True})], think=3)
    r.tool("set_caption", {"clip": 7, "text": PLAN[6][6], "size": 34, "color": "#ffffff", "box": True}, {"ok": True}, units=1)
    c7 = r.timeline["clips"][6]
    c7["thumb"] = r.draw_frame("clip07.png", c7["look"], c7["label"], c7["caption"], False)
    c7["effects"] = c7["effects"] + ["caption_box"]
    r.push_timeline()
    r.tool("check_frame", {"path": c7["thumb"], "expect_text": c7["caption"]},
           {"text_readable": True, "seen": "Теперь титр крупный и белый"}, units=2.5, secs=2.4)
    r.emit("frame", path=c7["thumb"], clip=7, seconds=round((c7["start"] + c7["end"]) / 2, 2),
           verdict={"text_readable": True, "seen": "Титр крупный и белый на подложке, читается"})

    # ---- review
    r.emit("phase", name="review", note="Финальная проверка ритма")
    r.llm("Ритм хороший: длинные планы в начале, короче к кульминации. Можно экспортировать.", [], think=4)

    # ---- export
    r.emit("phase", name="export", note="Рендер mp4")
    r.llm("Экспортирую тизер в output/trailer.mp4.", [("export_video", {"path": "output/trailer.mp4"})], think=2)
    r.call_n += 1
    cid = f"call_{r.call_n:03d}"
    r.stats["tool_calls"] += 1
    r.emit("tool_call", id=cid, name="export_video", args={"path": "output/trailer.mp4", "crf": 20, "fps": 25})
    t_exp = time.time()
    out = r.make_video(total)
    r.wait(4)
    size = out.stat().st_size
    r.emit("tool_result", id=cid, name="export_video", ok=True,
           result={"path": "output/trailer.mp4", "seconds": total, "size_bytes": size},
           seconds=round(time.time() - t_exp, 2))
    r.emit("export", path="output/trailer.mp4", seconds=total, size_bytes=size)
    r.wait(2)

    st = r.stats
    summary = {
        "turns": st["turns"], "tool_calls": st["tool_calls"], "errors": st["errors"],
        "completion_tokens": st["completion_tokens"],
        "avg_tokens_per_second": round(st["completion_tokens"] / max(st["llm_seconds"], 1e-6), 1),
        "clips": len(r.timeline["clips"]), "video_seconds": total,
        "output": "output/trailer.mp4", "wall_seconds": round(time.time() - r.t0, 1),
    }
    (r.dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if fail:
        r.emit("error", message="Агент не подтвердил финальную проверку", where="harness")
        r.emit("run_end", ok=False, reason="review_failed", summary=summary)
    else:
        r.emit("run_end", ok=True, reason="exported", summary=summary)


def main():
    ap = argparse.ArgumentParser(description="write a fake assemblee run for the web UI")
    ap.add_argument("--runs", default="runs", help="runs directory (default: runs)")
    ap.add_argument("--duration", type=float, default=60.0, help="approx. wall seconds (default 60)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--fail", action="store_true", help="finish with run_end ok=false")
    args = ap.parse_args()
    run = Run(Path(args.runs), args.duration, args.seed)
    print(f"fake run: {run.dir}")
    play(run, args.fail)
    print(f"done: {run.seq} events in {time.time() - run.t0:.1f} s")


if __name__ == "__main__":
    main()
