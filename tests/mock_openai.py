"""A fake OpenAI-compatible endpoint for testing the LLM agent loop offline.

It plays a fixed scientist script (chat/completions with tools) and validates
every request against the Meta Model API chat-completions format: system
first, function tools, assistant tool_calls echoed back, one tool message per
tool_call_id. Violations are collected in `MockServer.errors`.
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class MockServer:
    def __init__(self, mode: str | None = None, after: int = 0):
        """mode, from request number `after` on: "status:<code>" HTTP error, "malformed" (no choices), "silent"
        (no tool calls), "badjson" (tool arguments that aren't JSON), "badargs" (out-of-range arguments)."""
        self.mode, self.after = mode, after
        self.errors: list[str] = []
        self.requests: list[dict] = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()

    # -------------------------------------------------------------- policy
    def validate(self, body: dict):
        if not body.get("model"):
            self.errors.append("missing model")
        msgs = body.get("messages") or []
        if not msgs or msgs[0].get("role") != "system":
            self.errors.append("first message must be system")
        for t in body.get("tools") or []:
            f = t.get("function", {})
            if t.get("type") != "function" or not f.get("name") or f.get("parameters", {}).get("type") != "object":
                self.errors.append(f"bad tool definition {t}")
        pending = set()
        for m in msgs:
            if m["role"] == "assistant" and m.get("tool_calls"):
                if not isinstance(m.get("content"), str):
                    self.errors.append("assistant content must be a string when tool_calls present")
                for c in m["tool_calls"]:
                    pending.add(c["id"])
                    json.loads(c["function"]["arguments"])
            elif m["role"] == "tool":
                if m.get("tool_call_id") not in pending:
                    self.errors.append(f"tool message with unknown id {m.get('tool_call_id')}")
                pending.discard(m.get("tool_call_id"))
                json.loads(m["content"])
        if pending:
            self.errors.append(f"unanswered tool calls {pending}")
        if body.get("tool_choice") not in (None, "auto"):
            self.errors.append("only tool_choice auto is supported")

    def next_call(self, body: dict):
        """Plays a short farm-scientist script, reading ids from earlier tool results."""
        msgs = body["messages"]
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        n = len(tool_msgs)
        last = json.loads(tool_msgs[-1]["content"]) if tool_msgs else {}
        hist = "\n".join(m.get("content") or "" for m in tool_msgs)

        def last_id(prefix):
            ids = re.findall(rf'"({prefix}\d+)"', hist)
            return ids[-1] if ids else f"{prefix}1"

        script = [
            ("observe", {}),
            ("plan_season", {"rationale": "plan on published values"}),
            ("record_hypothesis", {"statement": "local varieties differ", "prediction": "some trials miss",
                                   "falsified_if": "all trials inside the bands"}),
            ("evaluate_trials", {"candidates": [
                {"crop": "wheat", "sow": 50, "plot": "normal"}, {"crop": "wheat", "sow": 50, "plot": "saline"},
                {"crop": "maize", "sow": 20, "plot": "normal"}, {"crop": "sweet_potato", "sow": 20, "plot": "normal"}]}),
            ("run_trials", lambda: {"candidate_ids": [o["candidate_id"] for o in last.get("options", []) if "candidate_id" in o],
                                    "hypothesis_id": last_id("H"), "rationale": "expose salt and growth traits"}),
            ("fit_crop_models", {"rationale": "learn"}),
            ("conclude", lambda: {"hypothesis_id": last_id("H"), "verdict": "supported", "evidence": "see fits"}),
            ("plan_season", {"rationale": "calibrated plan"}),
            ("start_season", lambda: {"plan_id": last_id("P"), "rationale": "go"}),
        ]
        if n < len(script):
            name, args = script[n]
            return name, (args() if callable(args) else args)
        if isinstance(last, dict) and last.get("anomaly") and "dismiss" not in (tool_msgs[-1].get("content") or ""):
            return "dismiss_anomaly", {"rationale": "mock ignores"}
        if isinstance(last, dict) and (last.get("result") or last.get("summary")):
            if "summary" in last:
                return None
            return "finish", {"summary": "mock run complete"}
        if n > 60:
            return "finish", {"summary": "mock run complete"}
        return "advance", {"days": 60, "rationale": "keep going"}

    def _handler(self):
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                srv.requests.append(body)
                if self.headers.get("Authorization", "").startswith("Bearer ") is False:
                    srv.errors.append("missing bearer auth")
                failing = srv.mode and len(srv.requests) > srv.after
                if failing and srv.mode.startswith("status:"):
                    code = int(srv.mode.split(":")[1])
                    data = json.dumps({"error": {"message": f"mock {code}"}}).encode()
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if failing and srv.mode == "malformed":
                    out = {"id": "x", "object": "chat.completion"}
                elif failing and srv.mode == "silent":
                    out = {"choices": [{"index": 0, "message": {"role": "assistant", "content": "I think we are done."}, "finish_reason": "stop"}]}
                elif failing and srv.mode in ("badjson", "badargs"):
                    arg = "{days: sixty" if srv.mode == "badjson" else json.dumps({"days": 100000, "rationale": "x", "extra": 1})
                    out = {"choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [
                        {"id": f"call_{len(srv.requests)}", "type": "function", "function": {"name": "advance", "arguments": arg}}]}}]}
                else:
                    out = None
                if out is not None:
                    data = json.dumps(out).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if self.path.endswith("/chat/completions"):
                    srv.validate(body)
                    nxt = srv.next_call(body)
                    if nxt is None:
                        msg = {"role": "assistant", "content": "Done."}
                        fr = "stop"
                    else:
                        i = len(srv.requests)
                        msg = {"role": "assistant", "content": None, "tool_calls": [
                            {"id": f"call_{i}", "type": "function",
                             "function": {"name": nxt[0], "arguments": json.dumps(nxt[1])}}]}
                        fr = "tool_calls"
                    out = {"id": "chatcmpl-mock", "object": "chat.completion", "model": body.get("model"),
                           "choices": [{"index": 0, "message": msg, "finish_reason": fr}],
                           "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
                else:
                    out = {"error": {"message": "not mocked"}}
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return H


def _first(result: dict, name_prefix: str):
    for o in result.get("options", []):
        if str(o.get("name", "")).startswith(name_prefix) and "candidate_id" in o:
            return o["candidate_id"]
    return None
