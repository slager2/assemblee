#!/usr/bin/env python3
"""Live monitoring server for assemblee runs.

Reads runs/<run_id>/ as described in docs/events.md and serves:

    GET /                               UI (web/static/index.html)
    GET /static/...                     UI assets
    GET /api/runs                       list of runs, newest first
    GET /api/runs/{id}                  task.json + summary.json + status
    GET /api/runs/{id}/events?after=N   events with seq > N (JSON list)
    GET /api/runs/{id}/stream           Server-Sent Events: replay, then tail
    GET /runs/{id}/files/{path}         files of a run (frames, output; Range ok)

Usage: python3 web/server.py --runs runs --port 8765
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from aiohttp import web

STATIC_DIR = Path(__file__).resolve().parent / "static"
RUN_ID_RE = re.compile(r"^\w[\w.-]{0,200}$")  # \w: run ids may contain Cyrillic (slug of the task)
POLL_SECONDS = 0.25
KEEPALIVE_SECONDS = 15.0
RUNS_KEY = web.AppKey("runs_dir", Path)
STOP_KEY = web.AppKey("stopping", asyncio.Event)


# ---------------------------------------------------------------- helpers


def run_dir(request: web.Request) -> Path:
    """Resolve the run directory from the URL, rejecting anything odd."""
    run_id = request.match_info["run_id"]
    if not RUN_ID_RE.match(run_id) or ".." in run_id:
        raise web.HTTPNotFound(text="bad run id")
    root = request.app[RUNS_KEY]
    path = (root / run_id).resolve()
    if path.parent != root or not path.is_dir():
        raise web.HTTPNotFound(text="no such run")
    return path


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def parse_line(line: bytes):
    line = line.strip()
    if not line:
        return None
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    return ev if isinstance(ev, dict) else None


def read_events(path: Path) -> list[dict]:
    """All complete events of a run (a trailing partial line is ignored)."""
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    end = raw.rfind(b"\n")
    if end < 0:
        return []
    out = []
    for line in raw[: end + 1].splitlines():
        ev = parse_line(line)
        if ev is not None:
            out.append(ev)
    return out


def first_and_last_event(path: Path) -> tuple[dict | None, dict | None]:
    """First and last complete events, reading only the file edges."""
    try:
        with path.open("rb") as f:
            first = parse_line(f.readline())
            f.seek(0, os.SEEK_END)
            size = f.tell()
            chunk = 64 * 1024
            last = None
            pos = size
            buf = b""
            while pos > 0 and last is None:
                step = min(chunk, pos)
                pos -= step
                f.seek(pos)
                buf = f.read(step) + buf
                complete = buf[: buf.rfind(b"\n") + 1] if b"\n" in buf else b""
                lines = complete.splitlines()
                # the first line in buf may be cut unless we reached the start
                candidates = lines if pos == 0 else lines[1:]
                for line in reversed(candidates):
                    last = parse_line(line)
                    if last is not None:
                        break
            return first, last
    except OSError:
        return None, None


def status_of(last: dict | None) -> str:
    if last and last.get("type") == "run_end":
        return "done" if (last.get("data") or {}).get("ok") else "failed"
    return "running"


def run_info(path: Path) -> dict:
    events = path / "events.jsonl"
    task = read_json(path / "task.json") or {}
    first, last = first_and_last_event(events)
    try:
        mtime = max(p.stat().st_mtime for p in (path, events) if p.exists())
    except ValueError:
        mtime = path.stat().st_mtime
    started = (first or {}).get("ts") or task.get("created_at")
    return {
        "run_id": path.name,
        "task": task.get("task") or ((first or {}).get("data") or {}).get("task"),
        "model": task.get("model") or ((first or {}).get("data") or {}).get("model"),
        "created_at": task.get("created_at"),
        "started_ts": started,
        "last_ts": (last or {}).get("ts"),
        "last_seq": (last or {}).get("seq"),
        "last_type": (last or {}).get("type"),
        "status": status_of(last),
        "updated_at": mtime,
    }


def sort_key(info: dict) -> float:
    for key in ("started_ts", "created_at"):
        v = info.get(key)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v).timestamp()
            except ValueError:
                pass
    return info.get("updated_at") or 0.0


# ---------------------------------------------------------------- handlers


async def index(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


async def list_runs(request: web.Request) -> web.Response:
    root = request.app[RUNS_KEY]
    runs = []
    if root.is_dir():
        for p in root.iterdir():
            if p.is_dir() and RUN_ID_RE.match(p.name) and (
                (p / "events.jsonl").exists() or (p / "task.json").exists()
            ):
                runs.append(run_info(p))
    runs.sort(key=sort_key, reverse=True)
    return web.json_response(runs)


async def get_run(request: web.Request) -> web.Response:
    path = run_dir(request)
    info = run_info(path)
    info["task_json"] = read_json(path / "task.json")
    info["summary"] = read_json(path / "summary.json")
    return web.json_response(info)


async def get_events(request: web.Request) -> web.Response:
    path = run_dir(request)
    try:
        after = int(request.query.get("after", "-1"))
    except ValueError:
        raise web.HTTPBadRequest(text="after must be an integer")
    events = [e for e in read_events(path / "events.jsonl") if (e.get("seq") or 0) > after]
    return web.json_response(events)


async def stream(request: web.Request) -> web.StreamResponse:
    """SSE: replay every event (or those after Last-Event-ID), then tail."""
    path = run_dir(request) / "events.jsonl"
    after = -1
    for raw in (request.headers.get("Last-Event-ID"), request.query.get("after")):
        if raw:
            try:
                after = int(raw)
                break
            except ValueError:
                pass

    resp = web.StreamResponse(
        headers={
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
    await resp.prepare(request)
    await resp.write(b"retry: 2000\n\n")

    offset = 0
    pending = b""
    last_write = time.monotonic()
    stopping = request.app[STOP_KEY]
    try:
        while not stopping.is_set():
            chunk = b""
            try:
                size = path.stat().st_size
                if size < offset:  # file was truncated/replaced: start over
                    offset, pending = 0, b""
                if size > offset:
                    with path.open("rb") as f:
                        f.seek(offset)
                        chunk = f.read(size - offset)
                    offset += len(chunk)
            except FileNotFoundError:
                pass

            if chunk:
                data = pending + chunk
                cut = data.rfind(b"\n")
                if cut < 0:
                    pending = data
                else:
                    pending = data[cut + 1 :]
                    out = []
                    for line in data[: cut + 1].splitlines():
                        ev = parse_line(line)
                        if ev is None:
                            continue
                        seq = ev.get("seq")
                        if isinstance(seq, int) and seq <= after:
                            continue
                        payload = json.dumps(ev, ensure_ascii=False, separators=(",", ":"))
                        head = f"id: {seq}\n" if isinstance(seq, int) else ""
                        out.append(f"{head}data: {payload}\n\n")
                    if out:
                        await resp.write("".join(out).encode("utf-8"))
                        last_write = time.monotonic()

            if time.monotonic() - last_write > KEEPALIVE_SECONDS:
                await resp.write(b": keepalive\n\n")
                last_write = time.monotonic()
            try:
                await asyncio.wait_for(stopping.wait(), POLL_SECONDS)
            except asyncio.TimeoutError:
                pass
    except ConnectionResetError:
        pass
    return resp


async def run_file(request: web.Request) -> web.StreamResponse:
    base = run_dir(request)
    rel = request.match_info["path"]
    if not rel or "\x00" in rel or rel.startswith("/"):
        raise web.HTTPNotFound()
    target = (base / rel).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise web.HTTPNotFound()
    # no-cache: frames get overwritten (clip03.png re-rendered), revalidate via ETag
    return web.FileResponse(target, headers={"Cache-Control": "no-cache"})


@web.middleware
async def no_cache_static(request: web.Request, handler):
    resp = await handler(request)
    if request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def make_app(runs: Path) -> web.Application:
    app = web.Application(middlewares=[no_cache_static])
    app[RUNS_KEY] = runs.resolve()
    app[STOP_KEY] = asyncio.Event()

    async def on_shutdown(app: web.Application) -> None:
        app[STOP_KEY].set()  # lets open SSE streams finish right away

    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_get("/api/runs", list_runs)
    app.router.add_get("/api/runs/{run_id}", get_run)
    app.router.add_get("/api/runs/{run_id}/events", get_events)
    app.router.add_get("/api/runs/{run_id}/stream", stream)
    app.router.add_get("/runs/{run_id}/files/{path:.+}", run_file)
    app.router.add_static("/static/", STATIC_DIR, follow_symlinks=False)
    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="assemblee live monitor")
    ap.add_argument("--runs", default="runs", help="runs directory (default: runs)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        ap.error("the monitor binds to localhost only")
    runs = Path(args.runs)
    runs.mkdir(parents=True, exist_ok=True)
    print(f"assemblee monitor: http://127.0.0.1:{args.port}/  (runs: {runs.resolve()})")
    web.run_app(make_app(runs), host=args.host, port=args.port, print=None, shutdown_timeout=1.0)


if __name__ == "__main__":
    main()
