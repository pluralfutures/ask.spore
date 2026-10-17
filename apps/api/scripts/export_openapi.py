"""Write the API's OpenAPI schema to apps/api/openapi.json (P0-15).

    uv run --directory apps/api python -m scripts.export_openapi

The web client types are generated from that file (``pnpm --dir apps/web
gen:api``). tests/test_api.py fails when the committed file is stale.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.main import create_app

OPENAPI_PATH = Path(__file__).resolve().parents[1] / "openapi.json"


def render() -> str:
    schema: dict[str, Any] = create_app().openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    OPENAPI_PATH.write_text(render(), encoding="utf-8")


if __name__ == "__main__":
    main()
