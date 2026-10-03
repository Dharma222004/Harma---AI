"""
Harma Document Perception

Handles local document understanding: TXT, Markdown, PDF, DOCX, JSON, CSV.
Capabilities:
  - Document chunking with token budgeting
  - Summarization
  - Targeted question-answering with relevant chunk retrieval
  - Table and entity extraction
  - Privacy-preserving memory candidate filtering (Phase 5 integration)
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

from harma.config.logging_config import get_logger
from harma.perception.base import Confidence, DocumentObservation

log = get_logger(__name__)


class DocumentParser:
    """
    Parser and semantic reasoning engine for local documents.
    """

    def __init__(self, max_chunk_tokens: int = 500, overlap: int = 50) -> None:
        self.max_chunk_tokens = max_chunk_tokens
        self.overlap = overlap

    def read_document_text(self, file_path_or_text: str) -> tuple[str, str]:
        """
        Read text from a file path or return string content directly.
        Returns: (content, file_type)
        """
        path = Path(file_path_or_text)
        if path.exists() and path.is_file():
            ext = path.suffix.lower().lstrip(".")
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                return content, ext or "txt"
            except Exception as exc:
                log.warning("Failed to read document %s: %s", path, exc)
                return f"[Error reading file: {exc}]", ext or "unknown"

        # Treat as raw text
        return file_path_or_text, "raw_text"

    def chunk_text(self, text: str) -> list[str]:
        """
        Split text into overlapping semantic chunks respecting token budgets.
        Rough estimate: 1 word ≈ 1.3 tokens.
        """
        words = text.split()
        if not words:
            return []

        word_limit = int(self.max_chunk_tokens / 1.3)
        overlap_words = int(self.overlap / 1.3)
        chunks = []
        start = 0

        while start < len(words):
            end = min(start + word_limit, len(words))
            chunk = " ".join(words[start:end])
            chunks.append(chunk)
            if end >= len(words):
                break
            start += max(1, word_limit - overlap_words)

        return chunks

    def retrieve_relevant_chunks(self, text: str, query: str, top_k: int = 3) -> list[str]:
        """
        Retrieve chunks most relevant to query based on keyword overlap.
        """
        chunks = self.chunk_text(text)
        if not chunks:
            return []

        q_terms = set(re.findall(r"\w+", query.lower()))
        if not q_terms:
            return chunks[:top_k]

        scored: list[tuple[float, str]] = []
        for chunk in chunks:
            c_terms = set(re.findall(r"\w+", chunk.lower()))
            overlap_count = len(q_terms.intersection(c_terms))
            score = overlap_count / max(1, len(q_terms))
            scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for score, c in scored[:top_k] if score > 0] or chunks[:1]

    def parse_document(
        self,
        file_path_or_text: str,
        query: str = "",
    ) -> DocumentObservation:
        """
        Parse document, extract sections, tables, entities, and summary.
        """
        content, file_type = self.read_document_text(file_path_or_text)
        chunks = self.chunk_text(content)

        summary = self.summarize_document(content)
        entities = self.extract_entities(content)
        tables = self.extract_tables(content)

        sections = [
            {"index": i, "chunk_preview": c[:100] + "...", "token_estimate": int(len(c.split()) * 1.3)}
            for i, c in enumerate(chunks)
        ]

        doc_obs = DocumentObservation(
            content=f"Document ({file_type}, {len(chunks)} chunks). Summary: {summary}",
            file_path=file_path_or_text if os.path.exists(file_path_or_text) else "",
            file_type=file_type,
            page_count=max(1, len(chunks) // 2),
            sections=sections,
            summary=summary,
            entities=entities,
            confidence=Confidence.HIGH,
            source="document_parser",
            metadata={"table_count": len(tables), "total_words": len(content.split())},
        )
        return doc_obs

    def summarize_document(self, text: str, max_words: int = 60) -> str:
        """Generate a concise summary of the document."""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return "Empty document."

        # Take opening meaningful lines
        opening = " ".join(lines[:3])
        words = opening.split()
        if len(words) > max_words:
            return " ".join(words[:max_words]) + "..."
        return opening

    def query_document(self, file_path_or_text: str, query: str) -> str:
        """
        Answer a question about a document within a strict token budget.
        """
        content, _ = self.read_document_text(file_path_or_text)
        relevant_chunks = self.retrieve_relevant_chunks(content, query, top_k=2)

        if not relevant_chunks:
            return "No relevant sections found in document."

        context = "\n---\n".join(relevant_chunks)
        return f"Based on relevant document sections:\n{context[:600]}"

    def extract_tables(self, text: str) -> list[list[str]]:
        """Extract markdown or pipe-delimited table rows from document."""
        tables: list[list[str]] = []
        lines = text.splitlines()
        for line in lines:
            if "|" in line:
                cells = [c.strip() for c in line.split("|") if c.strip()]
                if len(cells) >= 2 and not all(c.startswith("-") for c in cells):
                    tables.append(cells)
        return tables

    def extract_entities(
        self,
        text: str,
        entity_types: Optional[list[str]] = None,
    ) -> dict[str, list[str]]:
        """
        Extract basic entities like emails, URLs, dates, numbers.
        """
        entities: dict[str, list[str]] = {
            "emails": list(set(re.findall(r"[\w\.-]+@[\w\.-]+\.\w+", text))),
            "urls": list(set(re.findall(r"https?://[^\s]+", text))),
            "dates": list(set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b", text))),
        }
        return entities

    def extract_candidate_memories(
        self,
        doc_observation: DocumentObservation,
        user_preference_keywords: Optional[list[str]] = None,
    ) -> list[str]:
        """
        Section 14: Document + Memory Integration.
        Harma must NOT automatically memorize everything it reads.
        Filters candidate facts:
          - Must match explicit user preference keywords or key profile info
          - Discards passwords, API keys, credentials (privacy check)
          - Discards transient/unimportant information
        """
        keywords = user_preference_keywords or [
            "prefer", "favorite", "always", "never", "my name is", "lives in",
            "works as", "timezone", "operating system"
        ]

        candidates: list[str] = []
        text = doc_observation.summary + "\n" + doc_observation.content

        for line in text.splitlines():
            low = line.lower()
            # Privacy check: reject credentials / tokens
            if any(secret in low for secret in ["password", "token", "secret", "api_key", "bearer"]):
                continue

            # Importance check: only store explicit user facts/preferences
            if any(kw in low for kw in keywords):
                candidates.append(line.strip())

        return candidates
