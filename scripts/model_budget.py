"""Bound model requests and save a private, provider-level usage ledger."""
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MODELS = {"deepseek-flash", "deepseek-v4-pro"}
MAX_REQUEST_BYTES = 48000
MAX_OUTPUT_TOKENS = 4096


def record(path, obj):
    with path.open("x", encoding="utf-8") as file:
        json.dump(obj, file, ensure_ascii=False, indent=2)


def request(trace, key, model, cap, payload, role):
    if model not in MODELS or payload.get("model") != model:
        raise ValueError("unexpected model")
    payload = {**payload, "thinking": {"type": "disabled"}}
    payload["max_tokens"] = min(MAX_OUTPUT_TOKENS, int(payload.get("max_tokens", MAX_OUTPUT_TOKENS)))
    if payload["max_tokens"] < 1:
        raise ValueError("invalid output budget")
    endpoint = "https://api.deepseek.com/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode()
    if len(body) > MAX_REQUEST_BYTES or key.encode() in body:
        raise ValueError("input exceeds budget or contains the credential")

    trace.mkdir(mode=0o700, exist_ok=True)
    for index in range(1, cap + 1):
        call = trace / f"{index:02d}"
        try:
            call.mkdir(mode=0o700)
            break
        except FileExistsError:
            continue
    else:
        raise ValueError("model request budget exhausted")

    record(call / "request.json", {
        "endpoint": endpoint, "role": role, "unix_time": time.time(), "body": payload,
    })
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key}
    started = time.monotonic()
    try:
        with urlopen(Request(endpoint, body, headers), timeout=55) as resp:
            data = resp.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("provider response exceeded the byte limit")
        response = json.loads(data)
        record(call / "summary.json", {
            "usage": response.get("usage"), "model": response.get("model"),
            "finish_reason": response["choices"][0].get("finish_reason"),
            "seconds": round(time.monotonic() - started, 6),
        })
        (call / "provider-response").write_bytes(data)
        return data
    except Exception as error:
        record(call / "error.json", {
            "error_type": type(error).__name__,
            "http_status": error.code if isinstance(error, HTTPError) else None,
            "seconds": round(time.monotonic() - started, 6),
        })
        raise
