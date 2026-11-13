#!/usr/bin/env python3
"""Programmatic metrics (no LLM) for assemblee runs, grouped into a markdown comparison table + per-run CSV.

  python3 scripts/eval_report.py evals/results/<stamp>.jsonl [more.jsonl ...]
  python3 scripts/eval_report.py --runs runs                       # every run dir under runs/
  python3 scripts/eval_report.py --runs runs --match сделай --group-by run
  options: --group-by label|task|run|label+task  --csv out.csv  --md out.md  --no-media

Inputs: results jsonl from scripts/eval.py, run dirs, or --runs DIR. Each run dir needs summary.json with "edl".
Metric definitions: docs/eval.md. ffmpeg results are cached in evals/.media-cache/.
"""
import argparse
import csv
import difflib
import io
import json
import math
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TASKS = REPO / "evals" / "tasks"
MEDIA_CACHE = REPO / "evals" / ".media-cache"
sys.path.insert(0, str(REPO))

try:  # vocabulary sizes for the variety denominators (read-only import)
    from assemblee.cards import CARD_STYLES
    from assemblee.edl import EFFECTS, LOOKS, MOTIONS, TRANSITIONS
    from assemblee.media import CAPTION_STYLES
except Exception:  # keep the report usable while assemblee is being edited
    MOTIONS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "punch_in", "still"]
    LOOKS = dict.fromkeys(range(10))
    EFFECTS = dict.fromkeys(range(9))
    TRANSITIONS = ["cut"] + list(range(15))
    CAPTION_STYLES = list(range(5))
    CARD_STYLES = list(range(7))

INVALID = re.compile(r"bad arguments|missing \[|unknown (tool|section)|does not exist|not allowed|not a number")
READ_CPS = 14  # characters per second a viewer reads (same constant as the harness)


# ---------- text matching (copy of assemblee.agent.text_match, so the report does not import the agent) ----------
def norm_text(t):
    return re.sub(r"[^0-9a-zа-яё]+", " ", str(t).lower().replace("ё", "е")).strip()


def text_match(read, expected):
    r, e = norm_text(read), norm_text(expected)
    if not e:
        return 1.0
    if not r:
        return 0.0
    words = e.split()
    hit = sum(1 for w in words if any(difflib.SequenceMatcher(None, w, x).ratio() >= 0.75 for x in r.split()))
    return max(hit / len(words), difflib.SequenceMatcher(None, r, e).ratio())


# ---------- inputs ----------
def load_tasks():
    out = {}
    for p in TASKS.glob("*.json"):
        t = json.loads(p.read_text())
        out[t["id"]] = t
    return out


def guess_task(task_text, tasks):
    for tid, t in tasks.items():
        if norm_text(t["task"]) == norm_text(task_text):
            return tid
    best = max(tasks, key=lambda k: difflib.SequenceMatcher(None, tasks[k]["task"], task_text).ratio(), default=None)
    if best and difflib.SequenceMatcher(None, tasks[best]["task"], task_text).ratio() > 0.85:
        return best
    return None


def read_json(p, default=None):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def collect(inputs, runs_root, match):
    """-> list of (run_dir, record-from-results-or-{})"""
    items = []
    for x in inputs:
        p = Path(x)
        if p.is_file() and p.suffix == ".jsonl":
            for line in p.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    if rec.get("run_dir"):
                        items.append((Path(rec["run_dir"]), rec))
        elif p.is_dir():
            items.append((p, {}))
    if runs_root:
        for d in sorted(Path(runs_root).iterdir()):
            if d.is_dir():
                items.append((d, {}))
    if match:
        items = [(d, r) for d, r in items if re.search(match, d.name)]
    seen, out = set(), []
    for d, r in items:
        if d.resolve() not in seen:
            seen.add(d.resolve())
            out.append((d, r))
    return out


# ---------- media checks ----------
def ff(args):
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats"] + args, capture_output=True, text=True, timeout=600).stderr


def media_checks(mp4: Path):
    st = mp4.stat()
    MEDIA_CACHE.mkdir(parents=True, exist_ok=True)
    key = MEDIA_CACHE / (re.sub(r"[^\w.-]+", "_", f"{mp4.parent.parent.name}-{mp4.name}") + ".json")
    cached = read_json(key)
    if cached and cached.get("mtime") == st.st_mtime and cached.get("size") == st.st_size:
        return cached
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(mp4)],
                           capture_output=True, text=True)
    info = json.loads(probe.stdout or "{}")
    dur = float(info.get("format", {}).get("duration") or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    mean_db = max_db = None
    if has_audio:
        log = ff(["-i", str(mp4), "-vn", "-af", "volumedetect", "-f", "null", "-"])
        m = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", log)
        mean_db = float(m.group(1)) if m and m.group(1) != "-inf" else -91.0
        m = re.search(r"max_volume: (-?[\d.]+|-inf) dB", log)
        max_db = float(m.group(1)) if m and m.group(1) != "-inf" else -91.0
    log = ff(["-i", str(mp4), "-an", "-vf", "blackdetect=d=0.3:pix_th=0.10", "-f", "null", "-"])
    black = sum(float(x) for x in re.findall(r"black_duration:([\d.]+)", log))
    out = {"mtime": st.st_mtime, "size": st.st_size, "video_seconds": round(dur, 2), "has_audio": has_audio,
           "mean_db": mean_db, "max_db": max_db, "black_seconds": round(black, 2)}
    key.write_text(json.dumps(out))
    return out


# ---------- metrics ----------
def shot_text(s):
    if s["kind"] == "card":
        return " ".join(x for x in (s.get("title"), s.get("subtitle")) if x)
    return (s.get("caption") or {}).get("text") or ""


def ratio_distinct(values, vocab_size):
    values = [v for v in values if v not in (None, "")]
    if not values:
        return 0.0
    return len(set(values)) / max(1, min(len(values), vocab_size))


def analyse(run_dir: Path, rec: dict, tasks: dict, with_media=True):
    summary = read_json(run_dir / "summary.json")
    if not summary or not summary.get("edl"):
        return None
    task_json = read_json(run_dir / "task.json", {})
    meta = read_json(run_dir / "eval.json", {})
    events = []
    for line in (run_dir / "events.jsonl").read_text().splitlines() if (run_dir / "events.jsonl").exists() else []:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    start = next((e["data"] for e in events if e["type"] == "run_start"), {})
    dry = bool(meta.get("dry", rec.get("dry", task_json.get("model") == "fake-llm")))
    task_id = meta.get("task_id") or rec.get("task_id") or guess_task(task_json.get("task", ""), tasks)
    task = tasks.get(task_id, {})
    label = rec.get("label") or meta.get("label") or task_json.get("vocab") or task_json.get("mode") or ("dry_run.py" if dry else "strict")
    target = float(task_json.get("seconds") or start.get("seconds") or task.get("seconds") or 60)

    shots = summary["edl"]["shots"]
    pics = [s for s in shots if s["kind"] == "picture"]
    lens = [float(s["seconds"]) for s in shots]
    texts = [(s, shot_text(s)) for s in shots]
    text_shots = [(s, t) for s, t in texts if t.strip()]
    violations = sum(1 for s, t in text_shots if len(t.strip()) / READ_CPS > float(s["seconds"]) + 0.05)
    assets = [s["asset"] for s in pics]
    repeats = len(assets) - len(set(assets))

    var = {
        "var_motion": ratio_distinct([s["motion"] for s in pics], len(MOTIONS)),
        "var_look": ratio_distinct([s["look"] for s in pics], len(LOOKS)),
        "var_transition": ratio_distinct([s["transition_out"] for s in shots[:-1] if s["transition_out"] != "cut"], len(TRANSITIONS) - 1),
        "var_effect": ratio_distinct([e for s in pics for e in s.get("effects", [])], len(EFFECTS)),
        "var_caption_style": ratio_distinct([s["caption"]["style"] for s in pics if s.get("caption")], len(CAPTION_STYLES)),
    }

    must = task.get("must_mention") or []
    covered = []
    for m in must:
        alts = [m] if isinstance(m, str) else list(m)
        covered.append(any(text_match(t, alt) >= 0.6 for _, t in text_shots for alt in alts))
    coverage = sum(covered) / len(covered) if covered else None

    frames = [e["data"] for e in events if e["type"] == "frame" and e["data"].get("verdict")]
    by_round = defaultdict(list)
    for f in frames:
        m = re.search(r"-r(\d+)\.png$", f.get("path", ""))
        by_round[int(m.group(1)) if m else 1].append(f)
    def rate(fs):
        return sum(1 for f in fs if f["verdict"].get("text_readable")) / len(fs) if fs else None
    rounds = sorted(by_round)
    last = by_round[rounds[-1]] if rounds else []
    matches = [f["verdict"]["match"] for f in last if "match" in f["verdict"]]

    results = [e["data"] for e in events if e["type"] == "tool_result"]
    model_results = [r for r in results if not str(r.get("id", "")).startswith("h")]
    build_warn = sum(len((r.get("result") or {}).get("warnings") or []) for r in results if r.get("name") == "build_section")
    tool_warn = sum(len((r.get("result") or {}).get("warnings") or []) for r in model_results if isinstance(r.get("result"), dict))
    # invalid call = the model broke the tool contract; refusal = valid call the harness policy declined (8 sfx max, ...)
    invalid = [r for r in model_results if not r.get("ok") and INVALID.search(json.dumps(r.get("result"), ensure_ascii=False))]
    llm = summary.get("llm") or {}

    out_path = Path(summary.get("output") or "")
    if summary.get("output") and not out_path.is_absolute():
        out_path = run_dir / out_path
    exported = bool(summary.get("ok")) and out_path.is_file()
    row = {
        "run": run_dir.name, "task": task_id or "?", "label": label, "dry": dry, "exported": int(exported),
        "target_s": target, "edl_s": float(summary.get("seconds") or sum(lens)),
        "shots": len(shots), "cards": len(shots) - len(pics),
        "avg_shot_s": statistics.mean(lens) if lens else 0, "min_shot_s": min(lens) if lens else 0,
        "reading_violations": violations, "reading_ok": 1 - violations / len(text_shots) if text_shots else None,
        "repeated_assets": repeats, "unique_assets": 1 - repeats / len(assets) if assets else None,
        **var, "variety": statistics.mean(var.values()),
        "text_share": len(text_shots) / len(shots) if shots else 0,
        "must_mention": coverage, "must_missing": "; ".join((m if isinstance(m, str) else m[0]) for m, c in zip(must, covered) if not c),
        "readable_first": rate(by_round[rounds[0]]) if rounds else None, "readable_last": rate(last),
        "vision_match_last": statistics.mean(matches) if matches else None, "review_rounds": len(rounds),
        "schema_warnings": build_warn + tool_warn, "llm_warnings": sum(1 for e in events if e["type"] == "warning"),
        "tool_calls": len(model_results), "tool_errors": sum(1 for r in model_results if not r.get("ok")),
        "tool_invalid": len(invalid), "tool_refusals": sum(1 for r in model_results if not r.get("ok")) - len(invalid),
        "tool_ok": 1 - len(invalid) / len(model_results) if model_results else None,
        "error_events": sum(1 for e in events if e["type"] == "error"),
        "llm_requests": llm.get("requests"), "json_calls": sum(1 for e in events if e["type"] == "llm_request"),
        "prompt_tokens": llm.get("prompt_tokens"), "completion_tokens": llm.get("completion_tokens"),
        "llm_seconds": round(llm.get("seconds") or 0, 1), "wall_s": summary.get("wall_seconds"),
    }
    if with_media and exported:
        m = media_checks(out_path)
        row.update(video_s=m["video_seconds"], mean_db=m["mean_db"], audio_ok=int(m["has_audio"] and (m["mean_db"] or -99) > -40),
                   black_share=m["black_seconds"] / m["video_seconds"] if m["video_seconds"] else None)
    else:
        row.update(video_s=None, mean_db=None, audio_ok=None, black_share=None)
    dur = row["video_s"] or row["edl_s"]
    row["duration_err"] = abs(dur - target) / target if target else None
    row["score"] = score(row)
    return row


def score(r):
    """0..100: mean of the 0..1 quality components that are defined for this run (see docs/eval.md)."""
    parts = [r["exported"],
             max(0.0, 1 - r["duration_err"] / 0.5) if r["duration_err"] is not None else None,
             r["reading_ok"], r["readable_last"], r["must_mention"], r["unique_assets"], r["variety"],
             r["audio_ok"], (1 - r["black_share"]) if r["black_share"] is not None else None, r["tool_ok"]]
    parts = [p for p in parts if p is not None]
    return round(100 * statistics.mean(parts), 1) if parts else None


# ---------- output ----------
TABLE = [  # (column, title, format, better)
    ("score", "score (0–100)", "{:.1f}", "↑"),
    ("exported", "exported", "{:.2f}", "↑"),
    ("duration_err", "duration error, abs % of target", "{:.1%}", "↓"),
    ("shots", "shots", "{:.1f}", ""),
    ("avg_shot_s", "avg shot, s", "{:.2f}", ""),
    ("min_shot_s", "min shot, s", "{:.2f}", ""),
    ("reading_violations", "reading-time violations", "{:.1f}", "↓"),
    ("repeated_assets", "repeated assets", "{:.1f}", "↓"),
    ("var_motion", "variety: motion", "{:.2f}", "↑"),
    ("var_look", "variety: look", "{:.2f}", "↑"),
    ("var_transition", "variety: transition", "{:.2f}", "↑"),
    ("var_effect", "variety: effect", "{:.2f}", "↑"),
    ("var_caption_style", "variety: caption style", "{:.2f}", "↑"),
    ("text_share", "shots with text", "{:.0%}", ""),
    ("must_mention", "must_mention coverage", "{:.0%}", "↑"),
    ("readable_first", "vision readable, 1st round", "{:.0%}", "↑"),
    ("readable_last", "vision readable, last round", "{:.0%}", "↑"),
    ("schema_warnings", "schema/validation warnings", "{:.1f}", "↓"),
    ("tool_errors", "tool errors, all", "{:.1f}", "↓"),
    ("tool_invalid", "  of them invalid calls", "{:.1f}", "↓"),
    ("tool_refusals", "  of them policy refusals", "{:.1f}", ""),
    ("llm_warnings", "LLM retries/warnings", "{:.1f}", "↓"),
    ("llm_requests", "LLM requests (incl. vision)", "{:.0f}", "↓"),
    ("prompt_tokens", "prompt tokens", "{:.0f}", "↓"),
    ("completion_tokens", "completion tokens", "{:.0f}", "↓"),
    ("wall_s", "wall time, s", "{:.0f}", "↓"),
    ("audio_ok", "audio present (mean > −40 dB)", "{:.2f}", "↑"),
    ("mean_db", "mean volume, dB", "{:.1f}", ""),
    ("black_share", "black frames share", "{:.1%}", "↓"),
]


def cell(vals, fmt):
    vals = [v for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not vals:
        return "—"
    m = statistics.mean(vals)
    if len(vals) == 1:
        return fmt.format(m)
    sd = statistics.stdev(vals)
    return f"{fmt.format(m)} ± {fmt.format(sd)}"


def markdown(rows, group_by):
    def key(r):
        return {"run": r["run"][:15] + (f" {r['task']}" if r["dry"] else ""), "task": r["task"], "label": r["label"] + (" (dry)" if r["dry"] and "dry" not in r["label"] else ""),
                "label+task": f"{r['label']}{' (dry)' if r['dry'] and 'dry' not in r['label'] else ''} / {r['task']}"}[group_by]
    groups = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    names = list(groups)
    out = io.StringIO()
    out.write("| metric | " + " | ".join(f"{n} (n={len(groups[n])})" for n in names) + " |\n")
    out.write("|---|" + "---|" * len(names) + "\n")
    for col, title, fmt, better in TABLE:
        out.write(f"| {title} {better} | " + " | ".join(cell([r[col] for r in groups[n]], fmt) for n in names) + " |\n")
    missing = {n: Counter(m for r in groups[n] for m in r["must_missing"].split("; ") if m) for n in names}
    if any(missing.values()):
        out.write("\nmust_mention not found on screen: " + "; ".join(f"**{n}**: " + ", ".join(f"{m}×{c}" for m, c in v.items())
                                                                  for n, v in missing.items() if v) + "\n")
    return out.getvalue()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", help="results .jsonl files or run dirs")
    ap.add_argument("--runs", type=Path, help="scan every run dir under this folder")
    ap.add_argument("--match", help="regex on run dir names")
    ap.add_argument("--group-by", default="label", choices=["label", "task", "run", "label+task"])
    ap.add_argument("--csv", type=Path, help="per-run CSV (default: next to the first jsonl, or evals/results/report.csv)")
    ap.add_argument("--md", type=Path, help="also write the markdown table to this file")
    ap.add_argument("--no-media", action="store_true", help="skip ffmpeg checks")
    a = ap.parse_args()
    if not a.inputs and not a.runs:
        ap.error("give results .jsonl, run dirs or --runs DIR")
    tasks = load_tasks()
    rows, skipped = [], []
    for d, rec in collect(a.inputs, a.runs, a.match):
        try:
            r = analyse(d, rec, tasks, with_media=not a.no_media)
        except Exception as e:
            skipped.append(f"{d.name}: {type(e).__name__}: {e}")
            continue
        if r is None:
            skipped.append(f"{d.name}: no summary.json with an EDL")
        else:
            rows.append(r)
    if not rows:
        sys.exit("no analysable runs" + ("\n" + "\n".join(skipped) if skipped else ""))
    md = markdown(rows, a.group_by)
    print(md)
    if skipped:
        print("skipped:", *skipped, sep="\n  ")
    first = next((Path(x) for x in a.inputs if x.endswith(".jsonl")), None)
    csv_path = a.csv or (first.with_suffix(".csv") if first else REPO / "evals" / "results" / "report.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    print("csv:", csv_path)
    if a.md:
        a.md.write_text(md)
        print("md:", a.md)


if __name__ == "__main__":
    main()
