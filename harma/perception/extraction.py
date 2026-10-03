"""
Harma Structured Extraction

Extracts schema-conforming structured JSON from text, documents, or observations.
Validates strictly against the requested schema to prevent malformed data from
entering downstream tools.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.perception.base import Confidence, Observation, StructuredObservation

log = get_logger(__name__)


class SchemaValidationError(Exception):
    """Raised when extracted data fails schema validation."""


class StructuredExtractor:
    """
    Safely extracts and validates structured data from unstructured observations.
    """

    def extract(
        self,
        source: str | Observation,
        schema: dict[str, Any],
        schema_name: str = "custom_schema",
    ) -> StructuredObservation:
        """
        Extract structured data conforming to schema.

        Args:
            source: Raw string or Observation object.
            schema: Dict defining required properties and types:
                    Example:
                    {
                        "type": "object",
                        "properties": {
                            "company": {"type": "string"},
                            "revenue": {"type": "number"},
                            "date": {"type": "string"}
                        },
                        "required": ["company", "revenue"]
                    }
            schema_name: Name of the schema for logging and tracing.

        Returns:
            StructuredObservation with validated data.

        Raises:
            SchemaValidationError if extracted data does not meet schema requirements.
        """
        text = source.content if isinstance(source, Observation) else str(source)
        data = self._extract_json_candidate(text, schema)
        self.validate_against_schema(data, schema)

        return StructuredObservation(
            content=json.dumps(data, indent=2),
            schema_name=schema_name,
            data=data,
            confidence=Confidence.HIGH,
            source="structured_extractor",
        )

    def _extract_json_candidate(self, text: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Attempt to parse JSON block or heuristically extract fields."""
        # Check for json fenced block
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Check for bare JSON object
        bare_match = re.search(r"(\{.*\})", text, re.DOTALL)
        if bare_match:
            try:
                return json.loads(bare_match.group(1))
            except json.JSONDecodeError:
                pass

        # Fallback heuristic: construct dictionary from properties
        properties = schema.get("properties", {})
        result: dict[str, Any] = {}
        for prop, prop_spec in properties.items():
            prop_type = prop_spec.get("type", "string")
            # Search for "prop: value" or "prop = value"
            pattern = rf"(?i)\b{prop}\b\s*[:=]\s*([^\n\r,]+)"
            m = re.search(pattern, text)
            if m:
                val_str = m.group(1).strip().strip('"\'')
                if prop_type in ("number", "integer"):
                    num_match = re.search(r"[-+]?\d*\.?\d+", val_str)
                    if num_match:
                        result[prop] = float(num_match.group(0)) if "." in num_match.group(0) else int(num_match.group(0))
                elif prop_type == "boolean":
                    result[prop] = val_str.lower() in ("true", "yes", "1")
                else:
                    result[prop] = val_str

        return result

    def validate_against_schema(self, data: dict[str, Any], schema: dict[str, Any]) -> None:
        """
        Validate that data satisfies required fields and types in schema.
        """
        if not isinstance(data, dict):
            raise SchemaValidationError(f"Expected dict from extraction, got {type(data).__name__}")

        required = schema.get("required", [])
        for field_name in required:
            if field_name not in data or data[field_name] is None:
                raise SchemaValidationError(f"Missing required schema field: '{field_name}'")

        properties = schema.get("properties", {})
        for field_name, value in data.items():
            if field_name in properties:
                expected_type = properties[field_name].get("type")
                if expected_type == "string" and not isinstance(value, str):
                    raise SchemaValidationError(
                        f"Field '{field_name}' must be string, got {type(value).__name__}"
                    )
                elif expected_type in ("number", "integer") and not isinstance(value, (int, float)):
                    raise SchemaValidationError(
                        f"Field '{field_name}' must be numeric, got {type(value).__name__}"
                    )
                elif expected_type == "boolean" and not isinstance(value, bool):
                    raise SchemaValidationError(
                        f"Field '{field_name}' must be boolean, got {type(value).__name__}"
                    )
                elif expected_type == "array" and not isinstance(value, list):
                    raise SchemaValidationError(
                        f"Field '{field_name}' must be list, got {type(value).__name__}"
                    )
