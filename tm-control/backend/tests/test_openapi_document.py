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


def test_surveys_paths_are_declared_with_their_answers(settings):
    """The Location page's client is typed from these, so each path declares its success answer and its model."""
    paths = create_app(settings).openapi()["paths"]
    expected = {
        ("/api/v1/surveys", "get"): "200",
        ("/api/v1/surveys", "post"): "201",
        ("/api/v1/surveys/precision", "put"): "200",
        ("/api/v1/surveys/import", "post"): "200",
        ("/api/v1/surveys/{survey_id}", "patch"): "200",
        ("/api/v1/surveys/{survey_id}", "delete"): "204",
        ("/api/v1/surveys/{survey_id}/deploy", "post"): "200",
        ("/api/v1/surveys/{survey_id}/deployments", "get"): "200",
        ("/api/v1/surveys/{survey_id}/events", "get"): "200",
        ("/api/v1/surveys/{survey_id}/location", "post"): "200",
        ("/api/v1/surveys/{survey_id}/deployments/{deployment_id}/bearing", "post"): "200",
    }
    for (path, method), status in expected.items():
        responses = paths[path][method]["responses"]
        assert status in responses, (path, method)
        if status != "204":
            assert "$ref" in str(responses[status]["content"]["application/json"]["schema"]), (path, method)
