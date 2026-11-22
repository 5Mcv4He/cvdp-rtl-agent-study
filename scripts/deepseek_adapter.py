"""Send one bounded ACE-RTL model request and keep its public response and usage."""
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT = "https://api.deepseek.com/chat/completions"


def complete(incoming):
    model = incoming["model"]
    if model != "deepseek-flash":
        raise ValueError(f"unexpected P1 model: {model}")
    payload = {
        "model": model,
        "messages": incoming["messages"],
        "max_tokens": min(4096, int(incoming["max_tokens"])),
        "temperature": incoming["temperature"],
        "top_p": incoming["top_p"],
        "stream": False,
        "thinking": {"type": "disabled"},
    }
    body = json.dumps(payload).encode()
    key = os.environ["DEEPSEEK_API_KEY"]
    if len(body) > 48000 or key in body.decode():
        raise ValueError("request exceeds the P1 input limit or contains the API key")
    trace = Path(os.environ["P1_TRACE_DIR"])
    trace.mkdir(mode=0o700, exist_ok=True)
    # Reserve the single paid request before sending, including in retries.
    with (trace / "request.json").open("x", encoding="utf-8") as f:
        json.dump({
            "endpoint": ENDPOINT,
            "role": os.environ.get("ACE_RTL_COMPONENT"),
            "requested_at_unix": time.time(),
            "body": payload,
        }, f, ensure_ascii=False, indent=2)
    started = time.monotonic()
    try:
        request = Request(ENDPOINT, body, {
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        })
        with urlopen(request, timeout=95) as response:
            raw = json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        status = getattr(error, "code", None)
        (trace / "error.json").write_text(json.dumps({
            "error_type": type(error).__name__, "http_status": status,
            "seconds": time.monotonic() - started,
        }))
        raise RuntimeError(f"DeepSeek {type(error).__name__}, HTTP status {status}") from None

    choice = raw["choices"][0]
    result = {
        "id": raw.get("id"),
        "model": raw.get("model"),
        "choices": [{
            "message": {"role": "assistant", "content": choice["message"]["content"]},
            "finish_reason": choice["finish_reason"],
        }],
        "usage": raw.get("usage"),
    }
    (trace / "response.json").write_text(json.dumps({
        "response": result, "seconds": time.monotonic() - started,
    }, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    print(json.dumps(complete(json.load(sys.stdin)), ensure_ascii=False))
