#!/usr/bin/env python3
"""Fake OpenAI-compatible SSE endpoint (stdlib only).

Modes (argv[2]):
  lf          - events end with \n\n            (llama.cpp / vLLM style)
  crlf        - events end with \r\n\r\n        (TabbyAPI / sse-starlette style)
  mixed       - alternates \r\n\r\n and \n\n per event
  crlf-split  - like crlf, but every \r and \n of the delimiter is flushed
                separately, so HTTP reads split mid-delimiter

Usage: fake_sse_server.py <port> <mode> [token_delay_ms]
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODE = "lf"
TOKEN_DELAY = 0.015  # s between delta chunks


def write_raw(handler, data: bytes):
    handler.wfile.write(data)
    handler.wfile.flush()


def send_events(handler, events):
    """events: list of raw 'data: ...' payloads (without trailing newlines)."""
    for i, payload in enumerate(events):
        if MODE == "lf":
            frame = payload.encode() + b"\n\n"
            write_raw(handler, frame)
        elif MODE == "crlf":
            frame = payload.encode() + b"\r\n\r\n"
            write_raw(handler, frame)
        elif MODE == "mixed":
            ending = b"\r\n\r\n" if i % 2 == 0 else b"\n\n"
            write_raw(handler, payload.encode() + ending)
        elif MODE == "crlf-split":
            # Flush each byte of the CRLFCRLF delimiter separately.
            write_raw(handler, payload.encode() + b"\r")
            time.sleep(0.002)
            write_raw(handler, b"\n")
            time.sleep(0.002)
            write_raw(handler, b"\r")
            time.sleep(0.002)
            write_raw(handler, b"\n")
        time.sleep(TOKEN_DELAY)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        if not self.path.startswith("/v1/chat/completions"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            req = {}
        max_tokens = int(req.get("max_tokens") or 16)
        model = req.get("model") or "fake-crlf-model"
        want_usage = bool(
            (req.get("stream_options") or {}).get("include_usage", True)
        )

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        events = []
        # role chunk (like real servers)
        events.append(
            "data: "
            + json.dumps(
                {
                    "id": "chatcmpl-fake",
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [
                        {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
                    ],
                }
            )
        )
        for i in range(max_tokens):
            events.append(
                "data: "
                + json.dumps(
                    {
                        "id": "chatcmpl-fake",
                        "object": "chat.completion.chunk",
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": f"tok{i} "},
                                "finish_reason": None,
                            }
                        ],
                    }
                )
            )
        events.append(
            "data: "
            + json.dumps(
                {
                    "id": "chatcmpl-fake",
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [
                        {"index": 0, "delta": {}, "finish_reason": "stop"}
                    ],
                }
            )
        )
        if want_usage:
            events.append(
                "data: "
                + json.dumps(
                    {
                        "id": "chatcmpl-fake",
                        "object": "chat.completion.chunk",
                        "model": model,
                        "choices": [],
                        "usage": {
                            "prompt_tokens": 42,
                            "completion_tokens": max_tokens,
                            "total_tokens": 42 + max_tokens,
                        },
                    }
                )
            )
        events.append("data: [DONE]")
        send_events(self, events)
        self.close_connection = True


if __name__ == "__main__":
    port = int(sys.argv[1])
    MODE = sys.argv[2] if len(sys.argv) > 2 else "lf"
    if len(sys.argv) > 3:
        TOKEN_DELAY = float(sys.argv[3]) / 1000.0
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"fake-sse {MODE} on :{port}", flush=True)
    srv.serve_forever()
