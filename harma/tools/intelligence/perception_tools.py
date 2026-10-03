"""
Harma Multimodal Perception Tools — Phase 9

Includes:
  • observe_screen          — Perceives visual UI and window state on the desktop (SAFE)
  • parse_document          — Reads, summarizes, and answers questions on local files (SAFE)
  • extract_structured_data — Extracts schema-validated JSON from text/observations (SAFE)
"""

from __future__ import annotations

import json
from typing import Any

from harma.perception.document import DocumentParser
from harma.perception.extraction import SchemaValidationError, StructuredExtractor
from harma.perception.screen_understanding import ScreenPerception
from harma.tools.base import BaseTool, PermissionLevel, ToolResult


class PerceiveScreenTool(BaseTool):
    """Analyze current desktop display using multimodal vision and accessibility hierarchy."""

    name = "perceive_screen"
    description = (
        "Inspects what is currently visible on the computer screen. "
        "Returns active application name, visible text, detected buttons, and error alerts."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional search term or target element to look for on screen.",
            },
        },
        "required": [],
    }

    def __init__(self, screen_perception: ScreenPerception | None = None) -> None:
        self.screen_perception = screen_perception or ScreenPerception()

    async def execute(self, query: str = "", **kwargs: Any) -> ToolResult:
        obs = await self.screen_perception.perceive_screen(query=query)
        return ToolResult(
            success=True,
            output=obs.content,
            data={
                "active_app": obs.active_app,
                "window_title": obs.window_title,
                "confidence": obs.confidence.value,
                "elements_count": len(obs.detected_elements),
            },
        )


class ParseDocumentTool(BaseTool):
    """Parse, summarize, or query content from a local document (TXT, MD, PDF, etc.)."""

    name = "parse_document"
    description = (
        "Reads a local document, produces a concise summary, and retrieves answers to specific queries "
        "while strictly respecting context token budgets."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the document file (or raw document text).",
            },
            "query": {
                "type": "string",
                "description": "Optional question or topic to search within the document.",
            },
        },
        "required": ["file_path"],
    }

    def __init__(self, parser: DocumentParser | None = None) -> None:
        self.parser = parser or DocumentParser()

    async def execute(self, file_path: str, query: str = "", **kwargs: Any) -> ToolResult:
        if query:
            ans = self.parser.query_document(file_path, query)
            return ToolResult(success=True, output=ans)

        obs = self.parser.parse_document(file_path)
        return ToolResult(
            success=True,
            output=obs.content,
            data={
                "file_type": obs.file_type,
                "page_count": obs.page_count,
                "summary": obs.summary,
                "entities": obs.entities,
            },
        )


class ExtractStructuredDataTool(BaseTool):
    """Safely extracts structured, schema-validated JSON from unstructured text."""

    name = "extract_structured_data"
    description = (
        "Extracts structured data conforming strictly to a target JSON Schema. "
        "Validates field types and rejects malformed outputs."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "source_text": {
                "type": "string",
                "description": "The raw unstructured text or observation to extract data from.",
            },
            "schema_json": {
                "type": "string",
                "description": "JSON string representing the JSON schema with required fields and types.",
            },
        },
        "required": ["source_text", "schema_json"],
    }

    def __init__(self, extractor: StructuredExtractor | None = None) -> None:
        self.extractor = extractor or StructuredExtractor()

    async def execute(self, source_text: str, schema_json: str, **kwargs: Any) -> ToolResult:
        try:
            schema = json.loads(schema_json) if isinstance(schema_json, str) else schema_json
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"Invalid JSON schema: {exc}")

        try:
            res = self.extractor.extract(source_text, schema)
            return ToolResult(
                success=True,
                output=res.content,
                data=res.data,
            )
        except SchemaValidationError as sve:
            return ToolResult(
                success=False,
                output="",
                error=f"Schema validation failed: {sve}",
            )
