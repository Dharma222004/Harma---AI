"""
NVIDIA Provider Module

Exposes the NVIDIA LLM adapter implementation behind the LLMProvider abstraction.
"""

from harma.llm.adapters.nvidia_adapter import NVIDIAAdapter, NvidiaAdapter

__all__ = ["NVIDIAAdapter", "NvidiaAdapter"]
