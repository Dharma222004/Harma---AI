# Harma Voice Package — Phase 4
#
# Voice is an interface layer only.
# It does NOT contain business logic.
# All commands flow into the existing Agent Core.
#
# Public API:
#   from harma.voice.manager import VoiceManager
#   from harma.voice.models import AudioState, VoiceCommand
#   from harma.voice.exceptions import VoiceError

from __future__ import annotations
