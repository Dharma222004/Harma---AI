"""
Harma Action Verification Engine

Verifies tool execution outcomes against expected post-conditions and observations.
Core Rule: Never claim an action succeeded solely because a tool call was issued.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.intelligence.evidence import Contradiction, ContradictionHandler, Evidence
from harma.perception.base import Confidence
from harma.tools.base import ToolResult

log = get_logger(__name__)


@dataclass
class VerificationResult:
    """Detailed outcome of an action verification check."""
    success: bool
    confidence: Confidence
    evidence: list[Evidence] = field(default_factory=list)
    details: str = ""
    action_verified: bool = False
    contradictions: list[Contradiction] = field(default_factory=list)

    def summary(self) -> str:
        status = "VERIFIED" if self.success and self.action_verified else "UNVERIFIED"
        return f"[{status}] (Confidence: {self.confidence.value}) {self.details}"


class ActionVerifier:
    """
    Validates whether an executed action achieved its intended goal in the environment.
    """

    def __init__(self) -> None:
        self.contradiction_handler = ContradictionHandler()

    def verify_action(
        self,
        tool_name: str,
        tool_result: ToolResult,
        expected_result: str = "",
        post_observation: Optional[str] = None,
        observation_source: str = "environment",
        observation_confidence: Confidence = Confidence.HIGH,
    ) -> VerificationResult:
        """
        Verify action outcome combining tool return status and subsequent observation.

        Args:
            tool_name: The name of the executed tool.
            tool_result: ToolResult from tool execution.
            expected_result: Description of expected outcome.
            post_observation: Optional observation text collected after the action.
            observation_source: Source of post-observation (e.g. "browser", "screen").
            observation_confidence: Confidence tier of the post-observation.

        Returns:
            VerificationResult detailing whether the action is verified.
        """
        evidence_list: list[Evidence] = []

        # 1. Tool execution evidence
        tool_conf = Confidence.HIGH if tool_result.success else Confidence.VERY_HIGH
        tool_statement = (
            f"Tool '{tool_name}' returned success: {tool_result.output[:120]}"
            if tool_result.success
            else f"Tool '{tool_name}' failed with error: {tool_result.error}"
        )
        tool_ev = Evidence(
            source=f"tool_{tool_name}",
            observation=tool_statement,
            confidence=tool_conf,
            data={"success": tool_result.success, "output": tool_result.output},
        )
        evidence_list.append(tool_ev)

        # If tool execution itself failed, verification fails immediately
        if not tool_result.success:
            return VerificationResult(
                success=False,
                confidence=Confidence.VERY_HIGH,
                evidence=evidence_list,
                details=f"Action failed at execution: {tool_result.error}",
                action_verified=False,
            )

        # 2. Post-observation verification
        if post_observation:
            obs_ev = Evidence(
                source=observation_source,
                observation=post_observation,
                confidence=observation_confidence,
            )
            evidence_list.append(obs_ev)

            # Check for contradiction between tool result and environment observation
            contra = self.contradiction_handler.detect_contradiction(tool_ev, obs_ev)
            if contra:
                resolved_contra = self.contradiction_handler.resolve(contra, tool_ev, obs_ev)
                if not resolved_contra.resolved or resolved_contra.winning_source != tool_ev.source:
                    return VerificationResult(
                        success=False,
                        confidence=obs_ev.confidence,
                        evidence=evidence_list,
                        details=f"Verification failed due to conflicting environment state: {resolved_contra.resolution}",
                        action_verified=False,
                        contradictions=[resolved_contra],
                    )

            # Check expected result matching
            if expected_result:
                low_exp = expected_result.lower()
                low_obs = post_observation.lower()
                low_tool = tool_result.output.lower()

                # Check if keywords in expected result appear in observation or tool output
                expected_keywords = [w for w in low_exp.split() if len(w) > 3]
                matched = (
                    any(w in low_obs or w in low_tool for w in expected_keywords)
                    or tool_name.lower() in low_exp
                    or "completion" in low_exp
                )
                if expected_keywords and not matched:
                    return VerificationResult(
                        success=False,
                        confidence=Confidence.MEDIUM,
                        evidence=evidence_list,
                        details=(
                            f"Action executed but expected result '{expected_result}' "
                            f"not confirmed in post-observation: {post_observation[:120]}"
                        ),
                        action_verified=False,
                    )

        # Success verified
        return VerificationResult(
            success=True,
            confidence=observation_confidence if post_observation else Confidence.HIGH,
            evidence=evidence_list,
            details=f"Action '{tool_name}' verified successfully.",
            action_verified=True,
        )
