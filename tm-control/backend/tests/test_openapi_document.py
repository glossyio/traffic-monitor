"""The UI's API client is typed from a committed copy of the app's OpenAPI document, which must match the app."""

import json
from pathlib import Path

from tm_control.app import create_app

REPO = Path(__file__).resolve().parents[3]
COMMITTED = REPO / "tm-control" / "ui" / "src" / "api" / "openapi.json"


def test_committed_openapi_document_matches_the_app(settings):
    committed = json.loads(COMMITTED.read_text())
    assert create_app(settings).openapi() == committed, (
        "run: PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json"
        " && (cd tm-control/ui && npm run api:generate)"
    )
