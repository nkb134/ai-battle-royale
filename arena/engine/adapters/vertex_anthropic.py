"""Claude on Vertex AI. §5.1, §6.2.

Budget enforcement uses the native thinking budget where it exists, with `max_tokens`
set above it so the closing `<move>` tag always fits.

One provider constraint shapes the whole design here: Anthropic's extended thinking
requires `budget_tokens >= 1024`. A pacing budget below that cannot be expressed as a
thinking budget at all, so thinking is switched off and the budget becomes a plain
`max_tokens` cap. That is not a workaround — it is exactly the intended behaviour in
panic mode (§6.3), where the cap is 250 tokens and the model is being told to stop
reasoning and move.
"""

from __future__ import annotations

import os

from arena.engine.adapters.base import BaseAdapter, with_backoff
from arena.engine.prompts import render
from arena.engine.types import MoveContext, RawMoveResponse

MIN_THINKING_BUDGET = 1024


class VertexAnthropicAdapter(BaseAdapter):
    def __init__(
        self,
        name: str,
        model_string: str,
        *,
        project: str | None = None,
        location: str = "us-central1",
        thinking: bool = True,
        temperature: float = 0.0,
        **kw,
    ):
        super().__init__(name, model_string, thinking=thinking, **kw)
        self.project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self.location = location
        self.temperature = temperature
        self._client = None

    def _get_client(self):
        if self._client is None:
            from anthropic import AsyncAnthropicVertex

            self._client = AsyncAnthropicVertex(
                project_id=self.project, region=self.location
            )
        return self._client

    async def move(self, ctx: MoveContext) -> RawMoveResponse:
        prompt = render(ctx)
        client = self._get_client()

        budget = ctx.token_budget
        use_thinking = self.thinking and budget >= MIN_THINKING_BUDGET

        # Anthropic also counts thinking inside max_tokens, so the ceiling has to
        # clear the thinking budget by a whole short answer, not just the tag.
        kwargs: dict = {
            "model": self.model_string,
            "max_tokens": ctx.max_output_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if use_thinking:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            # Extended thinking requires the default temperature.
        else:
            kwargs["temperature"] = self.temperature  # §5.1 — temperature 0

        async def call():
            return await client.messages.create(**kwargs)

        msg = await with_backoff(call, what=f"anthropic:{self.model_string}")

        text = "".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        )
        thinking_text = "".join(
            getattr(block, "thinking", "")
            for block in msg.content
            if getattr(block, "type", "") == "thinking"
        )
        usage = getattr(msg, "usage", None)
        output_tokens = getattr(usage, "output_tokens", None)

        return RawMoveResponse(
            text=text,
            # Anthropic bills thinking inside output_tokens and does not break it out,
            # so reasoning is only what is left once the visible answer is removed.
            reasoning_tokens=output_tokens,
            output_tokens=output_tokens,
            truncated=getattr(msg, "stop_reason", None) == "max_tokens",
            raw={
                "stop_reason": getattr(msg, "stop_reason", None),
                "thinking": thinking_text,
                "thinking_enabled": use_thinking,
                "input_tokens": getattr(usage, "input_tokens", None),
            },
        )
