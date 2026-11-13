/* assemblée live monitor — vanilla JS, no build step. Contract: docs/events.md */
"use strict";

const $ = (sel) => document.querySelector(sel);
const PHASES = ["explore", "plan", "build", "polish", "director", "review", "export"];
const PHASE_RU = { explore: "Разведка", plan: "План", build: "Сборка", polish: "Полировка", director: "Режиссёр", review: "Проверка", export: "Экспорт" };
const STATUS_RU = { running: "идёт", done: "готово", failed: "ошибка", stale: "нет активности", "": "—" };
const MOOD_COLORS = {
  calm: "#3d8f8a", спокойно: "#3d8f8a", спокойная: "#3d8f8a",
  dark: "#4b4f9e", мрачно: "#4b4f9e", мрачная: "#4b4f9e",
  tense: "#b0603a", напряжённо: "#b0603a", напряженно: "#b0603a", напряжённая: "#b0603a",
  epic: "#b23a5a", кульминация: "#b23a5a", эпично: "#b23a5a", эпичная: "#b23a5a",
  upbeat: "#4f9a43", весело: "#4f9a43", бодро: "#4f9a43", energetic: "#4f9a43",
  sad: "#4a6c9b", грустно: "#4a6c9b", mysterious: "#6c4a9b", загадочно: "#6c4a9b",
  happy: "#a8962f", радостно: "#a8962f",
};
const STALE_SECONDS = 180;

/* ------------------------------------------------------------------ utils */

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : String(kid));
  }
  return el;
}

function moodColor(mood) {
  const key = String(mood || "").toLowerCase();
  if (MOOD_COLORS[key]) return MOOD_COLORS[key];
  let hash = 0;
  for (const ch of key) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
  return `hsl(${hash % 360} 42% 42%)`;
}

const fmtSec = (s) => (s == null || isNaN(s) ? "—" : Number(s).toFixed(1) + " с");
function fmtDur(sec) {
  if (sec == null || !isFinite(sec) || sec < 0) return "—";
  sec = Math.floor(sec);
  const hh = Math.floor(sec / 3600), mm = Math.floor((sec % 3600) / 60), ss = sec % 60;
  const p = (n) => String(n).padStart(2, "0");
  return hh ? `${hh}:${p(mm)}:${p(ss)}` : `${p(mm)}:${p(ss)}`;
}
function fmtTC(sec) {
  const t = Math.round((Number(sec) || 0) * 10) / 10;
  const m = Math.floor(t / 60), s = Math.round((t - m * 60) * 10) / 10;
  return `${m}:${s < 10 ? "0" : ""}${s.toFixed(s % 1 ? 1 : 0)}`;
}
const fmtInt = (n) => Number(n || 0).toLocaleString("ru-RU");
function fmtBytes(n) {
  if (!n) return "0 Б";
  const u = ["Б", "КБ", "МБ", "ГБ"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}
function clock(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("ru-RU", { hour12: false });
}
function fileUrl(runId, rel) {
  if (!rel) return null;
  const clean = String(rel).replace(/^\.?\//, "");
  return `/runs/${encodeURIComponent(runId)}/files/${clean.split("/").map(encodeURIComponent).join("/")}`;
}

/** One-line preview of args/results: key=value, key=value */
function preview(obj, max = 140) {
  if (obj == null) return "";
  if (typeof obj !== "object") return String(obj);
  const parts = [];
  for (const [k, v] of Object.entries(obj)) {
    let s;
    if (v == null) s = "null";
    else if (typeof v === "string") s = JSON.stringify(v.length > 40 ? v.slice(0, 40) + "…" : v);
    else if (Array.isArray(v)) s = `[${v.length}]`;
    else if (typeof v === "object") s = "{…}";
    else s = String(v);
    parts.push(`${k}=${s}`);
    if (parts.join(" ").length > max) break;
  }
  return parts.join("  ");
}

/** Syntax-coloured pretty JSON, built from text nodes (no innerHTML). */
function jsonPre(value) {
  const pre = h("pre", { class: "json" });
  let text;
  try { text = JSON.stringify(value, null, 2); } catch { text = String(value); }
  if (text === undefined) text = "undefined";
  const re = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) pre.append(text.slice(last, m.index));
    if (m[1]) {
      pre.append(h("span", { class: m[2] ? "k" : "s" }, m[1]));
      if (m[2]) pre.append(m[2]);
    } else if (m[3]) pre.append(h("span", { class: "b" }, m[3]));
    else pre.append(h("span", { class: "n" }, m[4]));
    last = re.lastIndex;
  }
  pre.append(text.slice(last));
  return pre;
}

/* ------------------------------------------------------------------ state */

let S = null;           // per-run state
let es = null;          // EventSource
let runs = [];
let pinned = true;
let zoom = 1;
let selectedClip = null;
let rafPending = false;

function freshState(runId) {
  return {
    runId, lastSeq: 0, firstTs: null, lastTs: null, ended: null, model: null, task: null,
    phase: null, phasesSeen: new Set(),
    turns: 0, calls: 0, errors: 0, completion: 0, llmSeconds: 0,
    tps: null, tpsHist: [],
    tools: new Map(),      // call id -> {el, call}
    pendingReq: null,
    timeline: null, timelineSeq: 0, prevClips: new Map(),
    frames: 0, exp: null,
    dirty: { timeline: false, header: true, counters: true },
  };
}

/* ------------------------------------------------------------------ feed */

const feed = $("#feed");

function feedAppend(el) {
  feed.append(el);
  $("#feedCount").textContent = `${feed.childElementCount} событий`;
  if (!pinned) $("#newBelow").hidden = false;
}

function metaRow(ev, ...extra) {
  return h("div", { class: "meta" }, h("span", { class: "t" }, clock(ev.ts)), ...extra);
}

function onRunStart(ev) {
  const d = ev.data || {};
  S.model = d.model || S.model;
  S.task = d.task || S.task;
  feedAppend(h("div", { class: "ev ev-banner" },
    h("b", null, "Запуск начат"),
    metaRow(ev, d.model ? h("span", { class: "mono" }, d.model) : null),
    (d.tools && d.tools.length) ? h("div", { class: "tools" }, d.tools.map((t) => h("code", null, t))) : null));
}

function onPhase(ev) {
  const d = ev.data || {};
  S.phase = d.name;
  S.phasesSeen.add(d.name);
  feedAppend(h("div", { class: "ev ev-phase", title: clock(ev.ts) },
    h("span", { class: "pill" }, PHASE_RU[d.name] || d.name),
    d.note ? h("span", { class: "note" }, d.note) : null));
}

function onLlmRequest(ev) {
  const d = ev.data || {};
  if (S.pendingReq) S.pendingReq.classList.add("answered");
  const el = h("div", { class: "ev ev-req" },
    h("span", { class: "dots" }, h("i"), h("i"), h("i")),
    h("span", null, `Ход ${d.turn ?? "?"} · запрос к модели · ${d.messages ?? "?"} сообщ. · ~${fmtInt(d.prompt_tokens_est)} ток.`));
  S.pendingReq = el;
  feedAppend(el);
}

function onLlmResponse(ev) {
  const d = ev.data || {};
  if (S.pendingReq) { S.pendingReq.classList.add("answered"); S.pendingReq = null; }
  S.turns += 1;
  const ct = (d.usage && d.usage.completion_tokens) || 0;
  S.completion += ct;
  S.llmSeconds += Number(d.seconds) || 0;
  if (d.tokens_per_second) pushTps(d.tokens_per_second);
  const calls = (d.tool_calls || []).length;
  const content = (d.content || "").trim();
  feedAppend(h("div", { class: "ev ev-msg" },
    h("div", { class: "meta" },
      h("span", { class: "who" }, `Модель · ход ${d.turn ?? S.turns}`),
      h("span", { class: "spacer" }),
      h("span", { class: "t" }, `${fmtInt(ct)} ток · ${fmtSec(d.seconds)} · ${d.tokens_per_second ? Number(d.tokens_per_second).toFixed(1) : "—"} ток/с`)),
    h("div", { class: "body" + (content ? "" : " empty-body") },
      content || (calls ? `(без текста, ${calls} вызов${calls === 1 ? "" : calls < 5 ? "а" : "ов"})` : "(пустой ответ)"))));
}

function onToolCall(ev) {
  const d = ev.data || {};
  S.calls += 1;
  const st = h("span", { class: "st" }, "выполняется…");
  const dur = h("span", { class: "dur" });
  const body = h("div", { class: "tbody" }, h("div", { class: "sec" }, "Аргументы"), jsonPre(d.args || {}));
  const el = h("div", { class: "ev ev-tool pending" },
    h("details", null,
      h("summary", { class: "row" },
        h("span", { class: "name" }, d.name || "?"),
        h("span", { class: "preview", title: preview(d.args, 1000) }, preview(d.args)),
        st, dur),
      body));
  S.tools.set(d.id, { el, st, dur, body });
  feedAppend(el);
}

function onToolResult(ev) {
  const d = ev.data || {};
  let t = S.tools.get(d.id);
  if (!t) { // result without a call (e.g. replay started mid-way)
    onToolCall({ ts: ev.ts, data: { id: d.id, name: d.name, args: {} } });
    t = S.tools.get(d.id);
  }
  const ok = !!d.ok;
  if (!ok) S.errors += 1;
  t.el.classList.remove("pending");
  t.el.classList.add(ok ? "ok" : "err");
  t.st.textContent = ok ? "✓ ок" : "✗ ошибка";
  t.dur.textContent = d.seconds != null ? fmtSec(d.seconds) : "";
  const r = d.result;
  if (!ok) {
    const msg = r && typeof r === "object" ? (r.error || r.message) : r;
    const text = msg != null ? String(msg) : (r && typeof r === "object" ? preview(r, 200) : "") || "ошибка без сообщения";
    t.el.append(h("div", { class: "err-line" }, text));
  }
  t.body.append(h("div", { class: "sec" }, "Результат"), jsonPre(r ?? null));
}

function onNote(ev, kind) {
  const d = ev.data || {};
  if (kind === "error") S.errors += 1;
  feedAppend(h("div", { class: `ev ev-note ev-${kind}` },
    h("span", { class: "tag" }, kind === "error" ? "Ошибка" : "Внимание"),
    h("span", null, d.message || ""),
    d.where ? h("span", { class: "mono small", style: { opacity: .7 } }, d.where) : null));
}

function onRunEnd(ev) {
  const d = ev.data || {};
  S.ended = { ok: !!d.ok, ts: ev.ts, reason: d.reason };
  const s = d.summary || {};
  const bits = [];
  if (s.clips != null) bits.push(`${s.clips} сцен`);
  if (s.video_seconds != null) bits.push(`${fmtSec(s.video_seconds)} видео`);
  if (s.tool_calls != null) bits.push(`${s.tool_calls} вызовов`);
  feedAppend(h("div", { class: `ev ev-banner ${d.ok ? "ok" : "fail"}` },
    h("b", null, d.ok ? "Запуск завершён успешно" : "Запуск завершён с ошибкой"),
    metaRow(ev, d.reason ? h("span", { class: "mono" }, d.reason) : null, bits.length ? h("span", null, bits.join(" · ")) : null)));
}

function pushTps(v) {
  S.tps = Number(v);
  S.tpsHist.push(S.tps);
  if (S.tpsHist.length > 40) S.tpsHist.shift();
}

/* ------------------------------------------------------------------ dispatch */

function handle(ev) {
  if (!S || typeof ev !== "object" || ev == null) return;
  if (typeof ev.seq === "number") {
    if (ev.seq <= S.lastSeq) return;
    S.lastSeq = ev.seq;
  }
  if (typeof ev.ts === "number") {
    if (S.firstTs == null) S.firstTs = ev.ts;
    S.lastTs = ev.ts;
  }
  const d = ev.data || {};
  switch (ev.type) {
    case "run_start": onRunStart(ev); break;
    case "phase": onPhase(ev); break;
    case "llm_request": onLlmRequest(ev); break;
    case "llm_response": onLlmResponse(ev); break;
    case "tool_call": onToolCall(ev); break;
    case "tool_result": onToolResult(ev); break;
    case "timeline":
      S.timeline = d; S.timelineSeq += 1; S.dirty.timeline = true;
      feedAppend(h("div", { class: "ev ev-sys" }, h("span", { class: "ico" }, "▤"),
        `Таймлайн v${S.timelineSeq}: ${(d.clips || []).length} сцен, ${fmtSec(d.total_seconds)}`));
      break;
    case "frame": addFrame(ev); break;
    case "llm_stats": if (d.tokens_per_second != null) pushTps(d.tokens_per_second); break;
    case "warning": onNote(ev, "warn"); break;
    case "error": onNote(ev, "error"); break;
    case "export": showExport(ev); break;
    case "run_end": onRunEnd(ev); break;
    default:
      feedAppend(h("div", { class: "ev ev-sys" }, h("span", { class: "ico" }, "·"), `${ev.type}`));
  }
  S.dirty.header = S.dirty.counters = true;
  schedule();
}

function schedule() {
  if (rafPending) return;
  rafPending = true;
  requestAnimationFrame(() => {
    rafPending = false;
    if (!S) return;
    if (S.dirty.timeline) { S.dirty.timeline = false; renderTimeline(); }
    if (S.dirty.header) { S.dirty.header = false; renderHeader(); }
    if (S.dirty.counters) { S.dirty.counters = false; renderCounters(); }
    if (pinned) feed.scrollTop = feed.scrollHeight;
  });
}

/* ------------------------------------------------------------------ header / footer */

function runStatus() {
  if (!S) return "";
  if (S.ended) return S.ended.ok ? "done" : "failed";
  if (S.lastTs && Date.now() / 1000 - S.lastTs > STALE_SECONDS) return "stale";
  return S.lastSeq ? "running" : "";
}

function renderHeader() {
  const st = runStatus();
  const badge = $("#status");
  badge.className = "badge " + st;
  badge.textContent = STATUS_RU[st] ?? st;
  $("#model").textContent = S.model || "—";
  $("#model").title = S.model || "";
  $("#task").textContent = S.task || "";
  $("#task").title = S.task || "";
  tickElapsed();
  $("#tps").textContent = S.tps != null ? S.tps.toFixed(1) : "—";
  const svg = $("#spark");
  svg.replaceChildren();
  const hist = S.tpsHist;
  if (hist.length > 1) {
    const max = Math.max(...hist) * 1.1 || 1, min = Math.min(0, ...hist);
    const pts = hist.map((v, i) => `${(i / (hist.length - 1)) * 72},${22 - ((v - min) / (max - min)) * 20}`);
    const ns = "http://www.w3.org/2000/svg";
    const poly = document.createElementNS(ns, "polygon");
    poly.setAttribute("points", `0,22 ${pts.join(" ")} 72,22`);
    const line = document.createElementNS(ns, "polyline");
    line.setAttribute("points", pts.join(" "));
    svg.append(poly, line);
  }
}

function tickElapsed() {
  if (!S || S.firstTs == null) { $("#elapsed").textContent = "—"; return; }
  const end = S.ended ? S.ended.ts : (runStatus() === "stale" ? S.lastTs : Date.now() / 1000);
  $("#elapsed").textContent = fmtDur(end - S.firstTs);
}

function renderCounters() {
  $("#cTurns").textContent = fmtInt(S.turns);
  $("#cCalls").textContent = fmtInt(S.calls);
  $("#cErrors").textContent = fmtInt(S.errors);
  $("#cErrBox").classList.toggle("has-err", S.errors > 0);
  $("#cTokens").textContent = fmtInt(S.completion);
  $("#cAvg").textContent = S.llmSeconds > 0 ? (S.completion / S.llmSeconds).toFixed(1) : "—";
  const box = $("#phases");
  box.replaceChildren();
  const curIdx = PHASES.indexOf(S.phase);
  const names = PHASES.concat(S.phase && curIdx < 0 ? [S.phase] : []);
  names.forEach((p, i) => {
    const idx = curIdx < 0 ? names.indexOf(S.phase) : curIdx;
    let cls = "ph";
    if (S.phase === p) cls += " cur" + (S.ended ? " ended" : "");
    else if (S.phasesSeen.has(p) || (idx >= 0 && i < idx)) cls += " past";
    box.append(h("span", { class: cls }, h("i"), PHASE_RU[p] || p));
  });
}

/* ------------------------------------------------------------------ timeline */

const tlBox = $("#timeline");
let tlRefs = null; // {inner, playhead, pps, scroll}
const tip = h("div", { class: "tl-tip", hidden: true });
document.body.append(tip);

function clipsSignature(c) {
  return JSON.stringify([c.kind, c.label, c.start, c.end, c.look, c.motion, c.effects, c.caption, c.thumb]);
}

function renderTimeline() {
  const tl = S.timeline;
  if (!tl || !(tl.clips || []).length) {
    tlBox.replaceChildren(h("div", { class: "empty" }, "Таймлайн пока пуст"));
    tlRefs = null;
    renderScenes();
    return;
  }
  const clips = tl.clips || [];
  const total = Math.max(Number(tl.total_seconds) || 0, ...clips.map((c) => Number(c.end) || 0),
    ...(tl.music || []).map((m) => Number(m.to) || 0), 1);
  const prevScroll = tlRefs ? tlRefs.scroll.scrollLeft : 0;

  const heads = h("div", { class: "tl-heads" },
    h("div", { class: "h-ruler" }, ""), h("div", { class: "h-video" }, "Видео"),
    h("div", { class: "h-caps" }, "Титры"), h("div", { class: "h-music" }, "Музыка"), h("div", { class: "h-sfx" }, "SFX"));
  const scroll = h("div", { class: "tl-scroll" });
  tlBox.replaceChildren(heads, scroll);

  const avail = Math.max(200, scroll.clientWidth - 40);
  const pps = (avail / total) * zoom;
  const width = Math.ceil(total * pps) + 40;
  const X = (t) => 8 + t * pps;

  // ruler step: aim for ~90px between labels
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];
  const major = steps.find((s) => s * pps >= 80) || 600;
  const minor = major / 5;
  const inner = h("div", { class: "tl-inner", style: { width: width + "px", "--major": major * pps + "px" } });
  inner.style.setProperty("--major", major * pps + "px");

  const ruler = h("div", { class: "tl-row ruler h-ruler" });
  for (let t = 0; t <= total + 1e-6; t += minor) {
    const isMajor = Math.abs(t / major - Math.round(t / major)) < 1e-6;
    ruler.append(h("div", { class: "tick" + (isMajor ? "" : " minor"), style: { left: X(t) + "px" } },
      isMajor ? h("span", null, fmtTC(Math.round(t * 10) / 10)) : null));
  }

  const video = h("div", { class: "tl-row video h-video" });
  const caps = h("div", { class: "tl-row caps h-caps" });
  for (const c of clips) {
    const s = Number(c.start) || 0, e = Number(c.end) || s;
    const w = Math.max(2, (e - s) * pps - 2);
    const sig = clipsSignature(c);
    const fresh = S.prevClips.size > 0 && S.prevClips.get(c.n) !== sig;
    const thumb = c.thumb ? fileUrl(S.runId, c.thumb) + `?v=${encodeURIComponent(sig.length + ":" + S.timelineSeq)}` : null;
    const el = h("div", {
      class: `tlc ${c.kind === "card" ? "card" : "pic"}${w < 46 ? " narrow" : ""}${fresh ? " fresh" : ""}${selectedClip === c.n ? " sel" : ""}`,
      style: { left: X(s) + 1 + "px", width: w + "px", backgroundImage: thumb ? `url("${thumb}")` : "none" },
      "data-n": c.n,
    },
    h("div", { class: "shade" }), h("div", { class: "bar" }),
    h("div", { class: "lbl" }, h("span", { class: "num" }, c.n), c.label || ""),
    (c.effects && c.effects.length) ? h("div", { class: "fx" }, c.effects.map((f) => h("i", null, f))) : null);
    el.addEventListener("mouseenter", () => showTip(el, c));
    el.addEventListener("mouseleave", hideTip);
    el.addEventListener("click", (e) => { e.stopPropagation(); selectClip(c.n, true); seekTo(s + 0.01); });
    video.append(el);
    if (c.caption) {
      caps.append(h("div", { class: "cap", style: { left: X(s) + 1 + "px", width: w + "px" }, title: c.caption }, c.caption));
    }
  }
  const byN = new Map(clips.map((c) => [c.n, c]));
  for (const tr of tl.transitions || []) {
    const [after, kind, secs] = tr;
    const c = byN.get(after);
    if (!c) continue;
    const isCut = !kind || kind === "cut";
    video.append(h("div", {
      class: "trans" + (isCut ? " cut" : ""),
      style: { left: X(Number(c.end) || 0) + "px" },
      title: `${kind || "cut"}${secs ? ` · ${secs} с` : ""} (после ${after})`,
    }, isCut ? null : shortTrans(kind)));
  }

  const music = h("div", { class: "tl-row music h-music" });
  for (const m of tl.music || []) {
    const a = Number(m.from) || 0, b = Number(m.to) || a;
    music.append(h("div", {
      class: "mus",
      style: { left: X(a) + 1 + "px", width: Math.max(2, (b - a) * pps - 2) + "px", background: moodColor(m.mood) },
      title: `${m.mood} · ${a}–${b} с · ${m.db} дБ`,
    }, m.mood || "музыка", m.db != null ? h("small", null, `${m.db} дБ`) : null));
  }

  const sfx = h("div", { class: "tl-row sfx h-sfx" });
  for (const x of tl.sfx || []) {
    let at = Number(x.at);
    if (!isFinite(at)) { const c = byN.get(x.clip); at = c ? Number(c.start) : 0; }
    sfx.append(h("div", { class: "sfxm", style: { left: X(at) + "px" }, title: `${x.kind} · ${at} с · сцена ${x.clip}` },
      h("span", null, x.kind)));
  }

  const playhead = h("div", { class: "playhead", hidden: true });
  inner.append(ruler, video, caps, music, sfx, playhead);
  inner.addEventListener("click", (e) => {
    const r = inner.getBoundingClientRect();
    seekTo(Math.max(0, (e.clientX - r.left - 8) / pps));
  });
  scroll.append(inner);
  scroll.scrollLeft = prevScroll;
  tlRefs = { inner, playhead, pps, scroll, X, total };

  S.prevClips = new Map(clips.map((c) => [c.n, clipsSignature(c)]));
  const nCards = clips.filter((c) => c.kind === "card").length;
  $("#tlInfo").textContent = `${clips.length} сцен (${clips.length - nCards} клипов, ${nCards} карточек) · ${fmtSec(total)} · v${S.timelineSeq}`;
  updatePlayhead();
  renderScenes();
}

function shortTrans(kind) {
  const map = { crossfade: "X", dissolve: "X", dip_black: "▼", fade: "▼", whip: "»", glitch: "≋", wipe: "▸", slide: "▸", zoom: "◎" };
  return map[kind] || String(kind).slice(0, 3);
}

function showTip(el, c) {
  tip.replaceChildren(
    h("b", null, `${c.n}. ${c.label || ""}`),
    h("div", { class: "kv" }, `${c.kind === "card" ? "карточка" : "клип"} · ${fmtTC(Number(c.start) || 0)}–${fmtTC(Number(c.end) || 0)} · ${fmtSec((c.end || 0) - (c.start || 0))}`),
    h("div", { class: "kv" }, [c.look, c.motion].filter(Boolean).join(" · ")),
    (c.effects && c.effects.length) ? h("div", { class: "kv" }, "эффекты: " + c.effects.join(", ")) : null,
    c.caption ? h("div", { style: { marginTop: "4px" } }, `«${c.caption}»`) : null);
  tip.hidden = false;
  const r = el.getBoundingClientRect();
  const tw = tip.offsetWidth;
  tip.style.left = Math.min(window.innerWidth - tw - 8, Math.max(8, r.left + r.width / 2 - tw / 2)) + "px";
  tip.style.top = r.bottom + 6 + "px";
}
function hideTip() { tip.hidden = true; }

function renderScenes() {
  const tb = $("#scenes tbody");
  tb.replaceChildren();
  const clips = (S.timeline && S.timeline.clips) || [];
  $("#scenesInfo").textContent = clips.length ? `${clips.length}` : "";
  if (!clips.length) {
    tb.append(h("tr", null, h("td", { colspan: 7, class: "empty" }, "Сцен пока нет")));
    return;
  }
  for (const c of clips) {
    const tr = h("tr", { "data-n": c.n, class: selectedClip === c.n ? "sel" : null, onclick: () => { selectClip(c.n, false); seekTo((Number(c.start) || 0) + 0.01); } },
      h("td", { class: "num" }, c.n),
      h("td", { class: `thumbcell ${c.kind === "card" ? "card" : "pic"}`, title: c.kind === "card" ? "карточка" : "клип" }, c.thumb ? h("img", { src: fileUrl(S.runId, c.thumb) + `?v=${S.timelineSeq}`, alt: "", loading: "lazy" }) : null),
      h("td", { class: "ell", title: c.label || "" }, c.label || ""),
      h("td", { class: "mono ell" }, `${fmtTC(Number(c.start) || 0)}–${fmtTC(Number(c.end) || 0)}`,
        h("span", { class: "muted" }, ` · ${((c.end || 0) - (c.start || 0)).toFixed(1)}с`)),
      h("td", { class: "mono ell", title: [c.look, c.motion].filter(Boolean).join(" · ") },
        c.look || "—", h("span", { class: "muted" }, " · "), c.motion || "—"),
      h("td", { class: "ell" }, (c.effects && c.effects.length) ? h("div", { class: "chips" }, c.effects.map((f) => h("i", null, f))) : h("span", { class: "muted" }, "—")),
      h("td", { class: "ell cap-cell", title: c.caption || "" }, c.caption ? `«${c.caption}»` : h("span", { class: "muted" }, "—")));
    tb.append(tr);
  }
  updatePlayhead();
}

function selectClip(n, scrollRow) {
  selectedClip = selectedClip === n ? null : n;
  document.querySelectorAll(".tlc.sel, .scenes tr.sel").forEach((e) => e.classList.remove("sel"));
  if (selectedClip == null) return;
  document.querySelectorAll(`.tlc[data-n="${CSS.escape(String(n))}"], .scenes tr[data-n="${CSS.escape(String(n))}"]`)
    .forEach((e) => e.classList.add("sel"));
  if (scrollRow) {
    const row = document.querySelector(`.scenes tr[data-n="${CSS.escape(String(n))}"]`);
    if (row) row.scrollIntoView({ block: "nearest" });
  }
}

/* ------------------------------------------------------------------ player / playhead */

function currentVideo() { return $("#player video"); }

function seekTo(t) {
  const v = currentVideo();
  if (!v) return;
  try { v.currentTime = Math.min(t, (v.duration || t)); } catch { /* not ready */ }
}

function updatePlayhead() {
  const v = currentVideo();
  if (!tlRefs) return;
  if (!v || !isFinite(v.currentTime)) { tlRefs.playhead.hidden = true; return; }
  const t = v.currentTime;
  tlRefs.playhead.hidden = false;
  tlRefs.playhead.style.left = tlRefs.X(t) + "px";
  const clips = (S.timeline && S.timeline.clips) || [];
  const cur = clips.find((c) => t >= c.start && t < c.end);
  document.querySelectorAll(".scenes tr.playing").forEach((e) => e.classList.remove("playing"));
  if (cur) {
    const row = document.querySelector(`.scenes tr[data-n="${CSS.escape(String(cur.n))}"]`);
    if (row) row.classList.add("playing");
  }
  if (!v.paused) { // keep the playhead in view while playing
    const sc = tlRefs.scroll, x = tlRefs.X(t);
    if (x < sc.scrollLeft || x > sc.scrollLeft + sc.clientWidth - 20) sc.scrollLeft = x - 40;
  }
}

function showExport(ev) {
  const d = ev.data || {};
  S.exp = d;
  const url = fileUrl(S.runId, d.path) + `?v=${ev.seq}`;
  const video = h("video", { controls: true, preload: "metadata", src: url });
  ["timeupdate", "seeked", "loadedmetadata", "play", "pause"].forEach((e) => video.addEventListener(e, updatePlayhead));
  const name = String(d.path || "").split("/").pop();
  $("#player").replaceChildren(video,
    h("div", { class: "export-meta" },
      h("a", { href: url, target: "_blank", rel: "noopener" }, name),
      h("span", null, fmtSec(d.seconds)), h("span", null, fmtBytes(d.size_bytes))));
  $("#exportInfo").textContent = clock(ev.ts);
  feedAppend(h("div", { class: "ev ev-sys" }, h("span", { class: "ico" }, "▶"), `Экспорт: ${d.path} · ${fmtSec(d.seconds)} · ${fmtBytes(d.size_bytes)}`));
}

/* ------------------------------------------------------------------ frames */

function addFrame(ev) {
  const d = ev.data || {};
  const grid = $("#frames");
  if (!S.frames) grid.replaceChildren();
  S.frames += 1;
  const url = fileUrl(S.runId, d.path) + `?v=${ev.seq}`;
  const v = d.verdict;
  const cls = v == null ? "none" : v.text_readable ? "good" : "bad";
  const where = [d.clip != null ? `сцена ${d.clip}` : null, d.seconds != null ? `${Number(d.seconds).toFixed(1)} с` : null].filter(Boolean).join(" · ");
  const card = h("div", { class: `frame ${cls}${Date.now() / 1000 - ev.ts < 5 ? " fresh" : ""}` },
    h("div", {
      class: "img", style: { backgroundImage: `url("${url}")` }, title: d.path,
      onclick: () => openLightbox(url, [where, v && v.seen].filter(Boolean).join(" — ")),
    }, where ? h("span", { class: "where" }, where) : null),
    h("div", { class: "verdict" },
      v == null ? "без проверки" : [h("span", { class: "mk" }, v.text_readable ? "✓" : "✗"), v.text_readable ? "Текст читается" : "Текст не читается"]),
    v && v.seen ? h("div", { class: "seen" }, v.seen) : null);
  grid.prepend(card);
  const bad = grid.querySelectorAll(".frame.bad").length;
  $("#framesInfo").textContent = `${S.frames}${bad ? ` · ${bad} ✗` : ""}`;
}

function openLightbox(url, caption) {
  const lb = $("#lightbox");
  lb.querySelector("img").src = url;
  lb.querySelector(".lb-cap").textContent = caption || "";
  lb.hidden = false;
}
$("#lightbox").addEventListener("click", () => { $("#lightbox").hidden = true; });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#lightbox").hidden = true; });

/* ------------------------------------------------------------------ run selection */

function resetPanels() {
  feed.replaceChildren();
  $("#feedCount").textContent = "";
  $("#newBelow").hidden = true;
  tlBox.replaceChildren(h("div", { class: "empty" }, "Таймлайн появится после первого события ", h("code", null, "timeline")));
  tlRefs = null;
  $("#tlInfo").textContent = "";
  $("#scenes tbody").replaceChildren();
  $("#scenesInfo").textContent = "";
  $("#player").replaceChildren(h("div", { class: "empty" }, "Видео ещё не экспортировано"));
  $("#exportInfo").textContent = "";
  $("#frames").replaceChildren(h("div", { class: "empty" }, "Кадров пока нет"));
  $("#framesInfo").textContent = "";
  selectedClip = null;
}

async function openRun(runId) {
  if (es) { es.close(); es = null; }
  resetPanels();
  S = freshState(runId);
  if (!runId) { renderHeader(); renderCounters(); return; }
  if (location.hash.slice(1) !== encodeURIComponent(runId)) history.replaceState(null, "", "#" + encodeURIComponent(runId));
  $("#runSel").value = runId;
  try {
    const info = await (await fetch(`/api/runs/${encodeURIComponent(runId)}`)).json();
    if (S.runId !== runId) return;
    const t = info.task_json || {};
    S.task = S.task || t.task || info.task;
    S.model = S.model || t.model || info.model;
    S.dirty.header = true; schedule();
  } catch { /* the stream still works */ }
  connect(runId);
}

function connect(runId) {
  const src = new EventSource(`/api/runs/${encodeURIComponent(runId)}/stream`);
  es = src;
  src.onmessage = (m) => {
    if (es !== src) return;
    let ev;
    try { ev = JSON.parse(m.data); } catch { return; }
    handle(ev);
  };
}

function runLabel(r) {
  const st = { running: "●", done: "✓", failed: "✗" }[r.status] || "·";
  return `${st} ${r.run_id}`;
}

async function refreshRuns(first) {
  try {
    runs = await (await fetch("/api/runs")).json();
  } catch { return; }
  const sel = $("#runSel");
  const cur = S ? S.runId : null;
  sel.replaceChildren(...(runs.length ? runs.map((r) => h("option", { value: r.run_id, title: r.task || "" }, runLabel(r)))
    : [h("option", { value: "" }, "нет запусков")]));
  if (cur && runs.some((r) => r.run_id === cur)) sel.value = cur;
  if (first) {
    const fromHash = decodeURIComponent(location.hash.slice(1));
    const pick = runs.find((r) => r.run_id === fromHash) || runs[0];
    await openRun(pick ? pick.run_id : null);
  } else if (!cur && runs.length) {
    await openRun(runs[0].run_id);
  }
}

$("#runSel").addEventListener("change", (e) => openRun(e.target.value));
window.addEventListener("hashchange", () => {
  const id = decodeURIComponent(location.hash.slice(1));
  if (id && (!S || S.runId !== id)) openRun(id);
});

/* ------------------------------------------------------------------ feed pinning, zoom */

function setPinned(on) {
  pinned = on;
  $("#pinBtn").classList.toggle("on", on);
  if (on) { feed.scrollTop = feed.scrollHeight; $("#newBelow").hidden = true; }
}
$("#pinBtn").addEventListener("click", () => setPinned(!pinned));
$("#newBelow").addEventListener("click", () => setPinned(true));
feed.addEventListener("wheel", (e) => { if (e.deltaY < 0 && pinned) setPinned(false); }, { passive: true });
feed.addEventListener("scroll", () => {
  const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 8;
  if (atBottom && !pinned) setPinned(true);
});

$("#zoom").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  zoom = Number(b.dataset.z) || 1;
  document.querySelectorAll("#zoom button").forEach((x) => x.classList.toggle("on", x === b));
  if (S && S.timeline) renderTimeline();
});
let resizeT = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeT);
  resizeT = setTimeout(() => { if (S && S.timeline) renderTimeline(); }, 120);
});

setInterval(() => { if (S) { tickElapsed(); const st = runStatus(); if (!$("#status").classList.contains(st)) renderHeader(); } }, 1000);
setInterval(() => refreshRuns(false), 5000);
refreshRuns(true);
