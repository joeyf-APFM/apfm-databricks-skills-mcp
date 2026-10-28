> **APFM note.** A Place for Mom added this note and the `apfm_fit` field to the upstream Databricks skill; the rest is unchanged.
> You're using this skill through APFM Platform MCP, where there's no Databricks CLI.
> - Run SQL with `databricks_call(workspace="aplaceformom", server="sql", tool="execute_sql_read_only", arguments={"query": "..."})`.
> - Ask data questions through the `helix_care_*` Genie servers that `databricks_discover_tools` lists.
> - Where this skill says to run a `databricks` CLI command, use the matching tool on the `skills` server if there is one, for example `describe_table` instead of `databricks tables get`. Otherwise skip that step and tell the user it needs a local Databricks setup.
