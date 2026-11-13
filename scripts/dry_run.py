#!/usr/bin/env python3
"""Run the whole agent with a scripted fake LLM (no GPU): exercises every phase, the event log and the real engines.

usage: python3 scripts/dry_run.py [assets_dir]
"""
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assemblee.agent import Agent  # noqa: E402
from assemblee.config import RUNS  # noqa: E402


class FakeLLM:
    totals = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0}

    def __init__(self):
        self.rng = random.Random(7)

    def health(self):
        return True

    def model_name(self):
        return "fake-llm"

    def _r(self, content):
        self.totals["requests"] += 1
        return {"message": {"role": "assistant", "content": content}, "usage": {"prompt_tokens": 1000, "completion_tokens": 120},
                "seconds": 0.05, "tokens_per_second": 42.0, "prompt_per_second": 900.0}

    def json(self, messages, schema, max_tokens=0, temperature=0):
        props = schema["properties"]
        if "sections" in props:
            out = {"title": "Dry run", "concept": "test", "sections": [
                {"name": "intro", "goal": "зацепить", "target_seconds": 4, "music": "dark_drone", "music_db": -10, "visual_style": "glitch", "asset_group": "any", "transition_in": "glitch"},
                {"name": "middle", "goal": "показать", "target_seconds": 8, "music": "chiptune", "music_db": -10, "visual_style": "bright", "asset_group": "server-beast", "transition_in": "whip"},
                {"name": "ending", "goal": "финал", "target_seconds": 4, "music": "epic", "music_db": -8, "visual_style": "dark", "asset_group": "spider", "transition_in": "flash"}]}
        elif "shots" in props:
            ids = [x for x in props["shots"]["items"]["properties"]["asset"]["enum"] if x]
            out = {"shots": [{"kind": "card", "asset": "", "seconds": 2, "card_title": "Заголовок", "card_subtitle": "подзаголовок", "card_style": "glitch",
                              "transition_out": "glitch"}] + [
                {"kind": "picture", "asset": self.rng.choice(ids), "seconds": 2, "motion": self.rng.choice(["zoom_in", "punch_in", "pan_left"]),
                 "look": "cartoon_pop", "caption": "Тестовая подпись", "caption_style": self.rng.choice(["cartoon", "system", "retro2011"]),
                 "caption_position": "bottom", "effects": ["rgb_split"], "transition_out": "cut"} for _ in range(2)]}
        elif "actions" in props:
            text = json.dumps(messages[-1]["content"], ensure_ascii=False)
            out = {"thoughts": "fix", "actions": [{"op": "add_sfx", "kind": "whoosh", "shot": 2, "at": "start"},
                                                  {"op": "update_shot", "shot": 3, "effects": [], "motion": "zoom_out"}], "done": True}
            if "читается плохо" in text:
                out["actions"] = [{"op": "update_shot", "shot": 2, "effects": []}]
        elif "text_readable" in props:
            out = {"text_readable": self.rng.random() > 0.3, "seen": "кадр с подписью"}
        else:
            out = {}
        return out, self._r(json.dumps(out, ensure_ascii=False))

    def vision(self, png, question, schema, max_side=960):
        return {"text_readable": self.rng.random() > 0.3, "seen": "кадр с подписью"}


assets = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/slager/Рабочий стол/refs")
run_dir = RUNS / (time.strftime("%Y%m%d-%H%M%S") + "-dry-run")
run_dir.mkdir(parents=True, exist_ok=True)
(run_dir / "task.json").write_text(json.dumps({"run_id": run_dir.name, "task": "dry run", "assets_dir": str(assets), "model": "fake-llm",
                                               "created_at": time.time()}, ensure_ascii=False))
s = Agent("Сухой прогон обвязки", assets, [], run_dir, seconds=16, slots=2, llm=FakeLLM(), output_name="dry.mp4").run()
print(json.dumps({k: v for k, v in s.items() if k != "edl"}, ensure_ascii=False, indent=1))
print("events:", sum(1 for _ in open(run_dir / "events.jsonl")), "run dir:", run_dir)
