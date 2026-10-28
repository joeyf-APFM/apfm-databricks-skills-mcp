from pathlib import Path

import pytest

from tests.conftest import MCP_HEADERS, make_client, mcp_call
from tools.curate import curate

FIXTURE = Path(__file__).parent / "fixtures" / "upstream"


@pytest.fixture(scope="module")
def curated(tmp_path_factory):
    out = tmp_path_factory.mktemp("curated") / "out"
    curate(FIXTURE, FIXTURE / "curation.yaml", out)
    return out


@pytest.fixture
def client(curated):
    with make_client(curated) as c:
        yield c


def rpc(client, method, params=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    r = client.post("/mcp", headers=MCP_HEADERS, json=body)
    assert r.status_code == 200, r.text
    return r.json()["result"]


def text(result):
    return result["content"][0]["text"]


def test_instructions_contain_index(client):
    result = rpc(
        client,
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
    )
    assert "| alpha |" in result["instructions"]


def test_list_skills_filters(client):
    result = mcp_call(client, "list_skills", {"query": "alpha"}, None)
    data = result["structuredContent"]
    assert [s["name"] for s in data["skills"]] == ["alpha"]
    assert set(data["skills"][0]) == {"name", "description", "fit"}
    assert data["upstream_version"]


def test_load_skill_returns_note_and_file_list(client):
    out = text(mcp_call(client, "load_skill", {"name": "alpha"}, None))
    assert "> **APFM note.**" in out
    last = out.rstrip().splitlines()[-1]
    assert last.startswith("Other files in this skill:") and "references/one.md" in last
    assert "SKILL.md" not in last


def test_load_skill_without_other_files_omits_line(client):
    out = text(mcp_call(client, "load_skill", {"name": "beta"}, None))
    assert "Beta" in out or "beta" in out
    assert "Other files in this skill" not in out


def test_get_skill_file_ok(client):
    result = mcp_call(client, "get_skill_file", {"name": "alpha", "path": "references/one.md"}, None)
    assert not result.get("isError")
    assert text(result)


def test_get_skill_file_traversal_is_tool_error(client):
    result = mcp_call(client, "get_skill_file", {"name": "alpha", "path": "../beta/SKILL.md"}, None)
    assert result["isError"] is True
    assert "'../beta/SKILL.md' isn't a file in skill 'alpha'. load_skill lists the skill's files." in text(result)


def test_unknown_skill_is_tool_error(client):
    result = mcp_call(client, "load_skill", {"name": "nope"}, None)
    assert result["isError"] is True
    assert "Unknown skill 'nope'. Call list_skills to see available skills." in text(result)


def test_resource_read_skill_md(client):
    result = rpc(client, "resources/read", {"uri": "skill://alpha"})
    item = result["contents"][0]
    assert item["mimeType"] == "text/markdown"
    assert "> **APFM note.**" in item["text"]


def test_prompt_per_skill(client):
    names = [p["name"] for p in rpc(client, "prompts/list")["prompts"]]
    assert "alpha" in names and "beta" in names
    result = rpc(client, "prompts/get", {"name": "alpha", "arguments": {"request": "do the thing"}})
    msg = result["messages"][0]["content"]["text"]
    assert msg == 'Load the alpha skill with load_skill("alpha") and follow it for this request: do the thing'


def test_skill_tools_need_no_user_token(client):
    result = mcp_call(client, "list_skills", {}, None)
    assert not result.get("isError")
    assert len(result["structuredContent"]["skills"]) == 2


def test_resource_read_unknown_skill_error_not_doubled(client):
    body = {"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": "skill://nope"}}
    r = client.post("/mcp", headers=MCP_HEADERS, json=body)
    message = r.json()["error"]["message"]
    assert message.count("Unknown skill 'nope'") == 1


def test_tools_list_contract(client):
    names = {t["name"] for t in rpc(client, "tools/list")["tools"]}
    assert names == {
        "whoami",
        "list_skills",
        "load_skill",
        "get_skill_file",
        "list_catalogs",
        "list_schemas",
        "list_tables",
        "describe_table",
    }
