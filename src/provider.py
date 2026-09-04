"""Single entry point for model calls.

Bedrock Converse rather than a vendor SDK because routing spans Amazon Nova
and Anthropic Claude, and Converse is the one interface that speaks to both.
Local Ollama keeps development spend at zero and uses the standard library, so
running this repo needs nothing beyond boto3 and Strands.

Token counts are read from the provider's own response and never estimated.
That is the one property the whole ledger rests on.
"""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

from . import config

TIMEOUT = 120
RETRIES = 3

# A refused connection is attempted twice, once per address family, so a probe
# against a dead Ollama costs two timeouts. The interface asks on every poll,
# which made /api/state block for four seconds. The answer does not change that
# fast, so it is remembered.
PROBE_TIMEOUT = 1.0
HEALTH_TTL = 10.0
_health = {"at": -1e9, "result": None}


class BackendUnavailable(RuntimeError):
    """No model could be reached. Callers say so rather than invent a number."""


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int


@lru_cache(maxsize=1)
def _bedrock():
    import boto3

    return boto3.client("bedrock-runtime", region_name=config.AWS_REGION)


def _converse(model, prompt, max_tokens):
    """Bedrock throttles, and a throttle mid-demo looks like a crash. Back off
    and retry rather than surfacing a 429 as a broken product."""
    for attempt in range(RETRIES):
        try:
            res = _bedrock().converse(
                modelId=model.id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"temperature": 0.3, "maxTokens": max_tokens},
            )
        except Exception as exc:
            throttled = "Throttling" in type(exc).__name__ or "Throttling" in str(exc)
            if throttled and attempt < RETRIES - 1:
                time.sleep(2**attempt)
                continue
            raise BackendUnavailable(f"bedrock: {exc}") from exc
        return Completion(
            res["output"]["message"]["content"][0]["text"],
            res["usage"]["inputTokens"],
            res["usage"]["outputTokens"],
        )


def _ollama(model, prompt, max_tokens):
    body = json.dumps({
        "model": model.id,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": max_tokens},
    }).encode()
    request = urllib.request.Request(
        f"{config.OLLAMA_HOST}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            res = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BackendUnavailable(
            f"ollama at {config.OLLAMA_HOST} is not answering ({exc}). "
            f"Start it and run: ollama pull {model.id}"
        ) from exc

    # Ollama omits the eval counts when it serves a fully cached prompt. Zero is
    # then the true count of tokens evaluated, not a placeholder for unknown.
    return Completion(
        res["message"]["content"],
        res.get("prompt_eval_count", 0),
        res.get("eval_count", 0),
    )


def complete(model, prompt, max_tokens=None):
    max_tokens = max_tokens or config.MAX_OUTPUT_TOKENS
    caller = _converse if config.USE_AWS else _ollama
    return caller(model, prompt, max_tokens)


def health(fresh=False):
    """Can a model actually be reached, and if not, what should the user do.

    The interface promises to say when there is no backend rather than invent
    numbers. That promise needs something that actually checks, but not on
    every single request: the answer is cached for HEALTH_TTL seconds. Pass
    fresh=True after changing the backend, where the stale answer would be
    worse than the wait.
    """
    now = time.monotonic()
    if not fresh and _health["result"] and now - _health["at"] < HEALTH_TTL:
        return _health["result"]
    result = _probe()
    _health.update(at=now, result=result)
    return result


def _probe():
    if config.USE_AWS:
        try:
            import boto3

            if boto3.Session(region_name=config.AWS_REGION).get_credentials() is None:
                return False, "no AWS credentials found. Run: aws configure"
        except Exception as exc:
            return False, f"bedrock unavailable: {exc}"
        return True, f"bedrock, {config.AWS_REGION}"

    found = installed()
    if found is None:
        return False, (f"ollama is not answering at {config.OLLAMA_HOST}. "
                       "Start it, or run with USE_AWS=true")
    if not found:
        return False, ("ollama is running but has no models. Pull any one you "
                       "like, for example: ollama pull qwen2.5:3b")

    # Whatever is there gets used, so the only real failure left is a tier
    # somebody pinned by hand to something that is not installed.
    chosen = config.adopt_ollama(found)
    have = {name for name, _ in found}
    missing = sorted({name for name in chosen.values()} - have)
    if missing:
        return False, "pinned but not installed: " + ", ".join(
            f"ollama pull {name}" for name in missing)
    return True, f"ollama, {config.OLLAMA_HOST}"


def installed():
    """What Ollama has, as (name, size in bytes). None if it is not answering."""
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_HOST}/api/tags", timeout=2) as res:
            models = json.load(res).get("models", [])
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    return [(m["name"], int(m.get("size", 0))) for m in models if m.get("name")]
