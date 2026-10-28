"""FastMCP server factory for the skills MCP app."""

from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from skills_mcp import auth


def build_server(skills_dir: Path | None = None) -> FastMCP:
    # The Databricks Apps proxy sets its own Host header, so DNS-rebinding host
    # validation (which defaults to localhost-only) would reject every request.
    mcp = FastMCP(
        "apfm-databricks-skills",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool()
    def whoami(ctx: Context) -> dict[str, str | None]:
        """Return the Databricks identity of the calling user."""
        me = auth.client_from_ctx(ctx).current_user.me()
        return {"user_name": me.user_name, "display_name": me.display_name}

    return mcp
