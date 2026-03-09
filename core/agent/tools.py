"""Agent tools for the Strands agent orchestrator."""

import ast
import logging
import math
import operator
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from strands import tool

if TYPE_CHECKING:
    from core.rag.pipeline import RAGPipeline

logger = logging.getLogger(__name__)

# Safe operators for the calculator
_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}

_SAFE_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "pi": math.pi,
    "e": math.e,
    "ceil": math.ceil,
    "floor": math.floor,
}


def _safe_eval(node: ast.AST) -> float:
    """Recursively evaluate an AST node with only safe operations.

    Args:
        node: AST node to evaluate.

    Returns:
        Numeric result.

    Raises:
        ValueError: If the expression contains unsafe operations.
    """
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"Unsafe constant: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id in _SAFE_FUNCTIONS:
            return _SAFE_FUNCTIONS[node.id]  # type: ignore
        raise ValueError(f"Unknown name: {node.id!r}")
    if isinstance(node, ast.Call):
        func = _safe_eval(node.func)
        args = [_safe_eval(a) for a in node.args]
        return func(*args)
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            raise ValueError(f"Unsafe operator: {op_type.__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return _SAFE_OPERATORS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            raise ValueError(f"Unsafe unary operator: {op_type.__name__}")
        operand = _safe_eval(node.operand)
        return _SAFE_OPERATORS[op_type](operand)
    raise ValueError(f"Unsupported AST node: {type(node).__name__}")


@tool
def calculator(expression: str) -> str:
    """Evaluate a mathematical expression safely.

    Supports: +, -, *, /, //, %, **, abs, round, sqrt, sin, cos, tan,
    log, log2, log10, ceil, floor, and the constants pi and e.

    Args:
        expression: A math expression string, e.g. "2 + 3 * 4" or "sqrt(16)".

    Returns:
        The result as a string, or an error message if evaluation fails.
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _safe_eval(tree)
        # Format nicely: int if whole number
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        logger.debug("calculator(%r) = %s", expression, result)
        return str(result)
    except ZeroDivisionError:
        return "Error: Division by zero"
    except (ValueError, TypeError) as e:
        return f"Error: {e}"
    except SyntaxError:
        return f"Error: Invalid expression syntax: {expression!r}"


@tool
def get_current_time() -> str:
    """Return the current UTC date and time in ISO 8601 format.

    Returns:
        Current UTC datetime string, e.g. "2024-11-15T10:30:00+00:00".
    """
    now = datetime.now(timezone.utc)
    formatted = now.isoformat()
    logger.debug("get_current_time() = %s", formatted)
    return formatted


@tool
def summarize_text(text: str) -> str:
    """Extract the key points from a long text (first 200 words as a preview).

    This is a lightweight summarization tool that extracts the beginning
    of the text. For production use, wire this up to the LLM provider.

    Args:
        text: The text to summarize.

    Returns:
        A condensed version of the text (up to ~200 words).
    """
    words = text.split()
    if len(words) <= 200:
        return text
    preview = " ".join(words[:200])
    logger.debug("summarize_text: truncated %d words to 200", len(words))
    return preview + f"\n\n[... truncated. Original: {len(words)} words]"


def make_rag_lookup_tool(rag_pipeline: "RAGPipeline", tenant_id: str | None = None):
    """Factory that creates a rag_lookup tool bound to a RAG pipeline.

    Args:
        rag_pipeline: Initialized RAGPipeline instance.
        tenant_id: Optional tenant ID for scoped queries.

    Returns:
        A Strands @tool-decorated function.
    """
    import asyncio

    @tool
    def rag_lookup(query: str) -> str:
        """Search the knowledge base for information relevant to a query.

        Uses the RAG pipeline to retrieve and synthesize information from
        ingested documents.

        Args:
            query: The search query to look up in the knowledge base.

        Returns:
            A synthesized answer from the knowledge base, or a message
            indicating no relevant documents were found.
        """
        try:
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(rag_pipeline.query(query, tenant_id=tenant_id))
            if result.sources:
                sources_str = ", ".join(s["source"] for s in result.sources)
                return f"{result.answer}\n\nSources: {sources_str}"
            return result.answer
        except Exception as e:
            logger.error("rag_lookup error: %s", e)
            return f"Error searching knowledge base: {e}"

    return rag_lookup
