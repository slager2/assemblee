#!/usr/bin/env bash
# Local llama-server for assemblee (RTX 3050 6 GB, Vulkan1).  See docs/llm-tuning.md.
#
#   scripts/serve_llm.sh start [agent|planner]   start (default: agent), wait until healthy
#   scripts/serve_llm.sh stop                    stop whatever this script started
#   scripts/serve_llm.sh status                  pid, profile, health, VRAM, RSS
#   scripts/serve_llm.sh restart [profile]
#
# Only one profile runs at a time (both do not fit into 6 GB); `start planner`
# while the agent runs swaps the models (takes a few seconds).
# Env overrides: LLAMA_SERVER, MODELS_DIR, LLM_PORT, LLM_HOST, LLM_DEVICE, LLM_EXTRA_ARGS.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE="$ROOT/.cache"
PIDFILE="$CACHE/llm-server.pid"
PROFILEFILE="$CACHE/llm-server.profile"
LLAMA_SERVER="${LLAMA_SERVER:-/home/slager/Documents/Codex/2026-10-13/v/artifacts/runtime-vulkan/build/bin/llama-server}"
MODELS_DIR="${MODELS_DIR:-/home/slager/Documents/Codex/2026-10-13/v/artifacts/models}"
PORT="${LLM_PORT:-8011}"
HOST="${LLM_HOST:-127.0.0.1}"
DEVICE="${LLM_DEVICE:-Vulkan1}"

profile_args() {
  case "$1" in
    agent)
      # 4B + vision.  q8_0 KV: same speed as f16, half the VRAM/RAM per cached prompt,
      # so 64k fits on the GPU and the agent's KV survives a vision request.
      # 2 slots in one unified KV pool: vision runs next to the agent turn instead of
      # evicting it; --no-cache-idle-slots stops the server from swapping the idle agent
      # slot out to RAM (that cost ~10 s per swap back).
      echo -m "$MODELS_DIR/Qwen3.5-4B-Q4_K_M.gguf" \
           --mmproj "$MODELS_DIR/Qwen3.5-4B-mmproj-F16.gguf" \
           -c 65536 -ctk q8_0 -ctv q8_0 -fa on \
           --parallel 2 --kv-unified --no-cache-idle-slots --cache-ram 1024 \
           -b 2048 -ub 512 -t 6 --poll 0
      ;;
    planner)
      # 9B text-only planner, fully on GPU.
      echo -m "$MODELS_DIR/Qwen3.5-9B-IQ4_XS.gguf" \
           -c 16384 -ctk q8_0 -ctv q8_0 -fa on \
           --parallel 1 --cache-ram 512 -t 6 --poll 0
      ;;
    *) echo "unknown profile: $1 (agent|planner)" >&2; exit 2 ;;
  esac
}

running_pid() {
  [[ -f "$PIDFILE" ]] || return 1
  local pid; pid="$(cat "$PIDFILE")"
  if kill -0 "$pid" 2>/dev/null && grep -q llama-server "/proc/$pid/cmdline" 2>/dev/null; then
    echo "$pid"; return 0
  fi
  rm -f "$PIDFILE" "$PROFILEFILE"; return 1
}

healthy() { curl -sf "http://$HOST:$PORT/health" >/dev/null 2>&1; }

do_stop() {
  local pid
  if pid="$(running_pid)"; then
    kill "$pid"
    for _ in $(seq 1 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    echo "stopped llama-server (pid $pid, profile $(cat "$PROFILEFILE" 2>/dev/null || echo ?))"
    rm -f "$PIDFILE" "$PROFILEFILE"
  else
    echo "not running"
  fi
}

do_start() {
  local profile="${1:-agent}" pid
  if pid="$(running_pid)"; then
    if [[ "$(cat "$PROFILEFILE" 2>/dev/null)" == "$profile" ]] && healthy; then
      echo "already running: profile $profile, pid $pid, http://$HOST:$PORT"; return 0
    fi
    do_stop
  fi
  if healthy; then
    echo "port $PORT is already served by another process; stop it first" >&2; exit 1
  fi
  mkdir -p "$CACHE"
  local log="$CACHE/llm-$profile.log"
  local t0=$SECONDS
  # shellcheck disable=SC2046
  nohup "$LLAMA_SERVER" $(profile_args "$profile") \
      --device "$DEVICE" -ngl 99 --host "$HOST" --port "$PORT" \
      --jinja --reasoning off --no-webui ${LLM_EXTRA_ARGS:-} >"$log" 2>&1 &
  pid=$!
  echo "$pid" >"$PIDFILE"; echo "$profile" >"$PROFILEFILE"
  for _ in $(seq 1 240); do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "llama-server died during startup, last log lines ($log):" >&2
      tail -n 20 "$log" >&2; rm -f "$PIDFILE" "$PROFILEFILE"; exit 1
    fi
    if healthy; then
      echo "ready: profile $profile, pid $pid, http://$HOST:$PORT ($((SECONDS - t0)) s), log $log"
      return 0
    fi
    sleep 0.5
  done
  echo "timeout waiting for health, see $log" >&2; exit 1
}

do_status() {
  local pid
  if pid="$(running_pid)"; then
    local h="down"; healthy && h="ok"
    echo "profile $(cat "$PROFILEFILE" 2>/dev/null) pid $pid health $h port $PORT rss $(( $(ps -o rss= -p "$pid") / 1024 )) MiB"
    command -v nvidia-smi >/dev/null && echo "vram $(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader)"
  else
    echo "not running"; return 3
  fi
}

case "${1:-}" in
  start)   do_start "${2:-agent}" ;;
  stop)    do_stop ;;
  restart) do_stop; do_start "${2:-agent}" ;;
  status)  do_status ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
