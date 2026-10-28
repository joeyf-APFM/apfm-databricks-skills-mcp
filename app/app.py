from pathlib import Path

from skills_mcp.server import build_server

app = build_server(Path(__file__).parent / "skills").streamable_http_app()
