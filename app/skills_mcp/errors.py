"""Map Databricks SDK errors to model-readable MCP tool errors."""

import functools
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from databricks.sdk.errors import DatabricksError, NotFound, PermissionDenied, Unauthenticated
from mcp.server.fastmcp.exceptions import ToolError

P = ParamSpec("P")
R = TypeVar("R")

UNAUTHENTICATED_MESSAGE = (
    "Your Databricks sign-in wasn't accepted. Reconnect Databricks in Platform MCP "
    "(provider_manage_connections) and try again."
)


def sdk_errors_as_tool_errors(fn: Callable[P, R]) -> Callable[P, R]:
    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except PermissionDenied as e:
            raise ToolError(
                f"Databricks denied access: {e}. Ask for the Unity Catalog grant you need, then try again."
            ) from None
        except NotFound as e:
            raise ToolError(f"Not found in Databricks: {e}") from None
        except Unauthenticated:
            raise ToolError(UNAUTHENTICATED_MESSAGE) from None
        except DatabricksError as e:
            raise ToolError(f"Databricks returned an error: {e}") from None

    return wrapper
