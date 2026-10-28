from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from skills_mcp.server import build_server

MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


@contextmanager
def make_client(skills_dir: Path | None = None):
    with TestClient(build_server(skills_dir).streamable_http_app()) as c:
        yield c


@pytest.fixture
def client():
    with make_client() as c:
        yield c


def mcp_call(client, tool: str, args: dict, token: str | None) -> dict:
    headers = dict(MCP_HEADERS)
    if token is not None:
        headers["x-forwarded-access-token"] = token
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
    r = client.post("/mcp", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()["result"]


@pytest.fixture
def fake_me(monkeypatch):
    me = SimpleNamespace(user_name="pat@aplaceformom.com", display_name="Pat")
    fake = SimpleNamespace(current_user=SimpleNamespace(me=lambda: me))
    monkeypatch.setattr("skills_mcp.auth.user_client", lambda token: fake)
    return me
