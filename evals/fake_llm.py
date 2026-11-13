"""Scripted fake LLM for --dry evaluation runs (no GPU).

Same idea as scripts/dry_run.py, but it answers any task: the storyboard is built from the schema enums
(asset groups, music, transitions), captions come from the task's must_mention phrases plus filler, and
the "vision" model reads a caption back correctly with a fixed probability. The seed makes repeats differ,
so dry runs give non-zero std and exercise every metric of scripts/eval_report.py.
"""
import json
import random
import re

FILLER = ["Сервер пуст", "Кто здесь?", "Растим монстра", "Эволюция", "Новый уровень", "Скоро в Roblox", "Заходи", "Это только начало"]


class FakeLLM:
    def __init__(self, seed=7, phrases=(), read_ok=0.75):
        self.rng = random.Random(seed)
        self.phrases = [p if isinstance(p, str) else p[0] for p in phrases] or FILLER[:3]
        self.read_ok = read_ok
        self.said = []
        self.totals = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0}

    def health(self):
        return True

    def model_name(self):
        return "fake-llm"

    def _text(self):
        t = self.rng.choice(self.phrases) if self.rng.random() < 0.5 else self.rng.choice(FILLER)
        self.said.append(t)
        return t

    def _r(self, content, prompt_chars):
        pt, ct = prompt_chars // 3, len(content) // 3
        self.totals["requests"] += 1
        self.totals["prompt_tokens"] += pt
        self.totals["completion_tokens"] += ct
        self.totals["seconds"] += 0.05
        return {"message": {"role": "assistant", "content": content}, "usage": {"prompt_tokens": pt, "completion_tokens": ct},
                "seconds": 0.05, "tokens_per_second": 42.0, "prompt_per_second": 900.0}

    @staticmethod
    def _enum(schema, *path):
        node = schema
        for k in path:
            node = node[k]
        return node.get("enum", [])

    @staticmethod
    def _choices(node):
        """Enum values of a schema node, also inside anyOf/oneOf or an object's id/name property (rich vocabulary)."""
        if "enum" in node:
            return list(node["enum"])
        for k in ("anyOf", "oneOf"):
            if k in node:
                return [v for sub in node[k] for v in FakeLLM._choices(sub)]
        props = node.get("properties", {})
        for k in ("id", "name", "effect"):
            if k in props:
                return [{k: v} for v in FakeLLM._choices(props[k])]
        return []

    def json(self, messages, schema, max_tokens=0, temperature=0):
        props = schema["properties"]
        rng = self.rng
        if "sections" in props:
            item = props["sections"]["items"]["properties"]
            groups = [g for g in item["asset_group"]["enum"] if g != "any"] or ["any"]
            n = rng.randint(3, 5)
            secs = []
            for k in range(n):
                group = "any" if k in (0, n - 1) else groups[(k - 1) % len(groups)]
                secs.append({"name": f"s{k + 1}_{group.replace('-', '_')}", "goal": "показать", "target_seconds": rng.choice([6, 8, 10, 12]),
                             "music": rng.choice(item["music"]["enum"]), "music_db": -10, "visual_style": "тест", "asset_group": group,
                             "transition_in": rng.choice(item["transition_in"]["enum"]),
                             "key_message": self.phrases[k % len(self.phrases)] if rng.random() < 0.7 else ""})
            for sec in secs:
                sec.update(shots=rng.randint(3, 6), caption_style=rng.choice(item["caption_style"]["enum"]) if "caption_style" in item else "subtitle")
            hook_ids = props.get("hook", {}).get("properties", {}).get("asset", {}).get("enum") or [""]
            out = {"title": "Dry eval", "concept": "тест", "sections": secs, "hook": {"asset": rng.choice(hook_ids), "caption": "Стоп. Смотри.", "why": "тест"},
                   "ending": "обрыв на пике"}
        elif "shots" in props:
            variants = props["shots"]["items"]["anyOf"]
            pic = next(v for v in variants if "asset" in v["properties"])["properties"]
            card = next(v for v in variants if "card_title" in v["properties"])["properties"]
            fx = self._choices(pic.get("effects", {}).get("items", {}))  # strict: enum of names; rich: maybe objects
            shots = []
            if rng.random() < 0.4:
                shots.append({"kind": "card", "card_title": self._text(), "card_subtitle": "", "card_style": rng.choice(card["card_style"]["enum"]),
                              "seconds": 2, "transition_out": "cut"})
            for _ in range(rng.randint(2, 4)):
                shots.append({"kind": "picture", "asset": rng.choice(pic["asset"]["enum"]), "seconds": rng.choice([0.8, 1.5, 2, 3, 4]),
                              "motion": rng.choice(pic["motion"]["enum"]), "look": rng.choice(pic["look"]["enum"]),
                              "caption": self._text() if rng.random() < 0.7 else "", "caption_style": rng.choice(pic["caption_style"]["enum"]),
                              "caption_position": rng.choice(pic["caption_position"]["enum"]),
                              "effects": rng.sample(fx, min(len(fx), rng.randint(0, 2))),
                              "transition_out": rng.choice(["cut", "cut", rng.choice(pic["transition_out"]["enum"])])})
            out = {"shots": shots}
        elif "actions" in props:
            text = json.dumps(messages[-1]["content"], ensure_ascii=False)
            n = max(1, int((re.findall(r'"shot": (\d+)', text) or ["3"])[-1]))
            out = {"thoughts": "fix", "done": True, "actions": [
                {"op": "add_sfx", "kind": rng.choice(["whoosh", "boom", "glitch", "rise"]), "shot": rng.randint(1, n), "at": "start"},
                {"op": "add_sfx", "kind": "notify", "shot": rng.randint(1, n), "at": "end"},
                {"op": "update_shot", "shot": rng.randint(1, n), "motion": "zoom_out"}]}
            if "читается плохо" in text:
                bad = [int(x) for x in re.findall(r"кадр (\d+):", text)] or [1]
                out["actions"] = [{"op": "update_shot", "shot": b, "effects": []} for b in bad]
        else:
            out = {}
        prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
        return out, self._r(json.dumps(out, ensure_ascii=False), prompt_chars)

    def vision(self, png, question, schema, max_side=960):
        self.totals["requests"] += 1
        props = schema.get("properties", {})
        if "what" in props:  # catalog description
            return {"what": "картинка (описание из сухого прогона)", "mood": "тест"}
        if "main_text" in props:
            ok = self.rng.random() < self.read_ok and self.said
            return {"main_text": self.rng.choice(self.said) if ok else "", "seen": "кадр с подписью"}
        return {k: "" for k in props}
