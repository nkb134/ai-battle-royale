"""Adapter registry. One file per provider, all implementing ModelAdapter (§5.1)."""

from __future__ import annotations

from arena.engine.types import ModelAdapter


def build_adapter(model_id: str, spec: dict, *, vertex: dict | None = None, **overrides):
    """Construct the adapter for a configured model.

    `spec` is the model's entry in arena.yaml. Model strings are pinned dated versions;
    a spec asking for "latest" is refused rather than silently resolved (§5.1).
    """
    provider = spec.get("provider")
    model_string = spec.get("model_string", "")
    if "latest" in model_string.lower():
        raise ValueError(
            f"{model_id}: model_string {model_string!r} is not pinned. "
            "§5.1 requires an exact dated version."
        )

    vertex = vertex or {}
    identity_keys = {"provider", "model_string", "display_name", "active", "tokens_per_sec"}
    kw = {k: v for k, v in spec.items() if k not in identity_keys}
    kw.update(overrides)

    if provider == "mock":
        from arena.engine.adapters.mock import MockAdapter

        # `tokens_per_sec` in the spec is the *calibrated* figure the pacing controller
        # trusts. `actual_tokens_per_sec` lets a mock generate slower than that, which
        # is how stale calibration is reproduced (§6.3).
        actual = kw.pop("actual_tokens_per_sec", None)
        kw.setdefault("tokens_per_sec", actual or spec.get("tokens_per_sec", 120.0))
        return MockAdapter(model_id, model_string, **kw)

    if provider == "vertex_anthropic":
        from arena.engine.adapters.vertex_anthropic import VertexAnthropicAdapter

        return VertexAnthropicAdapter(
            model_id,
            model_string,
            project=vertex.get("project"),
            location=vertex.get("location", "us-central1"),
            **kw,
        )

    if provider == "vertex_gemini":
        from arena.engine.adapters.vertex_gemini import VertexGeminiAdapter

        return VertexGeminiAdapter(
            model_id,
            model_string,
            project=vertex.get("project"),
            location=vertex.get("location", "us-central1"),
            **kw,
        )

    if provider in {"vertex_openai", "openai"}:
        from arena.engine.adapters.openai_api import OpenAIAdapter

        return OpenAIAdapter(
            model_id,
            model_string,
            vertex=(provider == "vertex_openai"),
            project=vertex.get("project"),
            location=vertex.get("location", "us-central1"),
            **kw,
        )

    raise ValueError(f"{model_id}: unknown provider {provider!r}")


__all__ = ["ModelAdapter", "build_adapter"]
