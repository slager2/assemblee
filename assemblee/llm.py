"""OpenAI-compatible client for llama-server: chat with tools, JSON-schema output, vision, server stats."""
import base64
import io
import json
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

    def model_name(self):
        try:
            with urllib.request.urlopen(self.base + "/v1/models", timeout=5) as r:
                d = json.load(r)
            return d["data"][0]["id"]
        except Exception:
            return "unknown"

    def chat(self, messages, tools=None, max_tokens=2048, temperature=0.3, response_format=None, tool_choice=None):
        body = {"model": "m", "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
                "top_p": 0.9, "cache_prompt": True}
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
        self.totals["requests"] += 1
        self.totals["prompt_tokens"] += usage.get("prompt_tokens", 0)
        self.totals["completion_tokens"] += usage.get("completion_tokens", 0)
        self.totals["seconds"] += dt
        msg = r["choices"][0]["message"]
        return {"message": msg, "finish_reason": r["choices"][0].get("finish_reason"), "usage": usage, "seconds": round(dt, 2),
                "tokens_per_second": round(timings.get("predicted_per_second") or (usage.get("completion_tokens", 0) / dt if dt else 0), 1),
                "prompt_per_second": round(timings.get("prompt_per_second", 0) or 0, 1)}

    def json(self, messages, schema, max_tokens=2048, temperature=0.3):
        """Constrained JSON answer (grammar from the schema)."""
        r = self.chat(messages, max_tokens=max_tokens, temperature=temperature,
                      response_format={"type": "json_schema", "json_schema": {"name": "out", "schema": schema}})
        try:
            return json.loads(r["message"].get("content") or ""), r
        except json.JSONDecodeError as e:
            raise LLMError(f"invalid JSON from model: {e}") from None

    def vision(self, png_bytes, question, schema, max_side=960):
        im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        msgs = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}, {"type": "text", "text": question}]}]
        out, _ = self.json(msgs, schema, max_tokens=300, temperature=0)
        return out
