"""The editing agent: harness-driven phases around a small local model.

  explore   harness loads the brief(s) and the vision-described asset catalog
  plan      model writes a storyboard (JSON schema: sections, goals, music, target seconds)
  build     model fills each section with shots (JSON schema, asset ids are an enum); sections run in parallel slots
  polish    model refines the whole edit with small tools (effects, sfx, order, music)
  review    harness compiles, renders every text frame, the vision model judges readability; model fixes failures
  export    harness compiles and exports, writes summary.json

The model only makes decisions; everything that needs arithmetic or craft is done by the harness.
"""
import json
import re
import shutil
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import assets as assets_mod
from .cards import CARD_STYLES, render_card
from .compiler import compile_edl, picture_media
from .edl import EDL, EFFECTS, LIMITS, LOOKS, MOTIONS, MUSIC, TRANSITIONS, Section
from .events import EventLog
from .llm import LLM, LLMError
from .media import CAPTION_STYLES, POSITIONS, h, thumb
from .tools import POLISH_TOOLS, PolishTools

SYSTEM = ("Ты опытный монтажёр коротких вертикальных роликов (Reels/Shorts/TikTok). Ты принимаешь творческие решения: "
          "структура, выбор кадров, ритм, подписи, стиль, музыка. Технику (кадрирование, анимацию, звук) делает программа. "
          "Пиши подписи по-русски, коротко и цепко. Не повторяй один и тот же кадр без причины. Меняй ритм: быстрые и медленные кадры, разные движения камеры.")


def brief_summary(path: Path, limit=1400) -> str:
    s = path.read_text(encoding="utf-8", errors="replace")
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    head = s[: limit // 2]
    style = re.search(r"#+\s*(Стиль|Style|Визуальный стиль)[^\n]*\n(.*?)(?=\n#+ |\Z)", s, re.S)
    return (head + ("\n…\nСтиль:\n" + style.group(2)[: limit // 2] if style else ""))[:limit]


class Agent:
    def __init__(self, task: str, assets_dir: Path, briefs: list[Path], run_dir: Path, seconds: float = 60, slots: int = 2,
                 llm: LLM | None = None, max_polish_turns=10, review_rounds=2, output_name="video.mp4"):
        self.task, self.assets_dir, self.briefs = task, Path(assets_dir), [Path(b) for b in briefs]
        self.run_dir, self.seconds, self.slots = Path(run_dir), float(seconds), max(1, int(slots))
        self.llm = llm or LLM()
        self.ev = EventLog(self.run_dir)
        self.max_polish_turns, self.review_rounds, self.output_name = max_polish_turns, review_rounds, output_name
        self.turn = 0
        self.counters = {"tool_calls": 0, "errors": 0}
        self.t0 = time.time()
        (self.run_dir / "frames" / "thumbs").mkdir(parents=True, exist_ok=True)

    # ---------- llm wrappers with events ----------
    def _llm_event(self, r, phase):
        msg = r["message"]
        self.ev.emit("llm_response", turn=self.turn, phase=phase, content=(msg.get("content") or "")[:4000],
                     tool_calls=[{"name": c["function"]["name"], "arguments": c["function"].get("arguments", "")[:4000]} for c in msg.get("tool_calls") or []],
                     usage=r["usage"], seconds=r["seconds"], tokens_per_second=r["tokens_per_second"])
        self.ev.emit("llm_stats", tokens_per_second=r["tokens_per_second"], prompt_per_second=r.get("prompt_per_second", 0),
                     kv_used=None, slots_busy=None, vram_mb=None, totals=dict(self.llm.totals))

    def ask_json(self, phase, messages, schema, max_tokens=3000, temperature=0.5, retries=2):
        for attempt in range(retries + 1):
            self.turn += 1
            self.ev.emit("llm_request", turn=self.turn, phase=phase, messages=len(messages), prompt_tokens_est=sum(len(str(m.get("content", ""))) for m in messages) // 3)
            try:
                out, r = self.llm.json(messages, schema, max_tokens=max_tokens, temperature=temperature)
                self._llm_event(r, phase)
                return out
            except LLMError as e:
                self.counters["errors"] += 1
                self.ev.emit("warning", message=f"{phase}: {e} (attempt {attempt + 1})")
        raise LLMError(f"{phase}: model failed {retries + 1} times")

    def step(self, name, args, result, ok=True):
        """A harness step shown in the feed like a tool call: tool_call + tool_result with the same id."""
        self._step_n = getattr(self, "_step_n", 0) + 1
        sid = f"h{self._step_n}-{name}"
        self.ev.emit("tool_call", id=sid, name=name, args=args)
        if not ok and isinstance(result, dict) and "error" not in result:
            result = {**result, "error": result.get("message", "проверка не пройдена")}
        self.ev.emit("tool_result", id=sid, name=name, ok=ok, result=result, seconds=0)

    # ---------- timeline events ----------
    def thumb_for(self, shot):
        try:
            if shot.kind == "card":
                media = render_card(shot.title, shot.subtitle, shot.card_style, shot.seconds)
            else:
                media = picture_media(self.edl.catalog[shot.asset])
            t = thumb(media)
            dst = self.run_dir / "frames" / "thumbs" / t.name
            if not dst.exists():
                shutil.copy(t, dst)
            return self.ev.rel(dst)
        except Exception:
            return None

    def emit_timeline(self):
        times = self.edl.times()
        clips = []
        for i, (s, (a, b)) in enumerate(zip(self.edl.shots, times), 1):
            clips.append({"n": i, "kind": "card" if s.kind == "card" else "clip", "label": s.label(), "section": s.section, "start": a, "end": b,
                          "look": s.look if s.kind == "picture" else s.card_style, "motion": s.motion if s.kind == "picture" else None,
                          "effects": list(s.effects), "caption": (s.caption.text if s.caption else (s.subtitle or None)),
                          "thumb": self._thumbs.get(i - 1)})
        music = []
        for sec in self.edl.sections:
            idx = self.edl.section_shots(sec.name)
            if idx and sec.music != "none":
                music.append({"mood": sec.music, "from": idx[0] + 1, "to": idx[-1] + 1, "db": sec.music_db, "section": sec.name})
        trans = [[i + 1, s.transition_out, s.transition_seconds] for i, s in enumerate(self.edl.shots[:-1]) if s.transition_out != "cut"]
        self.ev.emit("timeline", total_seconds=self.edl.total(), clips=clips, transitions=trans, music=music, sfx=self.edl.sfx,
                     sections=[{"name": s.name, "target_seconds": s.target_seconds} for s in self.edl.sections])

    def refresh_thumbs(self):
        self._thumbs = {}
        for i, s in enumerate(self.edl.shots):
            self._thumbs[i] = self.thumb_for(s)

    def changed(self):
        self._thumbs = {i: self.thumb_for(s) for i, s in enumerate(self.edl.shots)}
        self.emit_timeline()

    # ---------- phases ----------
    def explore(self):
        self.ev.emit("phase", name="explore", note="читаю материалы и каталог картинок")
        self.briefs_text = "\n\n".join(f"### {b.stem}\n{brief_summary(b)}" for b in self.briefs if b.exists())

        def described(key, entry):
            self.step("describe_asset", {"asset": key}, {"what": entry["what"], "mood": entry["mood"]})

        cat = assets_mod.load_or_build(self.assets_dir, llm=self.llm, on_item=described)
        if not cat:
            raise RuntimeError(f"no pictures found in {self.assets_dir}")
        self.edl = EDL(cat)
        self._thumbs = {}
        self.assets_text = assets_mod.compact_list(cat)
        self.groups = sorted({k.split("/")[0] for k in cat if "/" in k})
        self.step("catalog", {"dir": str(self.assets_dir)}, {"assets": len(cat), "briefs": [b.name for b in self.briefs]})

    def plan(self):
        self.ev.emit("phase", name="plan", note="раскадровка: секции, цели, музыка")
        schema = {"type": "object", "properties": {
            "title": {"type": "string"}, "concept": {"type": "string"},
            "sections": {"type": "array", "minItems": 3, "maxItems": 8, "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "goal": {"type": "string"}, "target_seconds": {"type": "number"},
                "music": {"type": "string", "enum": list(MUSIC)}, "music_db": {"type": "number"}, "visual_style": {"type": "string"},
                "asset_group": {"type": "string", "enum": self.groups + ["any"]},
                "transition_in": {"type": "string", "enum": TRANSITIONS}},
                "required": ["name", "goal", "target_seconds", "music", "visual_style", "asset_group", "transition_in"]}}},
            "required": ["title", "concept", "sections"]}
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"ЗАДАЧА:\n{self.task}\n\nДлительность ролика: около {int(self.seconds)} секунд.\n\nМАТЕРИАЛЫ:\n{self.briefs_text}\n\n"
                                            f"КАРТИНКИ (id | что | настроение):\n{self.assets_text}\n\n"
                                            "Сначала придумай раскадровку: 3-8 секций по порядку просмотра (интро и финал тоже секции). "
                                            "Для каждой: короткое имя (латиницей, без пробелов), цель секции, сколько секунд, музыка, визуальный стиль, "
                                            "asset_group — из какой папки картинок брать кадры (any — из любой, для интро и финала), "
                                            "transition_in — переход при входе в секцию (не cut: разные секции должны отличаться). Музыка: "
                                            + ", ".join(MUSIC) + ". Все тексты (title, concept, goal, visual_style) пиши по-русски."}]
        sb = self.ask_json("plan", msgs, schema, max_tokens=2500, temperature=0.7)
        total = sum(max(2.0, float(s.get("target_seconds", 8))) for s in sb["sections"]) or 1
        scale = self.seconds / total  # arithmetic belongs to the harness
        names = set()
        for s in sb["sections"]:
            name = re.sub(r"[^A-Za-z0-9_-]+", "_", s["name"]).strip("_")[:24] or f"s{len(names) + 1}"
            while name in names:
                name += "_2"
            names.add(name)
            self.edl.sections.append(Section(name=name, goal=s["goal"][:300], target_seconds=round(max(2.0, float(s["target_seconds"])) * scale, 1),
                                             music=s["music"] if s["music"] in MUSIC else "none", music_db=float(s.get("music_db", -10) or -10)))
            self.edl.sections[-1].visual_style = s.get("visual_style", "")[:200]
            self.edl.sections[-1].asset_group = s.get("asset_group", "any") if s.get("asset_group") in self.groups else "any"
            self.edl.sections[-1].transition_in = s.get("transition_in", "cross_dissolve") if s.get("transition_in") in TRANSITIONS else "cross_dissolve"
        self.storyboard = {"title": sb["title"], "concept": sb["concept"],
                           "sections": [{"name": s.name, "goal": s.goal, "target_seconds": s.target_seconds, "music": s.music,
                                         "visual_style": getattr(s, "visual_style", ""), "asset_group": getattr(s, "asset_group", "any"),
                                         "transition_in": getattr(s, "transition_in", "cut")} for s in self.edl.sections]}
        (self.run_dir / "storyboard.json").write_text(json.dumps(self.storyboard, ensure_ascii=False, indent=1))
        self.step("storyboard", {"seconds": self.seconds}, self.storyboard)
        self.emit_timeline()

    def shot_schema(self, group="any"):
        ids = [k for k in self.edl.catalog if group == "any" or k.startswith(group + "/")] or list(self.edl.catalog)
        picture = {"type": "object", "additionalProperties": False, "properties": {
            "kind": {"type": "string", "enum": ["picture"]}, "asset": {"type": "string", "enum": ids}, "seconds": {"type": "number"},
            "motion": {"type": "string", "enum": MOTIONS}, "look": {"type": "string", "enum": list(LOOKS)},
            "caption": {"type": "string", "description": "по-русски, до 60 символов, можно пусто"},
            "caption_style": {"type": "string", "enum": CAPTION_STYLES}, "caption_position": {"type": "string", "enum": POSITIONS},
            "effects": {"type": "array", "maxItems": 2, "items": {"type": "string", "enum": list(EFFECTS)}},
            "transition_out": {"type": "string", "enum": TRANSITIONS}},
            "required": ["kind", "asset", "seconds", "motion", "look", "caption", "caption_style", "caption_position", "effects", "transition_out"]}
        card = {"type": "object", "additionalProperties": False, "properties": {
            "kind": {"type": "string", "enum": ["card"]}, "card_title": {"type": "string"}, "card_subtitle": {"type": "string"},
            "card_style": {"type": "string", "enum": CARD_STYLES}, "seconds": {"type": "number"}, "transition_out": {"type": "string", "enum": TRANSITIONS}},
            "required": ["kind", "card_title", "card_subtitle", "card_style", "seconds", "transition_out"]}
        return {"type": "object", "properties": {"shots": {"type": "array", "minItems": 2, "maxItems": 8, "items": {"anyOf": [picture, card]}}}, "required": ["shots"]}

    def _build_section(self, k, sec, schema):
        prev = self.edl.sections[k - 1].name if k else "(начало ролика)"
        nxt = self.edl.sections[k + 1].name if k + 1 < len(self.edl.sections) else "(конец ролика)"
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"ЗАДАЧА:\n{self.task}\n\nМАТЕРИАЛЫ:\n{self.briefs_text}\n\nРАСКАДРОВКА:\n{json.dumps(self.storyboard, ensure_ascii=False)}\n\n"
                                            f"КАРТИНКИ (id | что | настроение):\n{self.assets_text}\n\n"
                                            f"Сейчас собери ТОЛЬКО секцию «{sec.name}» (до неё: {prev}, после: {nxt}). Цель: {sec.goal}. "
                                            f"Визуальный стиль: {getattr(sec, 'visual_style', '')}. Длительность секции около {sec.target_seconds} с.\n"
                                            "Кадр kind=picture: asset (id из списка), seconds 0.8-6, motion и look (меняй их от кадра к кадру под настроение секции), caption (до 60 символов, может быть пустой) со стилем и позицией, effects (0-2).\n"
                                            "Кадр kind=card: полноэкранная карточка, asset=\"\", card_title (до 28 символов), card_subtitle, card_style, seconds 1.5-3.\n"
                                            "transition_out — переход в следующий кадр (cut — склейка). Подбирай картинки по смыслу описаний, не повторяй одну картинку. "
                                            + ("Это интро или финал: бери по одной картинке из разных групп. " if getattr(sec, "asset_group", "any") == "any" else
                                               f"Бери картинки только из группы {sec.asset_group}. ")
                                            + "Все подписи и заголовки — только по-русски, без эмодзи."}]
        out = self.ask_json(f"build:{sec.name}", msgs, self.shot_schema(getattr(sec, "asset_group", "any")), max_tokens=2500, temperature=0.6)
        return k, out

    def build(self):
        self.ev.emit("phase", name="build", note=f"собираю {len(self.edl.sections)} секций, параллельно в {self.slots} слотах")
        results = {}
        with ThreadPoolExecutor(max_workers=self.slots) as pool:
            futs = [pool.submit(self._build_section, k, sec, None) for k, sec in enumerate(self.edl.sections)]
            for f in futs:
                try:
                    k, out = f.result()
                    results[k] = out
                except Exception as e:
                    self.counters["errors"] += 1
                    self.ev.emit("error", message=str(e)[:300], where="build")
        for k, sec in enumerate(self.edl.sections):
            out = results.get(k, {"shots": []})
            warnings, shots = [], []
            for raw in out.get("shots", []):
                if raw.get("kind") == "card":
                    raw = {**raw, "asset": ""}
                    raw.setdefault("card_title", sec.name)
                s = self.edl.make_shot(raw, sec.name, warnings)
                if s:
                    shots.append(s)
            if not shots:
                warnings.append("section came back empty; added a title card")
                s = self.edl.make_shot({"card_title": sec.goal[:28] or sec.name, "card_style": "minimal", "seconds": 2}, sec.name, warnings)
                shots.append(s)
            # 1) fit the section to its target length
            total = sum(s.seconds for s in shots)
            if total and abs(total - sec.target_seconds) / sec.target_seconds > 0.2:
                f = sec.target_seconds / total
                for s in shots:
                    lim = LIMITS["card_seconds"] if s.kind == "card" else LIMITS["picture_seconds"]
                    s.seconds = round(min(lim[1], max(lim[0], s.seconds * f)), 2)
                warnings.append(f"section {sec.name}: {round(total, 1)}s scaled toward target {sec.target_seconds}s")
            # 2) reading time floor for captions and cards wins over the target
            for s in shots:
                text = (s.caption.text if s.caption else "") + (" " + s.title + " " + s.subtitle if s.kind == "card" else "")
                need = round(min(6.0, max(1.2, len(text.strip()) / 14)), 1) if text.strip() else 0
                if need > s.seconds:
                    s.seconds = need
            # 3) still far too long: drop shots from the end (keep at least 2)
            while len(shots) > 2 and sum(s.seconds for s in shots) > sec.target_seconds * 1.4:
                gone = shots.pop()
                warnings.append(f"dropped {gone.label()} to keep the section near {sec.target_seconds}s")
            # 4) repeated pictures inside the section
            seen = set()
            for s in list(shots):
                if s.kind == "picture" and s.asset in seen and len(shots) > 2:
                    shots.remove(s)
                    warnings.append(f"removed repeated picture {s.asset}")
                seen.add(s.asset)
            # 5) not every cut is a transition: keep at most 2 inside the section
            inner = [s for s in shots[:-1] if s.transition_out != "cut"]
            for s in inner[2:]:
                s.transition_out = "cut"
            if len(inner) > 2:
                warnings.append(f"kept 2 of {len(inner)} transitions inside the section")
            if shots[-1].transition_out != "cut" and k + 1 < len(self.edl.sections):
                shots[-1].transition_out = "cut"  # the next section sets its own entrance transition
            # 6) section entrance transition
            if k and self.edl.shots and self.edl.shots[-1].transition_out == "cut":
                self.edl.shots[-1].transition_out = getattr(sec, "transition_in", "cross_dissolve")
                self.edl.shots[-1].transition_seconds = 0.6
            self.edl.shots.extend(shots)
            self.step("build_section", {"section": sec.name, "target_seconds": sec.target_seconds},
                      {"shots": len(shots), "seconds": round(sum(s.seconds for s in shots), 1), "warnings": warnings})
            self.refresh_thumbs()
            self.emit_timeline()

    def action_schema(self):
        """anyOf with one exact object per operation: the grammar only allows that op's own fields; sections and shots are enums."""
        n = max(1, len(self.edl.shots))
        shot = {"type": "integer", "minimum": 1, "maximum": n}
        section = {"type": "string", "enum": [x.name for x in self.edl.sections]}
        variants = []
        for t in POLISH_TOOLS:
            f = t["function"]
            if f["name"] == "done":
                continue
            props = {"op": {"type": "string", "enum": [f["name"]]}}
            for k, v in f["parameters"]["properties"].items():
                props[k] = shot if k in ("shot",) else section if k == "section" else ({"type": "integer", "minimum": 1, "maximum": n} if k == "to" else v)
            variants.append({"type": "object", "properties": props, "required": ["op"] + f["parameters"]["required"], "additionalProperties": False})
        return {"type": "object", "properties": {
            "thoughts": {"type": "string", "description": "одно-два предложения: что улучшаешь и зачем"},
            "actions": {"type": "array", "maxItems": 10, "items": {"anyOf": variants}},
            "done": {"type": "boolean"}}, "required": ["thoughts", "actions", "done"]}

    def action_rounds(self, phase, intro, handler, max_rounds):
        """The model answers with a JSON list of edit actions; the harness applies them and reports back."""
        schema = self.action_schema()
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": intro}]
        for rnd in range(max_rounds):
            try:
                out = self.ask_json(phase, msgs, schema, max_tokens=2000, temperature=0.4)
            except LLMError as e:
                self.ev.emit("warning", message=str(e)[:300])
                return
            msgs.append({"role": "assistant", "content": json.dumps(out, ensure_ascii=False)})
            results = []
            for k, act in enumerate(out.get("actions", [])):
                op = act.pop("op", "")
                args = {key: v for key, v in act.items() if v not in (None, "") or key == "caption"}
                cid = f"{phase}-{rnd}-{k}"
                self.ev.emit("tool_call", id=cid, name=op, args=args)
                t = time.time()
                res = handler.dispatch(op, args)
                ok = not (isinstance(res, dict) and "error" in res)
                self.counters["tool_calls"] += 1
                self.counters["errors"] += 0 if ok else 1
                self.ev.emit("tool_result", id=cid, name=op, ok=ok, result=res, seconds=round(time.time() - t, 3))
                results.append({"op": op, **(res if isinstance(res, dict) else {"result": res})})
            if out.get("done") or not out.get("actions"):
                return
            msgs.append({"role": "user", "content": f"Результаты: {json.dumps(results, ensure_ascii=False)[:2500]}\n\n"
                                                    f"Монтажный лист сейчас: {json.dumps(self.edl.summary(), ensure_ascii=False)[:6000]}\n\n"
                                                    "Если нужно ещё что-то — следующие действия, иначе done=true и пустой список."})

    def polish(self):
        self.ev.emit("phase", name="polish", note="доводка: эффекты, звуки, порядок, музыка")
        handler = PolishTools(self.edl, self.changed)
        intro = (f"ЗАДАЧА:\n{self.task}\n\nМонтаж собран. Монтажный лист:\n{json.dumps(self.edl.summary(), ensure_ascii=False)}\n\n"
                 "Доведи его: добавь 3-6 звуковых эффектов на сильные моменты (add_sfx), поправь эффекты и движения, чтобы было разнообразно, "
                 "проверь, что подписи короткие, по-русски и по делу, что нет повторов, что финал сильный. Верни список действий (op = имя операции и её поля). Делай только нужные правки; когда всё готово — done=true.")
        self.action_rounds("polish", intro, handler, max(1, self.max_polish_turns // 3))

    def review(self):
        for rnd in range(self.review_rounds):
            self.ev.emit("phase", name="review", note=f"проверка кадров зрением, раунд {rnd + 1}")
            compiled = compile_edl(self.edl, on_progress=lambda m: None)
            try:
                text_shots = [i for i, s in enumerate(self.edl.shots) if s.caption or s.kind == "card"]
                # render sequentially (one FilmCraft session), judge in parallel slots
                frames = []
                for i in text_shots:
                    a, b = compiled.times[i]
                    png = compiled.frame_png(a + (b - a) * 0.55)
                    p = self.run_dir / "frames" / f"shot{i + 1:02d}-r{rnd + 1}.png"
                    p.write_bytes(png)
                    frames.append((i, p))
                    self._thumbs[i] = self.ev.rel(p)
                self.emit_timeline()
            finally:
                compiled.close()
            schema = {"type": "object", "properties": {"text_readable": {"type": "boolean"}, "seen": {"type": "string"}}, "required": ["text_readable", "seen"]}
            q = "Кадр вертикального ролика. text_readable: можно ли легко прочитать главный текст (true/false). seen: что видно, до 12 слов, по-русски."

            def judge(item):
                i, p = item
                v = self.llm.vision(p.read_bytes(), q, schema)
                self.ev.emit("frame", path=self.ev.rel(p), clip=i + 1, seconds=None, verdict=v)
                return i, v

            with ThreadPoolExecutor(max_workers=self.slots) as pool:
                verdicts = list(pool.map(judge, frames))
            bad = [(i, v) for i, v in verdicts if not v.get("text_readable", True)]
            if not bad:
                self.step("review", {"round": rnd + 1}, {"checked": len(verdicts), "unreadable": 0})
                return
            self.step("review", {"round": rnd + 1}, {"checked": len(verdicts), "unreadable": [i + 1 for i, _ in bad],
                                                     "error": f"текст плохо читается на кадрах {[i + 1 for i, _ in bad]}"}, ok=False)
            handler = PolishTools(self.edl, self.changed)
            listing = "\n".join(f"кадр {i + 1}: {self.edl.shots[i].label()} — подпись «{self.edl.shots[i].caption.text if self.edl.shots[i].caption else self.edl.shots[i].title}», "
                                f"эффекты {self.edl.shots[i].effects}, look {self.edl.shots[i].look}; зрение увидело: {v.get('seen', '')}" for i, v in bad)
            intro = (f"Проверка зрением: на этих кадрах текст читается плохо:\n{listing}\n\nИсправь каждый: убери мешающие эффекты (effects=[]), "
                     "смени стиль/позицию подписи или look на более спокойный, сократи текст. Верни действия, потом done=true.")
            self.action_rounds("review", intro, handler, 2)

    def export(self):
        self.ev.emit("phase", name="export", note="финальная сборка и рендер")
        compiled = compile_edl(self.edl)
        try:
            out = compiled.export(self.run_dir / "output" / self.output_name)
        finally:
            compiled.close()
        self.ev.emit("export", path=self.ev.rel(out), seconds=self.edl.total(), size_bytes=out.stat().st_size)
        return out

    def run(self):
        self.ev.emit("run_start", task=self.task, model=self.llm.model_name(), tools=[t["function"]["name"] for t in POLISH_TOOLS],
                     assets_dir=str(self.assets_dir), briefs=[str(b) for b in self.briefs], seconds=self.seconds, slots=self.slots)
        ok, reason, out = False, "", None
        try:
            self.explore()
            self.plan()
            self.build()
            self.polish()
            self.review()
            out = self.export()
            ok, reason = True, "exported"
        except KeyboardInterrupt:
            reason = "interrupted"
        except Exception as e:
            reason = f"{type(e).__name__}: {e}"
            self.ev.emit("error", message=reason[:500], where=traceback.format_exc()[-800:])
        summary = {"ok": ok, "reason": reason, "output": str(out) if out else None, "seconds": getattr(self, "edl", None) and self.edl.total(),
                   "wall_seconds": round(time.time() - self.t0, 1), "llm": dict(self.llm.totals), **self.counters,
                   "edl": self.edl.to_dict() if hasattr(self, "edl") else None}
        (self.run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
        self.ev.emit("run_end", ok=ok, reason=reason, summary={k: v for k, v in summary.items() if k != "edl"})
        return summary
