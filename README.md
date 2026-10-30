# apfm-databricks-skills-mcp

MCP server, deployed as a Databricks App, that serves APFM-curated Databricks agent
skills and read-only Unity Catalog tools. Calls run as the end user via the
`x-forwarded-access-token` header.

## Tests

    uv sync
    uv run pytest

## Regenerating app/requirements.txt

Compile for the Databricks Apps runtime (Python 3.11, Linux), not the host:

    uv pip compile pyproject.toml -o app/requirements.txt --python-version 3.11 --python-platform x86_64-unknown-linux-gnu

## Bumping the upstream skills

1. Edit the tag in `upstream.lock`.
2. Fetch and re-curate:

       bash tools/fetch_upstream.sh /tmp/up
       uv run python -m tools.curate --upstream /tmp/up --config curation.yaml --out app/skills

3. Review the `app/skills/` diff in the PR.
4. If curate fails on a new upstream skill, add it to `curation.yaml` as
   `works`, `reference`, or `exclude`, then re-run step 2.

CI re-runs `curate --check` on every PR and fails if `app/skills/` differs.

## Deploy targets

- `sandbox` (default): app `mcp-apfm-skills-sbx`. Deployed by hand.
- `prod`: app `mcp-apfm-skills`. Deployed by `.github/workflows/deploy.yml` on push to `main`.

## First-time sandbox setup

    databricks apps deploy -t sandbox --profile <PROFILE> --var users_group=<GROUP>

## Before the first prod deploy: grant permissions

The first push to `main` creates `mcp-apfm-skills`. Set up these permissions first:

1. **Deploy service principal.** It must exist in the workspace and be allowed to
   create and manage apps, and its OAuth secret must be stored as the repo secrets
   below. It creates the prod app, so it ends up managing it.
2. **App users.** Set the `USERS_GROUP` repo variable to the group that holds the
   Databricks role in Platform MCP. The bundle grants that group `CAN_USE` on the app.
   The sandbox uses `DataServicesAdmins`.
3. **Unity Catalog grants for users.** The UC tools run as the caller, so each
   user only sees what their own grants allow: `USE CATALOG` and `USE SCHEMA` on
   the path, and `BROWSE` or `SELECT` on the tables. Grant these to users' groups.
4. **The app's own service principal needs no UC grants.** Nothing runs as it.
   Don't grant it data access to work around a user's missing grant, because then
   every caller gets that access.
5. **Allowed app scopes.** A workspace admin setting can restrict which scopes apps
   may request (`allowedAppsUserApiScopes`). It must keep allowing the three
   `catalog.*:read` scopes. It allows all scopes (`*`) as of 2026-10-29.
6. **Prod gate.** Add required reviewers to the `prod` GitHub environment if
   prod deploys should wait for approval.

## Auth spike check

Confirms calls run as the end user. Use the user's own profile.

    TOKEN=$(databricks auth token --profile <USER_PROFILE> | jq -r .access_token)
    curl -s -X POST "https://<APP_URL>/mcp" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -H "Accept: application/json, text/event-stream" \
      -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"whoami","arguments":{}}}'

Expected: a result containing your `user_name`.

Stop if you get a 401, an HTML login page, or the missing-token message. That
means the user token is not reaching the app. Do not go further until it is fixed.

## Verifying a deploy

1. Call `list_skills` (same curl, `"name":"list_skills"`). It should return the
   curated skills with `upstream_version` equal to the `upstream.lock` tag without the leading "v" (`v0.2.37` gives `0.2.37`).
2. Call `describe_table` on a table you can read (`"arguments":{"full_name":"<catalog>.<schema>.<table>"}`).
   A table you cannot read must be refused.

## If a deploy dropped the scopes

Prod CI checks this after every deploy. To check by hand:

    databricks apps get <APP_NAME> -o json | jq .effective_user_api_scopes

All four must be present: `iam.current-user:read`, `catalog.catalogs:read`,
`catalog.schemas:read`, `catalog.tables:read`. `iam.current-user:read` is a
default that Databricks adds itself; listing it in `databricks.yml` fails the
deploy with "not a valid scope". If any are missing:

1. Confirm `user_api_scopes` in `databricks.yml` still lists the three `catalog.*:read` scopes.
2. Re-deploy the target.
3. Check again. If still missing, set them in the app's settings in the workspace UI.

## CI secrets and variables

Recommended: enable branch protection on `main` and require the `ci` check, so only tested code reaches the prod deploy.

Repo secrets (a deploy service principal that can manage the prod app):

- `DATABRICKS_HOST`
- `DATABRICKS_CLIENT_ID`
- `DATABRICKS_CLIENT_SECRET`

Repo variable:

- `USERS_GROUP`

The deploy job uses the GitHub environment `prod`. Add required reviewers there to
gate prod deploys.
