"""Which model answers, and what to do when none can.

The agent is deliberately provider agnostic, but something has to choose, and
leaving that to the SDK's default means the only failure a new machine ever sees
is a credentials stack trace. So this picks from what is actually configured and,
when nothing is, says the two things that would fix it.

Order is deliberate. An explicit choice wins. Bedrock comes next because that is
where this runs in deployment. Ollama last, because it needs nothing but a
running daemon and is what makes the thing demonstrable on a laptop with no
account at all.
"""

import json
import os
import urllib.error
import urllib.request

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
PREFERRED_LOCAL = ("qwen3", "qwen2.5", "llama3.2", "llama3.1", "mistral")

_cached = None


class NoModel(RuntimeError):
    """Nothing is configured, and the message says how to change that."""


def _bedrock_ready():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if not region:
        return None
    has_key = os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_PROFILE")
    if not has_key:
        if not os.getenv("AWS_EXECUTION_ENV") and not os.getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"):
            return None
    return region


def local_models(host=None):
    """What Ollama already has. Empty list if it is not running."""
    try:
        with urllib.request.urlopen((host or OLLAMA_HOST) + "/api/tags",
                                    timeout=1.5) as response:
            body = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return []
    return [row.get("name", "") for row in body.get("models", [])]


def _pick_local(available):
    for wanted in PREFERRED_LOCAL:
        for name in available:
            if name.startswith(wanted):
                return name
    return available[0] if available else None


def describe():
    """What would answer right now, without building anything."""
    # Force bedrock as the default provider as requested
    choice = os.getenv("MODEL_PROVIDER", "bedrock").strip().lower()
    region = _bedrock_ready() or os.getenv("AWS_REGION", "us-east-1")
    
    if choice == "bedrock":
        return {"provider": "bedrock", "region": region,
                "model": os.getenv("BEDROCK_MODEL_ID",
                                   "qwen.qwen3-32b-v1:0")}
    available = local_models()
    if choice == "ollama" or (not choice and available):
        return {"provider": "ollama", "host": OLLAMA_HOST,
                "model": os.getenv("OLLAMA_MODEL") or _pick_local(available),
                "available": available}
    return {"provider": None}


def resolve(refresh=False):
    """Build the model object, or raise something a person can act on."""
    global _cached
    if _cached is not None and not refresh:
        return _cached

    found = describe()

    if found["provider"] == "bedrock":
        import boto3
        import botocore
        from botocore.config import Config
        from strands.models.bedrock import BedrockModel
        
        bearer = os.getenv("AWS_BEARER_TOKEN_BEDROCK")
        if bearer:
            session = boto3.Session(region_name=found["region"])
            def inject_bearer(request, **kwargs):
                request.headers.add_header('Authorization', f'Bearer {bearer}')
            session.events.register('request-created.bedrock-runtime', inject_bearer)
            client_config = Config(signature_version=botocore.UNSIGNED)
            
            _cached = BedrockModel(model_id=found["model"],
                                   temperature=0.3,
                                   boto_session=session,
                                   boto_client_config=client_config)
            print(f"Using AWS Bedrock via Bearer Token (Model: {found['model']}, Region: {found['region']})")
        else:
            _cached = BedrockModel(model_id=found["model"],
                                   region_name=found["region"],
                                   temperature=0.3)
            print(f"Using AWS Bedrock via IAM Credentials (Model: {found['model']}, Region: {found['region']})")
        return _cached

    if found["provider"] == "ollama":
        if not found.get("model"):
            raise NoModel(
                f"Ollama is running at {OLLAMA_HOST} but has no models pulled. "
                f"Run:  ollama pull qwen3")
        from strands.models.ollama import OllamaModel
        _cached = OllamaModel(host=OLLAMA_HOST, model_id=found["model"],
                              temperature=0.3)
        return _cached

    raise NoModel(
        "No model is configured, so there is nothing to reason with. Two ways "
        "to fix it, either is enough:\n"
        "  Local, no account:  install Ollama, then  ollama pull qwen3\n"
        "  AWS:                set AWS_REGION and credentials in .env, and "
        "enable Claude in the Bedrock console for that region.\n"
        "Every page keeps working without one. Only the agent needs it.")
