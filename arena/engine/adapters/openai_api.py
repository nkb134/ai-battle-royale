"""OpenAI-compatible endpoints. §5.1, §6.2.

Two deployments, one adapter:

  provider: vertex_openai  -> Vertex Model Garden's OpenAI-compatible endpoint, which
                              carries the open-weight gpt-oss family. Auth is the same
                              Google credentials as the other Vertex adapters.
  provider: openai         -> api.openai.com with OPENAI_API_KEY.

Budget enforcement differs by family and the difference is honest, not hidden. A plain
chat model takes the budget as a hard `max_tokens`. A reasoning model exposes only a
coarse `reasoning_effort` dial and no exact token budget, so the pacing budget is
mapped onto that dial and the enforced ceiling goes on `max_completion_tokens`. The
told budget is logged either way, so how well each family tracks it stays measurable.
"""

from __future__ import annotations

import os

from arena.engine.adapters.base import BaseAdapter, with_backoff
from arena.engine.prompts import render
from arena.engine.types import MoveContext, RawMoveResponse

VERTEX_OPENAI_BASE = "https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/endpoints/openapi"


def effort_for_budget(tokens: int) -> str:
    """Map a token budget onto the only pacing dial a reasoning model offers."""
    if tokens <= 400:
        return "low"
    if tokens <= 1500:
        return "medium"
    return "high"


class OpenAIAdapter(BaseAdapter):
    def __init__(
        self,
        name: str,
        model_string: str,
        *,
        base_url: str | None = None,
        project: str | None = None,
        location: str = "us-central1",
        vertex: bool = False,
        reasoning: bool = False,
        temperature: float = 0.0,
        seed: int = 7,
        **kw,
    ):
        super().__init__(name, model_string, **kw)
        self.vertex = vertex
        self.reasoning = reasoning
        self.temperature = temperature
        self.seed = seed
        self.project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self.location = location
        self.base_url = base_url or (
            VERTEX_OPENAI_BASE.format(location=location, project=self.project)
            if vertex
            else None
        )
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            if self.vertex:
                self._client = AsyncOpenAI(
                    base_url=self.base_url, api_key=_google_access_token()
                )
            else:
                self._client = AsyncOpenAI()
        return self._client

    async def move(self, ctx: MoveContext) -> RawMoveResponse:
        prompt = render(ctx)
        client = self._get_client()
        headroom = self.options.get("headroom", 96)
        ceiling = ctx.token_budget + headroom

        kwargs: dict = {
            "model": self.model_string,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.reasoning:
            kwargs["max_completion_tokens"] = ceiling
            kwargs["reasoning_effort"] = effort_for_budget(ctx.token_budget)
        else:
            kwargs["max_tokens"] = ceiling
            kwargs["temperature"] = self.temperature
            kwargs["seed"] = self.seed

        async def call():
            return await client.chat.completions.create(**kwargs)

        resp = await with_backoff(call, what=f"openai:{self.model_string}")

        choice = resp.choices[0]
        usage = getattr(resp, "usage", None)
        details = getattr(usage, "completion_tokens_details", None)

        # gpt-oss on Vertex returns its chain of thought in `reasoning_content` and
        # does not break reasoning out in the usage details. Log the text, but leave
        # reasoning_tokens as None rather than estimating from it: §13 says count on
        # completion from the usage field, never estimate.
        reasoning_text = getattr(choice.message, "reasoning_content", None)

        return RawMoveResponse(
            text=choice.message.content or "",
            reasoning_tokens=getattr(details, "reasoning_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            truncated=choice.finish_reason == "length",
            raw={
                "finish_reason": choice.finish_reason,
                "told_budget": ctx.token_budget,
                "reasoning_effort": kwargs.get("reasoning_effort"),
                "reasoning_content": reasoning_text,
            },
        )


def _google_access_token() -> str:
    """An OAuth token for Vertex's OpenAI-compatible endpoint.

    Uses application default credentials, so it needs `gcloud auth application-default
    login`. Tokens are short-lived; a match longer than the token's life will need this
    refreshed, which is why the client is built lazily per adapter.
    """
    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token
