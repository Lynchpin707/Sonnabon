"""Single entry point for model calls.

Bedrock Converse rather than a vendor SDK because routing spans Amazon Nova
and Anthropic Claude, and Converse is the one interface that speaks to both.
Local Ollama keeps development spend at zero.
"""

from dataclasses import dataclass
from functools import lru_cache

from . import config


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int


@lru_cache(maxsize=1)
def _bedrock():
    import boto3

    return boto3.client("bedrock-runtime", region_name=config.AWS_REGION)


@lru_cache(maxsize=1)
def _ollama():
    from openai import OpenAI

    return OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


def complete(model, prompt, max_tokens=None):
    max_tokens = max_tokens or config.MAX_OUTPUT_TOKENS

    if config.USE_AWS:
        res = _bedrock().converse(
            modelId=model.id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"temperature": 0.3, "maxTokens": max_tokens},
        )
        return Completion(
            res["output"]["message"]["content"][0]["text"],
            res["usage"]["inputTokens"],
            res["usage"]["outputTokens"],
        )

    res = _ollama().chat.completions.create(
        model=model.id,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=max_tokens,
    )
    return Completion(
        res.choices[0].message.content,
        res.usage.prompt_tokens,
        res.usage.completion_tokens,
    )
