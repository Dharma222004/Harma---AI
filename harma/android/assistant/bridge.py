"""
Harma Android Assistant Bridge (Spec §39, §42, §43)

Connects Android VoiceInteractionService / Session to the single Harma Agent Runtime.
Ensures Android UI never executes independent agent logic; all instructions route
through the authoritative Harma Core engine.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, Optional

from harma.android.capability_layer import AndroidCapabilityLayer
from harma.android.permissions import AndroidPermissionManager
from harma.config.logging_config import get_logger
from harma.core.agent import HarmaAgent
from harma.core.environment import DeviceInfo, EnvironmentResolver, EnvironmentType, get_device_registry
from harma.core.input_normalizer import HarmaRequest, InputModality, InputNormalizer
from harma.voice.models import VoiceCommand, VoiceState
from harma.voice.state_machine import VoiceStateMachine

log = get_logger(__name__)


class AndroidAssistantBridge:
    """
    Bridge connecting Android VoiceInteractionService / Session to Harma Core.
    Translates hotword / session events into normalized HarmaRequests and
    invokes the authoritative HarmaAgent.
    """

    def __init__(
        self,
        agent: HarmaAgent,
        capability_layer: Optional[AndroidCapabilityLayer] = None,
        permission_manager: Optional[AndroidPermissionManager] = None,
        device_id: str = "android_primary",
    ) -> None:
        self.agent = agent
        self.capability_layer = capability_layer or AndroidCapabilityLayer()
        self.permission_manager = permission_manager or AndroidPermissionManager()
        self.normalizer = InputNormalizer()
        self.voice_state = VoiceStateMachine()
        self.device_id = device_id
        self._session_active = False
        self._active_task: Optional[asyncio.Task] = None

        # Register device in central registry
        registry = get_device_registry()
        registry.register(
            DeviceInfo(
                device_id=self.device_id,
                device_type=EnvironmentType.ANDROID,
                name="Android Device",
                capabilities=[
                    "flashlight",
                    "wifi",
                    "mobile_data",
                    "bluetooth",
                    "volume",
                    "navigate",
                    "camera",
                    "lock",
                    "apps",
                    "browser",
                ],
                is_connected=True,
                is_active=True,
                platform="android",
            )
        )

        log.info("[ANDROID-ASSISTANT] Bridge initialized for device=%s", self.device_id)

    # ── Session Lifecycle (VoiceInteractionSession) ──────────────────────────

    def on_hotword_detected(self) -> None:
        """Called when hardware/DSP wake-word detector fires 'Hey Harma'."""
        log.info("[ANDROID-ASSISTANT] Hotword detected on Android device")
        self.voice_state.try_transition(VoiceState.WAKE_DETECTED)
        self._session_active = True

    def on_session_show(self) -> None:
        """Called when Assistant session overlay appears."""
        self._session_active = True
        self.voice_state.try_transition(VoiceState.LISTENING)

    def on_session_hide(self) -> None:
        """Called when Assistant overlay dismisses."""
        self._session_active = False
        self.voice_state.try_transition(VoiceState.IDLE)

    def on_barge_in(self) -> None:
        """Called when user speaks 'Stop' or interrupts speech/action."""
        log.info("[ANDROID-ASSISTANT] Barge-in requested on Android")
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()
        if hasattr(self.agent, "cancel"):
            self.agent.cancel()
        self.voice_state.try_transition(VoiceState.INTERRUPTED)

    # ── Command Execution ────────────────────────────────────────────────────

    async def handle_user_utterance(
        self,
        transcript: str,
        confidence: float = 1.0,
        language: str = "en",
    ) -> Dict[str, Any]:
        """
        Process a spoken or typed utterance from the Android assistant interface.
        Returns structured payload for the Android session UI/TTS.
        """
        self.voice_state.try_transition(VoiceState.UNDERSTANDING)

        # 1. Normalize request
        req: HarmaRequest = self.normalizer.normalize(
            raw_text=transcript,
            modality=InputModality.VOICE,
            confidence=confidence,
            language=language,
        )

        # 2. Control intent check (Spec §6, §30)
        if req.is_control_command and req.control_intent == "cancel":
            self.on_barge_in()
            return {
                "status": "cancelled",
                "speech": "Cancelled.",
                "visual_card": {"title": "Cancelled", "detail": "Assistant stopped."},
            }

        # 3. Consequential / Low-confidence safety gate (Spec §31, §32)
        if req.requires_confirmation:
            return {
                "status": "needs_confirmation",
                "speech": f"This action is consequential: {req.clean_goal}. Proceed?",
                "confirmation_prompt": req.clean_goal,
                "reason": req.confirmation_reason,
            }

        # 4. Authoritative execution via single Harma Agent Runtime (Spec §1, §42, §43)
        self.voice_state.try_transition(VoiceState.EXECUTING)
        try:
            self._active_task = asyncio.create_task(
                self.agent.run(req.clean_goal, request_id=req.request_id)
            )
            response = await self._active_task
            self.voice_state.try_transition(VoiceState.SPEAKING)

            # Verification check (Spec §29)
            meta = getattr(self.agent, "last_execution_meta", {}) or {}
            status = meta.get("status", "completed")
            verification = meta.get("verification", {})
            verif_status = ""
            if isinstance(verification, dict):
                verif_status = str(verification.get("status", "")).lower()
            elif isinstance(verification, str):
                verif_status = verification.lower()

            tool_calls = meta.get("tool_calls", [])

            # Real state verification check
            if status == "failed":
                speech = "I couldn't complete the requested action."
            elif tool_calls and verif_status in ("unverified", "failed"):
                speech = "I performed the action, but I couldn't verify the result."
            else:
                speech = response if len(response) <= 120 and "\n" not in response else "Done."

            return {
                "status": "success" if status != "failed" else "failed",
                "speech": speech,
                "raw_response": response,
                "execution_meta": meta,
            }

        except asyncio.CancelledError:
            self.voice_state.try_transition(VoiceState.INTERRUPTED)
            return {"status": "cancelled", "speech": "Cancelled."}
        except Exception as exc:
            log.exception("[ANDROID-ASSISTANT] Execution error: %s", exc)
            self.voice_state.try_transition(VoiceState.ERROR)
            return {"status": "error", "speech": "Sorry, an error occurred."}
        finally:
            self._active_task = None
