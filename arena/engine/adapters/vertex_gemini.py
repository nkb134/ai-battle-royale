"""Gemini on Vertex AI. §5.1, §6.2.

`thinking_budget` is the native lever; `max_output_tokens` sits above it with headroom
for the `<move>` tag. Note that the 2.5 Pro family cannot disable thinking entirely and
clamps a request for zero up to its own floor, so in panic mode the *told* budget and
the *enforced* budget genuinely diverge for this model. That divergence is a result
worth having (§6.2), not a bug to paper over, so both numbers are logged.
"""

from __future__ import annotations

import os

from arena.engine.adapters.base import BaseAdapter, with_backoff
from arena.engine.prompts import render
from arena.engine.types import MoveContext, RawMoveResponse


class VertexGeminiAdapter(BaseAdapter):
    def __init__(
        self,
        name: str,
        model_string: str,
        *,
        project: str | None = None,
        location: str = "us-central1",
        thinking: bool = True,
        temperature: float = 0.0,
        seed: int = 7,
        **kw,
    ):
        super().__init__(name, model_string, thinking=thinking, **kw)
        self.project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self.location = location
        self.temperature = temperature
        self.seed = seed
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=True, project=self.project, location=self.location
            )
        return self._client

    async def move(self, ctx: MoveContext) -> RawMoveResponse:
        from google.genai import types as gt

        prompt = render(ctx)
        client = self._get_client()

        # Gemini bills thinking and the visible answer against one ceiling, so
        # max_output_tokens must exceed thinking_budget by a whole short answer.
        config = gt.GenerateContentConfig(
            temperature=self.temperature,
            seed=self.seed,
            max_output_tokens=ctx.max_output_tokens,
            thinking_config=gt.ThinkingConfig(
                thinking_budget=ctx.token_budget if self.thinking else 0,
                include_thoughts=False,
            ),
        )

        async def call():
            return await client.aio.models.generate_content(
                model=self.model_string, contents=prompt, config=config
            )

        resp = await with_backoff(call, what=f"gemini:{self.model_string}")

        usage = getattr(resp, "usage_metadata", None)
        finish = None
        if getattr(resp, "candidates", None):
            finish = str(getattr(resp.candidates[0], "finish_reason", "") or "")

        return RawMoveResponse(
            text=resp.text or "",
            reasoning_tokens=getattr(usage, "thoughts_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
            truncated="MAX_TOKENS" in finish.upper() if finish else False,
            raw={
                "finish_reason": finish,
                "prompt_tokens": getattr(usage, "prompt_token_count", None),
                "told_budget": ctx.token_budget,
            },
        )
