"""Per-request user identity helpers for the skills MCP app."""

import os
from collections.abc import Callable, Mapping
from typing import Any

import anyio.to_thread

from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError

TOKEN_HEADER = "x-forwarded-access-token"

MISSING_TOKEN_MESSAGE = (
    "This tool needs your Databricks identity, and the request didn't include it. "
    "Call it through Platform MCP or the app's URL with your own Databricks sign-in."
)


class MissingUserToken(Exception):
    """The request carried no user access token."""


def user_token(headers: Mapping[str, str]) -> str:
    token = (headers.get(TOKEN_HEADER) or "").strip()
    if not token:
        raise MissingUserToken(MISSING_TOKEN_MESSAGE)
    return token


def user_client(token: str) -> WorkspaceClient:
    # auth_type="pat" ignores the app service principal's injected
    # DATABRICKS_CLIENT_ID/SECRET so calls run as the user.
    # Bounded timeouts keep worst-case SDK retries well under the 60 s Apps proxy limit.
    # WorkspaceClient itself doesn't accept these kwargs; Config does.
    config = Config(
        host=os.environ["DATABRICKS_HOST"],
        token=token,
        auth_type="pat",
        retry_timeout_seconds=30,
        http_timeout_seconds=15,
    )
    return WorkspaceClient(config=config)


def _token_from_ctx(ctx: Context) -> str:
    request = ctx.request_context.request
    headers = request.headers if request is not None else {}
    try:
        return user_token(headers)
    except MissingUserToken:
        raise ToolError(MISSING_TOKEN_MESSAGE) from None


async def run_as_user(ctx: Context, fn: Callable[..., Any], *args: Any) -> Any:
    """Run fn(user_client, *args) in a worker thread so blocking SDK calls don't stall the event loop."""
    token = _token_from_ctx(ctx)

    def call() -> Any:
        return fn(user_client(token), *args)

    return await anyio.to_thread.run_sync(call)
