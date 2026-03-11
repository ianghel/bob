"""Tests for web search tools and chat integration."""

import json
import pytest
from unittest.mock import MagicMock, patch

from core.chat.web_tools import (
    TOOL_SCHEMAS,
    execute_tool,
    fetch_webpage,
    search_products,
    web_search,
)


# ---------------------------------------------------------------------------
# Tool schema tests
# ---------------------------------------------------------------------------


def test_tool_schemas_has_three_tools():
    assert len(TOOL_SCHEMAS) == 3
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert names == {"web_search", "search_products", "fetch_webpage"}


def test_tool_schemas_are_valid_openai_format():
    for schema in TOOL_SCHEMAS:
        assert schema["type"] == "function"
        fn = schema["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        assert fn["parameters"]["type"] == "object"
        assert "required" in fn["parameters"]


# ---------------------------------------------------------------------------
# web_search tests
# ---------------------------------------------------------------------------


@patch("core.chat.web_tools.DDGS")
def test_web_search_returns_formatted_results(mock_ddgs_cls):
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = [
        {"title": "FastAPI Docs", "body": "FastAPI is a modern framework", "href": "https://fastapi.tiangolo.com"},
        {"title": "FastAPI Tutorial", "body": "Learn FastAPI in 5 minutes", "href": "https://example.com/tutorial"},
    ]
    mock_ddgs_cls.return_value = mock_ddgs

    result = web_search("FastAPI", max_results=2)
    assert "FastAPI Docs" in result
    assert "https://fastapi.tiangolo.com" in result
    assert "FastAPI Tutorial" in result
    mock_ddgs.text.assert_called_once_with("FastAPI", max_results=2)


@patch("core.chat.web_tools.DDGS")
def test_web_search_empty_results(mock_ddgs_cls):
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = []
    mock_ddgs_cls.return_value = mock_ddgs

    result = web_search("xyznonexistent123")
    assert "No results found" in result


@patch("core.chat.web_tools.DDGS")
def test_web_search_handles_error(mock_ddgs_cls):
    mock_ddgs_cls.side_effect = Exception("Network error")
    result = web_search("test")
    assert "Search failed" in result


# ---------------------------------------------------------------------------
# search_products tests
# ---------------------------------------------------------------------------


@patch("core.chat.web_tools.DDGS")
def test_search_products_enriches_query(mock_ddgs_cls):
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = [
        {"title": "Laptop Gaming", "body": "3500 lei - eMAG", "href": "https://emag.ro/laptop"},
    ]
    mock_ddgs_cls.return_value = mock_ddgs

    result = search_products("laptop gaming")
    assert "Laptop Gaming" in result
    # Check query was enriched with shopping terms
    call_args = mock_ddgs.text.call_args
    assert "preț" in call_args[0][0] or "preț" in str(call_args)


@patch("core.chat.web_tools.DDGS")
def test_search_products_no_results(mock_ddgs_cls):
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = []
    mock_ddgs_cls.return_value = mock_ddgs

    result = search_products("xyznonexistent")
    assert "No product results" in result


# ---------------------------------------------------------------------------
# fetch_webpage tests
# ---------------------------------------------------------------------------


@patch("core.chat.web_tools.httpx.Client")
def test_fetch_webpage_returns_text(mock_client_cls):
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_resp = MagicMock()
    mock_resp.text = "<html><body><h1>Hello</h1><p>World content here</p></body></html>"
    mock_resp.raise_for_status = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client_cls.return_value = mock_client

    result = fetch_webpage("https://example.com")
    assert "Hello" in result
    assert "World content here" in result
    assert "Content from https://example.com" in result


@patch("core.chat.web_tools.httpx.Client")
def test_fetch_webpage_handles_error(mock_client_cls):
    mock_client_cls.side_effect = Exception("Connection refused")
    result = fetch_webpage("https://bad-url.example")
    assert "Failed to fetch" in result


@patch("core.chat.web_tools.httpx.Client")
def test_fetch_webpage_truncates_long_content(mock_client_cls):
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_resp = MagicMock()
    mock_resp.text = "<html><body><p>" + "A" * 10000 + "</p></body></html>"
    mock_resp.raise_for_status = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client_cls.return_value = mock_client

    result = fetch_webpage("https://example.com/long")
    assert "[... truncated]" in result


# ---------------------------------------------------------------------------
# execute_tool dispatcher tests
# ---------------------------------------------------------------------------


def test_execute_tool_dispatches_web_search():
    mock_fn = MagicMock(return_value="search results")
    with patch.dict("core.chat.web_tools._TOOL_REGISTRY", {"web_search": mock_fn}):
        result = execute_tool("web_search", {"query": "test"})
    assert result == "search results"
    mock_fn.assert_called_once_with(query="test")


def test_execute_tool_dispatches_search_products():
    mock_fn = MagicMock(return_value="product results")
    with patch.dict("core.chat.web_tools._TOOL_REGISTRY", {"search_products": mock_fn}):
        result = execute_tool("search_products", {"query": "laptop"})
    assert result == "product results"


def test_execute_tool_dispatches_fetch_webpage():
    mock_fn = MagicMock(return_value="page content")
    with patch.dict("core.chat.web_tools._TOOL_REGISTRY", {"fetch_webpage": mock_fn}):
        result = execute_tool("fetch_webpage", {"url": "https://example.com"})
    assert result == "page content"


def test_execute_tool_unknown_tool():
    result = execute_tool("nonexistent_tool", {})
    assert "Unknown tool" in result


def test_execute_tool_parses_json_string():
    mock_fn = MagicMock(return_value="ok")
    with patch.dict("core.chat.web_tools._TOOL_REGISTRY", {"web_search": mock_fn}):
        result = execute_tool("web_search", '{"query": "hello"}')
    assert result == "ok"
    mock_fn.assert_called_once_with(query="hello")


def test_execute_tool_invalid_json_string():
    result = execute_tool("web_search", "not-valid-json")
    assert "Invalid arguments JSON" in result
