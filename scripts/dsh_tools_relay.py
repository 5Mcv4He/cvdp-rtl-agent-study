"""Loopback relay between the DSH runtime and the DeepSeek Messages API.

The DSH runtime speaks the Anthropic Messages protocol (POST {base}/v1/messages,
SSE replies). The relay binds 127.0.0.1 only, so the runtime process never holds
the real credential: it authenticates with a fixed dummy key and every request
is metered here.

Real mode forwards each request to the fixed upstream with the trusted key,
clamps the output budget, enforces the per-run request count and per-request
byte cap, and writes a provider-level ledger (one directory per call).
Mock mode serves scripted Anthropic SSE responses without any upstream contact,
which is how the tool loop and its isolation fences are accepted offline.

The ledger is private: request bodies and raw responses stay in the run
directory and are never published.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

UPSTREAM = "https://api.deepseek.com/anthropic/v1/messages"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
FORWARD_TIMEOUT_SECONDS = 90


def sse_bytes(events):
    """Encode (event_type, data) pairs as an Anthropic-style SSE stream."""
    frames = []
    for event_type, data in events:
        frames.append(f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n")
    return ("\n".join(frames) + "\n").encode()


def text_message(text, input_tokens, output_tokens, message_id="msg_mock"):
    """One assistant text block finishing the turn."""
    return sse_bytes([
        ("message_start", {"type": "message_start", "message": {
            "id": message_id, "type": "message", "role": "assistant", "content": [],
            "usage": {"input_tokens": input_tokens, "output_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta",
                           "delta": {"stop_reason": "end_turn"},
                           "usage": {"output_tokens": output_tokens}}),
        ("message_stop", {"type": "message_stop"}),
    ])


def tool_call_message(tool_name, arguments, input_tokens, output_tokens, step=0):
    """One assistant turn that invokes a single tool."""
    call_id = f"toolu_mock_{step:02d}"
    return sse_bytes([
        ("message_start", {"type": "message_start", "message": {
            "id": f"msg_mock_{step:02d}", "type": "message", "role": "assistant", "content": [],
            "usage": {"input_tokens": input_tokens, "output_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "tool_use", "id": call_id,
                                                   "name": tool_name, "input": {}}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "input_json_delta",
                                           "partial_json": json.dumps(arguments, ensure_ascii=False)}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta",
                           "delta": {"stop_reason": "tool_use"},
                           "usage": {"output_tokens": output_tokens}}),
        ("message_stop", {"type": "message_stop"}),
    ])


def parse_sse_usage(raw):
    """Extract cumulative usage and stop reason from an SSE byte stream."""
    usage = {}
    finish_reason = None
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:])
        except json.JSONDecodeError:
            continue
        if event.get("type") == "message_start":
            usage.update(event.get("message", {}).get("usage", {}) or {})
        elif event.get("type") == "message_delta":
            usage.update(event.get("usage", {}) or {})
            reason = (event.get("delta") or {}).get("stop_reason")
            if reason is not None:
                finish_reason = reason
    return {"usage": usage, "finish_reason": finish_reason}


class Relay:
    """One relay instance per run; bind() before launching the runtime."""

    def __init__(self, *, ledger_dir, mock_script=None, api_key=None,
                 max_requests=8, max_request_bytes=48000, max_output_tokens=4096):
        self.ledger_dir = ledger_dir
        self.mock_script = mock_script
        self.api_key = api_key
        self.max_requests = max_requests
        self.max_request_bytes = max_request_bytes
        self.max_output_tokens = max_output_tokens
        self.port = None
        self.server = None
        self.thread = None
        self.served = 0
        self.forwarded = 0
        self.rejections = []

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}"

    def bind(self):
        relay = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_POST(self):
                if not self.path.rstrip("/").endswith("/v1/messages"):
                    self._json_error(404, "not_found", "relay only serves /v1/messages")
                    return
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                relay._handle(self, body)

            def _json_error(self, status, kind, message):
                payload = json.dumps({"type": "error",
                                      "error": {"type": kind, "message": message}}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def shutdown(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)

    # -- internals ---------------------------------------------------------

    def _next_call_dir(self):
        self.served += 1
        call = self.ledger_dir / f"{self.served:02d}"
        call.mkdir(mode=0o700, parents=True)
        return call

    def _record_request(self, call, body, note=None):
        entry = {"endpoint": UPSTREAM if self.mock_script is None else "mock://127.0.0.1",
                 "role": "dsh-runtime", "unix_time": time.time(),
                 "caps": {"max_requests": self.max_requests,
                          "max_request_bytes": self.max_request_bytes,
                          "max_output_tokens": self.max_output_tokens}}
        if note:
            entry["note"] = note
        with (call / "request.json").open("x", encoding="utf-8") as file:
            json.dump(entry, file, ensure_ascii=False, indent=2)
        (call / "request-body.json").write_bytes(body)

    def _handle(self, handler, body):
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        if self.mock_script is None:
            if not self.api_key:
                raise RuntimeError("real relay requires the trusted API key")
            if len(self.api_key.encode()) and self.api_key.encode() in body:
                self.rejections.append("credential in body")
                self._reject(handler, payload, "credential_in_body",
                             "request carries the relay credential")
                return
            if payload.get("model") != "deepseek-flash":
                self.rejections.append("unexpected model")
                self._reject(handler, payload, "unexpected_model",
                             "study allows only deepseek-flash")
                return
        if self.served >= self.max_requests:
            self._reject(handler, payload, "request_budget",
                         f"study request budget of {self.max_requests} is exhausted")
            return
        if len(body) > self.max_request_bytes:
            self._reject(handler, payload, "input_limit",
                         f"request of {len(body)} bytes exceeds the {self.max_request_bytes}-byte study cap")
            return

        call = self._next_call_dir()
        clamped = dict(payload)
        if isinstance(payload.get("max_tokens"), int):
            clamped["max_tokens"] = min(self.max_output_tokens, payload["max_tokens"])
        else:
            clamped["max_tokens"] = self.max_output_tokens
        self._record_request(call, body)
        started = time.monotonic()
        if self.mock_script is not None:
            response = self.mock_script.respond(self.served, payload)
            (call / "mock-response").write_bytes(response)
            parsed = parse_sse_usage(response)
        else:
            self.forwarded += 1
            try:
                response, status = self._forward(clamped)
            except Exception as error:
                with (call / "error.json").open("x", encoding="utf-8") as file:
                    json.dump({"error_type": type(error).__name__,
                               "seconds": round(time.monotonic() - started, 6)}, file, indent=2)
                handler._json_error(502, "upstream_error",
                                    f"relay upstream failure: {type(error).__name__}")
                return
            if status != 200:
                handler._json_error(status, "upstream_error", "upstream rejected the request")
                return
            (call / "provider-response").write_bytes(response)
            parsed = parse_sse_usage(response)
        with (call / "summary.json").open("x", encoding="utf-8") as file:
            json.dump({"mode": "mock" if self.mock_script is not None else "forward",
                       "request_bytes": len(body), "forwarded_bytes": len(json.dumps(clamped).encode()),
                       "seconds": round(time.monotonic() - started, 6), **parsed},
                      file, ensure_ascii=False, indent=2)
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Content-Length", str(len(response)))
        handler.end_headers()
        handler.wfile.write(response)

    def _reject(self, handler, payload, reason, message):
        self.served += 1
        call = self._next_call_dir()
        if reason == "credential_in_body":
            # Never persist a body that carried the credential; keep only its size.
            body = json.dumps({"redacted": "request body carried the credential",
                               "body_bytes": len(json.dumps(payload, ensure_ascii=False).encode())}).encode()
        else:
            body = json.dumps(payload, ensure_ascii=False).encode()
        self._record_request(call, body, note=reason)
        with (call / "error.json").open("x", encoding="utf-8") as file:
            json.dump({"rejected": reason, "message": message}, file, indent=2)
        self.rejections.append(reason)
        handler._json_error(400, "invalid_request_error", message)

    def _forward(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream",
                   "anthropic-version": "2023-06-01",
                   "Authorization": "Bearer " + self.api_key}
        request = Request(UPSTREAM, body, headers, method="POST")
        try:
            with urlopen(request, timeout=FORWARD_TIMEOUT_SECONDS) as response:
                data = response.read(MAX_RESPONSE_BYTES + 1)
                return data, response.status
        except HTTPError as error:
            return error.read(MAX_RESPONSE_BYTES + 1), error.code
