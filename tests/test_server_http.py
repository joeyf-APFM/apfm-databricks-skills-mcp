from skills_mcp.auth import MISSING_TOKEN_MESSAGE

from .conftest import MCP_HEADERS, TOOLS_LIST, mcp_call


def test_whoami_returns_calling_user(client, fake_me):
    result = mcp_call(client, "whoami", {}, token="t")
    assert result["structuredContent"]["user_name"] == "pat@aplaceformom.com"


def test_whoami_without_token_fails_closed(client):
    result = mcp_call(client, "whoami", {}, token=None)
    assert result["isError"] is True
    assert MISSING_TOKEN_MESSAGE in result["content"][0]["text"]


def test_accepts_databricks_apps_host_header(client):
    r = client.post(
        "/mcp",
        headers={"host": "mcp-apfm-skills-123.aws.databricksapps.com", **MCP_HEADERS},
        json=TOOLS_LIST,
    )
    assert r.status_code == 200
