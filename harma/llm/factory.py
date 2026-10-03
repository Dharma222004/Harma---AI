"""
LLM Provider Factory

Returns the correct LLMProvider instance based on the configured provider name.
Adding a new provider only requires:
  1. Writing an adapter in harma/llm/adapters/
  2. Adding an entry to PROVIDER_MAP below
"""

from __future__ import annotations

from harma.config.settings import config
from harma.llm.provider import LLMProvider


PROVIDER_MAP = {
    "nvidia":    "harma.llm.adapters.nvidia_adapter.NVIDIAAdapter",
    "openai":    "harma.llm.adapters.openai_adapter.OpenAIAdapter",
    "gemini":    "harma.llm.adapters.gemini_adapter.GeminiAdapter",
    "claude":    "harma.llm.adapters.claude_adapter.ClaudeAdapter",
    "anthropic": "harma.llm.adapters.claude_adapter.ClaudeAdapter",
    "groq":      "harma.llm.adapters.groq_adapter.GroqAdapter",
    # Add more: "ollama": "harma.llm.adapters.ollama_adapter.OllamaAdapter"
}


_PROVIDER_CACHE: dict[str, LLMProvider] = {}


def get_provider(provider_name: str | None = None, force_new: bool = False) -> LLMProvider:
    """
    Instantiate and return the requested LLM provider, caching singletons for session reuse.

    Args:
        provider_name: Override the configured provider. Falls back to
                       config.llm.provider if None.
        force_new: If True, bypass the provider cache and instantiate fresh.

    Returns:
        A ready-to-use LLMProvider instance.

    Raises:
        ValueError: If the provider name is not registered.
        ImportError: If the required SDK for the provider is not installed.
    """
    name = (provider_name or config.llm.provider).lower()

    if not force_new and config.performance.session_reuse and name in _PROVIDER_CACHE:
        return _PROVIDER_CACHE[name]

    dotted_path = PROVIDER_MAP.get(name)
    if not dotted_path:
        available = ", ".join(PROVIDER_MAP.keys())
        raise ValueError(
            f"Unknown LLM provider '{name}'. "
            f"Available: {available}\n"
            f"To add a new provider, register it in harma/llm/factory.py."
        )

    module_path, class_name = dotted_path.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    instance = cls()
    _PROVIDER_CACHE[name] = instance
    return instance
