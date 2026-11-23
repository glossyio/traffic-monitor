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


def test_sharing_paths_are_declared_with_their_answers(settings):
    """The Sharing page's client is typed from these, so each path declares its success answer and its model."""
    paths = create_app(settings).openapi()["paths"]
    expected = {
        ("/api/v1/sharing", "get"): "200",
        ("/api/v1/sharing", "put"): "200",
        ("/api/v1/sharing/notice", "get"): "200",
        ("/api/v1/sharing/reviewed", "post"): "204",
    }
    for (path, method), status in expected.items():
        responses = paths[path][method]["responses"]
        assert status in responses, (path, method)
        if status != "204":
            assert "$ref" in str(responses[status]["content"]["application/json"]["schema"]), (path, method)


def test_surveys_paths_are_declared_with_their_answers(settings):
    """The Location page's client is typed from these, so each path declares its success answer and its model."""
    paths = create_app(settings).openapi()["paths"]
    expected = {
        ("/api/v1/surveys", "get"): "200",
        ("/api/v1/surveys", "post"): "201",
        ("/api/v1/surveys/precision", "put"): "200",
        ("/api/v1/surveys/import", "post"): "200",
        ("/api/v1/surveys/database-copy", "post"): "200",
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


def test_reference_paths_are_declared_with_their_answers(settings):
    """The Cameras page's reference picture: the take answers its model, the pictures and the zip are binary."""
    paths = create_app(settings).openapi()["paths"]
    prefix = "/api/v1/cameras/{name}/reference"
    take = paths[prefix]["post"]["responses"]
    assert "$ref" in str(take["200"]["content"]["application/json"]["schema"])
    binary = {"type": "string", "format": "binary"}
    picture = paths[prefix + "/{ticket}/{picture}"]["get"]["responses"]["200"]["content"]
    assert picture["image/jpeg"]["schema"] == binary
    package = paths[prefix + "/{ticket}/package"]["get"]["responses"]["200"]["content"]
    assert package["application/zip"]["schema"] == binary
    assert "204" in paths[prefix + "/{ticket}"]["delete"]["responses"]
