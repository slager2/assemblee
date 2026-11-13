#!/usr/bin/env python3
"""Run the evaluation tasks (evals/tasks/*.json) and collect the run dirs into evals/results/<timestamp>.jsonl.

  python3 scripts/eval.py                                  # all tasks, 1 repeat, real model (server must be up)
  python3 scripts/eval.py --tasks pitch3 fast30 -n 3 --label rich -- --vocab rich
  python3 scripts/eval.py --dry -n 2                       # fake LLM, no GPU (evals/dry_agent.py)
  python3 scripts/eval.py --list

Everything after `--` is passed to `python3 -m assemblee run` unchanged (or, with --dry, mapped onto Agent
keyword arguments by evals/dry_agent.py). Then: python3 scripts/eval_report.py evals/results/<timestamp>.jsonl
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TASKS = REPO / "evals" / "tasks"
RESULTS = REPO / "evals" / "results"
sys.path.insert(0, str(REPO))


def load_tasks(ids=None):
    tasks = {}
    for p in sorted(TASKS.glob("*.json")):
        t = json.loads(p.read_text())
        t["_file"] = str(p)
        tasks[t["id"]] = t
    if ids:
        missing = [i for i in ids if i not in tasks]
        if missing:
            sys.exit(f"unknown task(s): {missing}; known: {list(tasks)}")
        return [tasks[i] for i in ids]
    return list(tasks.values())


def assets_path(t):
    p = Path(t["assets_dir"])
    return p if p.is_absolute() else REPO / p


def has_pictures(d):
    return d.is_dir() and any(x.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif") for x in d.rglob("*"))


def runs_dir():
    return Path(os.environ.get("ASSEMBLEE_RUNS", REPO / "runs")).expanduser()


def run_real(t, extra, log):
    cmd = [sys.executable, "-m", "assemblee", "run", "--task", t["task"], "--assets", str(assets_path(t)), "--seconds", str(t["seconds"])]
    for b in t["briefs"]:
        cmd += ["--brief", b]
    cmd += extra
    run_dir, lines = None, []
    with subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as p:
        for line in p.stdout:
            lines.append(line)
            log.write(line)
            m = re.match(r"run: (.+)$", line.strip())
            if m and run_dir is None:
                run_dir = Path(m.group(1))
    return p.returncode, run_dir, "".join(lines[-20:])


def run_dry(t, extra, seed, log):
    run_dir = runs_dir() / f"{time.strftime('%Y%m%d-%H%M%S')}-eval-dry-{t['id']}-s{seed}"
    env = {**os.environ, "ASSEMBLEE_CACHE": str(REPO / "evals" / ".cache-dry"),
           "ASSEMBLEE_AUDIO": os.environ.get("ASSEMBLEE_AUDIO", str(REPO / ".cache" / "audio"))}
    cmd = [sys.executable, str(REPO / "evals" / "dry_agent.py"), t["_file"], str(run_dir), "--seed", str(seed), "--"] + extra
    r = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True)
    log.write(r.stdout + r.stderr)
    return r.returncode, run_dir, (r.stdout + r.stderr)[-1500:]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", nargs="*", help="task ids (default: all)")
    ap.add_argument("-n", "--repeats", type=int, default=1)
    ap.add_argument("--dry", action="store_true", help="fake LLM (evals/fake_llm.py), no model server needed")
    ap.add_argument("--label", help="group name for the report (default: the extra args, or 'strict')")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", type=Path, help="results jsonl (default evals/results/<timestamp>.jsonl)")
    argv = sys.argv[1:]
    extra = argv[argv.index("--") + 1:] if "--" in argv else []
    a = ap.parse_args(argv[:argv.index("--")] if "--" in argv else argv)
    tasks = load_tasks(a.tasks)
    if a.list:
        for t in tasks:
            print(f"{t['id']:22} {t['seconds']:>4}s  {'needs fetch: ' + t['fetch'] if t.get('fetch') else ''} {t['task'][:70]}")
        return
    if not a.dry:
        from assemblee.llm import LLM
        if not LLM().health():
            sys.exit("LLM server is down (scripts/serve_llm.sh start agent). Refusing to run; use --dry for a fake-LLM run.")
    label = a.label or (" ".join(extra) if extra else "strict")
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = a.out or RESULTS / f"{stamp}{'-dry' if a.dry else ''}.jsonl"
    log = open(RESULTS / f"{out.stem}.log", "a")
    for t in tasks:
        if not has_pictures(assets_path(t)):
            why = f"needs-fetch ({t['fetch']})" if t.get("fetch") else "no-assets"
            print(f"skip {t['id']}: {why}: {assets_path(t)}", flush=True)
            rec = {"task_id": t["id"], "skipped": why, "label": label, "dry": a.dry, "extra_args": extra, "started": time.time()}
            with open(out, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            continue
        for k in range(a.repeats):
            t0 = time.time()
            print(f"run {t['id']} #{k + 1}/{a.repeats} [{label}]{' dry' if a.dry else ''} ...", flush=True)
            code, run_dir, tail = run_dry(t, extra, k + 1, log) if a.dry else run_real(t, extra, log)
            if run_dir and run_dir.is_dir() and not (run_dir / "eval.json").exists():
                (run_dir / "eval.json").write_text(json.dumps({"task_id": t["id"], "dry": a.dry, "repeat": k + 1, "label": label,
                                                               "extra_args": extra}, ensure_ascii=False, indent=1))
            elif run_dir and (run_dir / "eval.json").exists():
                meta = json.loads((run_dir / "eval.json").read_text())
                meta.update(repeat=k + 1, label=label)
                (run_dir / "eval.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
            rec = {"task_id": t["id"], "repeat": k + 1, "label": label, "dry": a.dry, "extra_args": extra, "returncode": code,
                   "run_dir": str(run_dir) if run_dir else None, "wall_seconds": round(time.time() - t0, 1), "started": t0}
            if code:
                rec["tail"] = tail[-600:]
            with open(out, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            summ = Path(run_dir) / "summary.json" if run_dir else None
            ok = code == 0 and summ is not None and summ.exists() and json.loads(summ.read_text()).get("ok")
            rec["ok"] = bool(ok)
            reason = "" if ok else (json.loads(summ.read_text()).get("reason", "")[:120] if summ and summ.exists() else f"exit {code}")
            print(f"  -> {'ok' if ok else 'FAILED: ' + reason} {rec['wall_seconds']}s {run_dir}", flush=True)
    print("results:", out)
    print("report:  python3 scripts/eval_report.py", out)


if __name__ == "__main__":
    main()
