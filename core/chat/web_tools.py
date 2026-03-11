"""Web search and fetch tools for chat-mode tool calling.

Provides Bing-based search (general + products) and webpage fetching.
Tools are exposed as OpenAI function-calling schemas so the LLM can decide
when to invoke them.
"""

import json
import logging
from typing import Any
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ro;q=0.8",
}

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _bing_search(query: str, max_results: int = 5) -> list[dict]:
    """Scrape Bing search results and return a list of {title, body, href}."""
    url = f"https://www.bing.com/search?q={quote_plus(query)}&count={max_results}"
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        resp = client.get(url, headers=_SEARCH_HEADERS)
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for li in soup.select("li.b_algo"):
        a_tag = li.select_one("h2 a")
        if not a_tag:
            continue
        title = a_tag.get_text(strip=True)
        href = a_tag.get("href", "")
        snippet_tag = li.select_one("p") or li.select_one(".b_caption p")
        body = snippet_tag.get_text(strip=True) if snippet_tag else ""
        results.append({"title": title, "body": body, "href": href})
        if len(results) >= max_results:
            break
    return results


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web using Bing and return formatted results."""
    try:
        results = _bing_search(query, max_results)
        if not results:
            return f"No results found for: {query}"
        parts = []
        for i, r in enumerate(results, 1):
            parts.append(
                f"{i}. **{r['title']}**\n   {r['body']}\n   URL: {r['href']}"
            )
        return "\n\n".join(parts)
    except Exception as e:
        logger.error("web_search error: %s", e)
        return f"Search failed: {e}"


def search_products(query: str, max_results: int = 5) -> str:
    """Search for products with price-oriented results via Bing."""
    enriched_query = f"{query} preț cumpără magazin"
    try:
        results = _bing_search(enriched_query, max_results)
        if not results:
            return f"No product results found for: {query}"
        parts = []
        for i, r in enumerate(results, 1):
            parts.append(
                f"{i}. **{r['title']}**\n"
                f"   {r['body']}\n"
                f"   Link: {r['href']}"
            )
        return "\n\n".join(parts)
    except Exception as e:
        logger.error("search_products error: %s", e)
        return f"Product search failed: {e}"


def fetch_webpage(url: str) -> str:
    """Fetch a webpage and return its text content (max ~4000 chars)."""
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "Mozilla/5.0 (Bob-Agent)"})
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove script/style tags
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Collapse blank lines
        lines = [ln for ln in text.splitlines() if ln.strip()]
        clean = "\n".join(lines)
        if len(clean) > 4000:
            clean = clean[:4000] + "\n\n[... truncated]"
        return f"Content from {url}:\n\n{clean}"
    except Exception as e:
        logger.error("fetch_webpage error for %s: %s", url, e)
        return f"Failed to fetch {url}: {e}"


# ---------------------------------------------------------------------------
# OpenAI function-calling tool schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the internet for information using Bing. "
                "Use this for general questions, news, facts, tutorials, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Search for products, compare prices and find deals. "
                "Use this when the user asks about buying something, "
                "price comparisons, product recommendations, or shopping."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Product search query (e.g. 'laptop gaming sub 4000 lei')",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": (
                "Fetch and read the text content of a specific webpage URL. "
                "Use this when the user asks to read, download, or get content from a URL."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL to fetch (e.g. 'https://example.com/page')",
                    },
                },
                "required": ["url"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_TOOL_REGISTRY = {
    "web_search": web_search,
    "search_products": search_products,
    "fetch_webpage": fetch_webpage,
}


def execute_tool(name: str, arguments: str | dict) -> str:
    """Execute a tool by name with the given arguments.

    Args:
        name: Tool function name.
        arguments: JSON string or dict of keyword arguments.

    Returns:
        Tool result as a string.
    """
    func = _TOOL_REGISTRY.get(name)
    if func is None:
        return f"Unknown tool: {name}"
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return f"Invalid arguments JSON for {name}: {arguments}"
    try:
        return func(**arguments)
    except Exception as e:
        logger.error("Tool %s execution error: %s", name, e)
        return f"Tool {name} failed: {e}"
