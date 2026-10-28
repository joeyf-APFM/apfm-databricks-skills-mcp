"""Per-request user identity helpers for the skills MCP app."""

import os
from collections.abc import Mapping

from databricks.sdk import WorkspaceClient
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
    return WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=token, auth_type="pat")


def client_from_ctx(ctx: Context) -> WorkspaceClient:
    request = ctx.request_context.request
    headers = request.headers if request is not None else {}
    try:
        return user_client(user_token(headers))
    except MissingUserToken:
        raise ToolError(MISSING_TOKEN_MESSAGE) from None
