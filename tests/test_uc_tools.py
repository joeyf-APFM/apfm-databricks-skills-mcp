import threading
from unittest.mock import MagicMock

import anyio
import httpx
import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound, PermissionDenied, Unauthenticated
from databricks.sdk.service.catalog import (
    CatalogInfo,
    ColumnInfo,
    DataSourceFormat,
    SchemaInfo,
    TableInfo,
    TableType,
)
from mcp.server.fastmcp.exceptions import ToolError

from skills_mcp import uc_tools
from skills_mcp.auth import MISSING_TOKEN_MESSAGE
from skills_mcp.errors import sdk_errors_as_tool_errors
from tests.conftest import mcp_call

UC_TOOL_ARGS = {
    "list_catalogs": {},
    "list_schemas": {"catalog": "main"},
    "list_tables": {"catalog": "main", "schema": "default"},
    "describe_table": {"full_name": "main.default.t"},
}


def fake_workspace() -> MagicMock:
    w = MagicMock(spec=WorkspaceClient)
    for attr in ("catalogs", "schemas", "tables"):
        setattr(w, attr, MagicMock())
    return w


def test_list_tables_caps_and_flags_truncation():
    w = fake_workspace()
    consumed = []

    def gen():
        for i in range(1000):
            consumed.append(i)
            yield TableInfo(name=f"t{i}", full_name=f"c.s.t{i}", table_type=TableType.MANAGED, comment=None)

    w.tables.list.return_value = gen()
    out = uc_tools.list_tables(w, "c", "s", limit=100)
    assert len(out["items"]) == 100
    assert out["truncated"] is True
    assert len(consumed) == 101
    assert out["items"][0] == {"name": "t0", "full_name": "c.s.t0", "table_type": "MANAGED", "comment": None}
    w.tables.list.assert_called_once_with(
        catalog_name="c", schema_name="s", omit_columns=True, omit_properties=True
    )


def test_not_truncated_when_exactly_limit():
    w = fake_workspace()
    w.catalogs.list.return_value = iter([CatalogInfo(name=f"c{i}") for i in range(3)])
    out = uc_tools.list_catalogs(w, limit=3)
    assert len(out["items"]) == 3
    assert out["truncated"] is False
    assert out["items"][0] == {"name": "c0", "comment": None, "owner": None}


def test_limit_clamped():
    w = fake_workspace()
    w.catalogs.list.return_value = iter([CatalogInfo(name=f"c{i}") for i in range(1000)])
    assert len(uc_tools.list_catalogs(w, limit=0)["items"]) == 1
    w.catalogs.list.return_value = iter([CatalogInfo(name=f"c{i}") for i in range(1000)])
    out = uc_tools.list_catalogs(w, limit=10_000)
    assert len(out["items"]) == 500
    assert out["truncated"] is True


def test_list_schemas_passes_catalog_name():
    w = fake_workspace()
    w.schemas.list.return_value = iter([SchemaInfo(name="default", comment="c", owner="o")])
    out = uc_tools.list_schemas(w, "main")
    w.schemas.list.assert_called_once_with(catalog_name="main")
    assert out == {"items": [{"name": "default", "comment": "c", "owner": "o"}], "truncated": False}


def test_describe_table_trims_fields():
    w = fake_workspace()
    w.tables.get.return_value = TableInfo(
        name="t",
        full_name="main.default.t",
        table_type=TableType.EXTERNAL,
        data_source_format=DataSourceFormat.DELTA,
        owner="me",
        comment="hi",
        storage_location="s3://secret",
        columns=[ColumnInfo(name="id", type_text="bigint", nullable=False, comment=None, position=0)],
    )
    out = uc_tools.describe_table(w, "main.default.t")
    w.tables.get.assert_called_once_with(full_name="main.default.t")
    assert out == {
        "full_name": "main.default.t",
        "table_type": "EXTERNAL",
        "data_source_format": "DELTA",
        "owner": "me",
        "comment": "hi",
        "columns": [{"name": "id", "type_text": "bigint", "nullable": False, "comment": None}],
    }


def test_describe_table_handles_missing_enums_and_columns():
    w = fake_workspace()
    w.tables.get.return_value = TableInfo(full_name="a.b.c")
    out = uc_tools.describe_table(w, "a.b.c")
    assert out["table_type"] is None and out["data_source_format"] is None and out["columns"] == []


@pytest.mark.parametrize(
    "exc,phrase",
    [
        (PermissionDenied("no"), "Databricks denied access: no."),
        (NotFound("x"), "Not found in Databricks: x"),
        (Unauthenticated("x"), "Reconnect Databricks"),
    ],
)
def test_sdk_errors_become_tool_errors(exc, phrase):
    @sdk_errors_as_tool_errors
    def boom():
        raise exc

    with pytest.raises(ToolError, match=phrase) as info:
        boom()
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_other_databricks_error_mapped():
    from databricks.sdk.errors import DatabricksError

    @sdk_errors_as_tool_errors
    def boom():
        raise DatabricksError("kaput")

    with pytest.raises(ToolError, match="Databricks returned an error: kaput"):
        boom()


def test_tool_error_passes_through_unchanged():
    @sdk_errors_as_tool_errors
    def boom():
        raise ToolError(MISSING_TOKEN_MESSAGE)

    with pytest.raises(ToolError) as info:
        boom()
    assert str(info.value) == MISSING_TOKEN_MESSAGE


@pytest.mark.parametrize("tool", list(UC_TOOL_ARGS))
def test_each_uc_tool_without_token_fails_closed(client, tool):
    result = mcp_call(client, tool, UC_TOOL_ARGS[tool], token=None)
    assert result["isError"] is True
    assert MISSING_TOKEN_MESSAGE in result["content"][0]["text"]


def test_uc_tool_uses_user_client(client, monkeypatch):
    seen = []
    w = fake_workspace()
    w.catalogs.list.return_value = iter([CatalogInfo(name="main", comment="c", owner="o")])

    def fake_user_client(token):
        seen.append(token)
        return w

    monkeypatch.setattr("skills_mcp.auth.user_client", fake_user_client)
    result = mcp_call(client, "list_catalogs", {}, token="user-token-123")
    assert seen == ["user-token-123"]
    assert result["structuredContent"] == {
        "items": [{"name": "main", "comment": "c", "owner": "o"}],
        "truncated": False,
    }


def test_uc_tool_maps_sdk_error_over_http(client, monkeypatch):
    w = fake_workspace()
    w.tables.get.side_effect = PermissionDenied("nope")
    monkeypatch.setattr("skills_mcp.auth.user_client", lambda token: w)
    result = mcp_call(client, "describe_table", {"full_name": "a.b.c"}, token="t")
    assert result["isError"] is True
    assert "Databricks denied access: nope" in result["content"][0]["text"]


def test_async_function_sdk_error_is_mapped():
    @sdk_errors_as_tool_errors
    async def boom():
        raise PermissionDenied("no")

    import asyncio

    with pytest.raises(ToolError, match="Databricks denied access: no."):
        asyncio.run(boom())


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_blocked_uc_call_does_not_block_other_requests(curated_skills, monkeypatch):
    from skills_mcp.server import build_server
    from tests.conftest import MCP_HEADERS

    started, release = threading.Event(), threading.Event()
    results = {}
    w = fake_workspace()

    def blocking_get(full_name):
        started.set()
        results["released_by_test"] = release.wait(timeout=3)
        return TableInfo(full_name=full_name)

    w.tables.get.side_effect = blocking_get
    monkeypatch.setattr("skills_mcp.auth.user_client", lambda token: w)
    app = build_server(curated_skills).streamable_http_app()

    def body(tool, args):
        return {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:

            async def describe():
                headers = {**MCP_HEADERS, "x-forwarded-access-token": "t"}
                r = await c.post("/mcp", headers=headers, json=body("describe_table", {"full_name": "a.b.c"}))
                results["describe"] = r.json()["result"]

            async with anyio.create_task_group() as tg:
                tg.start_soon(describe)
                while not started.is_set():
                    await anyio.sleep(0.01)
                with anyio.fail_after(5):
                    r = await c.post("/mcp", headers=MCP_HEADERS, json=body("list_skills", {}))
                results["list_done_before_release"] = not release.is_set()
                release.set()
    # If the loop were blocked, the fake's wait would time out before the test could release it.
    assert results["released_by_test"] is True
    assert results["list_done_before_release"] is True
    assert r.json()["result"]["structuredContent"]["skills"]
    assert results["describe"]["structuredContent"]["full_name"] == "a.b.c"
