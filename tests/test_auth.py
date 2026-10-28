import pytest

from skills_mcp.auth import MissingUserToken, user_client, user_token


def test_user_token_returns_header_value():
    assert user_token({"x-forwarded-access-token": " abc "}) == "abc"


@pytest.mark.parametrize("headers", [{}, {"x-forwarded-access-token": ""}, {"x-forwarded-access-token": "  "}])
def test_user_token_missing_raises(headers):
    with pytest.raises(MissingUserToken):
        user_token(headers)


def test_user_client_uses_pat_auth_and_https_host(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "dbc-88a3d066-4cdb.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "sp-id")  # Apps injects these; must be ignored
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "sp-secret")
    w = user_client("user-token")
    assert w.config.auth_type == "pat"
    assert w.config.host == "https://dbc-88a3d066-4cdb.cloud.databricks.com"


def test_user_client_sets_bounded_timeouts(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "dbc-88a3d066-4cdb.cloud.databricks.com")
    w = user_client("user-token")
    assert w.config.retry_timeout_seconds == 30
    assert w.config.http_timeout_seconds == 15
