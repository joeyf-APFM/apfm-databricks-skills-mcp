# Databricks Skills MCP App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy an APFM-owned MCP server, hosted as a Databricks App on the `aplaceformom` workspace. It serves a curated, APFM-annotated copy of `databricks/databricks-agent-skills` plus read-only Unity Catalog tools built on the Databricks Python SDK.

**Architecture:** A Python package, `skills_mcp`, builds a FastMCP server. It runs in stateless HTTP mode with JSON responses and is served by uvicorn at `/mcp` inside a Databricks App. Skill content is produced offline: `tools/curate.py` turns a pinned upstream release into `app/skills/`, which is committed so reviewers can see each version bump as a diff, and deployed with the app. Every Databricks API call runs as the calling user, through a `WorkspaceClient` built from the `x-forwarded-access-token` header. Nothing falls back to the app's service principal.

**Tech Stack:** Python 3.11+, `mcp` (FastMCP), `databricks-sdk`, `PyYAML`, `pytest`, `httpx`/Starlette `TestClient`, Declarative Automation Bundles (`databricks.yml`), GitHub Actions.

**Spec:** `databricks-skills-proposal.html` (published at https://claude.ai/artifact/59Xz5a8gnNYkoBMiUnjvrG), sections "What we're building", "Python SDK only", and "Rollout plan". Companion plan: `2026-10-28-platform-mcp-skills-server.md` (the Platform MCP side).

**New repo:** `aplaceformom/apfm-databricks-skills-mcp`. The name is proposed; confirm it with DPLAT before Task 1.

## Global Constraints

- The app uses the Databricks Python SDK only. Never install, vendor, or shell out to the Databricks CLI inside the app. CI may use the CLI to deploy.
- Every tool is read-only. Write tools are out of scope for this plan.
- Databricks calls run as the user only: `WorkspaceClient(host=..., token=<x-forwarded-access-token>, auth_type="pat")`. If the header is missing, the tool fails with `MISSING_TOKEN_MESSAGE` (Task 1). It never uses the app service principal.
- Tool names are fixed, because Platform MCP allowlists them exactly: `whoami`, `list_skills`, `load_skill`, `get_skill_file`, `list_catalogs`, `list_schemas`, `list_tables`, `describe_table`.
- App names: `mcp-apfm-skills` (target `prod`) and `mcp-apfm-skills-sbx` (target `sandbox`). Both are at most 30 characters, as Apps requires.
- `user_api_scopes`, exactly: `iam.current-user:read`, `catalog.catalogs:read`, `catalog.schemas:read`, `catalog.tables:read`.
- App runtime limits: one port (`8000`, via `DATABRICKS_APP_PORT`), 10 MB maximum per file, startup within 10 minutes, and a proxy that returns 502 when no response headers arrive within 60 seconds. Every tool must answer in well under 60 seconds.
- License: every published skill directory sits beside a copy of upstream `LICENSE` and `NOTICE`. Every modified `SKILL.md` carries the APFM note, which states that A Place for Mom modified it.
- Curated set: the 31 skills marked Works or Reference in the proposal's skill-fit table. Excluded: `databricks-setup-local`, `databricks-unity-gateway`, and everything under upstream `experimental/`.
- Upstream is pinned in `upstream.lock` to a release tag. The first tag is `v0.2.37`.

**Deviation from the proposal, deliberately:** the proposal's first tool set listed `get_job_run`, `list_pipelines`, `get_app_status`, and `genie_ask`. This plan ships only the Unity Catalog tools. The Apps scope list published in the `databricks-apps` skill names no jobs, pipelines, or apps read scopes, so those tools wait until their scope names are confirmed in the Apps auth docs. Genie is already served by Platform MCP's existing `helix_care_*` servers, and a Genie answer can outlast the 60-second proxy limit. There's one smaller deviation too. Resources are `skill://{name}` (the `SKILL.md` only), not `skill://<name>/<path>`, because reference files are already reachable through `get_skill_file`. Update the proposal page to match.

**Startup instructions don't pass through Platform MCP.** Platform MCP forwards tools, not the app's startup instructions. Agents reaching the app through Platform MCP find skills through the guidance section added in the Platform MCP plan. Agents connecting to the app directly get the index from its instructions.

## Review Focus

1. **Path traversal in `get_skill_file`.** Inputs such as `../../app.py`, `/etc/passwd`, `references/../../x`, a symlink inside a skill, and `%2e%2e/` must be rejected with `FileNotAllowed`. Test in Task 3.
2. **No user token.** A direct call to the app, or a call made before scopes are granted, must get `MISSING_TOKEN_MESSAGE`. It must not get a result made with the service principal, and it must not crash. Test in Task 1 (`whoami`) and Task 6 (each UC tool).
3. **Databricks denies or can't find something.** A 403 or 404 from the SDK becomes a clear tool error naming the next step, with no stack trace. Test in Task 6.
4. **Upstream adds, removes, or renames a skill.** `curate` fails loudly and names the skill, so a version bump can't silently ship an uncurated or missing skill. Test in Task 2.
5. **Huge listings.** `list_tables` on a schema with thousands of tables returns at most `limit` items (default 100, clamped to 1-500) with `truncated: true`. Test in Task 6.

---

## File Structure

```
apfm-databricks-skills-mcp/
  pyproject.toml                 # deps + pytest config; package dir = app/
  upstream.lock                  # one line: upstream tag, e.g. v0.2.37
  curation.yaml                  # which upstream skills ship, and their fit
  databricks.yml                 # bundle: app, scopes, CAN_USE, targets
  overlay/
    note-works.md                # APFM note for "works" skills (exact copy below)
    note-reference.md            # extra paragraph for "reference" skills
  tools/
    __init__.py
    curate.py                    # upstream checkout -> app/skills/
    fetch_upstream.sh            # shallow clone of the pinned tag
  app/                           # source_code_path for the app
    app.yaml                     # uvicorn command
    requirements.txt             # pinned, compiled from pyproject.toml
    app.py                       # ASGI entry: `app`
    skills/                      # GENERATED by tools/curate.py, committed
    skills_mcp/
      __init__.py
      auth.py                    # user token + per-user WorkspaceClient
      catalog.py                 # Skill, SkillCatalog, safe file reads
      index.py                   # startup-instructions skill index
      uc_tools.py                # read-only Unity Catalog operations
      errors.py                  # SDK error -> ToolError mapping
      server.py                  # build_server(): registers everything
  tests/
    conftest.py                  # mcp_call() helper over Starlette TestClient
    fixtures/upstream/           # tiny fake upstream release
    test_auth.py
    test_curate.py
    test_catalog.py
    test_index.py
    test_server_skills.py
    test_uc_tools.py
    test_server_http.py
  .github/workflows/
    ci.yml                       # tests + curate --check on PRs
    deploy.yml                   # deploy prod on main
  README.md                      # runbook: bump upstream, deploy, verify
```

---

### Task 1: Minimal app with `whoami`, deployed to sandbox (auth spike gate)

This task proves the riskiest assumption before anything else is built. Can the app receive a user's token, and does it accept a workspace OAuth token like the one Platform MCP holds? **If Step 9 fails, stop the plan** and record the result in the DPLAT ticket. The fallback is the proposal's Option B, bundling the skills inside Platform MCP.

**Files:**
- Create: `pyproject.toml`, `app/app.yaml`, `app/requirements.txt`, `app/app.py`, `app/skills_mcp/__init__.py`, `app/skills_mcp/auth.py`, `app/skills_mcp/server.py`, `databricks.yml`, `tests/conftest.py`, `tests/test_auth.py`, `tests/test_server_http.py`, `.gitignore`, `README.md`

**Interfaces:**
- Produces:
  - `auth.MISSING_TOKEN_MESSAGE: str`, exactly: `"This tool needs your Databricks identity, and the request didn't include it. Call it through Platform MCP or the app's URL with your own Databricks sign-in."`
  - `auth.MissingUserToken(Exception)`
  - `auth.user_token(headers: Mapping[str, str]) -> str`: returns the stripped `x-forwarded-access-token` value. Raises `MissingUserToken` if it's absent or blank.
  - `auth.user_client(token: str) -> databricks.sdk.WorkspaceClient`: host from `DATABRICKS_HOST`, `auth_type="pat"`.
  - `auth.client_from_ctx(ctx: mcp.server.fastmcp.Context) -> WorkspaceClient`: reads `ctx.request_context.request.headers`. Raises `ToolError(MISSING_TOKEN_MESSAGE)` if the token is missing.
  - `server.build_server(skills_dir: Path | None = None) -> FastMCP`, constructed with `stateless_http=True, json_response=True`.
  - `app.app`: the ASGI app from `build_server(...).streamable_http_app()`, serving `/mcp`.
  - Test helper `tests/conftest.py::mcp_call(client, tool: str, args: dict, token: str | None) -> dict`: posts the JSON-RPC `tools/call` and returns the `result` object.
  - Test helper `tests/conftest.py::make_client(skills_dir: Path | None = None)`: a context manager yielding a `TestClient` over `build_server(skills_dir).streamable_http_app()`. A `client` fixture wraps `make_client()` with no skills. Task 5 overrides `client` in its own test module to point at curated fixture output.

- [ ] **Step 1: Write the failing auth tests** in `tests/test_auth.py`

```python
def test_user_token_returns_header_value():
    assert user_token({"x-forwarded-access-token": " abc "}) == "abc"

@pytest.mark.parametrize("headers", [{}, {"x-forwarded-access-token": ""}, {"x-forwarded-access-token": "  "}])
def test_user_token_missing_raises(headers):
    with pytest.raises(MissingUserToken):
        user_token(headers)

def test_user_client_uses_pat_auth_and_https_host(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "dbc-88a3d066-4cdb.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "sp-id")        # Apps injects these; must be ignored
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "sp-secret")
    w = user_client("user-token")
    assert w.config.auth_type == "pat"
    assert w.config.host == "https://dbc-88a3d066-4cdb.cloud.databricks.com"
```

- [ ] **Step 2: Run them and confirm they fail.** Run `uv run pytest tests/test_auth.py -v`. Expected: FAIL with `ModuleNotFoundError: skills_mcp`.

- [ ] **Step 3: Create `pyproject.toml` and implement `auth.py`.**
  - `pyproject.toml` dependencies: `mcp>=1.10,<2`, `databricks-sdk>=0.40`, `PyYAML>=6`.
  - Dev group: `pytest`, `httpx`.
  - Set `[tool.pytest.ini_options] pythonpath = ["app", "."]`.

- [ ] **Step 4: Run the tests and confirm they pass.** Run `uv run pytest tests/test_auth.py -v`. Expected: 4 passed.

- [ ] **Step 5: Write the failing HTTP tests** in `tests/test_server_http.py`, using the `mcp_call` helper over `starlette.testclient.TestClient(app)` (as a context manager, so the lifespan runs). Patch `skills_mcp.auth.user_client` to return a fake whose `current_user.me()` returns an object with `user_name="pat@aplaceformom.com"`.

```python
def test_whoami_returns_calling_user(client, fake_me):
    result = mcp_call(client, "whoami", {}, token="t")
    assert result["structuredContent"]["user_name"] == "pat@aplaceformom.com"

def test_whoami_without_token_fails_closed(client):
    result = mcp_call(client, "whoami", {}, token=None)
    assert result["isError"] is True
    assert MISSING_TOKEN_MESSAGE in result["content"][0]["text"]

def test_accepts_databricks_apps_host_header(client):
    r = client.post("/mcp", headers={"host": "mcp-apfm-skills-123.aws.databricksapps.com", **MCP_HEADERS},
                    json=TOOLS_LIST)
    assert r.status_code == 200
```

`MCP_HEADERS` is `{"accept": "application/json, text/event-stream", "content-type": "application/json"}`. `TOOLS_LIST` is a JSON-RPC `tools/list` request.

- [ ] **Step 6: Run them and confirm they fail.** Run `uv run pytest tests/test_server_http.py -v`. Expected: FAIL. `build_server` and `whoami` aren't defined yet.

- [ ] **Step 7: Implement `server.build_server` with the `whoami` tool, plus `app/app.py`.**
  - `whoami(ctx: Context) -> dict` returns `{"user_name": me.user_name, "display_name": me.display_name}` from `client_from_ctx(ctx).current_user.me()`.
  - If the Host test fails with 421, disable host validation through FastMCP's `transport_security` setting. The Apps proxy sets the Host header.
  - `app/app.yaml`: `command: ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]`.
  - `app/requirements.txt`: `uv pip compile pyproject.toml -o app/requirements.txt`.

  Run `uv run pytest -v`. Expected: all pass.

- [ ] **Step 8: Add `databricks.yml` and deploy to sandbox.** This step needs the user's explicit OK, and they choose the CLI profile.

```yaml
bundle:
  name: apfm-databricks-skills-mcp
variables:
  app_name: { default: mcp-apfm-skills-sbx }
  users_group: { description: "Group(s) that hold the Databricks role in Platform MCP" }
resources:
  apps:
    skills_mcp:
      name: ${var.app_name}
      description: "APFM-curated Databricks agent skills and read-only Unity Catalog tools"
      source_code_path: ./app
      user_api_scopes: [iam.current-user:read, catalog.catalogs:read, catalog.schemas:read, catalog.tables:read]
      permissions:
        - group_name: ${var.users_group}
          level: CAN_USE
targets:
  sandbox: { default: true, workspace: { host: https://dbc-88a3d066-4cdb.cloud.databricks.com } }
  prod:    { mode: production, variables: { app_name: mcp-apfm-skills }, workspace: { host: https://dbc-88a3d066-4cdb.cloud.databricks.com } }
```

Run `databricks apps deploy -t sandbox --profile <PROFILE> --var users_group=<GROUP>`. Expected: the deploy finishes and prints the app URL.

Then run `databricks apps get mcp-apfm-skills-sbx --profile <PROFILE>`. Expected: `user_api_scopes` lists exactly the four scopes above.

- [ ] **Step 9: Spike check. This step is the gate.** With a user's workspace OAuth token, which is the same kind of token Platform MCP holds:

```bash
TOKEN=$(databricks auth token --profile <USER_PROFILE> | jq -r .access_token)
curl -s https://<APP_URL>/mcp -H "Authorization: Bearer $TOKEN" \
  -H 'accept: application/json, text/event-stream' -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"whoami","arguments":{}}}'
```

Expected: `user_name` is the token owner's email. A 401, an HTML login page, or `MISSING_TOKEN_MESSAGE` means the gate failed: stop and escalate. Record the result in the DPLAT ticket either way.

- [ ] **Step 10: Commit.**

```bash
git add -A && git commit -m "feat: minimal skills MCP app with whoami, sandbox bundle"
```

---

### Task 2: Curation tool

**Files:**
- Create: `tools/__init__.py`, `tools/curate.py`, `tools/fetch_upstream.sh`, `curation.yaml`, `overlay/note-works.md`, `overlay/note-reference.md`, `upstream.lock`, `tests/fixtures/upstream/**`, `tests/test_curate.py`

**Interfaces:**
- Produces:
  - `tools.curate.CurationError(Exception)`
  - `tools.curate.CurationResult`: a dataclass with `included: list[str]`, `excluded: list[str]`, `upstream_version: str`.
  - `tools.curate.curate(upstream: Path, config: Path, out: Path) -> CurationResult`
  - CLI: `python -m tools.curate --upstream DIR --config curation.yaml --out app/skills [--check]`. `--check` exits 1 and prints the differing paths if the output would change.
  - Output layout, consumed by Task 3:
    - `out/<skill>/SKILL.md` gets a `apfm_fit: works|reference` line inserted before the closing `---` of the frontmatter, and the APFM note inserted directly after the frontmatter.
    - The skill's `*.md` and `*.py` files are copied with relative paths kept.
    - `out/LICENSE`, `out/NOTICE`, and `out/UPSTREAM_VERSION` hold the upstream manifest's `version`.

`curation.yaml` shape:

```yaml
include:
  works: [databricks-dbsql, databricks-data-discovery, databricks-metric-views, databricks-ai-functions,
          databricks-unity-catalog, databricks-iceberg, databricks-docs, databricks-spark-structured-streaming,
          databricks-app-design, databricks-synthetic-data-gen]
  reference: [databricks-apps, databricks-apps-python, databricks-dabs, databricks-jobs, databricks-pipelines,
              databricks-lakebase, databricks-model-serving, databricks-vector-search, databricks-execution-compute,
              databricks-ml-training, databricks-mlflow-evaluation, databricks-genie-agents, databricks-lakeflow-connect,
              databricks-serverless-migration, databricks-serverless, databricks-zerobus-ingest, databricks-python-sdk,
              databricks-aibi-dashboards, databricks-ai-runtime, databricks-unstructured-pdf-generation, databricks-core]
exclude: [databricks-setup-local, databricks-unity-gateway]
```

`overlay/note-works.md`. This is exact copy:

```markdown
> **APFM note.** A Place for Mom added this note and the `apfm_fit` field to the upstream Databricks skill; the rest is unchanged.
> You're using this skill through APFM Platform MCP, where there's no Databricks CLI.
> - Run SQL with `databricks_call(workspace="aplaceformom", server="sql", tool="execute_sql_read_only", arguments={"query": "..."})`.
> - Ask data questions through the `helix_care_*` Genie servers that `databricks_discover_tools` lists.
> - Where this skill says to run a `databricks` CLI command, use the matching tool on the `skills` server if there is one, for example `describe_table` instead of `databricks tables get`. Otherwise skip that step and tell the user it needs a local Databricks setup.
```

`overlay/note-reference.md`, appended after the works note for reference skills:

```markdown
>
> This skill is reference-only through Platform MCP. Its deploy, create, and write steps need a local Databricks setup and aren't available here.
```

- [ ] **Step 1: Build the fixture** at `tests/fixtures/upstream/`, containing:
  - `manifest.json` (`{"version": "0.0.1", "skills": {"alpha": {}, "beta": {}, "gamma": {}}}`)
  - `LICENSE` and `NOTICE`
  - `skills/alpha/SKILL.md` (YAML frontmatter with a folded `description: >-`), `skills/alpha/references/one.md`, `skills/alpha/examples/ex.py`, `skills/alpha/assets/icon.png`, `skills/alpha/agents/openai.yaml`
  - `skills/beta/SKILL.md` and `skills/gamma/SKILL.md`

  Add a fixture config: `include: {works: [alpha], reference: [beta]}`, `exclude: [gamma]`.

- [ ] **Step 2: Write the failing tests** in `tests/test_curate.py`.

```python
def test_copies_md_and_py_only(tmp_path): ...       # alpha/references/one.md, alpha/examples/ex.py exist; no .png/.yaml
def test_inserts_fit_and_note_after_frontmatter(tmp_path):
    text = (out / "alpha/SKILL.md").read_text()
    front, body = split_frontmatter(text)
    assert yaml.safe_load(front)["apfm_fit"] == "works"
    assert body.lstrip().startswith("> **APFM note.**")
    assert upstream_body_of("alpha") in body          # upstream text unchanged
def test_reference_skill_gets_reference_paragraph(tmp_path): ...   # "reference-only through Platform MCP" in beta
def test_writes_license_notice_and_version(tmp_path): ...          # UPSTREAM_VERSION == "0.0.1"
def test_unlisted_upstream_skill_fails(tmp_path):                  # add skills/delta -> CurationError mentioning "delta"
def test_listed_skill_missing_upstream_fails(tmp_path):            # config lists "omega" -> CurationError mentioning "omega"
def test_removes_stale_output(tmp_path): ...                       # pre-existing out/old-skill/ is gone after run
def test_rejects_file_over_10mb(tmp_path): ...                     # 10*1024*1024+1 byte .md -> CurationError naming the file
def test_check_mode_reports_drift(tmp_path): ...                   # CLI --check exits 1 after editing an output file
def test_skill_in_both_include_and_exclude_fails(tmp_path): ...
```

- [ ] **Step 3: Run them and confirm they fail.** Run `uv run pytest tests/test_curate.py -v`. Expected: FAIL with `ModuleNotFoundError: tools.curate`.

- [ ] **Step 4: Implement `curate`.**
  - Insert text into the frontmatter and body rather than re-serializing the YAML, so upstream bytes stay identical apart from the two insertions.
  - Write into a temp directory, then swap it into `out`. That's how stale skills disappear.
  - Ignore `experimental/`. Only `skills/` counts as stable upstream.

- [ ] **Step 5: Run the tests and confirm they pass.** Run `uv run pytest tests/test_curate.py -v`. Expected: all pass.

- [ ] **Step 6: Generate the real output.**
  - Write `v0.2.37` to `upstream.lock`.
  - `tools/fetch_upstream.sh` runs `git clone --depth 1 --branch "$(cat upstream.lock)" https://github.com/databricks/databricks-agent-skills "$1"`.
  - Run `bash tools/fetch_upstream.sh /tmp/up && uv run python -m tools.curate --upstream /tmp/up --config curation.yaml --out app/skills`.

  Expected: 31 skill directories in `app/skills/`, plus `LICENSE`, `NOTICE`, and `UPSTREAM_VERSION` containing the upstream version.

- [ ] **Step 7: Commit.**

```bash
git add tools curation.yaml overlay upstream.lock tests app/skills && git commit -m "feat: curate pinned databricks-agent-skills into app/skills"
```

---

### Task 3: Skill catalog with safe file reads

**Files:**
- Create: `app/skills_mcp/catalog.py`, `tests/test_catalog.py`

**Interfaces:**
- Consumes: the Task 2 output layout.
- Produces:
  - `catalog.Skill`: a frozen dataclass with `name: str`, `description: str`, `fit: str` (`"works"` or `"reference"`), `files: tuple[str, ...]` (POSIX relative paths, sorted).
  - `catalog.SkillNotFound(KeyError)` and `catalog.FileNotAllowed(ValueError)`.
  - `catalog.SkillCatalog.from_dir(root: Path) -> SkillCatalog`
  - `SkillCatalog.names() -> list[str]` (sorted), `SkillCatalog.get(name: str) -> Skill`, `SkillCatalog.list(query: str | None = None) -> list[Skill]`
  - `SkillCatalog.read(name: str, path: str = "SKILL.md") -> str`
  - `SkillCatalog.upstream_version: str`

- [ ] **Step 1: Write the failing tests.** Use a `tmp_path` built by running `curate` on the Task 2 fixture.

```python
def test_loads_name_description_fit(): assert cat.get("alpha").fit == "works"
def test_folded_description_is_one_line(): assert "\n" not in cat.get("alpha").description
def test_list_query_matches_name_or_description_case_insensitive(): ...
def test_read_default_is_skill_md(): assert cat.read("alpha").startswith("---")
def test_read_reference_file(): assert "..." in cat.read("alpha", "references/one.md")
def test_unknown_skill_raises(): pytest.raises(SkillNotFound, cat.read, "nope")
@pytest.mark.parametrize("bad", ["../beta/SKILL.md", "/etc/passwd", "references/../../beta/SKILL.md",
                                  "%2e%2e/beta/SKILL.md", "references/missing.md", ""])
def test_rejects_paths_outside_skill_or_unlisted(bad): pytest.raises(FileNotAllowed, cat.read, "alpha", bad)
def test_rejects_symlink_escaping_skill(tmp_path): ...   # alpha/link.md -> ../beta/SKILL.md raises FileNotAllowed
def test_upstream_version_read(): assert cat.upstream_version == "0.0.1"
```

- [ ] **Step 2: Run them and confirm they fail.** Run `uv run pytest tests/test_catalog.py -v`. Expected: FAIL with an import error.

- [ ] **Step 3: Implement `SkillCatalog`.**
  - Read only paths already in `Skill.files`, which is built at load time from regular, non-symlink files.
  - URL-decode `path` before the lookup, so `%2e%2e/` is checked in its decoded form.

- [ ] **Step 4: Run the tests and confirm they pass.** Expected: all pass.

- [ ] **Step 5: Commit.** `git commit -am "feat: skill catalog with allowlisted file reads"`

---

### Task 4: Skill index for startup instructions

**Files:**
- Create: `app/skills_mcp/index.py`, `tests/test_index.py`

**Interfaces:**
- Consumes: `SkillCatalog` (Task 3).
- Produces: `index.build_index(catalog: SkillCatalog, max_chars: int = 8000) -> str`. Raises `ValueError` if the result exceeds `max_chars`.

Exact header copy:

```markdown
# APFM Databricks skills

Before doing Databricks work a skill below covers, load it with `load_skill(name)` and follow it. Load reference files it mentions with `get_skill_file(name, path)`. "reference" skills explain concepts and code, but their deploy and write steps aren't available here.

| Skill | Use when | Fit |
|---|---|---|
```

Each row is `| <name> | <use when> | <fit> |`. The "use when" text is the description's first sentence, capped at 120 characters with a trailing `…` when cut. Escape `|` as `\|`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_one_row_per_skill_sorted(): ...
def test_use_when_is_first_sentence_capped_at_120(): ...
def test_pipe_in_description_is_escaped(): ...
def test_raises_when_over_max_chars(): pytest.raises(ValueError, build_index, big_catalog, max_chars=500)
def test_real_skills_fit_in_8000_chars():   # skipped if app/skills missing
    assert len(build_index(SkillCatalog.from_dir(Path("app/skills")))) <= 8000
```

- [ ] **Step 2: Run them and confirm they fail.** Expected: import error.

- [ ] **Step 3: Implement `build_index`.**

- [ ] **Step 4: Run the tests and confirm they pass.** Expected: all pass, including `test_real_skills_fit_in_8000_chars` against the 31 committed skills.

- [ ] **Step 5: Commit.** `git commit -am "feat: skill index for MCP instructions"`

---

### Task 5: Skill tools, resources, and prompts on the server

**Files:**
- Modify: `app/skills_mcp/server.py`, `app/app.py` (pass `Path(__file__).parent / "skills"`)
- Create: `tests/test_server_skills.py`

**Interfaces:**
- Consumes: `SkillCatalog` and its errors (Task 3), `build_index` (Task 4), `mcp_call` (Task 1).
- Produces, registered on the server:
  - `instructions = build_index(catalog)`
  - Tool `list_skills(query: str | None = None) -> {"skills": [{"name", "description", "fit"}], "upstream_version": str}`
  - Tool `load_skill(name: str) -> str`: the full `SKILL.md`, followed by a final line listing the skill's other files.
  - Tool `get_skill_file(name: str, path: str) -> str`
  - Resource template `skill://{name}`, returning `SKILL.md` as `text/markdown`.
  - One prompt per skill, named after the skill, with argument `request: str`. It renders: `Load the {name} skill with load_skill("{name}") and follow it for this request: {request}`.
  - `SkillNotFound` becomes `ToolError("Unknown skill '{name}'. Call list_skills to see available skills.")`. `FileNotAllowed` becomes `ToolError("'{path}' isn't a file in skill '{name}'. load_skill lists the skill's files.")`.

- [ ] **Step 1: Write the failing HTTP tests.** Point the server at the curated fixture output.

```python
def test_instructions_contain_index(client): ...           # initialize result.instructions has "| alpha |"
def test_list_skills_filters(client): ...                  # query="alpha" -> one result
def test_load_skill_returns_note_and_file_list(client): ...# text contains "> **APFM note.**" and "references/one.md"
def test_get_skill_file_ok(client): ...
def test_get_skill_file_traversal_is_tool_error(client):   # isError True, message from interface above
def test_unknown_skill_is_tool_error(client): ...
def test_resource_read_skill_md(client): ...               # resources/read skill://alpha
def test_prompt_per_skill(client): ...                     # prompts/list has "alpha"; prompts/get renders request text
def test_skill_tools_need_no_user_token(client): ...       # list_skills works with token=None
```

- [ ] **Step 2: Run them and confirm they fail.** Run `uv run pytest tests/test_server_skills.py -v`. Expected: FAIL with unknown tool `list_skills`.

- [ ] **Step 3: Implement the registrations in `build_server`.** Register prompts in a loop with `mcp.add_prompt(Prompt.from_function(...))`.

- [ ] **Step 4: Run the full suite and confirm it passes.** Run `uv run pytest -v`. Expected: all pass.

- [ ] **Step 5: Commit.** `git commit -am "feat: serve curated skills as MCP tools, resources, prompts"`

---

### Task 6: Read-only Unity Catalog tools

**Files:**
- Create: `app/skills_mcp/uc_tools.py`, `app/skills_mcp/errors.py`, `tests/test_uc_tools.py`
- Modify: `app/skills_mcp/server.py`

**Interfaces:**
- Consumes: `auth.client_from_ctx` (Task 1).
- Produces, as pure functions taking a `WorkspaceClient`, each wrapped by a server tool of the same name that takes `ctx` first:
  - `list_catalogs(w, limit: int = 100) -> {"items": [{"name", "comment", "owner"}], "truncated": bool}`
  - `list_schemas(w, catalog: str, limit: int = 100) -> same shape`, from `w.schemas.list(catalog_name=catalog)`
  - `list_tables(w, catalog: str, schema: str, limit: int = 100) -> {"items": [{"name", "full_name", "table_type", "comment"}], "truncated": bool}`
  - `describe_table(w, full_name: str) -> {"full_name", "table_type", "data_source_format", "owner", "comment", "columns": [{"name", "type_text", "nullable", "comment"}]}`
  - `limit` is clamped to the range 1-500. `truncated` is true when more items existed. Read at most `limit + 1` items from the SDK iterator.
  - `errors.sdk_errors_as_tool_errors` is a decorator that maps:
    - `PermissionDenied` to `"Databricks denied access: {msg}. Ask for the Unity Catalog grant you need, then try again."`
    - `NotFound` to `"Not found in Databricks: {msg}"`
    - `Unauthenticated` to `"Your Databricks sign-in wasn't accepted. Reconnect Databricks in Platform MCP (provider_manage_connections) and try again."`
    - any other `DatabricksError` to `"Databricks returned an error: {msg}"`

- [ ] **Step 1: Write the failing tests.** Use a fake `WorkspaceClient` built with `MagicMock(spec=WorkspaceClient)` whose list methods return iterators of SDK dataclasses.

```python
def test_list_tables_caps_and_flags_truncation(): # 1000 tables, limit=100 -> 100 items, truncated True
def test_limit_clamped(): # limit=0 -> 1 item; limit=10_000 -> at most 500
def test_list_schemas_passes_catalog_name(): ...
def test_describe_table_trims_fields(): ...
@pytest.mark.parametrize("exc,phrase", [(PermissionDenied("no"), "denied access"), (NotFound("x"), "Not found"),
                                        (Unauthenticated("x"), "Reconnect Databricks")])
def test_sdk_errors_become_tool_errors(exc, phrase): ...
def test_each_uc_tool_without_token_fails_closed(client):   # HTTP: every UC tool, token=None -> MISSING_TOKEN_MESSAGE
def test_uc_tool_uses_user_client(client, monkeypatch): ... # user_client called with the request's token
```

- [ ] **Step 2: Run them and confirm they fail.** Run `uv run pytest tests/test_uc_tools.py -v`. Expected: import error.

- [ ] **Step 3: Implement `uc_tools.py` and `errors.py`, and register the four tools.** Wrap `whoami` with the error decorator too.

- [ ] **Step 4: Run the full suite and confirm it passes.** Run `uv run pytest -v`. Expected: all pass.

- [ ] **Step 5: Redeploy to sandbox and verify as a real user.** This needs the user's OK. Run `databricks apps deploy -t sandbox --profile <PROFILE> --var users_group=<GROUP>`. Then, with the Task 1 Step 9 curl, check two things:
  - `describe_table` on a table you can read returns its columns.
  - `describe_table` on a table you can't read returns the "denied access" message.

- [ ] **Step 6: Commit.** `git commit -am "feat: read-only Unity Catalog tools running as the user"`

---

### Task 7: CI, prod deploy, and runbook

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes:
  - CLI from Task 2: `python -m tools.curate ... --check` and `tools/fetch_upstream.sh`.
  - Bundle targets from Task 1.
- Produces:
  - Prod app `mcp-apfm-skills` and its URL. The Platform MCP plan's `base_url` uses this URL.

- [ ] **Step 1: Write `ci.yml`.** It runs on pull requests:
  1. `uv sync`
  2. `uv run pytest -v`
  3. `bash tools/fetch_upstream.sh "$RUNNER_TEMP/up"`
  4. `uv run python -m tools.curate --upstream "$RUNNER_TEMP/up" --config curation.yaml --out app/skills --check`

- [ ] **Step 2: Prove that CI catches drift.** On a branch, edit one file under `app/skills/` by hand and push. Expected: the `curate --check` step fails and names the file. Revert the edit.

- [ ] **Step 3: Write `deploy.yml`.** It runs on push to `main`:
  - Install the Databricks CLI with `databricks/setup-cli`, pinned to a release tag.
  - Run `databricks apps deploy -t prod --var users_group=${{ vars.USERS_GROUP }}`.
  - Authenticate with a deploy service principal through repo secrets `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, and `DATABRICKS_CLIENT_SECRET`. Data Platform creates this principal and grants it permission to manage the app.
  - After the deploy, run `databricks apps get mcp-apfm-skills` and fail the job unless `user_api_scopes` contains all four scopes.

- [ ] **Step 4: Write the README runbook.** Cover these:
  - Bumping upstream: edit `upstream.lock`, re-run curate, and review the `app/skills/` diff in the PR. If the run fails on a new upstream skill, add it to `curation.yaml` as works, reference, or exclude.
  - The two deploy targets, and how to verify with `whoami`.
  - What to do if a deploy dropped the scopes.

- [ ] **Step 5: Merge to `main` and verify prod.** This needs the user's OK. Expected: `deploy.yml` passes. The Task 1 Step 9 curl against the prod URL returns your `user_name`, and `list_skills` returns 31 skills with `upstream_version` set to the pinned version.

- [ ] **Step 6: Record the prod app URL** in the DPLAT ticket for the Platform MCP plan.

- [ ] **Step 7: Commit.** `git commit -am "ci: test, curate drift check, prod deploy; runbook"`
