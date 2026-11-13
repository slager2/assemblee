"""OpenAI-compatible client for llama-server: chat with tools, JSON-schema output, vision, server stats."""
import base64
import io
import json
import threading
import time
import urllib.error
import urllib.request

from PIL import Image

from .config import LLM_URL


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, base=LLM_URL, timeout=900):
        self.base, self.timeout = base.rstrip("/"), timeout
        self.totals = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0}
        self._lock = threading.Lock()

    def _post(self, path, body):
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise LLMError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:400]}") from None
        except urllib.error.URLError as e:
            raise LLMError(f"server unreachable: {e.reason}") from None

    def health(self):
        try:
            with urllib.request.urlopen(self.base + "/health", timeout=5) as r:
                return json.load(r).get("status") == "ok"
        except Exception:
            return False

    def count_tokens(self, text):
        try:
            return len(self._post("/tokenize", {"content": text}).get("tokens", []))
        except LLMError:
            return len(text) // 3

    def model_name(self):
        try:
            with urllib.request.urlopen(self.base + "/v1/models", timeout=5) as r:
                d = json.load(r)
            return d["data"][0]["id"]
        except Exception:
            return "unknown"

    def chat(self, messages, tools=None, max_tokens=2048, temperature=0.3, response_format=None, tool_choice=None,
             think=False, think_budget=1024):
        """think=True: Qwen3.5 thinks first (chat_template_kwargs.enable_thinking, per request), at most think_budget
        tokens (server-side reasoning budget, then it is forced to close the think block). The reasoning is
        returned separately (reasoning_format=deepseek -> message.reasoning_content), never inside content;
        max_tokens is for the answer, the budget is added on top."""
        body = {"model": "m", "messages": messages, "max_tokens": max_tokens + (think_budget if think else 0), "temperature": temperature,
                "top_p": 0.9, "cache_prompt": True, "reasoning_format": "deepseek",
                "chat_template_kwargs": {"enable_thinking": bool(think)}}
        if think:
            body["reasoning_budget_tokens"] = int(think_budget)
            body["reasoning_budget_message"] = " Хватит думать, пишу ответ."
        if tools:
            body["tools"] = tools
            if tool_choice:
                body["tool_choice"] = tool_choice
        if response_format:
            body["response_format"] = response_format
        t0 = time.time()
        r = self._post("/v1/chat/completions", body)
        dt = time.time() - t0
        usage = r.get("usage", {})
        timings = r.get("timings", {})
        with self._lock:  # requests run from parallel threads
            self.totals["requests"] += 1
            self.totals["prompt_tokens"] += usage.get("prompt_tokens", 0)
            self.totals["completion_tokens"] += usage.get("completion_tokens", 0)
            self.totals["seconds"] += dt
        msg = r["choices"][0]["message"]
        content = msg.get("content") or ""
        if "</think>" in content:  # a template/parser that left the thoughts in content
            head, _, content = content.partition("</think>")
            msg["reasoning_content"] = (msg.get("reasoning_content") or "") + head.replace("<think>", "").strip()
            msg["content"] = content.strip()
        reasoning = msg.get("reasoning_content") or ""
        reasoning_tokens = self.count_tokens(reasoning) if reasoning else 0
        with self._lock:
            self.totals["reasoning_tokens"] = self.totals.get("reasoning_tokens", 0) + reasoning_tokens
        return {"message": msg, "reasoning": reasoning, "reasoning_tokens": reasoning_tokens, "finish_reason": r["choices"][0].get("finish_reason"), "usage": usage, "seconds": round(dt, 2),
                "tokens_per_second": round(timings.get("predicted_per_second") or (usage.get("completion_tokens", 0) / dt if dt else 0), 1),
                "prompt_per_second": round(timings.get("prompt_per_second", 0) or 0, 1)}

    def json(self, messages, schema, max_tokens=2048, temperature=0.3, think=False, think_budget=1024):
        """Constrained JSON answer (grammar from the schema; with think=True the grammar applies after the thoughts)."""
        r = self.chat(messages, max_tokens=max_tokens, temperature=temperature, think=think, think_budget=think_budget,
                      response_format={"type": "json_schema", "json_schema": {"name": "out", "schema": schema}})
        try:
            return json.loads(r["message"].get("content") or ""), r
        except json.JSONDecodeError as e:
            raise LLMError(f"invalid JSON from model: {e}") from None

    @staticmethod
    def image_part(png_bytes, max_side=960):
        im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}

    def vision(self, png_bytes, question, schema, max_side=960):
        msgs = [{"role": "user", "content": [self.image_part(png_bytes, max_side), {"type": "text", "text": question}]}]
        out, _ = self.json(msgs, schema, max_tokens=300, temperature=0)
        return out
