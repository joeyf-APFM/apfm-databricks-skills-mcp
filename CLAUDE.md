# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An MCP server deployed as a Databricks App (bundle `apfm-databricks-skills-mcp`). It serves two things
to agents connecting through APFM Platform MCP:

1. **Curated Databricks agent skills**, vendored from upstream `databricks/databricks-agent-skills` at the
   tag pinned in `upstream.lock`, exposed as tools (`list_skills`, `load_skill`, `get_skill_file`),
   `skill://{name}` resources, and one MCP prompt per skill.
2. **Read-only Unity Catalog tools** (`whoami`, `list_catalogs`, `list_schemas`, `list_tables`,
   `describe_table`) that run **as the calling user**, never as the app service principal.

`README.md` holds the operational runbook (auth spike check, deploy verification, scope recovery, CI
secrets). Read it before deploying.

## Commands

```bash
uv sync
uv run pytest                                   # pythonpath = ["app", "."], testpaths = tests
uv run pytest tests/test_uc_tools.py::test_list_tables_caps_and_flags_truncation  # single test

# Regenerate the curated skills after changing upstream.lock, curation.yaml, or overlay/
bash tools/fetch_upstream.sh /tmp/up
uv run python -m tools.curate --upstream /tmp/up --config curation.yaml --out app/skills
uv run python -m tools.curate --upstream /tmp/up --config curation.yaml --out app/skills --check  # what CI runs

# Regenerate app/requirements.txt (the Apps runtime installs from this, not pyproject/uv.lock)
uv pip compile pyproject.toml -o app/requirements.txt --python-version 3.11 --python-platform x86_64-unknown-linux-gnu

# Sandbox deploy (by hand). Pass the profile explicitly; never auto-select one.
databricks apps deploy -t sandbox --profile <PROFILE> --var users_group=<GROUP>
```

There is no linter or type checker configured. Local dev Python is pinned by `.python-version`; the
Apps runtime is Python 3.11.

## Architecture

### Skills pipeline (build time)

`app/skills/` is **generated output; never hand-edit it.** `tools/curate.py` builds it from an upstream
checkout:

- Every upstream skill must appear in `curation.yaml` under `include.works`, `include.reference`, or
  `exclude`, or curation fails. A config name missing upstream also fails. A new upstream tag that adds
  a skill therefore breaks curation until `curation.yaml` is updated.
- Only `.md` and `.py` files are copied (no assets, no `agents/*.yaml`), each capped at 10 MB.
- Each `SKILL.md` gets `apfm_fit: <works|reference>` injected into its frontmatter, and the
  `overlay/note-works.md` note (plus `overlay/note-reference.md` for `reference` skills) inserted right
  after the frontmatter. Editing an overlay changes every curated skill, so re-run curate and commit
  the diff.
- `UPSTREAM_VERSION` comes from upstream `metaplugin/version.meta.json` (`current_version`), which is
  why `list_skills` reports the version without the tag's leading `v`.
- Output is written to a temp dir and swapped in atomically. `--check` rebuilds to a temp dir and diffs;
  CI (`ci.yml` on PRs, and the `test` job of `deploy.yml`) fails if `app/skills/` drifts.

"works" means the skill is usable through Platform MCP (no CLI, SQL via `databricks_call`);
"reference" means its deploy/write steps need a local Databricks setup. The overlay text tells the
consuming agent this.

### Server (runtime)

`app/app.py` builds the ASGI app via `skills_mcp.server.build_server(app/skills)` and uvicorn serves it
(`app/app.yaml`). Key points spread across `app/skills_mcp/`:

- `catalog.py` loads skills at startup and **fails startup** (`CatalogError`) on bad frontmatter, empty
  description, or missing/invalid `apfm_fit`. `read()` only serves paths in the precomputed file list
  (symlinks skipped), which is the path-traversal guard.
- `index.py` renders a skill table into the FastMCP server `instructions`, capped at 8000 chars
  (raises if exceeded). Adding many skills or long first sentences can break startup.
- `server.py` runs FastMCP with `stateless_http=True`, `json_response=True`, and DNS-rebinding
  protection **disabled** because the Apps proxy rewrites the Host header.
- `auth.py`: the user's token arrives in the `x-forwarded-access-token` header. `user_client` builds a
  `WorkspaceClient` with `auth_type="pat"` so the SDK ignores the app SP's injected
  `DATABRICKS_CLIENT_ID/SECRET`. SDK timeouts are bounded (30 s retry, 15 s HTTP) to stay under the
  Apps proxy's 60 s limit. `run_as_user` runs the blocking SDK call in a worker thread.
- `errors.py`: `@sdk_errors_as_tool_errors` maps SDK `PermissionDenied`/`NotFound`/`Unauthenticated`
  to user-readable `ToolError`s. New UC tools should follow the existing pattern in
  `_register_uc_tools`: async tool, decorated, delegating to a pure function in `uc_tools.py` via
  `auth.run_as_user`.
- `uc_tools.py` list functions clamp `limit` to 1..500 and return `{"items", "truncated"}`.

### Scopes

Adding a UC tool that calls a new API usually needs a new entry in `user_api_scopes` in
`databricks.yml`, **and** in the scope check loop in `.github/workflows/deploy.yml`, **and** in the
README's list. Deploys have been known to drop scopes; the prod workflow verifies them after deploy
against `effective_user_api_scopes`. Never list `iam.current-user:read` or `iam.access-control:read`
in `databricks.yml`: they are defaults Databricks adds itself, and requesting them fails the deploy with
"not a valid scope".

### Tests

`tests/fixtures/upstream/` is a miniature upstream checkout (skills `alpha`, `beta`, `gamma` with its
own `curation.yaml`). The session fixture `curated_skills` curates it once. Server tests use
`make_client()` (Starlette `TestClient` over the streamable HTTP app) and `mcp_call()` to POST JSON-RPC
to `/mcp`; `fake_me` monkeypatches `skills_mcp.auth.user_client` so no real Databricks call is made.

## Deploy

- `sandbox` (default target): app `mcp-apfm-skills-sbx`, deployed by hand.
- `prod`: app `mcp-apfm-skills`, deployed by `deploy.yml` on push to `main` after tests and the curate
  check pass, using OAuth M2M secrets and the `prod` GitHub environment.
