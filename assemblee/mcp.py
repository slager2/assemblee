"""Minimal MCP stdio client for the FilmCraft / EffectCraft headless servers."""
import json
import queue
import subprocess
import threading


class MCPError(RuntimeError):
    pass


class MCP:
    def __init__(self, cmd, timeout=120):
        self.cmd, self.timeout = [str(c) for c in cmd], timeout
        try:
            self._start()
        except BaseException:  # a failed handshake must not leave the engine process behind
            self.close()
            raise

    def _start(self):
        self.p = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.i = 0
        self.lines = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "assemblee", "version": "0.1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _reader(self):
        for line in self.p.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _send(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def rpc(self, method, params):
        self.i += 1
        self._send({"jsonrpc": "2.0", "id": self.i, "method": method, "params": params})
        while True:
            try:
                line = self.lines.get(timeout=self.timeout)
            except queue.Empty:
                raise MCPError(f"{method}: no answer in {self.timeout}s")
            if line is None:
                raise MCPError("MCP server exited")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == self.i:
                if "error" in msg:
                    raise MCPError(json.dumps(msg["error"], ensure_ascii=False)[:400])
                return msg["result"]

    def call(self, name, args=None):
        r = self.rpc("tools/call", {"name": name, "arguments": args or {}})
        out = []
        for c in r.get("content", []):
            if c["type"] == "text":
                try:
                    out.append(json.loads(c["text"]))
                except json.JSONDecodeError:
                    out.append(c["text"])
            elif c["type"] == "image":
                out.append({"image_png_b64": c["data"]})
        if r.get("isError"):
            raise MCPError(json.dumps(out, ensure_ascii=False)[:400])
        return out[0] if len(out) == 1 else out

    def run(self, command_id, params=None):
        return self.call("command_run", {"id": command_id, "params": params or {}})

    def close(self):
        p = getattr(self, "p", None)
        if p is None:
            return
        try:
            p.kill()
            p.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
