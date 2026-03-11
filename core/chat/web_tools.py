"""Web search and fetch tools for chat-mode tool calling.

Uses Serper.dev (Google Search API) for high-quality search results.
All returned URLs are validated with HEAD requests to ensure they're live.
Tools are exposed as OpenAI function-calling schemas so the LLM can decide
when to invoke them.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx
from bs4 import BeautifulSoup

from core.config import get_settings

logger = logging.getLogger(__name__)

_SERPER_URL = "https://google.serper.dev/search"

_HEAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


def _is_url_alive(url: str) -> bool:
    """Return True if a HEAD (or GET fallback) request returns 2xx/3xx."""
    if not url:
        return False
    try:
        with httpx.Client(
            timeout=6, follow_redirects=True, headers=_HEAD_HEADERS
        ) as client:
            # Try HEAD first (fast, no body downloaded)
            resp = client.head(url)
            if resp.status_code < 400:
                return True
            # Some sites block HEAD — fall back to GET with stream
            resp = client.get(url, headers={"Range": "bytes=0-0"})
            return resp.status_code < 400
    except Exception:
        return False


def _validate_results(results: list[dict]) -> list[dict]:
    """Validate URLs concurrently, return only results with live links."""
    if not results:
        return []

    alive: dict[str, bool] = {}

    with ThreadPoolExecutor(max_workers=6) as pool:
        future_to_url = {
            pool.submit(_is_url_alive, r["href"]): r["href"] for r in results
        }
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                alive[url] = future.result()
            except Exception:
                alive[url] = False

    valid = [r for r in results if alive.get(r["href"], False)]
    dead = [r["href"] for r in results if not alive.get(r["href"], False)]
    if dead:
        logger.info("Filtered %d dead URLs: %s", len(dead), dead)
    return valid


# ---------------------------------------------------------------------------
# Serper search
# ---------------------------------------------------------------------------


def _serper_search(
    query: str, max_results: int = 5, gl: str = "ro", hl: str = "ro"
) -> list[dict]:
    """Search via Serper.dev and return a list of {title, body, href}."""
    api_key = get_settings().serper_api_key
    if not api_key:
        raise RuntimeError("SERPER_API_KEY is not configured")

    # Fetch extra results so we still have enough after filtering dead links
    fetch_count = max_results * 3

    payload = {"q": query, "gl": gl, "hl": hl, "num": fetch_count}
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}

    with httpx.Client(timeout=15) as client:
        resp = client.post(_SERPER_URL, json=payload, headers=headers)
        resp.raise_for_status()

    data = resp.json()
    candidates: list[dict] = []

    for item in data.get("organic", []):
        candidates.append(
            {
                "title": item.get("title", ""),
                "body": item.get("snippet", ""),
                "href": item.get("link", ""),
            }
        )

    # Include shopping results (great for product queries)
    for item in data.get("shopping", []):
        title = item.get("title", "")
        price = item.get("price", "")
        source = item.get("source", "")
        link = item.get("link", "")
        body = f"{price} — {source}" if price else source
        if link and title:
            candidates.append({"title": title, "body": body, "href": link})

    # Validate URLs and keep only live ones
    valid = _validate_results(candidates)
    return valid[:max_results]


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web using Google (via Serper) and return validated results."""
    try:
        results = _serper_search(query, max_results)
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
    """Search for products with price-oriented results via Google (Serper)."""
    enriched_query = f"{query} preț cumpără"
    try:
        results = _serper_search(enriched_query, max_results)
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
                "Search the internet for information using Google. "
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
