"""
Harma Integrations — Tool Discovery & Search Engine

Enables dynamic tool discovery and selective loading so the LLM prompt is not
polluted with dozens of unused external tool schemas on every request.
"""

from __future__ import annotations

import re
from typing import Optional

from harma.integrations.models import IntegrationToolDef
from harma.integrations.registry import IntegrationRegistry


class ToolSearchEngine:
    """
    Search index matching user queries against available integration tools
    to dynamically retrieve relevant tools.
    """

    def __init__(self, registry: IntegrationRegistry) -> None:
        self.registry = registry

    def find_relevant_tools(
        self,
        query: str,
        server_name: Optional[str] = None,
        top_k: int = 5,
    ) -> list[IntegrationToolDef]:
        """
        Rank and return the top-K relevant integration tools matching the user query.
        """
        all_tools = self.registry.list_tools(server_name=server_name)
        if not all_tools:
            return []

        query_tokens = set(re.findall(r"\w+", query.lower()))
        if not query_tokens:
            return all_tools[:top_k]

        scored: list[tuple[float, IntegrationToolDef]] = []
        for tool in all_tools:
            score = self._score_tool(tool, query_tokens, query.lower())
            if score > 0:
                scored.append((score, tool))

        # Sort descending by relevance score
        scored.sort(key=lambda x: x[0], reverse=True)
        return [tool for _, tool in scored[:top_k]]

    def _score_tool(self, tool: IntegrationToolDef, query_tokens: set[str], query_raw: str) -> float:
        score = 0.0
        name_parts = set(re.findall(r"\w+", tool.name.lower()))
        desc_tokens = set(re.findall(r"\w+", tool.description.lower()))

        # Direct server name hit (e.g. "github" in query)
        if tool.server_name.lower() in query_tokens:
            score += 5.0

        # Exact tool name token overlap
        name_matches = query_tokens.intersection(name_parts)
        score += len(name_matches) * 3.0

        # Description token overlap
        desc_matches = query_tokens.intersection(desc_tokens)
        score += len(desc_matches) * 1.0

        # Substring hits in tool name
        for token in query_tokens:
            if token in tool.name.lower():
                score += 2.0

        # Capability category match
        if tool.capability.value in query_tokens:
            score += 2.0

        return score
