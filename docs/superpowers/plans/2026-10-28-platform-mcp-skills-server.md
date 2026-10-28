# Platform MCP Skills Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Platform MCP users reach the Databricks Skills MCP App through the existing Databricks provider, as a new `skills` server on the `aplaceformom` workspace.

**Architecture:** Today the provider builds every upstream URL as `https://<workspace hostname>` + the server type's `PathTemplate` (`resolveServer` → `buildUpstreamURL` in `internal/providers/databricks/client.go`). The app lives on its own `*.databricksapps.com` host. So this plan adds an optional per-server `base_url`, which only server types flagged `RequiresBaseURL` may use, and a `skills` server type with an exact read-tier allowlist. The user's existing per-workspace OAuth token is sent unchanged, through the same `OAuthHelper` path as `sql` and `genie`.

**Tech Stack:** Go 1.26, `modelcontextprotocol/go-sdk`, existing `internal/providers/databricks` package and tests.

**Spec:** `databricks-skills-proposal.html`, section "Platform MCP changes". Depends on `2026-10-28-databricks-skills-mcp-app.md`. That plan's Task 1 auth spike must have passed, and its Task 7 must have produced the prod app URL.

## Global Constraints

- Allowlist for `skills`, exactly, every entry `util.TierRead`: `whoami`, `list_skills`, `load_skill`, `get_skill_file`, `list_catalogs`, `list_schemas`, `list_tables`, `describe_table`.
- `base_url` must use `https`, and its host must end in `.databricksapps.com` with at least one label before it. It may not have a path (other than a bare `/`), query, fragment, userinfo, or port. The only exception is `http` on `localhost`, `127.0.0.1`, or `::1`, for tests, matching `validateHostname`.
- `base_url` is required for types with `RequiresBaseURL: true` and rejected for every other type. A mis-set `base_url` must never redirect `sql` or `genie` traffic, or a user's token, to another host.
- v1 uses one `base_url`, the prod app `mcp-apfm-skills`, for both the sandbox and prod Platform MCP deployments, because `config.yaml` is shared. The sandbox app is tested directly in the app repo.
- Follow the package's existing style: table-free `TestXxx_Yyy` tests, errors prefixed `databricks: workspace %q server %q`.

## Review Focus

1. **A `base_url` pointing anywhere but a Databricks Apps host,** such as `https://evil.example.com`, `https://databricksapps.com.evil.io`, `https://x.databricksapps.com@evil.io`, or `https://x.databricksapps.com:8443`. Config load fails, so a user token can't leak. Test in Task 1.
2. **`base_url` set on a `sql` or `genie` server.** Config load fails rather than silently re-routing that traffic. Test in Task 1.
3. **A `skills` server with no `base_url`.** Config load fails with an error naming `base_url`, rather than calling `https://<workspace>/mcp`. Test in Task 1.
4. **A trailing slash on `base_url`.** It resolves to `.../mcp` with no double slash, matching how `buildUpstreamURL` treats hostnames. Test in Task 1.
5. **A tool name the app adds later but the allowlist lacks.** `databricks_call` rejects it with the existing "not allowed" error, and discovery doesn't list it. Test in Task 2.

---

### Task 1: Per-server `base_url` for Databricks Apps servers

**Files:**
- Modify: `internal/providers/databricks/config.go`. Add `ServerConfig.BaseURL`, and extend `validateServer` at `config.go:154-171`.
- Modify: `internal/providers/databricks/servertypes.go`. Add `ServerType.RequiresBaseURL`.
- Modify: `internal/providers/databricks/client.go`. In `resolveServer` at `client.go:103-133`, choose the base.
- Test: `internal/providers/databricks/config_test.go` and `internal/providers/databricks/client_test.go`

**Interfaces:**
- Produces:
  - `ServerConfig.BaseURL string \`yaml:"base_url,omitempty"\``
  - `ServerType.RequiresBaseURL bool`
  - `func validateAppBaseURL(raw string) error`
  - `resolveServer` uses `server.BaseURL` instead of `ws.Hostname` when the field is non-empty, still via `buildUpstreamURL(base, path)`.
- Task 1 uses a test-only server type registered in the test file, `testAppType` (`PathTemplate: "/mcp"`, `RequiresBaseURL: true`), so it doesn't depend on Task 2.

- [ ] **Step 1: Write the failing tests** in `config_test.go`.

```go
func TestConfig_AppServerRequiresBaseURL(t *testing.T)            // error contains "requires base_url"
func TestConfig_BaseURLRejectedOnNonAppType(t *testing.T)         // sql server with base_url -> error contains "base_url is only allowed"
func TestConfig_BaseURLMustBeDatabricksAppsHost(t *testing.T)     // each bad value from Review Focus 1 -> error
func TestConfig_BaseURLValidOK(t *testing.T)                      // "https://mcp-apfm-skills-123.aws.databricksapps.com" and the same with "/" -> nil
func TestConfig_BaseURLHTTPLoopbackAllowed(t *testing.T)          // "http://127.0.0.1:9999" -> nil
```

And in `client_test.go`:

```go
func TestResolveServer_AppTypeUsesBaseURL(t *testing.T)           // url == "https://mcp-apfm-skills-123.aws.databricksapps.com/mcp"
func TestResolveServer_BaseURLTrailingSlashNoDoubleSlash(t *testing.T)
func TestResolveServer_NonAppTypeStillUsesHostname(t *testing.T)  // sql url unchanged
```

- [ ] **Step 2: Run them and confirm they fail.** Run `go test ./internal/providers/databricks/ -run 'BaseURL|AppType|AppServer' -v`. Expected: FAIL to compile, because `BaseURL` and `RequiresBaseURL` are undefined.

- [ ] **Step 3: Implement the fields, `validateAppBaseURL`, and the `resolveServer` change.**
  - Parse with `net/url`. Reject when `u.User != nil` or `u.Port() != ""`, except on loopback.
  - Check the host with `strings.HasSuffix(host, ".databricksapps.com") && host != ".databricksapps.com"`.
  - Reuse `validateHostname`'s raw `?#` delimiter check.

- [ ] **Step 4: Run the tests and confirm they pass.** Run `go test ./internal/providers/databricks/... -v`. Expected: all pass, including every existing test.

- [ ] **Step 5: Commit.**

```bash
git add internal/providers/databricks && git commit -m "[DPLAT-XXXX] Databricks provider: per-server base_url for Databricks Apps servers"
```

---

### Task 2: `skills` server type, config, guidance, and docs

**Files:**
- Modify: `internal/providers/databricks/servertypes.go`. Add a `serverTypes["skills"]` entry.
- Modify: `config.yaml`. Add the server under `providers.databricks.workspaces.aplaceformom.servers`.
- Modify: `internal/providers/databricks/guidance.md`. Add a "Skills server" section.
- Modify: `docs/providers/databricks.md`. Add a row to the server-type table and a config example.
- Modify: `.claude/skills/mcp-e2e/SKILL.md`. Add a Block C row after C6.
- Test: `internal/providers/databricks/servertypes_test.go` and `internal/providers/databricks/provider_test.go`

**Interfaces:**
- Consumes: `ServerType.RequiresBaseURL` and `ServerConfig.BaseURL` (Task 1).
- Produces:

```go
"skills": {
    PathTemplate:    "/mcp",
    RequiresBaseURL: true,
    Description:     "APFM skills app — curated Databricks agent skills and read-only Unity Catalog tools",
    AllowedTools:    map[string]string{ /* the eight Global Constraints names, all util.TierRead */ },
},
```

`config.yaml` entry:

```yaml
          skills:
            type: skills
            enabled: true
            base_url: "<prod app URL from the app plan, Task 7>"
            description: "Curated Databricks agent skills (load before Databricks work) and read-only Unity Catalog lookups that run as you."
```

`guidance.md` section, exact copy:

```markdown
## Skills server

The `skills` server is APFM's Databricks skills app. Before Databricks work such as writing SQL against Unity Catalog, choosing a Genie space, or explaining jobs, pipelines, or apps, call `databricks_call(workspace="aplaceformom", server="skills", tool="list_skills")`, then `load_skill` with the best match, and follow it. Its `list_catalogs`, `list_schemas`, `list_tables`, and `describe_table` tools run as you, under your Unity Catalog permissions.
```

- [ ] **Step 1: Write the failing tests.**

```go
func TestServerTypes_SkillsAllowlistExact(t *testing.T)   // AllowedTools has exactly the 8 names, each util.TierRead; RequiresBaseURL true
func TestServerTypes_RegistryShape(t *testing.T)          // extend `required` slice with "skills"
func TestHandleCall_SkillsRejectsUnlistedTool(t *testing.T) // provider_test: tool "delete_everything" on server "skills" -> existing "not allowed" error
```

- [ ] **Step 2: Run them and confirm they fail.** Run `go test ./internal/providers/databricks/ -run 'Skills|RegistryShape' -v`. Expected: FAIL with "registry missing required server type \"skills\"".

- [ ] **Step 3: Add the registry entry, config entry, guidance section, docs row, and e2e row.**
  - The e2e row C7 calls `databricks_call` with `{"workspace":"aplaceformom","server":"skills","tool":"whoami","arguments":{}}`.
  - Pass criteria: `user_name` matches the runner's email, compared case-insensitively, the same rule as C6.

- [ ] **Step 4: Run the full test suite and confirm it passes.** Run `go test ./...`. Expected: PASS, including `guidance_test.go` and `seed_config_test.go` against the new `config.yaml`.

- [ ] **Step 5: Commit and open the PR.**

```bash
git add -A && git commit -m "[DPLAT-XXXX] Databricks provider: skills server type for the APFM skills app"
```

---

### Task 3: Sandbox verification

**Files:** none

- [ ] **Step 1: Deploy the PR branch to sandbox.** Use the team's normal ECS deploy and wait for the service to stabilize.

- [ ] **Step 2: Run `/mcp-e2e sandbox`.** Expected:
  - C6 and the new C7 both pass.
  - `databricks_discover_tools` lists the `skills` server with exactly the eight tools.

- [ ] **Step 3: Run a manual skill flow through `platform-mcp-sandbox`.** Expected:
  - `list_skills` returns 31 skills.
  - `load_skill("databricks-dbsql")` starts with frontmatter and contains `> **APFM note.**`.
  - `describe_table` on a table you can read returns its columns.

- [ ] **Step 4: Record the results in the DPLAT ticket and request review.**

- [ ] **Step 5: After the prod release, update the Confluence "Platform MCP — Getting Started" page.** Add what the skills server does and the local-plugin path for engineers, then announce it. This needs the user's OK, because it publishes content.
