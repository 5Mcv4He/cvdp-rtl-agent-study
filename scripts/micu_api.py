"""Translate ACE text requests to the two documented MiCu external APIs."""

CLAUDE = "claude-opus-5-5"
GPT = "gpt-6.2-astra"
KEY_VARIABLES = {CLAUDE: "MICU_CLAUDE_API_KEY", GPT: "MICU_CODEX_API_KEY"}
HOST = "https://www.micuapi.ai"
TIMEOUT = 110


def prepare(payload):
    model = payload["model"]
    messages = payload["messages"]
    # ACE sends role instructions before the conversation.
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    conversation = [m for m in messages if m["role"] != "system"]
    if model == CLAUDE:
        body = {
            "model": model, "messages": conversation, "max_tokens": payload["max_tokens"],
            "thinking": {"type": "adaptive", "display": "omitted"},
            "output_config": {"effort": "low"},
        }
        if system:
            body["system"] = system
        return HOST + "/v1/messages", {
            "anthropic-version": "2023-06-01",
            "User-Agent": "claude-cli/2.0.76 (external, cli)",
        }, body
    body = {
        "model": model, "input": conversation, "instructions": system or "Follow the user request.",
        "max_output_tokens": payload["max_tokens"], "reasoning": {"effort": "low"},
        "stream": False, "store": False,
    }
    return HOST + "/v1/responses", {
        "User-Agent": "codex_cli_rs/0.77.0 (Windows 10.0.26100; x86_64) WindowsTerminal",
    }, body


def normalize(model, response):
    if response.get("model") != model:
        raise ValueError("MiCu did not return the requested model ID")
    usage = response["usage"]
    if model == CLAUDE:
        text = "".join(block["text"] for block in response["content"] if block["type"] == "text")
        stop = response["stop_reason"]
        finish = "length" if stop == "max_tokens" else stop
        cached = usage.get("cache_read_input_tokens", 0)
        cache_write = usage.get("cache_creation_input_tokens", 0)
        uncached = usage["input_tokens"] + cache_write
        reasoning = usage.get("output_tokens_details", {}).get("thinking_tokens")
    else:
        text = "".join(
            block["text"] for item in response["output"] if item["type"] == "message"
            for block in item["content"] if block["type"] == "output_text"
        )
        finish = response["status"]
        if finish == "incomplete" and (response.get("incomplete_details") or {}).get("reason") == "max_output_tokens":
            finish = "length"
        details = usage.get("input_tokens_details", {})
        cached = details.get("cached_tokens", 0)
        cache_write = details.get("cache_write_tokens", 0)
        uncached = usage["input_tokens"] - cached
        reasoning = usage.get("output_tokens_details", {}).get("reasoning_tokens")
    return {
        "model": model,
        "choices": [{"message": {"content": text}, "finish_reason": finish}],
        "usage": {
            "prompt_cache_miss_tokens": uncached, "prompt_cache_hit_tokens": cached,
            "prompt_cache_write_tokens": cache_write, "completion_tokens": usage["output_tokens"],
            "reasoning_tokens": reasoning,
        },
    }
