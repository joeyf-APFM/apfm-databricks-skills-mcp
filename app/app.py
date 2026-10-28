from skills_mcp.server import build_server

app = build_server().streamable_http_app()
