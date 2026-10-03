"""
Harma Evidence & Contradiction System

Defines evidence models, confidence levels, and contradiction handling
for verifying actions and managing conflicting observations.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.perception.base import Confidence

log = get_logger(__name__)


@dataclass
class Evidence:
    """
    Evidence piece gathered during or after tool execution to verify outcome.
    """
    source: str
    observation: str
    confidence: Confidence = Confidence.MEDIUM
    data: Any = None
    timestamp: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def __str__(self) -> str:
        return f"[{self.source.upper()} | {self.confidence.value}] {self.observation}"


@dataclass
class Contradiction:
    """
    Represents a detected contradiction between two evidence sources.
    """
    source_a: str
    source_b: str
    statement_a: str
    statement_b: str
    resolved: bool = False
    resolution: str = ""
    winning_source: Optional[str] = None


class ContradictionHandler:
    """
    Detects and resolves conflicting observations.
    Prioritizes evidence based on confidence hierarchy:
    VERY_HIGH > HIGH > MEDIUM > LOW > UNKNOWN.
    """

    def detect_contradiction(
        self,
        item_a: Evidence,
        item_b: Evidence,
    ) -> Optional[Contradiction]:
        """
        Check if two evidence statements represent a factual contradiction.
        """
        obs_a = item_a.observation.lower()
        obs_b = item_b.observation.lower()

        # Direct antonym/negation checks
        contradiction_pairs = [
            ("succeeded", "failed"),
            ("open", "closed"),
            ("success", "error"),
            ("found", "not found"),
            ("completed", "incomplete"),
            ("true", "false"),
            ("exists", "does not exist"),
        ]

        for word1, word2 in contradiction_pairs:
            if (word1 in obs_a and word2 in obs_b) or (word2 in obs_a and word1 in obs_b):
                return Contradiction(
                    source_a=item_a.source,
                    source_b=item_b.source,
                    statement_a=item_a.observation,
                    statement_b=item_b.observation,
                )

        return None

    def resolve(
        self,
        contradiction: Contradiction,
        evidence_a: Evidence,
        evidence_b: Evidence,
    ) -> Contradiction:
        """
        Resolve contradiction using confidence scores.
        If scores are tied, marks as unresolved/uncertain.
        """
        score_a = evidence_a.confidence.score
        score_b = evidence_b.confidence.score

        if score_a > score_b:
            contradiction.resolved = True
            contradiction.winning_source = evidence_a.source
            contradiction.resolution = (
                f"Resolved in favor of {evidence_a.source} "
                f"({evidence_a.confidence.value} > {evidence_b.confidence.value}): {evidence_a.observation}"
            )
            log.info("[CONTRADICTION] Resolved: %s", contradiction.resolution)
        elif score_b > score_a:
            contradiction.resolved = True
            contradiction.winning_source = evidence_b.source
            contradiction.resolution = (
                f"Resolved in favor of {evidence_b.source} "
                f"({evidence_b.confidence.value} > {evidence_a.confidence.value}): {evidence_b.observation}"
            )
            log.info("[CONTRADICTION] Resolved: %s", contradiction.resolution)
        else:
            contradiction.resolved = False
            contradiction.winning_source = None
            contradiction.resolution = (
                f"Uncertain: Equal confidence ({evidence_a.confidence.value}) "
                f"between '{evidence_a.source}' and '{evidence_b.source}'. Flagged for clarification."
            )
            log.warning("[CONTRADICTION] Unresolved: %s", contradiction.resolution)

        return contradiction
