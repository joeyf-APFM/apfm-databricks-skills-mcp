# Integrating databricks-agent-skills into platform-mcp

Analyzed: `aplaceformom/platform-mcp` @ `6675af1` (2026-10-21), `databricks/databricks-agent-skills` @ `b743666` (v0.2.37, 2026-10-28).

## 1. What each repo is

**platform-mcp** is a Go MCP gateway (`modelcontextprotocol/go-sdk` v1.4.1) at `https://platform-mcp.apfmtech.com/mcp/`. Users reach it from Claude Code and Codex over HTTP and from Claude Desktop through the `.mcpb` connector. Relevant mechanics:

- **Provider pattern.** Each provider exposes a `<p>_discover_tools` / `<p>_call` pair (`internal/providers/<name>/provider.go`). The Databricks provider proxies Databricks *managed MCP servers* (sql, genie, vector_search, uc functions). It uses per-user, workspace-scoped OAuth (scopes `sql all-apis offline_access`) against `dbc-88a3d066-4cdb`. The server-type registry (`servertypes.go`) sets each type's URL path template and tool allowlist in code, with tiers read/write/block. The docs say a new server type is "a ~5-line registry entry plus a guidance.md section".
- **Per-request entitlement filtering** (`internal/server/mcp_handler.go`). The MCP server is rebuilt on every request. A provider's tools are registered only if the caller's role allows it. Built-in tools and guidance resources are always registered.
- **Guidance channel already exists.** `internal/server/guidance.go` serves the embedded `guidance.md` files in two ways: concatenated into the MCP `Instructions`, and as `platform://guidance/<provider>` resources. Server-side "agent knowledge" delivery is already in place.
- **Today the Databricks provider is read-only.** It can run `execute_sql_read_only` and `poll_sql_result`, and query 7 Helix Care Genie spaces. It has no CLI, no compute, no writes.

**databricks-agent-skills** contains 33 stable skills (`skills/*/SKILL.md` + `references/`, ~3.3 MB in total). Each has `parent: databricks-core` frontmatter. A generated `manifest.json` drives `databricks aitools install`. The repo also has plugin bundles for Claude Code, Cursor, Codex and Copilot, with hooks: a prompt router, a context primer and an auth-failure hint. Licensed under the **Databricks License**: redistribution is allowed for use with Databricks Services, but you must include the License and NOTICE and mark any modified files prominently.

## 2. The core mismatch (this drives the design)

| Assumption in the skills | Reality for a platform-mcp user |
|---|---|
| A local `databricks` CLI with an authenticated profile (`databricks-core` has 136 CLI lines; apps 89, genie-agents 71, lakebase 64, pipelines 56, …) | No CLI is needed or present. Auth is server-side OAuth. Desktop users have no shell at all. |
| Skills are files on disk that the agent auto-loads by description | MCP has no native "skill" primitive. Content has to be pulled on demand through tools or resources and steered by instructions. |
| Full read/write (deploy bundles, create jobs, apps, endpoints) | Only read-only SQL and Genie are allowlisted. |
| `databricks-data-discovery` → `databricks genie ask` (Genie One) | The equivalent is `databricks_call(server="helix_care_*", tool="query_space_*")` |

Shipping the skills unchanged through platform-mcp would therefore tell most users to run commands they can't run. The integration needs **(a)** a delivery channel, **(b)** a capability filter, and **(c)** a thin APFM overlay that rewrites the "how to execute" parts onto platform-mcp tools.

Skills sorted by whether they work through platform-mcp today:

- **Works through platform-mcp (read-only SQL/Genie or pure knowledge):** `dbsql`, `data-discovery` (needs overlay), `metric-views` (querying), `ai-functions` (in `SELECT`), `unity-catalog` (system tables, grants reasoning), `iceberg`, `docs`, `spark-structured-streaming`, `app-design`, `synthetic-data-gen` (authoring guidance).
- **Knowledge-only (needs a local CLI or write access to act on):** `apps`, `apps-python`, `dabs`, `jobs`, `pipelines`, `lakebase`, `model-serving`, `vector-search`, `execution-compute`, `ml-training`, `mlflow-evaluation`, `genie-agents`, `lakeflow-connect`, `serverless-migration`, `unity-gateway`, `zerobus-ingest`, `python-sdk`, `aibi-dashboards`, `ai-runtime`, `unstructured-pdf-generation`.
- **Exclude:** `databricks-setup-local` (CLI install and profile setup is meaningless behind the gateway) and everything in `experimental/`.

## 3. Options

### Option A: Client-side install only (no platform-mcp code)
Engineers run `/plugin marketplace add databricks/databricks-agent-skills` or `databricks aitools install`. You can push this org-wide through Claude Code managed settings (`extraKnownMarketplaces` + `enabledPlugins`).
- ✅ Zero maintenance. Databricks ships updates. Hooks and routing included.
- ❌ Doesn't reach Desktop or non-CLI users. Requires a personal CLI profile, which bypasses platform-mcp's role gating and audit. No APFM context (workspace names, Genie spaces).

### Option B: Embed a vendored skill catalog in platform-mcp
Vendor a pinned release into `internal/skills/databricks/` with `go:embed`, plus an APFM overlay directory. Serve it through:
- resources `skill://databricks/<name>/SKILL.md` and `skill://databricks/<name>/<ref-path>`
- two tools on the Databricks provider, `databricks_list_skills` and `databricks_load_skill(name, file?)`, so clients that ignore resources (Claude Desktop) can still pull content
- optional MCP prompts (`AddPrompt`) for each skill. In Claude Code these show up as `/mcp__platform-mcp__databricks-dbsql` slash commands.
- ✅ Works for every client today. Fully under APFM control. Gated by the existing Databricks entitlement because the tools sit on the provider. Works before the user has linked OAuth.
- ❌ APFM owns the sync and overlay. Updates need a platform-mcp redeploy. Skills are invisible to Databricks-native agents (Genie Code, Agent Bricks).

### Option C: Publish to Unity Catalog Skills and proxy them as a new Databricks server type (recommended)
The `aplaceformom` workspace already serves the Databricks skill registry MCP at `https://dbc-88a3d066-4cdb.cloud.databricks.com/ai-gateway/skills/` (your local `databricks-skill-registry` MCP points there). Its tools are `list_skills`, `load_skill`, `get_skill_files`, and per-schema `skill_*` tools, plus `create/update/delete_skill`, which only *return* CLI commands.

1. **Publish:** a CI job (in a small `apfm-databricks-skills` repo, or in platform-mcp's `infrastructure/`) pulls a pinned `databricks-agent-skills` release tag. It applies the APFM overlay, adds the LICENSE, NOTICE and modification notices, and publishes each skill with `databricks skills create|update` into something like `platform.agent_skills`. APFM-authored skills (for example the AI Platform Kit skills) go into the same schema.
2. **Govern:** UC grants (`USE`/`EXECUTE` on the schema for the relevant account groups) control who sees which skill, enforced as the human user. This matches the provider's "on behalf of user" model.
3. **Proxy:** add a `skills` entry to `internal/providers/databricks/servertypes.go`:
   ```go
   "skills": {
       PathTemplate: "/ai-gateway/skills/",
       AllowedTools: map[string]string{
           "list_skills": util.TierRead, "load_skill": util.TierRead, "get_skill_files": util.TierRead,
           "create_skill": util.TierBlock, "update_skill": util.TierBlock, "delete_skill": util.TierBlock,
       },
       // plus an AllowedToolTemplates entry if scoped skill_* tools are used
   }
   ```
   and enable it in `config.yaml` under `workspaces.aplaceformom.servers.skills: { type: skills, enabled: true, description: "APFM-curated Databricks agent skills" }`. This change fits the documented path for adding a server type.
- ✅ Native fit with the provider architecture, with almost no new Go code. Permissions are UC-governed and per user, and audited in Databricks. A single source serves platform-mcp, Databricks-native agents and local `ug mcp-proxy` users. Updates need no platform-mcp redeploy.
- ❌ Skills are reachable only after the user links Databricks OAuth, and two levels deep (`databricks_call(server="skills", tool="load_skill", …)`). The UC Skills / AI Gateway feature may still be preview. **Two things are unverified:** (i) whether the platform-mcp OAuth app's `all-apis` scope is accepted on `/ai-gateway/skills/`, and (ii) whether the response is plain MCP JSON-RPC that `providerclient.HTTPClient` can consume. The URL is outside `/api/2.0/mcp/`.

## 4. Recommendation

Use **C as the system of record, with two thin additions:**

1. **Discoverability layer in platform-mcp** (small, provider-local). Add a "Databricks skills" routing table to `internal/providers/databricks/guidance.md`: skill name → one-line "use when" → how to load. Generate it at publish time from the curated `manifest.json`. This plays the role of the upstream prompt-router hook, which can't run over MCP. Agents get the index in `Instructions` and on `platform://guidance/databricks`, then call `load_skill` on demand. About 2–3 KB of always-on context, compared with 3.3 MB for the full set.
2. **APFM overlay.** It's applied in the publish job, never in Go. For each published skill, add a short preamble: *"Behind platform-mcp: run SQL with `databricks_call(workspace="aplaceformom", server="sql", tool="execute_sql_read_only")`. Ask Genie via the `helix_care_*` servers. CLI, deploy and write steps in this skill need a local Databricks CLI and are not available through platform-mcp."* Replace `databricks-data-discovery`'s Genie One routing with the configured Genie spaces. Mark the knowledge-only skills with `compatibility: requires local Databricks CLI`.
3. **Engineers with a CLI** keep using Option A for full read/write workflows. Document this in the Confluence "Platform MCP — Getting Started" page so the two don't compete. platform-mcp handles governed read and query; the plugin handles building and deploying.

**Fallback:** if step 0 below shows `/ai-gateway/skills/` can't be called with the platform-mcp token, build Option B. The publish job and overlay don't change; only the sink changes, to a PR into `internal/skills/`. The two provider tools are about 150 lines on top of the existing `staticTextResourceHandler`.

## 5. Implementation plan

| # | Step | Repo / area | Done when |
|---|---|---|---|
| 0 | **Spike:** with a platform-mcp-issued user token (sandbox), call `tools/list` on `https://dbc-88a3d066-4cdb.cloud.databricks.com/ai-gateway/skills/`. Confirm scope, response shape and preview status. | sandbox | Decision C vs B recorded in a DPLAT ticket |
| 1 | Create `platform.agent_skills` (or similar). Grant `USE CATALOG`/`USE SCHEMA` plus skill read to the Duo-backed groups that hold the Databricks platform-mcp role. | Databricks UC (Terraform) | A non-admin user can `list_skills` |
| 2 | Publish job: pin a `databricks-agent-skills` tag, filter to the curated list (§2), apply the overlay, add the license and modification notices, publish with `databricks skills create/update` using an SP, and regenerate the guidance index. Schedule it weekly or on upstream release, with a PR gate on the version bump. | new repo or `platform-mcp/infrastructure/` | Skills visible in UC; index file produced |
| 3 | Add the `skills` server type, with tests mirroring `servertypes_test.go` (allowlist, block tier). Add the `config.yaml` entry. | `internal/providers/databricks/` | `databricks_discover_tools` lists `skills`; `create_skill` is rejected |
| 4 | Embed the generated skill index in `guidance.md` and add a "Loading skills" section. | `internal/providers/databricks/guidance.md` | `guidance_test.go` passes; index visible in Instructions |
| 5 | Extend the `.claude/skills/mcp-e2e` checks: list skills, load `databricks-dbsql`, follow it to run a read-only query. | `.claude/skills/mcp-e2e` | e2e case passes in sandbox |
| 6 | Docs: `docs/providers/databricks.md` server-type table, the Confluence Getting Started page, and the Option A instructions for engineers. | docs | Published |

## 6. Risks and open questions

- **License hygiene.** The overlay modifies the skill files. Keep upstream files byte-identical where possible and put APFM changes in a separate prepended section or file. Ship LICENSE and NOTICE with every published skill.
- **Context bloat.** Never inline whole skills into `Instructions`. Inline only the index.
- **Drift.** Upstream skills cite CLI flags that change quickly (the repo ships near-daily releases). Pin tags and update deliberately.
- **Entitlement interplay.** Skills sit behind the Databricks provider entitlement *and* UC grants. A user denied the provider sees no skills. That's probably right, but confirm with the role catalog owners.
- **Client behavior.** Claude Desktop and Codex don't auto-invoke MCP-delivered "skills" the way they do local skills. Steering depends on the guidance index, so measure it in mcp-e2e rather than assuming it.
