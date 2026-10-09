"""Claude on Amazon Bedrock with JSON-schema outputs, response caching and spend accounting."""

from __future__ import annotations

import json
import os
import time

from .common import Cache, Ledger, digest, utcnow

# USD per million tokens (input, output): list prices plus 10% for EU regional inference profiles.
PRICES: dict[str, tuple[float, float]] = {
    "eu.anthropic.claude-sonnet-4-6": (3.30, 16.50),
    "eu.anthropic.claude-opus-4-6-v1": (5.50, 27.50),
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0": (1.10, 5.50),
    "eu.anthropic.claude-sonnet-4-5-20250929-v1:0": (3.30, 16.50),
}
DEFAULT_EXTRACT_MODEL = "eu.anthropic.claude-sonnet-4-6"
DEFAULT_TRIAGE_MODEL = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"


class LLMError(RuntimeError):
    pass


class LLM:
    """One model, called with a system prompt, a user prompt and a JSON schema for the answer.

    Answers are cached by a hash of (model, prompts, schema, max_tokens); reruns replay them, so
    outputs stay deterministic once collected. Credentials come from the standard AWS chain, or
    from ``<env_prefix>AWS_ACCESS_KEY_ID`` / ``<env_prefix>AWS_SECRET_ACCESS_KEY`` when a prefix is set.
    """

    def __init__(self, cache: Cache, ledger: Ledger, model: str, region: str | None = None,
                 env_prefix: str = ""):
        if model not in PRICES:
            raise ValueError(f"no price configured for {model}; add it to PRICES first")
        self.cache = cache
        self.ledger = ledger
        self.model = model
        self.env_prefix = env_prefix
        self.region = region or os.environ.get(f"{env_prefix}AWS_REGION") or os.environ.get("AWS_REGION") \
            or "eu-central-1"
        self._client = None

    def _client_or_create(self):
        if self._client is None:
            import anthropic

            kwargs = {"aws_region": self.region, "max_retries": 5}
            if self.env_prefix:
                kwargs["aws_access_key"] = os.environ[f"{self.env_prefix}AWS_ACCESS_KEY_ID"]
                kwargs["aws_secret_key"] = os.environ[f"{self.env_prefix}AWS_SECRET_ACCESS_KEY"]
            self._client = anthropic.AnthropicBedrock(**kwargs)
        return self._client

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        price_in, price_out = PRICES[self.model]
        return (input_tokens * price_in + output_tokens * price_out) / 1_000_000

    def _create(self, system: str, prompt: str, schema: dict, max_tokens: int):
        """Messages call; on throttling, wait longer than the SDK's own short retries do."""
        import anthropic

        for attempt in range(6):
            try:
                return self._client_or_create().messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                    output_config={"format": {"type": "json_schema", "schema": schema}},
                )
            except (anthropic.RateLimitError, anthropic.InternalServerError) as error:
                if attempt == 5:
                    raise LLMError(f"throttled after retries: {type(error).__name__}") from error
                time.sleep(15 * (attempt + 1))
        raise LLMError("unreachable")

    def json(self, *, system: str, prompt: str, schema: dict, max_tokens: int = 4000, tag: str = "") -> dict:
        key = digest({"model": self.model, "system": system, "prompt": prompt, "schema": schema,
                      "max_tokens": max_tokens})
        cached = self.cache.get("llm", key)
        if cached is not None:
            return cached["output"]
        self.cache.miss(f"llm {tag}")
        # Czech text runs at roughly 2.5 characters per token; budget the worst case.
        self.ledger.check("bedrock", self.cost(int(len(system + prompt) / 2.5), max_tokens))
        response = self._create(system, prompt, schema, max_tokens)
        usage = response.usage
        cost = self.cost(usage.input_tokens, usage.output_tokens)
        self.ledger.record("bedrock", cost, {"model": self.model, "tag": tag, "input_tokens": usage.input_tokens,
                                              "output_tokens": usage.output_tokens})
        if response.stop_reason != "end_turn":
            raise LLMError(f"{tag}: stop_reason={response.stop_reason}")
        text = "".join(block.text for block in response.content if block.type == "text")
        output = json.loads(text)
        self.cache.put("llm", key, {"model": self.model, "tag": tag, "created_at": utcnow(), "output": output,
                                    "usage": {"input_tokens": usage.input_tokens,
                                              "output_tokens": usage.output_tokens}})
        return output
