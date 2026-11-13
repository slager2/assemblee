# Run events protocol

Every editing run lives in `runs/<run_id>/`:

| File | What |
|---|---|
| `events.jsonl` | append-only event log, one JSON object per line (the contract below) |
| `task.json` | the task: `{"run_id", "task", "assets_dir", "gdds", "model", "created_at"}` |
| `frames/` | PNG frames the agent rendered or checked (`clip03.png`, `t012.40.png`) |
| `output/` | exported video(s) |
| `summary.json` | written at the end |

The harness only appends to `events.jsonl`; the web server tails it and streams
new lines to the browser (SSE). Nothing else is shared between the harness and
the UI, so either can be restarted independently.

## Event shape

```json
{"seq": 17, "ts": 1794560000.123, "type": "tool_result", "data": {...}}
```

`seq` increases by 1 per event inside a run; `ts` is Unix seconds (float).

## Types

| type | data |
|---|---|
| `run_start` | `{"task": str, "model": str, "tools": [names]}` |
| `phase` | `{"name": "explore" \| "plan" \| "build" \| "polish" \| "director" \| "review" \| "export", "note": str}` (model swaps are announced as notes of the next phase) |
| `llm_request` | `{"turn": int, "messages": int, "prompt_tokens_est": int}` |
| `llm_response` | `{"turn": int, "content": str, "tool_calls": [{"name", "arguments"}], "usage": {"prompt_tokens", "completion_tokens"}, "seconds": float, "tokens_per_second": float, "reasoning_tokens": int}` (with thinking, `content` starts with `[мысли] <thoughts, truncated>`, then the answer) |
| `tool_call` | `{"id": str, "name": str, "args": {}}` |
| `tool_result` | `{"id": str, "name": str, "ok": bool, "result": {}, "seconds": float}` |
| `timeline` | `{"total_seconds": float, "clips": [{"n", "kind": "clip"\|"card", "label", "start", "end", "look", "motion", "effects": [], "caption": str\|null, "thumb": "frames/…png"\|null}], "transitions": [[after_n, kind, seconds]], "music": [{"mood", "from", "to", "db"}], "sfx": [{"kind", "clip", "at"}]}` |
| `frame` | `{"path": "frames/clip03.png", "clip": int\|null, "seconds": float, "verdict": {"text_readable": bool, "seen": str}\|null}` |
| `llm_stats` | `{"tokens_per_second": float, "kv_used": float, "slots_busy": int, "vram_mb": int\|null}` |
| `warning` | `{"message": str}` |
| `error` | `{"message": str, "where": str}` |
| `export` | `{"path": "output/x.mp4", "seconds": float, "size_bytes": int}` |
| `run_end` | `{"ok": bool, "reason": str, "summary": {}}` |

Paths inside events are relative to the run directory.
