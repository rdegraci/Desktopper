"""Named LLM providers. Secrets stay in .env."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url: str
    default_model: str
    token_field: str
    json_object: bool
    reasoning: bool
    cache_header: str | None
    cache_key: str | None
    env_keys: tuple[str, ...]


XAI = ProviderSpec(
    name="xai",
    base_url="https://api.x.ai/v1",
    default_model="grok-4.6",
    token_field="max_completion_tokens",
    json_object=True,
    reasoning=True,
    cache_header="x-grok-conv-id",
    cache_key="desktopper-intent",
    env_keys=("LLM_API_KEY", "XAI_API_KEY"),
)

OPENAI_COMPATIBLE = ProviderSpec(
    name="openai_compatible",
    base_url="http://127.0.0.1:11434/v1",
    default_model="llama3.2",
    token_field="max_tokens",
    json_object=False,
    reasoning=False,
    cache_header=None,
    cache_key=None,
    env_keys=("LLM_API_KEY",),
)

PROVIDERS: dict[str, ProviderSpec] = {
    "xai": XAI,
    "grok": XAI,
    "openai_compatible": OPENAI_COMPATIBLE,
    "ollama": OPENAI_COMPATIBLE,
}

KNOWN_PROVIDER_NAMES = ("xai", "openai_compatible")
REASONING_EFFORTS = ("low", "medium", "high", "xhigh")


class UnknownLlmProviderError(Exception):
    error_code = "unknown_llm_provider"

    def __init__(self, name: str) -> None:
        supported = ", ".join(KNOWN_PROVIDER_NAMES)
        super().__init__(
            f"Unknown LLM provider {name!r}. Supported: {supported}."
        )
        self.name = name


def resolve_provider(name: str | None) -> ProviderSpec:
    key = (name or "").strip().lower()
    if not key:
        return OPENAI_COMPATIBLE
    spec = PROVIDERS.get(key)
    if spec is None:
        raise UnknownLlmProviderError(key)
    return spec


def pick_api_key(env: dict[str, str], spec: ProviderSpec) -> str:
    for key in spec.env_keys:
        value = (env.get(key) or "").strip()
        if value:
            return value
    return ""
