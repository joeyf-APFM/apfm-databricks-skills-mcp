# Discovery: connecting Claude Desktop to this app

Status: proxy check run on October 30, 2026, against the sandbox app (results
below). The bearer-token path works. Option A's discovery partly works; it
still needs a test with a real Claude custom connector.

Agents are meant to reach this server through APFM Platform MCP. This note
covers connecting Claude Desktop (or claude.ai) to the app directly.

## Why "Add custom connector" fails by default

Claude's custom connectors expect an OAuth server that supports dynamic client
registration. Databricks does not offer that, so adding the app URL with no
other settings fails with an error like "does not support dynamic client
registration".

## Option A: native connector with a registered OAuth client

The Databricks docs for custom MCP servers on Apps
(https://docs.databricks.com/aws/en/generative-ai/mcp/custom-mcp) describe this
path for "other clients": "Register an OAuth client with the client's redirect
URL and the app's user authorization scopes." Callers need `CAN_USE` on the app
and an OAuth token. PATs are not accepted.

1. An account admin creates an OAuth app connection (Account Console, Settings,
   App connections), or Terraforms it in `ds-infra` with
   `databricks_custom_app_integration` on the account-level provider:
   - Redirect URLs: `https://claude.ai/api/mcp/auth_callback` and
     `https://claude.com/api/mcp/auth_callback`
   - Scopes: the app's `user_api_scopes` from `databricks.yml`
     (`catalog.catalogs:read`, `catalog.schemas:read`, `catalog.tables:read`),
     plus `offline_access` so Claude can refresh tokens
   - Changes can take up to 30 minutes to take effect
2. Each user adds a custom connector in Claude with the URL
   `https://<APP_URL>/mcp`, and enters the connection's client ID (and secret,
   for a confidential client) under Advanced settings.

No change to `app/` should be needed. `auth.py` reads the user token from
`x-forwarded-access-token`, which the Apps proxy sets whatever client signed in.

If the app gains a UC tool that needs a new scope, add that scope to the app
connection too, along with the places listed under "Scopes" in `CLAUDE.md`.

### Open question: can Claude discover the Databricks login?

Before it starts the OAuth flow, Claude has to find the authorization server.
It looks for a `401` with a `WWW-Authenticate` header, or for
`/.well-known/oauth-protected-resource` or
`/.well-known/oauth-authorization-server` on the app's host.

The Apps proxy handles every request before it reaches our code. If it answers
unauthenticated requests with a redirect to a browser login page, Claude cannot
discover anything, and the app cannot fix that because those requests never
arrive. The Databricks docs do not say how the proxy behaves here.

Check it with unauthenticated requests (no credentials, read-only):

    APP_URL=$(databricks apps get <APP_NAME> --profile <PROFILE> | jq -r .url)
    curl -si -X POST "$APP_URL/mcp" -H "Content-Type: application/json" -d '{}' | head -20
    curl -si "$APP_URL/.well-known/oauth-protected-resource" | head -20
    curl -si "$APP_URL/.well-known/oauth-authorization-server" | head -20

Read the result:

- A `401` with `WWW-Authenticate`, or JSON metadata naming a Databricks
  authorization server: Option A should work. Next step is the `ds-infra`
  Terraform for the app connection.
- A `302` or HTML login page: a native connector will not work through the
  proxy. Use Option B, or raise it with Databricks.

### Results: October 30, 2026

These checks ran against `mcp-apfm-skills-sbx` (status `RUNNING`) at
`https://mcp-apfm-skills-sbx-6444514236792964.aws.databricksapps.com`. All of
them were read-only.

The app's effective scopes are `catalog.catalogs:read`, `catalog.schemas:read`,
`catalog.tables:read`, `iam.access-control:read`, and `iam.current-user:read`.
Databricks added the two `iam` scopes itself.

**Bearer token: works.** The token came from `databricks auth token` on a U2M
profile, so it's a workspace user OAuth token issued to the Databricks CLI's
OAuth client.

| Request | Result |
|---|---|
| `POST /mcp` `tools/list`, no credential | `401`, `Location` set to the workspace `/oidc/oauth2/v2.0/authorize`, body `{}`, no `WWW-Authenticate` |
| `POST /mcp` `tools/list`, `Authorization: Bearer <token>` | `200`, all 8 tools listed |
| `whoami`, bearer | `200`, returned the calling user's email and display name |
| `list_catalogs` with `limit: 3`, bearer | `200`, real catalogs returned |
| `list_skills`, bearer | `200`, 31 skills, `upstream_version` `0.2.37` |

The proxy accepts a user OAuth token as a bearer credential. It forwards the
user's identity in `x-forwarded-access-token`, which is what `auth.py` reads.
The catalog scopes are in effect. The auth spike check in `README.md` passes.

Not yet tested: a token from Platform MCP's own OAuth client
(`apfm-platform-mcp`, scopes `sql`, `all-apis`, `offline_access`). It's also a
workspace user token, so it should behave the same. Task 3 of the Platform
MCP plan confirms it end to end.

**Discovery: metadata is served, but there's no `WWW-Authenticate` header.**

| Request | Result |
|---|---|
| `GET /.well-known/oauth-protected-resource` | `200` JSON: `resource` is the app URL, `authorization_servers` is `https://dbc-88a3d066-4cdb.cloud.databricks.com/oidc`, `scopes_supported` lists the five scopes above |
| `GET /.well-known/oauth-protected-resource/mcp` | `200` JSON, the same, with `resource` set to `<APP_URL>/mcp` |
| `GET /.well-known/oauth-authorization-server` | `302` to the workspace login page, not metadata |
| `POST /mcp` with no `Accept` header | `302` to the login page |

The Apps proxy publishes OAuth protected-resource metadata (RFC 9728) itself,
naming the workspace as the authorization server. So a client that checks
`/.well-known/oauth-protected-resource` can find the Databricks login. A
client that relies only on a `WWW-Authenticate` header in the `401` can't,
because the proxy doesn't send one. The authorization server's own metadata
lives on the workspace host, not the app host.

Next step for Option A: register the app connection described above, then try
adding the app as a custom connector in Claude. That shows whether Claude's
discovery uses the protected-resource metadata.

## Option B: local bridge with `mcp-remote` (works today)

Claude Desktop runs `mcp-remote` as a local stdio server that forwards to the
app with the user's OAuth token. This is the same Bearer-token path as the
auth spike check in `README.md`, which passed on October 30, 2026 (see Results
above).

In `~/Library/Application Support/Claude/claude_desktop_config.json`:

    {
      "mcpServers": {
        "apfm-databricks-skills": {
          "command": "/bin/sh",
          "args": [
            "-c",
            "exec /opt/homebrew/bin/npx -y mcp-remote \"https://<APP_URL>/mcp\" --header \"Authorization: Bearer $(/opt/homebrew/bin/databricks auth token --profile <PROFILE> | /opt/homebrew/bin/jq -r .access_token)\""
          ]
        }
      }
    }

- Use absolute paths (`which npx databricks jq`). Claude Desktop starts
  commands with a very limited `PATH`.
- `<PROFILE>` must be an OAuth (U2M) profile (`databricks auth login`).
- Restart Claude Desktop, then call `whoami` to confirm it runs as you.

Limitation: the token is fetched once, when the server starts, and lasts about
an hour. When tools start returning auth errors, restart Claude Desktop.

## Testing locally (no deploy, no Platform MCP)

Run the server on your machine and connect a client to it directly. There is no
Apps proxy locally, so you set `x-forwarded-access-token` yourself; it's the
header the proxy would set. This tests the server (skills, prompts, UC tools
running as you, error mapping), not the proxy or OAuth.

Replace `<PROFILE>` and the other placeholders with real values, without the
angle brackets. Left in, zsh reads `<` and `>` as redirection and fails with
"parse error near `|`". Use a U2M profile on the app's workspace
(`dbc-88a3d066-4cdb.cloud.databricks.com`).

Start the server from the repo root:

    DATABRICKS_HOST=https://dbc-88a3d066-4cdb.cloud.databricks.com \
      uv run uvicorn app:app --app-dir app --host 127.0.0.1 --port 8000

Bind to `127.0.0.1`. Locally, anyone who can reach the port can send a token
header.

Smoke test with curl:

    TOKEN=$(databricks auth token --profile <PROFILE> | jq -r .access_token)
    curl -s -X POST http://127.0.0.1:8000/mcp \
      -H "x-forwarded-access-token: $TOKEN" \
      -H "Content-Type: application/json" \
      -H "Accept: application/json, text/event-stream" \
      -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"whoami","arguments":{}}}'

Expected: your `user_name`. Without the header, `whoami` and the UC tools
return the "needs your Databricks identity" error, and `list_skills`,
`load_skill`, and `get_skill_file` still work.

### MCP Inspector

    npx @modelcontextprotocol/inspector

In the browser UI, choose the Streamable HTTP transport, set the URL to
`http://127.0.0.1:8000/mcp`, and add the header `x-forwarded-access-token`
with the value of `$TOKEN`. You can then call each tool, read `skill://`
resources, and render prompts.

### Claude Desktop

Use the Option B config with the local URL and the forwarded-token header in
place of `Authorization`:

    "exec /opt/homebrew/bin/npx -y mcp-remote \"http://127.0.0.1:8000/mcp\" --allow-http --header \"x-forwarded-access-token: $(/opt/homebrew/bin/databricks auth token --profile <PROFILE> | /opt/homebrew/bin/jq -r .access_token)\""

Start the local server before Claude Desktop. The same one-hour token limit
applies.
