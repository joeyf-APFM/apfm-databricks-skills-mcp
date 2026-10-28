"""FastMCP server factory for the skills MCP app."""

from pathlib import Path
from typing import Any

from databricks.sdk import WorkspaceClient
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.prompts import Prompt
from mcp.server.transport_security import TransportSecuritySettings

from skills_mcp import auth, uc_tools
from skills_mcp.catalog import FileNotAllowed, SkillCatalog, SkillNotFound
from skills_mcp.errors import sdk_errors_as_tool_errors
from skills_mcp.index import build_index


def _whoami(w: WorkspaceClient) -> dict[str, str | None]:
    me = w.current_user.me()
    return {"user_name": me.user_name, "display_name": me.display_name}


def build_server(skills_dir: Path | None = None) -> FastMCP:
    # The Databricks Apps proxy sets its own Host header, so DNS-rebinding host
    # validation (which defaults to localhost-only) would reject every request.
    # A CatalogError from a malformed skills dir propagates so startup fails fast.
    catalog = SkillCatalog.from_dir(skills_dir) if skills_dir is not None else None
    mcp = FastMCP(
        "apfm-databricks-skills",
        instructions=build_index(catalog) if catalog is not None else None,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool()
    @sdk_errors_as_tool_errors
    async def whoami(ctx: Context) -> dict[str, str | None]:
        """Return the Databricks identity of the calling user."""
        return await auth.run_as_user(ctx, _whoami)

    _register_uc_tools(mcp)

    if catalog is not None:
        _register_skills(mcp, catalog)

    return mcp


def _register_uc_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    @sdk_errors_as_tool_errors
    async def list_catalogs(ctx: Context, limit: int = 100) -> dict[str, Any]:
        """List Unity Catalog catalogs you can see (max 500; `truncated` says if more exist)."""
        return await auth.run_as_user(ctx, uc_tools.list_catalogs, limit)

    @mcp.tool()
    @sdk_errors_as_tool_errors
    async def list_schemas(ctx: Context, catalog: str, limit: int = 100) -> dict[str, Any]:
        """List schemas in a catalog (max 500; `truncated` says if more exist)."""
        return await auth.run_as_user(ctx, uc_tools.list_schemas, catalog, limit)

    @mcp.tool()
    @sdk_errors_as_tool_errors
    async def list_tables(ctx: Context, catalog: str, schema: str, limit: int = 100) -> dict[str, Any]:
        """List tables in a schema (max 500; `truncated` says if more exist)."""
        return await auth.run_as_user(ctx, uc_tools.list_tables, catalog, schema, limit)

    @mcp.tool()
    @sdk_errors_as_tool_errors
    async def describe_table(ctx: Context, full_name: str) -> dict[str, Any]:
        """Describe a table (catalog.schema.table): type, format, owner, comment and columns."""
        return await auth.run_as_user(ctx, uc_tools.describe_table, full_name)


def _read(catalog: SkillCatalog, name: str, path: str = "SKILL.md") -> str:
    try:
        return catalog.read(name, path)
    except SkillNotFound:
        raise ToolError(f"Unknown skill '{name}'. Call list_skills to see available skills.") from None
    except FileNotAllowed:
        raise ToolError(f"'{path}' isn't a file in skill '{name}'. load_skill lists the skill's files.") from None


def _register_skills(mcp: FastMCP, catalog: SkillCatalog) -> None:
    @mcp.tool()
    def list_skills(query: str | None = None) -> dict[str, object]:
        """List the available Databricks skills, optionally filtered by a name/description substring."""
        return {
            "skills": [{"name": s.name, "description": s.description, "fit": s.fit} for s in catalog.list(query)],
            "upstream_version": catalog.upstream_version,
        }

    @mcp.tool()
    def load_skill(name: str) -> str:
        """Return a skill's full SKILL.md, plus a line listing its other files."""
        body = _read(catalog, name)
        others = [f for f in catalog.get(name).files if f != "SKILL.md"]
        if others:
            body = body.rstrip("\n") + "\n\nOther files in this skill: " + ", ".join(others)
        return body

    @mcp.tool()
    def get_skill_file(name: str, path: str) -> str:
        """Return one supporting file from a skill (a path listed by load_skill)."""
        return _read(catalog, name, path)

    @mcp.resource("skill://{name}", mime_type="text/markdown")
    def skill_resource(name: str) -> str:
        """A skill's SKILL.md."""
        try:
            return catalog.read(name)
        except SkillNotFound:
            raise ValueError(f"Unknown skill '{name}'. Call list_skills to see available skills.") from None

    for skill in catalog.list():
        mcp.add_prompt(Prompt.from_function(_prompt_fn(skill.name), name=skill.name, description=skill.description))


def _prompt_fn(name: str):
    def render(request: str) -> str:
        return f'Load the {name} skill with load_skill("{name}") and follow it for this request: {request}'

    return render
