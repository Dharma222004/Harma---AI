"""
Tavily Live Web Search & Intelligence Synthesizer.
Provides real-time web search capabilities using Tavily API,
structured and formatted using Harma's active LLM (NVIDIA NIM).
"""

from __future__ import annotations

import os
import re
from typing import Any, List, Optional
import httpx

from harma.config.logging_config import get_logger
from harma.llm.provider import LLMProvider, Message, Role

log = get_logger(__name__)

_DEFAULT_TAVILY_KEY = "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"
_TAVILY_ENDPOINT = "https://api.tavily.com/search"

# Keywords that indicate the user query seeks current / live web data
_LIVE_SEARCH_PATTERNS = [
    r"\b(latest|news|today|tonight|current|currently|weather|forecast|score|match|game)\b",
    r"\b(price|stock|market|crypto|valuation|bitcoin|btc|eth)\b",
    r"\b(update|recent|recently|happened|happening|trending|events?)\b",
    r"\b(who is|what is|where is|when is|why did|how is)\b",
    r"\b(search|google|look up|find out|browse|check online)\b",
    r"\b(2025|2026|release date|schedule|standings|winner)\b",
    r"\b(review|vs|versus|comparison|features|specs)\b",
]
_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _LIVE_SEARCH_PATTERNS]


def is_live_search_query(query: str) -> bool:
    """Determine whether the query is asking for live web information."""
    q = query.strip()
    if len(q) < 3:
        return False
    # If the user explicitly asks to search or find
    for pat in _COMPILED_PATTERNS:
        if pat.search(q):
            return True
    return False


class TavilySearchClient:
    """Async Tavily Search API client."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", _DEFAULT_TAVILY_KEY)

    async def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_answer: bool = True,
    ) -> dict[str, Any]:
        """Execute web search via Tavily API."""
        if not self.api_key:
            log.warning("[TAVILY] No API key available for search.")
            return {"query": query, "results": [], "answer": None, "sources": []}

        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": search_depth,
            "max_results": max_results,
            "include_answer": include_answer,
        }

        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                res = await client.post(_TAVILY_ENDPOINT, json=payload)
                if res.status_code != 200:
                    log.warning("[TAVILY] HTTP %d: %s", res.status_code, res.text[:120])
                    return {"query": query, "results": [], "answer": None, "sources": []}

                data = res.json()
                raw_results = data.get("results", [])
                results = []
                sources = []

                for r in raw_results:
                    title = r.get("title", "Source")
                    url = r.get("url", "")
                    content = r.get("content", "")
                    results.append({
                        "title": title,
                        "url": url,
                        "content": content,
                        "score": r.get("score", 0.0),
                    })
                    if url:
                        sources.append({"title": title, "url": url})

                return {
                    "query": query,
                    "answer": data.get("answer"),
                    "results": results,
                    "sources": sources,
                }
        except Exception as exc:
            log.warning("[TAVILY] Search request failed: %s", exc)
            return {"query": query, "results": [], "answer": None, "sources": []}


def sanitize_vendor_branding(text: str) -> str:
    """
    Ensure all responses are strictly white-labeled as Harma AI.
    Replaces any accidental leaks of backend providers or search APIs.
    """
    import re
    if not text:
        return text
    # Replace provider names
    cleaned = re.sub(r"\bNemotron(?:\s*-\s*\d+[\w-]*|\s+\d+[\w-]*)?", "Harma AI", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bNVIDIA(?:\s+NIM|\s+LLM|\s+API)?\b", "Harma AI", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bTavily(?:\s+API|\s+Search)?\b", "Harma AI", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bHarma AI AI\b", "Harma AI", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bHarma AI's\b", "Harma AI's", cleaned, flags=re.IGNORECASE)
    return cleaned


async def answer_with_live_search(
    query: str,
    llm: LLMProvider,
    search_client: Optional[TavilySearchClient] = None,
    force_search: bool = False,
) -> tuple[str, list[dict[str, str]]]:
    """
    Handle a user query in Chat mode:
    1. If live search is needed (or forced), queries web perception.
    2. Passes live context to Harma AI to structure and format the final answer.
    3. Returns (formatted_answer, sources).
    """
    client = search_client or TavilySearchClient()
    should_search = force_search or is_live_search_query(query)

    search_data = None
    sources: list[dict[str, str]] = []

    if should_search:
        log.info("[CHAT_MODE] Executing web search perception for: '%s'", query[:60])
        search_data = await client.search(query=query, max_results=5)
        sources = search_data.get("sources", [])

    # If search returned results, synthesize with Harma AI
    if search_data and search_data.get("results"):
        context_parts = []
        if search_data.get("answer"):
            context_parts.append(f"Quick Answer Summary: {search_data['answer']}")

        for idx, r in enumerate(search_data["results"], 1):
            context_parts.append(
                f"[{idx}] {r['title']}\nURL: {r['url']}\nSummary: {r['content']}\n"
            )

        context_str = "\n".join(context_parts)

        prompt = f"""You are Harma AI, a professional, high-performance personal AI operating assistant.
The user asked: {query}

Below is the verified real-time information retrieved from the web:
---------------------
{context_str}
---------------------

Instructions:
1. Provide a comprehensive, accurate, and cleanly structured response addressing the user's question directly as Harma AI.
2. Structure your response with clean Markdown:
   - Begin with a clear section heading (##) and an executive summary answering the question directly.
   - Organize key facts, updates, and analyses into clear subsections with descriptive headings (###).
   - Use bullet points for readability, bolding key metrics, dates, companies, or individuals.
   - If comparing items or presenting numerical data, format them into a neat Markdown table.
3. Keep the tone professional, objective, and authoritative.
4. MANDATORY IDENTITY RULE: Present all knowledge directly as Harma AI. Never mention internal search APIs or LLM vendors (NVIDIA, Nemotron, Tavily).
5. Conclude with a clean '### Sources' list with markdown links [Title](URL) for the references used.
"""
        messages = [
            Message(
                role=Role.SYSTEM,
                content=(
                    "You are Harma AI, an intelligent personal AI operating assistant with live web perception and structured analytical synthesis. "
                    "Your identity is Harma AI. Never refer to external models or providers."
                ),
            ),
            Message(role=Role.USER, content=prompt),
        ]
    else:
        # Direct conversational answer from Harma AI
        system_prompt = (
            "You are Harma AI, an advanced, high-performance personal AI operating system developed to assist users with reasoning, automation, research, and operating tasks.\n\n"
            "MANDATORY IDENTITY DIRECTIVES:\n"
            "- Your name and identity is strictly 'Harma AI' (or simply 'Harma').\n"
            "- When asked who you are, what model you are, who created you, or your capabilities, ALWAYS answer that you are Harma AI.\n"
            "- NEVER state or imply that you are Nemotron, NVIDIA, OpenAI, Anthropic, or any third-party model or vendor.\n"
            "- Always respond with clarity, elegance, and professional Markdown formatting."
        )
        messages = [
            Message(role=Role.SYSTEM, content=system_prompt),
            Message(role=Role.USER, content=query),
        ]

    try:
        llm_resp = await llm.complete(messages)
        content = sanitize_vendor_branding(llm_resp.content or "")
        return content, sources
    except Exception as exc:
        log.error("[CHAT_MODE] LLM completion failed: %s", exc)
        # Fallback to direct answer if available
        if search_data and search_data.get("answer"):
            cleaned = sanitize_vendor_branding(search_data["answer"])
            return f"**Harma AI Summary:**\n\n{cleaned}", sources
        raise exc
