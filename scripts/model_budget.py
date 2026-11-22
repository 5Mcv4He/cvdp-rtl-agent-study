"""Bound model requests and save a private, provider-level usage ledger."""
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

import micu_api

MODELS = {"deepseek-flash", "deepseek-v4-pro"}
ACE_MODELS = MODELS | micu_api.KEY_VARIABLES.keys()
MAX_REQUEST_BYTES = 48000
MAX_OUTPUT_TOKENS = 4096


class RefuseRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def record(path, obj):
    with path.open("x", encoding="utf-8") as file:
        json.dump(obj, file, ensure_ascii=False, indent=2)


def request(trace, key, model, cap, payload, role, max_request_bytes=MAX_REQUEST_BYTES):
    if model not in ACE_MODELS or payload.get("model") != model:
        raise ValueError("unexpected model")
    payload = dict(payload)
    payload["max_tokens"] = min(MAX_OUTPUT_TOKENS, int(payload.get("max_tokens", MAX_OUTPUT_TOKENS)))
    if payload["max_tokens"] < 1:
        raise ValueError("invalid output budget")
    micu = model in micu_api.KEY_VARIABLES
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key}
    if micu:
        endpoint, extra_headers, payload = micu_api.prepare(payload)
        headers.update(extra_headers)
        open_response = build_opener(RefuseRedirects()).open
        timeout = micu_api.TIMEOUT
    else:
        endpoint = "https://api.deepseek.com/chat/completions"
        payload["thinking"] = {"type": "disabled"}
        open_response = urlopen
        timeout = 55
    body = json.dumps(payload, ensure_ascii=False).encode()
    if len(body) > max_request_bytes or key.encode() in body:
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
    started = time.monotonic()
    try:
        with open_response(Request(endpoint, body, headers), timeout=timeout) as resp:
            data = resp.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024 or key.encode() in data:
            raise ValueError("provider response exceeds budget or contains the credential")
        response = json.loads(data)
        (call / "provider-response").write_bytes(data)
        if micu:
            response = micu_api.normalize(model, response)
        record(call / "summary.json", {
            "usage": response.get("usage"), "model": response.get("model"),
            "finish_reason": response["choices"][0].get("finish_reason"),
            "seconds": round(time.monotonic() - started, 6),
        })
        return json.dumps(response, ensure_ascii=False).encode() if micu else data
    except Exception as error:
        record(call / "error.json", {
            "error_type": type(error).__name__,
            "http_status": error.code if isinstance(error, HTTPError) else None,
            "seconds": round(time.monotonic() - started, 6),
        })
        raise
