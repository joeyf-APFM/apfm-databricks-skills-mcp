"""Map Databricks SDK errors to model-readable MCP tool errors."""

import functools
import inspect
from collections.abc import Callable
from typing import Any, NoReturn, ParamSpec, TypeVar

from databricks.sdk.errors import DatabricksError, NotFound, PermissionDenied, Unauthenticated
from mcp.server.fastmcp.exceptions import ToolError

P = ParamSpec("P")
R = TypeVar("R")

UNAUTHENTICATED_MESSAGE = (
    "Your Databricks sign-in wasn't accepted. Reconnect Databricks in Platform MCP "
    "(provider_manage_connections) and try again."
)


def _raise_mapped(e: Exception) -> NoReturn:
    if isinstance(e, ToolError):
        raise e
    if isinstance(e, PermissionDenied):
        raise ToolError(
            f"Databricks denied access: {e}. Ask for the Unity Catalog grant you need, then try again."
        ) from None
    if isinstance(e, NotFound):
        raise ToolError(f"Not found in Databricks: {e}") from None
    if isinstance(e, Unauthenticated):
        raise ToolError(UNAUTHENTICATED_MESSAGE) from None
    if isinstance(e, DatabricksError):
        raise ToolError(f"Databricks returned an error: {e}") from None
    raise e


def sdk_errors_as_tool_errors(fn: Callable[P, R]) -> Callable[P, R]:
    """Map SDK errors to ToolError; works for sync and async functions."""
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                _raise_mapped(e)

        return async_wrapper  # type: ignore[return-value]

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            _raise_mapped(e)

    return wrapper
