#!/usr/bin/env python3
"""One --dry evaluation run: the real Agent (real engines, real event log) driven by evals/fake_llm.FakeLLM.

Built like scripts/dry_run.py (Agent(..., llm=FakeLLM())), so no assemblee code is changed.
scripts/eval.py starts this in a subprocess with ASSEMBLEE_CACHE pointing to a separate dry cache, so the
fake catalog descriptions never overwrite the real vision catalog in .cache/catalogs.

usage: evals/dry_agent.py TASK.json RUN_DIR --seed N [-- extra agent flags, e.g. --vocab rich]
Extra flags become Agent keyword arguments when Agent accepts them (--vocab rich -> vocab="rich");
unsupported ones are recorded in eval.json as ignored.
"""
import argparse
import inspect
import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "evals"))


def parse_extra(extra):
    out, k = {}, 0
    while k < len(extra):
        a = extra[k]
        if a.startswith("--"):
            key = a[2:].replace("-", "_")
            if "=" in key:
                key, val = key.split("=", 1)
                out[key] = val
            elif k + 1 < len(extra) and not extra[k + 1].startswith("--"):
                out[key] = extra[k + 1]
                k += 1
            else:
                out[key] = True
        k += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task_file", type=Path)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--real-cache", type=Path, default=REPO / ".cache")
    a, extra = ap.parse_known_args()
    extra = [x for x in extra if x != "--"]
    t = json.loads(a.task_file.read_text())

    from assemblee.agent import Agent
    from assemblee.assets import catalog_path
    from fake_llm import FakeLLM

    # seed the dry cache with the real catalog (read-only copy), so dry runs see real picture descriptions
    dst = catalog_path(t["assets_dir"])
    src = a.real_cache / "catalogs" / dst.name
    if src.exists() and not dst.exists() and src.resolve() != dst.resolve():
        shutil.copy(src, dst)

    params = inspect.signature(Agent.__init__).parameters
    kwargs, ignored = {}, {}
    for key, val in parse_extra(extra).items():
        mapped = {"polish_turns": "max_polish_turns", "name": "output_name"}.get(key, key)
        if mapped in params and mapped not in ("task", "assets_dir", "briefs", "run_dir", "llm"):
            ann = params[mapped].default
            kwargs[mapped] = type(ann)(val) if isinstance(ann, (int, float)) and not isinstance(ann, bool) else val
        else:
            ignored[key] = val

    run_dir = a.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task.json").write_text(json.dumps({"run_id": run_dir.name, "task": t["task"], "assets_dir": t["assets_dir"], "briefs": t["briefs"],
                                                   "model": "fake-llm", "seconds": t["seconds"], "created_at": time.time()}, ensure_ascii=False, indent=1))
    (run_dir / "eval.json").write_text(json.dumps({"task_id": t["id"], "dry": True, "seed": a.seed, "extra_args": extra,
                                                   "agent_kwargs": kwargs, "ignored_args": ignored}, ensure_ascii=False, indent=1))
    kwargs.setdefault("seconds", t["seconds"])
    kwargs.setdefault("output_name", "video.mp4")
    llm = FakeLLM(seed=a.seed, phrases=t.get("must_mention", []))
    s = Agent(t["task"], Path(t["assets_dir"]), [Path(b) for b in t["briefs"]], run_dir, llm=llm, **kwargs).run()
    print(json.dumps({k: v for k, v in s.items() if k != "edl"}, ensure_ascii=False))
    sys.exit(0 if s.get("ok") else 1)


if __name__ == "__main__":
    main()
