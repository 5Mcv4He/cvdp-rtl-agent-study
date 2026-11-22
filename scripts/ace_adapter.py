"""ACE-RTL JSON-over-stdin adapter for the bounded comparison runner."""
import json
import os
from pathlib import Path
import sys

from model_budget import request


def main():
    incoming = json.load(sys.stdin)
    payload = {
        "model": incoming["model"], "messages": incoming["messages"],
        "temperature": 0.2, "top_p": 0.95, "stream": False,
        "max_tokens": incoming["max_tokens"],
    }
    try:
        data = request(
            Path(os.environ["STUDY_TRACE"]), os.environ["DEEPSEEK_API_KEY"],
            os.environ["STUDY_MODEL"], int(os.environ["STUDY_MAX_CALLS"]),
            payload, os.environ.get("ACE_RTL_COMPONENT", "unknown"),
        )
    except Exception as error:
        # The credential and provider body should never appear in stderr.
        raise SystemExit(f"Study adapter failed: {type(error).__name__}") from None
    sys.stdout.buffer.write(data)


if __name__ == "__main__":
    main()
