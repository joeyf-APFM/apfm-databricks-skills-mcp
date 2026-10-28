# apfm-databricks-skills-mcp

MCP server, deployed as a Databricks App, that serves APFM-curated Databricks agent
skills and read-only Unity Catalog tools. Calls run as the end user via the
`x-forwarded-access-token` header.

## Tests

    uv sync
    uv run pytest

Deployment and usage docs: to be expanded.
