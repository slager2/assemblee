"""The editing agent: harness-driven phases around a small local model.

  explore   harness loads the brief(s) and the vision-described asset catalog
  plan      model writes a storyboard (JSON schema: sections, goals, music, target seconds)
  build     model fills each section with shots (JSON schema, asset ids are an enum); sections run in parallel slots
  polish    model refines the whole edit with small tools (effects, sfx, order, music)
  review    harness compiles, renders every text frame, the vision model judges readability; model fixes failures
  export    harness compiles and exports, writes summary.json

The model only makes decisions; everything that needs arithmetic or craft is done by the harness.
"""
import hashlib
import json
import threading
import re
import io
import shutil
import subprocess
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import assets as assets_mod
from . import ideas as ideas_mod
from . import music as music_mod
from . import vocab
from .cards import CARD_STYLES, render_card
from .compiler import compile_edl, picture_media
from .config import FONT_BOLD, REPO
from .edl import EDL, EFFECTS, LIMITS, clamp, LOOKS, MOTIONS, MUSIC, TRANSITIONS, Section
from .events import EventLog
from .llm import LLM, LLMError
from .media import CAPTION_STYLES, POSITIONS, h, thumb
from .tools import POLISH_TOOLS, PolishTools, polish_tools

GUARDRAILS = ("full", "light", "off")
SERVE = REPO / "scripts" / "serve_llm.sh"
PROFILE_FILE = REPO / ".cache" / "llm-server.profile"  # written by serve_llm.sh
PLANNERS = {"9b": "planner"}  # --planner value -> serve_llm.sh profile
THINK_NEEDS_PROFILE = False  # the plain profiles (--reasoning off) still honour chat_template_kwargs.enable_thinking per request
READ_FLOOR = 0.8  # hard minimum for a shot with text, in every guardrails mode

SYSTEM = ("Ты опытный монтажёр коротких вертикальных роликов (Reels/Shorts/TikTok). Ты принимаешь творческие решения: "
          "структура, выбор кадров, ритм, подписи, стиль, музыка. Технику (кадрирование, анимацию, звук) делает программа. "
          "Пиши подписи по-русски, коротко и цепко. Не повторяй один и тот же кадр без причины. Меняй ритм: быстрые и медленные кадры, разные движения камеры."
          + " Ответы в JSON пиши компактно, одной строкой, без отступов и переносов.")


def brief_summary(path: Path, limit=1400) -> str:
    s = path.read_text(encoding="utf-8", errors="replace")
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    head = s[: limit // 2]
    style = re.search(r"#+\s*(Стиль|Style|Визуальный стиль)[^\n]*\n(.*?)(?=\n#+ |\Z)", s, re.S)
    return (head + ("\n…\nСтиль:\n" + style.group(2)[: limit // 2] if style else ""))[:limit]


def norm_text(t):
    return re.sub(r"[^0-9a-zа-яё]+", " ", str(t).lower().replace("ё", "е")).strip()


def contact_sheet(frames, labels, cols=None, tile_w=216, start=1):
    """One tile per shot, numbered, in reading order: the director's view of the whole edit (JPEG bytes)."""
    from PIL import Image, ImageDraw, ImageFont
    n = len(frames)
    cols = cols or max(1, min(6, round((n * 9 / 16) ** 0.5 * 1.25)))
    rows = -(-n // cols)
    tile_h, pad = tile_w * 16 // 9, 6
    sheet = Image.new("RGB", (cols * (tile_w + pad) + pad, rows * (tile_h + pad) + pad), (24, 24, 24))
    big, small = ImageFont.truetype(FONT_BOLD, 34), ImageFont.truetype(FONT_BOLD, 15)
    for k, (png, label) in enumerate(zip(frames, labels)):
        im = Image.open(io.BytesIO(png)).convert("RGB").resize((tile_w, tile_h))
        d = ImageDraw.Draw(im)
        num = str(k + start)
        bw = d.textlength(num, font=big) + 14
        d.rectangle([0, 0, bw, 44], fill=(230, 30, 30))
        d.text((7, 3), num, font=big, fill=(255, 255, 255))
        d.rectangle([0, tile_h - 22, tile_w, tile_h], fill=(0, 0, 0))
        d.text((5, tile_h - 20), label[:26], font=small, fill=(255, 255, 255))
        sheet.paste(im, (pad + (k % cols) * (tile_w + pad), pad + (k // cols) * (tile_h + pad)))
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def frame_flags(png):
    """Cheap pixel check, no model: 'почти белый' / 'почти чёрный' frames (blown-out glow, full vignette, empty dark shot)."""
    from PIL import Image, ImageStat
    im = Image.open(io.BytesIO(png)).convert("L").resize((108, 192))
    st = ImageStat.Stat(im)
    mean, std = st.mean[0], st.stddev[0]
    if mean > 225 and std < 30:
        return "почти белый (засвет)"
    if mean < 18 and std < 14:
        return "почти чёрный"
    return ""


def text_match(read, expected):
    """How much of the expected text the vision model managed to read (0..1), order-insensitive by words."""
    import difflib
    r, e = norm_text(read), norm_text(expected)
    if not e:
        return 1.0
    if not r:
        return 0.0
    words = e.split()
    hit = sum(1 for w in words if any(difflib.SequenceMatcher(None, w, x).ratio() >= 0.75 for x in r.split()))
    return max(hit / len(words), difflib.SequenceMatcher(None, r, e).ratio())


MUSIC_DESC = {"dark_drone": "низкий тревожный гул, без ритма (хоррор, тайна)", "chiptune": "весёлый 8-бит, 120 BPM (игры, юмор, быстро)",
              "epic": "бочка и синт, 140 BPM (масштаб, кульминация)", "warm_pad": "мягкие аккорды без ударных (тепло, семья, воспоминания)",
              "none": "тишина"}
THINK_PLAN = ("Если думаешь — думай по-русски и коротко, не пересказывай задачу. По порядку: 1) крючок первых 2 секунд: какая картинка и какие 3-5 слов; "
              "2) из каких частей ролик и чем каждая отличается (цвет, стиль подписей, музыка, темп); 3) финал: пик, обрыв или петля. Потом ответ.")
THINK_BUILD = ("Если думаешь — думай по-русски и коротко, не пересказывай задачу: для каждого кадра — какая картинка и почему она подходит "
               "к подписи по смыслу, длина кадра, и чем соседние кадры отличаются. Потом ответ.")


def cut_words(text, limit):
    """Truncate at a word boundary, never mid-word."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit + 1].rsplit(" ", 1)[0]
    return (cut if len(cut) >= limit // 2 else t[:limit]).rstrip(" ,.;:-—")


class Agent:
    def __init__(self, task: str, assets_dir: Path, briefs: list[Path], run_dir: Path, seconds: float = 60, slots: int = 2,
                 llm: LLM | None = None, max_polish_turns=10, review_rounds=2, output_name="video.mp4", mode="strict", fetch: str | None = None,
                 guardrails="full", think=False, think_budget=1024, planner=None, director=None,
                 music_web=False, ideas=None, surprise=False):
        """guardrails: full (the harness fixes durations, key messages, transitions, asset groups itself), light (only
        validation; everything else becomes feedback the model sees in polish), off (light without reading-time
        warnings and duplicate removal). think: storyboard and section building think first. planner: "9b" runs
        plan/build/polish on Qwen3.5-9B and swaps back to the 4B for vision. director: contact-sheet self-review
        (default: on unless guardrails=full)."""
        if guardrails not in GUARDRAILS:
            raise ValueError(f"guardrails must be one of {GUARDRAILS}")
        self.task, self.assets_dir, self.briefs = task, Path(assets_dir), [Path(b) for b in briefs]
        self.run_dir, self.seconds, self.slots = Path(run_dir), float(seconds), max(1, int(slots))
        self.llm = llm or LLM()
        self.ev = EventLog(self.run_dir)
        self.max_polish_turns, self.review_rounds, self.output_name = max_polish_turns, review_rounds, output_name
        self.mode, self.fetch = mode, fetch
        self.guardrails, self.think, self.think_budget, self.planner = guardrails, bool(think), int(think_budget), planner
        self.director_on = (guardrails != "full") if director is None else bool(director)
        if planner and planner not in PLANNERS:
            raise ValueError(f"planner must be one of {list(PLANNERS)}")
        self.music_web, self.surprise = bool(music_web), bool(surprise)
        self.ideas_on = (mode == "rich") if ideas is None else bool(ideas)
        self.seed = int(time.time()) % 100000  # different inspiration recipes every run
        self.concept, self.image_groups, self.music_moods, self.music_queries = None, None, None, None
        self.swaps, self.phase_seconds = [], {}
        self.turn = 0
        self._lock = threading.Lock()
        self._verdicts = {}  # (frame hash, expected text) -> review verdict
        self.counters = {"tool_calls": 0, "errors": 0}
        self.t0 = time.time()
        (self.run_dir / "frames" / "thumbs").mkdir(parents=True, exist_ok=True)

    # ---------- llm wrappers with events ----------
    def _next_turn(self):
        with self._lock:  # parallel section builds share the counter
            self.turn += 1
            return self.turn

    def _llm_event(self, r, phase, turn=None):
        msg = r["message"]
        content = msg.get("content") or ""
        if r.get("reasoning"):
            thoughts = r["reasoning"].strip()
            content = "[мысли] " + (thoughts if len(thoughts) <= 1500 else thoughts[:700] + " … " + thoughts[-700:]) + "\n\n" + content
        self.ev.emit("llm_response", turn=turn if turn is not None else self.turn, phase=phase, content=content[:4000], reasoning_tokens=r.get("reasoning_tokens", 0),
                     tool_calls=[{"name": c["function"]["name"], "arguments": c["function"].get("arguments", "")[:4000]} for c in msg.get("tool_calls") or []],
                     usage=r["usage"], seconds=r["seconds"], tokens_per_second=r["tokens_per_second"])
        self.ev.emit("llm_stats", tokens_per_second=r["tokens_per_second"], prompt_per_second=r.get("prompt_per_second", 0),
                     kv_used=None, slots_busy=None, vram_mb=None, totals=dict(self.llm.totals))

    THINK_SHARE = {"plan": 0.625, "build": 0.25, "director": 0.0}  # measured: every request used its whole budget

    def think_for(self, phase):
        """Thinking budget of a phase (tokens; 0 = no thinking): the concept gets the full budget, planning less,
        each section build a short one, the director's act step none (its thinking happened in the look step)."""
        if not self.think:
            return 0
        return int(self.think_budget * self.THINK_SHARE.get(phase, 1.0))

    def ask_json(self, phase, messages, schema, max_tokens=3000, temperature=0.5, retries=2, think=False):
        for attempt in range(retries + 1):
            turn = self._next_turn()
            self.ev.emit("llm_request", turn=turn, phase=phase, messages=len(messages), prompt_tokens_est=sum(len(str(m.get("content", ""))) for m in messages) // 3)
            try:
                budget = self.think_budget if think is True else int(think or 0)  # think=True: full budget; an int: that many tokens
                out, r = self.llm.json(messages, schema, max_tokens=max_tokens, temperature=temperature,
                                       **({"think": True, "think_budget": budget} if budget > 0 else {}))
                self._llm_event(r, phase, turn)
                return out
            except LLMError as e:
                with self._lock:
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

    @staticmethod
    def expected_text(shot):
        if shot.kind == "card":
            return shot.title
        return shot.caption.text if shot.caption else ""

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

    # ---------- model swaps (serve_llm.sh profiles; only at phase boundaries) ----------
    @staticmethod
    def current_profile():
        return PROFILE_FILE.read_text().strip() if PROFILE_FILE.exists() else None

    def profile_for(self, role):
        base = PLANNERS[self.planner] if role == "planner" and self.planner else "agent"
        return base + ("-think" if self.think and THINK_NEEDS_PROFILE else "")

    def use_model(self, role, phase):
        """role "vision" (4B + mmproj) or "planner"; swaps the llama-server profile if needed and logs the cost."""
        if not self.planner and not (self.think and THINK_NEEDS_PROFILE):
            return
        want, have = self.profile_for(role), self.current_profile()
        if have == want and self.llm.health():
            return
        if have is None and self.llm.health():
            raise RuntimeError("llama-server was not started by scripts/serve_llm.sh; model swaps need it "
                               f"(stop it and run scripts/serve_llm.sh start {self.profile_for('vision')})")
        self.ev.emit("phase", name=phase, note=f"меняю модель: {have or '—'} → {want}")
        t = time.time()
        r = subprocess.run([str(SERVE), "start", want], capture_output=True, text=True, timeout=600)
        dt = round(time.time() - t, 1)
        if r.returncode:
            raise RuntimeError(f"model swap to {want} failed: {(r.stderr or r.stdout)[-400:]}")
        self.swaps.append({"from": have, "to": want, "seconds": dt, "before": phase})
        self.step("swap_model", {"from": have, "to": want}, {"seconds": dt, "model": self.llm.model_name(), "server": r.stdout.strip()[-160:]})
        self.ev.emit("phase", name=phase, note=f"модель {want} готова за {dt} с")

    # ---------- phases ----------
    def concept_phase(self):
        """The model invents the video itself: idea, what pictures to look for online, what music. Nothing is chosen by the harness."""
        self.ev.emit("phase", name="plan", note="модель придумывает концепцию, что искать в интернете и какую музыку")
        q = {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string", "maxLength": 60}}
        schema = {"type": "object", "properties": {
            "title": {"type": "string", "maxLength": 60}, "logline": {"type": "string", "maxLength": 300},
            "why_surprising": {"type": "string", "maxLength": 300}, "style": {"type": "string", "maxLength": 300},
            "picture_groups": {"type": "array", "minItems": 2, "maxItems": 5, "items": {"type": "object", "properties": {
                "name": {"type": "string", "maxLength": 24}, "shows": {"type": "string", "maxLength": 120}, "queries_en": q},
                "required": ["name", "shows", "queries_en"], "additionalProperties": False}},
            "music_moods": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "object", "properties": {
                "name": {"type": "string", "maxLength": 24}, "description": {"type": "string", "maxLength": 120}, "queries_en": q},
                "required": ["name", "description", "queries_en"], "additionalProperties": False}}},
            "required": ["title", "logline", "why_surprising", "style", "picture_groups", "music_moods"]}
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"ЗАПРОС:\n{self.task}\n\nДлительность: около {int(self.seconds)} секунд.\n"
                                            + (f"\nМАТЕРИАЛЫ:\n{self.briefs_text}\n" if self.briefs_text else "")
                                            + "\nПридумай сам, каким будет ролик — так, чтобы зритель удивился: неожиданная идея, сильный крючок в первые 2 секунды, "
                                            "необычная подача. Ты сам решаешь тему, стиль, какие картинки найти в интернете (группы и поисковые запросы на английском "
                                            "для фотобанков с открытыми лицензиями — Openverse и Wikimedia Commons, ищи конкретные вещи, а не абстракции) и какую музыку найти "
                                            "(настроения и запросы на английском для Jamendo/ccMixter). Тексты title/logline/why_surprising/style — по-русски.\n\n"
                                            + ideas_mod.hook_ideas(n=6, seed=self.seed)}]
        c = self.ask_json("concept", msgs, schema, max_tokens=1800, temperature=0.9, think=self.think)  # the idea deserves the full budget
        self.concept = c
        def group_name(g, i):  # the model may name groups in Russian: fall back to its English query
            for cand in [g["name"]] + list(g["queries_en"]):
                n = re.sub(r"[^a-z0-9_]+", "_", cand.lower()).strip("_")[:24]
                if n:
                    return n
            return f"g{i}"
        self.image_groups = [{"name": group_name(g, i), "shows": g["shows"],
                              "queries": g["queries_en"]} for i, g in enumerate(c["picture_groups"])]
        names = [re.sub(r"[^a-z0-9_]+", "_", m["name"].lower()).strip("_")[:24] or f"m{i}" for i, m in enumerate(c["music_moods"])]
        self.music_moods = {n: m["description"] for n, m in zip(names, c["music_moods"])}
        self.music_queries = {n: m["queries_en"] for n, m in zip(names, c["music_moods"])}
        (self.run_dir / "concept.json").write_text(json.dumps(c, ensure_ascii=False, indent=1))
        self.task = (f"{self.task}\n\nКОНЦЕПЦИЯ (придумана тобой): «{c['title']}». {c['logline']} Почему удивит: {c['why_surprising']} "
                     f"Стиль: {c['style']}")
        self.step("concept", {"request": self.task[:200]}, c)

    def explore(self):
        self.ev.emit("phase", name="explore", note="читаю материалы и каталог картинок")
        self.briefs_text = "\n\n".join(f"### {b.stem}\n{brief_summary(b)}" for b in self.briefs if b.exists())

        def described(key, entry):
            self.step("describe_asset", {"asset": key}, {"what": entry["what"], "mood": entry["mood"]})

        if self.fetch or self.image_groups:
            from . import fetch as fetch_mod
            self.ev.emit("phase", name="explore", note=f"ищу и скачиваю картинки: {self.fetch or ', '.join(g['name'] for g in self.image_groups)}")
            fetch_mod.gather(self.fetch or self.task, self.llm, self.assets_dir, groups=self.image_groups,
                             on_event=lambda t, d: self.ev.emit(t, **d))
        library = {}
        if self.music_web:
            self.ev.emit("phase", name="explore", note="ищу и скачиваю музыку с открытыми лицензиями")
            moods = self.music_moods or {"main": self.task[:200]}
            try:
                lib = music_mod.gather_music(self.task, self.llm, self.run_dir, moods, queries=self.music_queries,
                                             on_event=lambda t, d: self.ev.emit(t, **d))
                library = {t["id"]: t for t in lib}
            except Exception as e:
                self.ev.emit("warning", message=f"музыка из интернета не скачалась: {str(e)[:200]}; остаются встроенные подложки")
        cat = assets_mod.load_or_build(self.assets_dir, llm=self.llm, on_item=described)
        if not cat:
            raise RuntimeError(f"no pictures found in {self.assets_dir}")
        self.edl = EDL(cat, mode=self.mode)
        self.edl.music_library = library
        self._thumbs = {}
        self.assets_text = assets_mod.compact_list(cat)
        self.groups = sorted({k.split("/")[0] for k in cat if "/" in k})
        self.step("catalog", {"dir": str(self.assets_dir)}, {"assets": len(cat), "briefs": [b.name for b in self.briefs]})

    def plan(self):
        self.ev.emit("phase", name="plan", note="раскадровка: секции, цели, музыка")
        schema = {"type": "object", "properties": {
            "title": {"type": "string", "maxLength": 80}, "concept": {"type": "string", "maxLength": 400},
            "hook": {"type": "object", "additionalProperties": False, "properties": {
                "asset": {"type": "string", "enum": list(self.edl.catalog)}, "caption": {"type": "string", "maxLength": 40},
                "why": {"type": "string", "maxLength": 160}}, "required": ["asset", "caption", "why"]},
            "ending": {"type": "string", "maxLength": 200, "description": "чем заканчивается ролик: пик, обрыв или петля"},
            "sections": {"type": "array", "minItems": 3, "maxItems": 8, "items": {"type": "object", "properties": {
                "name": {"type": "string", "maxLength": 24}, "goal": {"type": "string", "maxLength": 240}, "target_seconds": {"type": "number"},
                "shots": {"type": "integer", "minimum": 1, "maximum": 10}, "caption_style": {"type": "string", "enum": CAPTION_STYLES},
                "music": {"type": "string", "enum": self.edl.music_choices()}, "music_db": {"type": "number", "minimum": -24, "maximum": 3}, "visual_style": {"type": "string"},
                "asset_group": {"type": "string", "enum": self.groups + ["any"]},
                "transition_in": {"type": "string", "enum": TRANSITIONS},
                "key_message": {"type": "string", "maxLength": 40, "description": "главная мысль секции, 2-6 слов по-русски; обязательно появится в кадре"}},
                "required": ["name", "goal", "target_seconds", "shots", "caption_style", "music", "visual_style", "asset_group", "transition_in", "key_message"]}}},
            "required": ["title", "concept", "hook", "ending", "sections"]}
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"ЗАДАЧА:\n{self.task}\n\nДлительность ролика: около {int(self.seconds)} секунд.\n\nМАТЕРИАЛЫ:\n{self.briefs_text}\n\n"
                                            f"КАРТИНКИ (id | что | настроение):\n{self.assets_text}\n\n"
                                            "Сначала придумай раскадровку: 3-8 секций по порядку просмотра (интро и финал тоже секции). "
                                            "Для каждой: короткое имя (латиницей, без пробелов), key_message — главная мысль секции в 2-6 словах, цель секции, сколько секунд, музыка, визуальный стиль, "
                                            "asset_group — из какой папки картинок брать кадры (any — из любой, для интро и финала), "
                                            "transition_in — переход при входе в секцию (не cut: разные секции должны отличаться), "
                                            "shots — сколько кадров (обычно кадр 1-2.5 с: секция 10 с ≈ 5-7 кадров; «быстро» — до 1.2 с; одна пауза-удар на ролик допустима), "
                                            "caption_style — свой стиль подписей секции, чтобы части отличались характером.\n"
                                            "hook — крючок первых 2 секунд: картинка и 3-5 слов, которые остановят листание (не заставка с названием). "
                                            "ending — финал: последние 2-3 секунды — пик, обрыв или петля к началу; финальная карточка не дольше 2 с, один призыв, без повтора подписью и карточкой.\n"
                                            "Музыка: " + "; ".join(f"{k} — {v}" for k, v in MUSIC_DESC.items())
                                            + (f", или настоящие треки из интернета (id, настроение, темп, где «дроп»): {json.dumps(music_mod.library_for_prompt(self.edl.music_library), ensure_ascii=False)}"
                                               if self.edl.music_library else "")
                                            + ". Все тексты (title, concept, goal, visual_style) пиши по-русски."
                                            + "\n\n" + ideas_mod.hook_ideas(n=5 if self.ideas_on else 3, seed=self.seed)
                                            + ("\n\n" + THINK_PLAN if self.think else "")}]
        sb = self.ask_json("plan", msgs, schema, max_tokens=2500, temperature=0.7, think=self.think_for("plan"))
        self.hook = sb.get("hook") or {}
        self.ending = cut_words(sb.get("ending", ""), 200)
        total = sum(max(2.0, float(s.get("target_seconds", 8))) for s in sb["sections"]) or 1
        scale = self.seconds / total if self.guardrails == "full" else 1.0  # full: arithmetic belongs to the harness
        names = set()
        for s in sb["sections"]:
            name = re.sub(r"[^A-Za-z0-9_-]+", "_", s["name"]).strip("_")[:24] or f"s{len(names) + 1}"
            while name in names:
                name += "_2"
            names.add(name)
            self.edl.sections.append(Section(name=name, goal=s["goal"][:300], target_seconds=round(max(2.0, float(s["target_seconds"])) * scale, 1),
                                             music=self.edl.resolve_music(s["music"], []),
                                             music_db=clamp(s.get("music_db", -10.0), LIMITS["music_db"], -10.0, "music_db", [])))
            self.edl.sections[-1].visual_style = s.get("visual_style", "")[:200]
            self.edl.sections[-1].asset_group = s.get("asset_group", "any") if s.get("asset_group") in self.groups else "any"
            self.edl.sections[-1].transition_in = s.get("transition_in", "cross_dissolve") if s.get("transition_in") in TRANSITIONS else "cross_dissolve"
            self.edl.sections[-1].key_message = cut_words(s.get("key_message", ""), 40)
            self.edl.sections[-1].shots_hint = int(s.get("shots") or 0)
            self.edl.sections[-1].caption_style = s.get("caption_style") if s.get("caption_style") in CAPTION_STYLES else ""
        self.storyboard = {"title": sb["title"], "concept": sb["concept"], "hook": self.hook, "ending": self.ending,
                           "sections": [{"name": s.name, "goal": s.goal, "target_seconds": s.target_seconds, "music": s.music,
                                         "visual_style": getattr(s, "visual_style", ""), "asset_group": getattr(s, "asset_group", "any"),
                                         "transition_in": getattr(s, "transition_in", "cut"), "key_message": getattr(s, "key_message", ""),
                                         "shots": getattr(s, "shots_hint", 0), "caption_style": getattr(s, "caption_style", "")} for s in self.edl.sections]}
        (self.run_dir / "storyboard.json").write_text(json.dumps(self.storyboard, ensure_ascii=False, indent=1))
        self.step("storyboard", {"seconds": self.seconds}, self.storyboard)
        self.emit_timeline()

    def shot_schema(self, group="any"):
        ids = [k for k in self.edl.catalog if group == "any" or self.guardrails != "full" or k.startswith(group + "/")] or list(self.edl.catalog)
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
        frag = vocab.schema_fragments(self.mode, effect_params=False)
        picture["properties"].update(frag["picture"])
        card["properties"].update(frag["card"])
        return {"type": "object", "properties": {"shots": {"type": "array", "minItems": 2, "maxItems": 8, "items": {"anyOf": [picture, card]}}}, "required": ["shots"]}

    def _build_section(self, k, sec, schema):
        prev = self.edl.sections[k - 1].name if k else "(начало ролика)"
        nxt = self.edl.sections[k + 1].name if k + 1 < len(self.edl.sections) else "(конец ролика)"
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"ЗАДАЧА:\n{self.task}\n\nМАТЕРИАЛЫ:\n{self.briefs_text}\n\nРАСКАДРОВКА:\n{json.dumps(self.storyboard, ensure_ascii=False)}\n\n"
                                            f"КАРТИНКИ (id | что | настроение):\n{self.assets_text}\n\n"
                                            + (f"СЛОВАРЬ ПРИЁМОВ (можно использовать любые, подбирай под настроение секции):\n{vocab.prompt_section('rich', with_params=False)}\n"
                                               "Для картинок можно задавать grade (цвет числами), camera (движение камеры с easing), effects как {id, amount 0..100 — сила в процентах}; "
                                               "для карточек text_anim.\n\n" if self.mode == "rich" else "")},
                # second message: everything that differs per section, so the shared first message stays cache-reusable
                {"role": "user", "content": (ideas_mod.ideas_prompt(n=8, seed=self.seed + k) + "\n\n" if self.ideas_on else "")
                                            + f"Сейчас собери ТОЛЬКО секцию «{sec.name}» (до неё: {prev}, после: {nxt}). Цель: {sec.goal}. "
                                            f"Визуальный стиль: {getattr(sec, 'visual_style', '')}. Главная мысль, которая должна прозвучать в подписи или карточке: «{getattr(sec, 'key_message', '')}». Длительность секции около {sec.target_seconds} с"
                                            + (f", примерно {sec.shots_hint} кадров по ~{round(sec.target_seconds / max(1, sec.shots_hint), 1)} с" if getattr(sec, "shots_hint", 0) else "")
                                            + (f". Стиль подписей секции: {sec.caption_style}" if getattr(sec, "caption_style", "") else "") + ".\n"
                                            + (f"Это начало ролика: ПЕРВЫЙ кадр — крючок из раскадровки: картинка {self.hook.get('asset')} и подпись «{self.hook.get('caption')}» "
                                               f"(короткий, 0.8-1.5 с, сразу в действие, не заставка).\n" if k == 0 and getattr(self, "hook", None) else "")
                                            + (f"Это финал ролика: {self.ending}\n" if k + 1 == len(self.edl.sections) and getattr(self, "ending", "") else "")
                                            + "Кадр kind=picture: asset (id из списка), seconds 0.8-6, motion и look (меняй их от кадра к кадру под настроение секции), caption (до 60 символов, может быть пустой) со стилем и позицией, effects (0-2).\n"
                                            "Кадр kind=card: полноэкранная карточка, asset=\"\", card_title (до 28 символов), card_subtitle, card_style, seconds 1.5-3.\n"
                                            "transition_out — переход в следующий кадр (cut — склейка). Подбирай картинки по смыслу описаний, не повторяй одну картинку. "
                                            + ("Это интро или финал: бери по одной картинке из разных групп. " if getattr(sec, "asset_group", "any") == "any" else
                                               f"Бери картинки только из группы {sec.asset_group}. " if self.guardrails == "full" else
                                               f"Подсказка: для этой секции подходят картинки группы {sec.asset_group}, но можешь брать любые, если так сильнее. ")
                                            + "Все подписи и заголовки — только по-русски, без эмодзи."
                                            + ("\n\n" + THINK_BUILD if self.think else "")}]
        out = self.ask_json(f"build:{sec.name}", msgs, self.shot_schema(getattr(sec, "asset_group", "any")), max_tokens=2500, temperature=0.6, think=self.think_for("build"))
        return k, out

    def snap_to_beats(self, when):
        if not self.edl.music_library:
            return
        try:
            report = music_mod.snap_edl(self.edl)
        except Exception as e:
            self.ev.emit("warning", message=f"подгонка под бит не удалась: {str(e)[:160]}")
            return
        if report:
            self.step("beat_snap", {"after": when}, {"sections": {k: (str(v)[:160]) for k, v in report.items()}})
            self.changed()

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
            full = self.guardrails == "full"
            # 1) fit the section to its target length (full only; otherwise the polish notes report it)
            total = sum(s.seconds for s in shots)
            if full and total and abs(total - sec.target_seconds) / sec.target_seconds > 0.2:
                f = sec.target_seconds / total
                for s in shots:
                    lim = LIMITS["card_seconds"] if s.kind == "card" else LIMITS["picture_seconds"]
                    s.seconds = round(min(lim[1], max(lim[0], s.seconds * f)), 2)
                warnings.append(f"section {sec.name}: {round(total, 1)}s scaled toward target {sec.target_seconds}s")
            # 2) reading time floor for captions and cards wins over the target
            for s in shots:
                need = self.reading_seconds(s)
                if not full:
                    need = READ_FLOOR if need else 0  # only a hard floor; the rest is a warning in polish
                if need > s.seconds:
                    if not full:
                        warnings.append(f"{s.label()}: {s.seconds}s is too short to see the text, raised to {need}s")
                    s.seconds = need
            # 3) still far too long: drop shots from the end (keep at least 2)
            while full and len(shots) > 2 and sum(s.seconds for s in shots) > sec.target_seconds * 1.4:
                gone = shots.pop()
                warnings.append(f"dropped {gone.label()} to keep the section near {sec.target_seconds}s")
            # 2b) the section's key message must be on screen (card at the start; for the last section at the end)
            key = getattr(sec, "key_message", "")
            if full and key and not self.key_on_screen(key, shots):
                last = k + 1 == len(self.edl.sections)
                card = self.edl.make_shot({"card_title": key, "card_style": "final" if last else "minimal", "seconds": 2.5}, sec.name, warnings)
                if card:
                    card.seconds = max(card.seconds, self.reading_seconds(card))
                    shots.insert(len(shots) if last else (1 if k == 0 and shots else 0), card)  # never shot 1 of the video
                    warnings.append(f"key message «{key}» was missing: added a card")
            # 4) repeated pictures inside the section
            seen = set()
            for s in list(shots):
                if self.guardrails != "off" and s.kind == "picture" and s.asset in seen and len(shots) > 2:
                    shots.remove(s)
                    warnings.append(f"removed repeated picture {s.asset}")
                seen.add(s.asset)
            # 5) not every cut is a transition: keep at most 2 inside the section
            inner = [s for s in shots[:-1] if s.transition_out != "cut"]
            if full:
                for s in inner[2:]:
                    s.transition_out = "cut"
                if len(inner) > 2:
                    warnings.append(f"kept 2 of {len(inner)} transitions inside the section")
            if full and shots[-1].transition_out != "cut" and k + 1 < len(self.edl.sections):
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
        self.limit_heavy_effects()

    def limit_heavy_effects(self):
        """Render-cost budget, not taste: heavy effects (glint, rays, glow...) on at most MAX_HEAVY_SHOTS shots."""
        heavy_shots, dropped = 0, []
        for i, s in enumerate(self.edl.shots, 1):
            ids = [e["id"] if isinstance(e, dict) else e for e in s.effects]
            if not any(x in vocab.HEAVY_EFFECTS for x in ids):
                continue
            heavy_shots += 1
            if heavy_shots > vocab.MAX_HEAVY_SHOTS:
                s.effects = [e for e in s.effects if (e["id"] if isinstance(e, dict) else e) not in vocab.HEAVY_EFFECTS]
                dropped.append(i)
        if dropped:
            self.step("render_budget", {"max_heavy_shots": vocab.MAX_HEAVY_SHOTS},
                      {"warnings": [f"тяжёлые эффекты сняты с кадров {dropped}: экспорт был бы в разы дольше"]})
            self.changed()

    @staticmethod
    def reading_seconds(shot):
        """How long the shot's text needs on screen (about 14 characters per second, 1.2-6 s); 0 without text."""
        text = (shot.caption.text if shot.caption else "") + (" " + shot.title + " " + shot.subtitle if shot.kind == "card" else "")
        return round(min(6.0, max(1.2, len(text.strip()) / 14)), 1) if text.strip() else 0

    def key_on_screen(self, key, shots):
        return any(text_match(self.expected_text(x) + " " + (x.subtitle if x.kind == "card" else ""), key) >= 0.6 for x in shots)

    def notes(self):
        """light/off guardrails: what the full harness would have fixed silently, as information for the model."""
        if self.guardrails == "full":
            return []
        out, total = [], self.edl.total()
        if abs(total - self.seconds) / self.seconds > 0.15:
            out.append(f"ролик сейчас {total} с, в задании около {int(self.seconds)} с")
        for sec in self.edl.sections:
            shots = [self.edl.shots[i] for i in self.edl.section_shots(sec.name)]
            if not shots:
                out.append(f"секция {sec.name} пустая")
                continue
            got = round(sum(s.seconds for s in shots), 1)
            if abs(got - sec.target_seconds) / max(1.0, sec.target_seconds) > 0.25:
                out.append(f"секция {sec.name}: {got} с, в раскадровке {sec.target_seconds} с")
            key = getattr(sec, "key_message", "")
            if key and not self.key_on_screen(key, shots):
                out.append(f"секция {sec.name}: главная мысль «{key}» не появляется в кадре (ни в подписи, ни в карточке)")
        if self.guardrails == "light":
            for i, s in enumerate(self.edl.shots, 1):
                need = self.reading_seconds(s)
                if need > s.seconds + 0.05:
                    out.append(f"кадр {i}: текст «{self.expected_text(s)[:40]}» на экране {s.seconds} с, для чтения нужно ~{need} с")
        seen = {}
        for i, s in enumerate(self.edl.shots, 1):
            if s.kind == "picture":
                seen.setdefault(s.asset, []).append(i)
        out += [f"картинка {a} стоит в кадрах {v}" for a, v in seen.items() if len(v) > 1]
        return out

    def notes_text(self):
        n = self.notes()
        return ("ЗАМЕЧАНИЯ ОБВЯЗКИ (только информация, решаешь ты; исправляй, если согласен):\n- " + "\n- ".join(n) +
                "\n(длительность меняют retime_section — вся секция — или update_shot с seconds)\n\n") if n else ""

    def action_schema(self, ops=None):
        """anyOf with one exact object per operation: the grammar only allows that op's own fields; sections and shots are enums."""
        n = max(1, len(self.edl.shots))
        shot = {"type": "integer", "minimum": 1, "maximum": n}
        section = {"type": "string", "enum": [x.name for x in self.edl.sections]}
        variants = []
        for t in polish_tools(self.mode, music=list(self.edl.music_library) or None):
            f = t["function"]
            if f["name"] == "done" or (ops and f["name"] not in ops):
                continue
            props = {"op": {"type": "string", "enum": [f["name"]]}}
            for k, v in f["parameters"]["properties"].items():
                props[k] = shot if k in ("shot",) else section if k == "section" else ({"type": "integer", "minimum": 1, "maximum": n} if k == "to" else
                           {"type": "string", "enum": list(self.edl.catalog)} if k == "asset" else v)
            variants.append({"type": "object", "properties": props, "required": ["op"] + f["parameters"]["required"], "additionalProperties": False})
        return {"type": "object", "properties": {
            "thoughts": {"type": "string", "maxLength": 200, "description": "одно-два предложения: что улучшаешь и зачем"},
            "actions": {"type": "array", "maxItems": 6, "items": {"anyOf": variants}},
            "done": {"type": "boolean"}}, "required": ["thoughts", "actions", "done"]}

    def action_rounds(self, phase, intro, handler, max_rounds, ops=None):
        """The model answers with a JSON list of edit actions; the harness applies them and reports back."""
        schema = self.action_schema(ops)
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": intro}]
        for rnd in range(max_rounds):
            try:
                out = self.ask_json(phase, msgs, schema, max_tokens=2000, temperature=0.4)
            except LLMError as e:
                self.ev.emit("warning", message=str(e)[:300])
                return
            msgs.append({"role": "assistant", "content": json.dumps(out, ensure_ascii=False)})
            results = self.apply_actions(phase, rnd, out, handler)
            if out.get("done") or not out.get("actions"):
                return
            msgs.append({"role": "user", "content": f"Результаты: {json.dumps(results, ensure_ascii=False)[:2500]}\n\n"
                                                    f"Монтажный лист сейчас: {json.dumps(self.edl.summary(), ensure_ascii=False)[:6000]}\n\n" + self.notes_text() +
                                                    "Если нужно ещё что-то — следующие действия, иначе done=true и пустой список."})

    def apply_actions(self, phase, rnd, out, handler):
        """Shot numbers in one batch refer to the list the model saw: after a delete or move earlier in the batch
        they are mapped to the same shot's current position. Exact repeats of an action are skipped."""
        results, seen = [], set()
        before = list(self.edl.shots)
        for k, act in enumerate(out.get("actions", [])):
            op = act.pop("op", "")
            args = {key: v for key, v in act.items() if v not in (None, "") or key == "caption"}
            cid = f"{phase}-{rnd}-{k}"
            sig = json.dumps([op, args], sort_keys=True, ensure_ascii=False)
            res = None
            if sig in seen:
                res = {"error": "same action twice in one answer, skipped"}
            seen.add(sig)
            if res is None and isinstance(args.get("shot"), int) and 1 <= args["shot"] <= len(before):
                target = before[args["shot"] - 1]
                now = next((i for i, s in enumerate(self.edl.shots) if s is target), None)
                if now is None:
                    res = {"error": f"shot {args['shot']} was already deleted in this answer"}
                elif now + 1 != args["shot"]:
                    args = {**args, "shot": now + 1, "listed_as": args["shot"]}
            if res is None and op == "move_shot" and isinstance(args.get("to"), int) and 1 <= args["to"] <= len(before):
                anchor = before[args["to"] - 1]  # "to" also refers to the list the model saw
                pos = next((i for i, s in enumerate(self.edl.shots) if s is anchor), None)
                if pos is not None:
                    args = {**args, "to": pos + 1}
            self.ev.emit("tool_call", id=cid, name=op, args=args)
            args.pop("listed_as", None)
            t = time.time()
            res = res or handler.dispatch(op, args)
            ok = not (isinstance(res, dict) and "error" in res)
            self.counters["tool_calls"] += 1
            self.counters["errors"] += 0 if ok else 1
            self.ev.emit("tool_result", id=cid, name=op, ok=ok, result=res, seconds=round(time.time() - t, 3))
            results.append({"op": op, **(res if isinstance(res, dict) else {"result": res})})
        return results

    def polish(self):
        self._polish()
        self.limit_heavy_effects()
        self.snap_to_beats("polish")

    def _polish(self):
        self.ev.emit("phase", name="polish", note="доводка: эффекты, звуки, порядок, музыка")
        handler = PolishTools(self.edl, self.changed, guardrails=self.guardrails)
        if self.guardrails == "full":
            ask = ("Доведи его: добавь 3-6 звуковых эффектов на сильные моменты (add_sfx), поправь эффекты и движения, чтобы было разнообразно, "
                   "проверь, что подписи короткие, по-русски и по делу, что нет повторов, что финал сильный. ")
        else:
            ask = (f"РАСКАДРОВКА:\n{json.dumps(self.storyboard, ensure_ascii=False)}\n\n{self.notes_text()}"
                   "Доведи монтаж так, как считаешь лучшим: длительности, порядок, подписи, движения, эффекты, переходы, звуки (add_sfx), музыка. "
                   "Обвязка больше ничего не подгоняет сама: длительности секций, главные мысли в кадре и время на чтение — на тебе. ")
        intro = (f"ЗАДАЧА:\n{self.task}\n\nМонтаж собран. Монтажный лист:\n{json.dumps(self.edl.summary(), ensure_ascii=False)}\n\n" + ask +
                 "Верни список действий (op = имя операции и её поля). Делай только нужные правки; когда всё готово — done=true.")
        self.action_rounds("polish", intro, handler, max(1, min(2, self.max_polish_turns // 3)))  # measured: rounds 3+ rarely help

    def director(self, rounds=2):
        """The vision model watches a contact sheet of the whole edit (one numbered frame per shot) next to the
        storyboard and writes a critique with concrete problems (look); then, without the picture, it turns its own
        critique into polish actions (act). Splitting looking from editing keeps the small model from looping on
        one operation. At most `rounds` rounds."""
        handler = PolishTools(self.edl, self.changed, guardrails=self.guardrails)
        last = None
        for rnd in range(rounds):
            self.ev.emit("phase", name="director", note=f"режиссёр смотрит весь монтаж, раунд {rnd + 1}")
            compiled = compile_edl(self.edl, on_progress=lambda m: None)
            try:
                frames = [compiled.frame_png(a + (b - a) * 0.55) for a, b in compiled.times]
            finally:
                compiled.close()
            labels = [s.section + " · " + (s.title if s.kind == "card" else s.asset.split("/")[-1]) for s in self.edl.shots]
            # at most 12 bigger tiles per sheet: 21 tiles of 216 px made the 4B mistake photos for black frames
            sheets = [contact_sheet(frames[j:j + 12], labels[j:j + 12], tile_w=300, start=j + 1) for j in range(0, len(frames), 12)]
            sheet = sheets[0]
            for m, sh in enumerate(sheets, 1):
                path = self.run_dir / "frames" / f"director-r{rnd + 1}{'' if len(sheets) == 1 else '-' + str(m)}.jpg"
                path.write_bytes(sh)
                self.ev.emit("frame", path=self.ev.rel(path), clip=None, seconds=None, verdict=None)
            n = len(self.edl.shots)
            # the look step gets only what a viewer gets: the pictures and the words; no parameters, no harness notes
            flags = {i: frame_flags(png) for i, png in enumerate(frames, 1)}
            flagged = "".join(f"кадр {i}: {f}; " for i, f in flags.items() if f)
            listing = "\n".join(f"{i} | {s.section} | {s.seconds} с | {self.expected_text(s)[:60]} | "
                                + ("карточка" if s.kind == "card" else self.edl.catalog.get(s.asset, {}).get("what", "")[:70])
                                for i, s in enumerate(self.edl.shots, 1))
            look_schema = {"type": "object", "properties": {
                "critique": {"type": "string", "maxLength": 600, "description": "2-4 предложения: что в монтаже плохо и что хорошо"},
                "problems": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
                    "shot": {"type": "integer", "minimum": 1, "maximum": n}, "problem": {"type": "string", "maxLength": 200}, "fix": {"type": "string", "maxLength": 200}},
                    "required": ["shot", "problem", "fix"], "additionalProperties": False}},
                "verdict": {"type": "string", "enum": ["готово", "нужны правки"]}}, "required": ["critique", "problems", "verdict"]}
            text = ("Ты режиссёр этого ролика. На картинке — контактный лист монтажа: по одному кадру из каждого плана по порядку "
                    "(слева направо, сверху вниз; если листов несколько — они идут подряд), красная цифра = номер кадра в монтажном листе, внизу секция и картинка. Проверь, подходит ли картинка к подписи по смыслу (колонка «что на картинке»).\n\n"
                    f"ЗАДАЧА:\n{self.task}\n\nРАСКАДРОВКА:\n{json.dumps(self.storyboard, ensure_ascii=False)}\n\n"
                    f"КАДРЫ (номер | секция | секунды | текст | что на картинке):\n{listing}\n\n"
                    + (f"Замер яркости (без модели): {flagged}\n\n" if flagged else "")
                    + (f"Прошлый раунд: ты написал «{last['critique']}», правки: {json.dumps(last['results'], ensure_ascii=False)[:1000]}. "
                       "Это новый лист после правок: оцени заново, не повторяй старую критику, если это уже исправлено.\n\n" if last else "")
                    + "Посмотри на ролик целиком: держит ли он задачу и раскадровку, понятна ли история, нет ли однообразия "
                    "(одни и те же картинки, цвета, движения, подписи), сильные ли начало и финал, видна ли главная мысль каждой секции, "
                    "не мешают ли эффекты, не слишком ли тёмные или пустые кадры. critique — 2-4 предложения по-русски. "
                    "Суди по тому, что видно на картинках. problems — до 6 конкретных проблем: номер кадра, что не так, как исправить. "
                    "verdict — «готово», если править нечего.")
            msgs = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": [LLM.image_part(sh, max_side=1600) for sh in sheets] + [{"type": "text", "text": text}]}]
            try:
                look = self.ask_json("director", msgs, look_schema, max_tokens=1200, temperature=0.3)
            except LLMError as e:
                self.ev.emit("warning", message=str(e)[:300])
                return
            problems = look.get("problems") or []
            self.step("director_critique", {"round": rnd + 1, "shots": n},
                      {"critique": look.get("critique", ""), "problems": problems, "verdict": look.get("verdict")})
            if look.get("verdict") == "готово" or not problems:
                return
            schema = self.action_schema()
            schema["properties"]["actions"]["maxItems"] = 8
            listing = "\n".join(f"- кадр {x['shot']}: {x['problem']} → {x['fix']}" for x in problems)
            act_text = (f"ЗАДАЧА:\n{self.task}\n\nМОНТАЖНЫЙ ЛИСТ:\n{json.dumps(self.edl.summary(), ensure_ascii=False)[:6000]}\n\n{self.notes_text()}"
                        f"Ты посмотрел весь ролик как режиссёр. Критика: {look.get('critique', '')}\nПроблемы:\n{listing}\n\n"
                        "Преврати каждую проблему в правку (op = имя операции и её поля; номера кадров — из монтажного листа). "
                        "Одна проблема — одна-две правки, без повторов одной и той же операции. Потом done=true.")
            try:
                out = self.ask_json("director", [{"role": "system", "content": SYSTEM}, {"role": "user", "content": act_text}],
                                    schema, max_tokens=2000, temperature=0.3, think=self.think_for("director"))
            except LLMError as e:
                self.ev.emit("warning", message=str(e)[:300])
                return
            results = self.apply_actions("director", rnd, out, handler)
            last = {"critique": look.get("critique", "")[:400], "results": results}

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
                    # two moments per shot: animated effects (blooms, glitches) can hide the text at one of them
                    for tag, f in (("a", 0.3), ("b", 0.75)):
                        png = compiled.frame_png(a + (b - a) * f)
                        p = self.run_dir / "frames" / f"shot{i + 1:02d}-r{rnd + 1}{tag}.png"
                        p.write_bytes(png)
                        frames.append((i, p))
                    self._thumbs[i] = self.ev.rel(p)
                self.emit_timeline()
            finally:
                compiled.close()
            schema = {"type": "object", "properties": {"main_text": {"type": "string", "maxLength": 160}, "seen": {"type": "string", "maxLength": 120}},
                      "required": ["main_text", "seen"]}
            q = ("Кадр вертикального ролика. main_text: перепиши дословно самый крупный наложенный текст (подпись или заголовок), "
                 "если его нельзя разобрать — пустая строка. seen: что на картинке, до 10 слов, по-русски.")

            def judge(item):
                i, p = item
                data = p.read_bytes()
                key = (hashlib.sha1(data).hexdigest(), self.expected_text(self.edl.shots[i]))
                if key in self._verdicts:  # unchanged frame and text: the earlier verdict stands
                    return i, self._verdicts[key]
                try:
                    v = self.llm.vision(data, q, schema, max_side=640)  # same reading as 960 px, ~26% faster
                except Exception as e:  # one failed vision call must not cost the whole video
                    self.ev.emit("warning", message=f"проверка кадра {i + 1} не удалась: {str(e)[:160]}")
                    return i, {"text_readable": True, "seen": "", "error": str(e)[:160]}
                expected = self.expected_text(self.edl.shots[i])
                score = text_match(v.get("main_text", ""), expected)
                verdict = {"text_readable": score >= 0.6, "seen": v.get("seen", ""), "read": v.get("main_text", "")[:120], "match": round(score, 2)}
                self.ev.emit("frame", path=self.ev.rel(p), clip=i + 1, seconds=None, verdict=verdict)
                self._verdicts[key] = verdict
                return i, verdict

            with ThreadPoolExecutor(max_workers=self.slots) as pool:
                per_frame = list(pool.map(judge, frames))
            worst = {}  # a shot passes only if both of its moments are readable
            for i, v in per_frame:
                if i not in worst or (worst[i].get("text_readable", True) and not v.get("text_readable", True)):
                    worst[i] = v
            verdicts = sorted(worst.items())
            bad = [(i, v) for i, v in verdicts if not v.get("text_readable", True)]
            if not bad:
                self.step("review", {"round": rnd + 1}, {"checked": len(verdicts), "unreadable": 0})
                return
            self.step("review", {"round": rnd + 1}, {"checked": len(verdicts), "unreadable": [i + 1 for i, _ in bad],
                                                     "error": f"текст плохо читается на кадрах {[i + 1 for i, _ in bad]}"}, ok=False)
            handler = PolishTools(self.edl, self.changed, guardrails=self.guardrails)
            listing = "\n".join(f"кадр {i + 1}: {self.edl.shots[i].label()} — нужный текст «{self.expected_text(self.edl.shots[i])}», "
                                f"стиль {self.edl.shots[i].caption.style if self.edl.shots[i].caption else self.edl.shots[i].card_style}, эффекты {self.edl.shots[i].effects}, "
                                f"look {self.edl.shots[i].look}; зрение прочитало «{v.get('read', '')}»" for i, v in bad)
            intro = (f"Проверка зрением: на этих кадрах текст читается плохо:\n{listing}\n\nИсправь каждый: убери мешающие эффекты (effects=[]), "
                     "смени стиль/позицию подписи или look на более спокойный, сократи текст. Верни действия, потом done=true.")
            self.action_rounds("review", intro, handler, 2, ops=["update_shot"])  # readability fixes only

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
        self.ev.emit("run_start", task=self.task, model=self.llm.model_name(), tools=[t["function"]["name"] for t in POLISH_TOOLS], vocab=self.mode, fetch=self.fetch,
                     assets_dir=str(self.assets_dir), briefs=[str(b) for b in self.briefs], seconds=self.seconds, slots=self.slots,
                     guardrails=self.guardrails, think=self.think, think_budget=self.think_budget, planner=self.planner, director=self.director_on,
                     music_web=self.music_web, ideas=self.ideas_on, surprise=self.surprise, seed=self.seed)
        ok, reason, out = False, "", None
        try:
            steps = []
            if self.surprise:  # the model invents the video before anything is searched
                self.briefs_text = "\n\n".join(f"### {b.stem}\n{brief_summary(b)}" for b in self.briefs if b.exists())
                steps += [("swap", lambda: self.use_model("planner", "concept")), ("concept", self.concept_phase)]
            steps += [("swap", lambda: self.use_model("vision", "explore")), ("explore", self.explore),
                     ("swap", lambda: self.use_model("planner", "plan")), ("plan", self.plan), ("build", self.build), ("beat_snap", lambda: self.snap_to_beats("build")), ("polish", self.polish),
                     ("swap", lambda: self.use_model("vision", "director" if self.director_on else "review"))]
            steps += [("director", self.director)] if self.director_on else []
            steps += [("review", self.review), ("export", self.export)]
            for name, fn in steps:  # model swaps only happen at these phase boundaries: 4B (vision) -> planner -> 4B
                t = time.time()
                out = fn()
                self.phase_seconds[name] = round(self.phase_seconds.get(name, 0) + time.time() - t, 1)
            ok, reason = True, "exported"
        except KeyboardInterrupt:
            reason = "interrupted"
        except Exception as e:
            reason = f"{type(e).__name__}: {e}"
            self.ev.emit("error", message=reason[:500], where=traceback.format_exc()[-800:])
        summary = {"ok": ok, "reason": reason, "output": str(out) if out else None, "seconds": getattr(self, "edl", None) and self.edl.total(),
                   "wall_seconds": round(time.time() - self.t0, 1), "llm": dict(self.llm.totals), **self.counters, "swaps": self.swaps,
                   "phase_seconds": self.phase_seconds, "concept": self.concept,
                   "edl": self.edl.to_dict() if hasattr(self, "edl") else None}
        (self.run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
        self.ev.emit("run_end", ok=ok, reason=reason, summary={k: v for k, v in summary.items() if k != "edl"})
        return summary
