"""
Harma Android Assistant Platform Architecture (Spec §39, §40, §41, §42)

Provides platform-supported VoiceInteractionService and VoiceInteractionSessionService
components and Python-Android Assistant IPC bridge.
"""

from harma.android.assistant.bridge import AndroidAssistantBridge

__all__ = ["AndroidAssistantBridge"]
