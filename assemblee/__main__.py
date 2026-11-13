"""assemblee CLI.

  python3 -m assemblee run --task "..." --assets DIR [--brief file.md ...] [--seconds 60] [--slots 2] [--name video.mp4]
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
    r.add_argument("--assets", required=True, type=Path)
    r.add_argument("--brief", action="append", default=[], type=Path, help="markdown brief/GDD, repeatable")
    r.add_argument("--seconds", type=float, default=60)
    r.add_argument("--slots", type=int, default=2, help="parallel requests (match llama-server --parallel)")
    r.add_argument("--name", default="video.mp4")
    r.add_argument("--polish-turns", type=int, default=9)
    r.add_argument("--review-rounds", type=int, default=2)
    c = sub.add_parser("catalog", help="describe pictures with the vision model")
    c.add_argument("dir", type=Path)
    a = ap.parse_args(argv)

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
    (run_dir / "task.json").write_text(json.dumps({"run_id": run_id, "task": task, "assets_dir": str(a.assets), "briefs": [str(b) for b in a.brief],
                                                    "model": llm.model_name(), "seconds": a.seconds, "slots": a.slots, "created_at": time.time()},
                                                   ensure_ascii=False, indent=1))
    print("run:", run_dir, flush=True)
    from .agent import Agent
    summary = Agent(task, a.assets, a.brief, run_dir, seconds=a.seconds, slots=a.slots, llm=llm, max_polish_turns=a.polish_turns,
                    review_rounds=a.review_rounds, output_name=a.name).run()
    print(json.dumps({k: v for k, v in summary.items() if k != "edl"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
