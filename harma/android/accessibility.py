"""
Harma Android Accessibility & UI Hierarchy Parser

Parses Android uiautomator dump XML output into structured UIElement trees.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional

from harma.android.models import Bounds, UIElement
from harma.config.logging_config import get_logger

log = get_logger(__name__)


class UIHierarchyParser:
    """
    Parses Android uiautomator XML dump into normalized UIElement hierarchy.
    """

    def parse(self, xml_content: str) -> list[UIElement]:
        """
        Parse XML string and return flat list of all UIElement nodes.
        """
        if not xml_content or not xml_content.strip():
            return []

        try:
            root = ET.fromstring(xml_content.strip())
        except ET.ParseError as exc:
            log.warning("XML parse error on Android UI hierarchy: %s", exc)
            return []

        elements: list[UIElement] = []
        node_id_counter = 0

        def _traverse(node: ET.Element, parent_id: Optional[str] = None) -> Optional[UIElement]:
            nonlocal node_id_counter
            if node.tag != "node":
                for child in node:
                    _traverse(child, parent_id)
                return None

            node_id_counter += 1
            internal_id = f"el_{node_id_counter}"

            res_id = node.attrib.get("resource-id", "").strip()
            role = node.attrib.get("class", "").strip()
            text = node.attrib.get("text", "").strip()
            desc = node.attrib.get("content-desc", "").strip()
            bounds_str = node.attrib.get("bounds", "[0,0][0,0]")
            pkg = node.attrib.get("package", "").strip()

            clickable = node.attrib.get("clickable", "false").lower() == "true"
            enabled = node.attrib.get("enabled", "true").lower() == "true"
            checked = node.attrib.get("checked", "false").lower() == "true"
            checkable = node.attrib.get("checkable", "false").lower() == "true"
            focused = node.attrib.get("focused", "false").lower() == "true"
            selected = node.attrib.get("selected", "false").lower() == "true"
            scrollable = node.attrib.get("scrollable", "false").lower() == "true"
            long_clickable = node.attrib.get("long-clickable", "false").lower() == "true"
            password = node.attrib.get("password", "false").lower() == "true"

            bounds = Bounds.from_str(bounds_str)

            el = UIElement(
                id=res_id or internal_id,
                role=role,
                text=text,
                content_description=desc,
                bounds=bounds,
                clickable=clickable,
                enabled=enabled,
                checked=checked,
                checkable=checkable,
                focused=focused,
                selected=selected,
                scrollable=scrollable,
                long_clickable=long_clickable,
                password=password,
                package=pkg,
                parent_id=parent_id,
            )

            # Recurse children
            for child in node:
                child_el = _traverse(child, parent_id=el.id)
                if child_el:
                    el.children.append(child_el)

            elements.append(el)
            return el

        for child in root:
            _traverse(child)

        return elements

    def build_summary(self, elements: list[UIElement]) -> str:
        """
        Generate a concise, LLM-friendly textual summary of the visible UI elements.
        """
        if not elements:
            return "Screen is empty or hierarchy unavailable."

        lines: list[str] = []
        interactive = [el for el in elements if el.clickable or el.checkable or el.scrollable or el.text]

        for el in interactive[:25]:  # Limit to top 25 prominent elements
            label_parts: list[str] = []
            if el.text:
                label_parts.append(f'text="{el.text}"')
            if el.content_description:
                label_parts.append(f'desc="{el.content_description}"')
            if el.id and not el.id.startswith("el_"):
                # show short ID
                short_id = el.id.split("/")[-1]
                label_parts.append(f"id={short_id}")

            state_parts: list[str] = []
            if el.checked:
                state_parts.append("checked")
            if el.focused:
                state_parts.append("focused")
            if el.clickable:
                state_parts.append("clickable")

            desc = ", ".join(label_parts)
            state = f" ({', '.join(state_parts)})" if state_parts else ""
            center = f"at ({el.center[0]}, {el.center[1]})"

            lines.append(f"- [{el.simple_role}] {desc} {state} {center}")

        return "\n".join(lines)
