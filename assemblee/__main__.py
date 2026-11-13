"""assemblee CLI.

  python3 -m assemblee run --task "..." --assets DIR [--brief file.md ...] [--seconds 60] [--slots 2] [--name video.mp4]
        [--vocab strict|rich] [--guardrails full|light|off] [--think] [--planner 9b] [--director] [--max]
  python3 -m assemblee catalog DIR        # describe every picture once with the vision model (cached)
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

from .config import RUNS
from .llm import LLM


def slug(text, n=32):
    s = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ]+", "-", text.lower()).strip("-")
    return s[:n] or "run"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="assemblee")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="edit a video")
    r.add_argument("--task", required=True, help="what to make (text or @file)")
    r.add_argument("--assets", type=Path, help="folder of pictures (with --fetch: where downloaded pictures go)")
    r.add_argument("--fetch", default=None, help="search and download licensed pictures for this text before editing")
    r.add_argument("--vocab", choices=["strict", "rich"], default="strict", help="strict: small menus; rich: every engine transition/effect, grade, camera, text animation")
    r.add_argument("--brief", action="append", default=[], type=Path, help="markdown brief/GDD, repeatable")
    r.add_argument("--seconds", type=float, default=60)
    r.add_argument("--slots", type=int, default=2, help="parallel requests (match llama-server --parallel)")
    r.add_argument("--name", default="video.mp4")
    r.add_argument("--polish-turns", type=int, default=9)
    r.add_argument("--review-rounds", type=int, default=2)
    r.add_argument("--guardrails", choices=["full", "light", "off"], default="full",
                   help="full: harness fixes durations/key messages/transitions; light: only validation, the rest is feedback; off: light without reading warnings and duplicate removal")
    r.add_argument("--think", action="store_true", help="storyboard and section building think first (Qwen3.5 thinking)")
    r.add_argument("--think-budget", type=int, default=1024, help="thinking token budget per request")
    r.add_argument("--planner", choices=["9b"], default=None, help="plan/build/polish on Qwen3.5-9B, vision on the 4B (swaps llama-server via scripts/serve_llm.sh)")
    r.add_argument("--director", action=argparse.BooleanOptionalAction, default=None,
                   help="contact-sheet self-review by the vision model after polish (default: on unless --guardrails full)")
    r.add_argument("--max", action="store_true", help="= --vocab rich --guardrails light --think --planner 9b --director")
    c = sub.add_parser("catalog", help="describe pictures with the vision model")
    c.add_argument("dir", type=Path)
    a = ap.parse_args(argv)
    if getattr(a, "max", False):
        a.vocab, a.guardrails, a.think, a.planner, a.director = "rich", "light", True, "9b", True

    llm = LLM()
    if not llm.health():
        sys.exit("LLM server is not running: scripts/serve_llm.sh start agent")
    if a.cmd == "catalog":
        from .assets import load_or_build
        cat = load_or_build(a.dir, llm=llm, on_item=lambda k, e: print(k, "|", e["what"], "|", e["mood"], flush=True))
        print(len(cat), "assets")
        return
    task = Path(a.task[1:]).read_text() if a.task.startswith("@") else a.task
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + slug(task)
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if a.assets is None:
        if not a.fetch:
            sys.exit("--assets is required unless --fetch is given")
        a.assets = run_dir / "assets"
    (run_dir / "task.json").write_text(json.dumps({"run_id": run_id, "task": task, "assets_dir": str(a.assets), "briefs": [str(b) for b in a.brief],
                                                    "vocab": a.vocab, "fetch": a.fetch, "guardrails": a.guardrails, "think": a.think,
                                                    "planner": a.planner, "director": a.director,
                                                    "model": llm.model_name(), "seconds": a.seconds, "slots": a.slots, "created_at": time.time()},
                                                   ensure_ascii=False, indent=1))
    print("run:", run_dir, flush=True)
    from .agent import Agent
    summary = Agent(task, a.assets, a.brief, run_dir, seconds=a.seconds, slots=a.slots, llm=llm, max_polish_turns=a.polish_turns,
                    review_rounds=a.review_rounds, output_name=a.name, mode=a.vocab, fetch=a.fetch, guardrails=a.guardrails,
                    think=a.think, think_budget=a.think_budget, planner=a.planner, director=a.director).run()
    print(json.dumps({k: v for k, v in summary.items() if k != "edl"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
