# assemblée · live monitor

Web UI for watching an editing run live: agent feed, timeline, checked frames,
exported video. It only reads `runs/<run_id>/` (contract: `docs/events.md`), so
the harness and the monitor can be started and restarted independently.

## Run

```bash
python3 web/server.py --runs runs --port 8765
# open http://127.0.0.1:8765/
```

Needs Python 3.12 + `aiohttp`. No build step, no CDN: the UI is plain
`web/static/{index.html,app.js,style.css}` and works offline. The server binds
to `127.0.0.1` only.

## Demo without the model

```bash
python3 scripts/fake_run.py                  # ~60 s run into runs/fake-<timestamp>/
python3 scripts/fake_run.py --duration 10    # faster
python3 scripts/fake_run.py --fail           # ends with run_end ok=false
```

It appends every event type over time, grows a 15-scene timeline, draws
placeholder frames with Pillow and makes `output/trailer.mp4` with ffmpeg
`testsrc2`. Open the monitor while it runs; the newest run is selected by
default (or pick one in the header; the URL hash `#<run_id>` is a permalink).

## UI

- **Header**: run selector, status (идёт / готово / ошибка / нет активности
  after 3 min of silence), elapsed time, model, tokens/s with a sparkline.
- **Лента агента** (left): model messages, tool calls merged with their results
  (click a row for arguments/result JSON; red = error), phase dividers,
  warnings/errors. "Следить" keeps it pinned to the bottom; scrolling up unpins.
- **Таймлайн** (center): clips to scale (blue = clip, violet = card) with
  thumbnails and effect badges, transitions on the cuts, captions track, music
  by mood, SFX markers. Zoom: Вписать / 2× / 4×. Changed scenes flash on each
  `timeline` event. Once the video is exported a red playhead follows it; click
  the timeline or a scene to seek. **Сцены** below lists every scene.
- **Экспорт / Кадры** (right): the exported mp4 (seekable, HTTP Range) and the
  latest frames with the readability verdict (✓/✗) and what the model saw;
  click a frame to enlarge.
- **Bottom bar**: turns, tool calls, errors (failed tool results + `error`
  events), completion tokens, average tokens/s, phase progress.

## HTTP API

| Endpoint | |
|---|---|
| `GET /api/runs` | runs, newest first: `run_id, task, model, status, started_ts, last_ts, last_seq, ...` |
| `GET /api/runs/{id}` | the same + `task_json`, `summary` (null until written) |
| `GET /api/runs/{id}/events?after=SEQ` | JSON list of events with `seq > SEQ` |
| `GET /api/runs/{id}/stream` | SSE: replays all events (`id:` = seq; honours `Last-Event-ID` / `?after=`), then tails the file; `: keepalive` every 15 s |
| `GET /runs/{id}/files/<path>` | files inside the run dir (frames, output video with Range) |

`status` is `done`/`failed` from the last `run_end` event, otherwise `running`.
