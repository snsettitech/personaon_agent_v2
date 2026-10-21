from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from modules.auth_guard import get_current_user
from modules.interaction_context import InteractionContext, ResolvedInteractionContext


client = TestClient(app)


def _owner_user():
    return {
        "user_id": "owner-1",
        "tenant_id": "tenant-1",
        "role": "owner",
    }


def _training_context(session_id: str = "ts-1") -> ResolvedInteractionContext:
    return ResolvedInteractionContext(
        context=InteractionContext.OWNER_TRAINING,
        origin_endpoint="chat",
        training_session_id=session_id,
    )


def test_sjt_capture_requires_owner_training_context():
    app.dependency_overrides[get_current_user] = _owner_user
    try:
        with patch("routers.decision_capture.verify_twin_ownership"), patch(
            "routers.decision_capture.ensure_twin_active"
        ), patch(
            "routers.decision_capture.require_owner_training_context",
            side_effect=HTTPException(status_code=403, detail="SJT decision capture requires owner_training context"),
        ):
            resp = client.post(
                "/twins/twin-1/decision-capture/sjt",
                json={
                    "training_session_id": "ts-1",
                    "prompt": "User asks advice with missing data.",
                    "options": [{"label": "Clarify"}, {"label": "Answer"}],
                    "selected_option": "Clarify",
                },
            )
            assert resp.status_code == 403
    finally:
        app.dependency_overrides = {}


def test_sjt_capture_success():
    app.dependency_overrides[get_current_user] = _owner_user
    try:
        with patch("routers.decision_capture.verify_twin_ownership"), patch(
            "routers.decision_capture.ensure_twin_active"
        ), patch(
            "routers.decision_capture.require_owner_training_context",
            return_value=_training_context("ts-1"),
        ), patch(
            "routers.decision_capture.record_sjt_capture",
            return_value={
                "event": {"id": "evt-1"},
                "module": {"id": "mod-1", "module_id": "procedural.decision.clarify_before_advice"},
                "clause_ids": ["POL_DECISION_ABC123"],
            },
        ):
            resp = client.post(
                "/twins/twin-1/decision-capture/sjt",
                json={
                    "training_session_id": "ts-1",
                    "intent_label": "advice_or_stance",
                    "prompt": "User asks advice with missing data.",
                    "options": [{"label": "Clarify"}, {"label": "Answer"}],
                    "selected_option": "Clarify",
                    "rationale": "Need key constraints before advising.",
                    "thresholds": {"missing_material_parameters": True},
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "recorded"
            assert body["capture_type"] == "sjt"
            assert body["interaction_context"] == "owner_training"
            assert body["training_session_id"] == "ts-1"
            assert body["clause_ids"] == ["POL_DECISION_ABC123"]
    finally:
        app.dependency_overrides = {}


def test_pairwise_capture_success():
    app.dependency_overrides[get_current_user] = _owner_user
    try:
        with patch("routers.decision_capture.verify_twin_ownership"), patch(
            "routers.decision_capture.ensure_twin_active"
        ), patch(
            "routers.decision_capture.require_owner_training_context",
            return_value=_training_context("ts-2"),
        ), patch(
            "routers.decision_capture.record_pairwise_capture",
            return_value={
                "event": {"id": "evt-2"},
                "module": {"id": "mod-2", "module_id": "procedural.style.concise_direct"},
                "clause_ids": ["POL_STYLE_DEF456"],
            },
        ):
            resp = client.post(
                "/twins/twin-1/decision-capture/pairwise",
                json={
                    "training_session_id": "ts-2",
                    "prompt": "How should I answer this?",
                    "candidate_a": {"text": "Short direct answer."},
                    "candidate_b": {"text": "Long detailed answer."},
                    "preferred": "a",
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["capture_type"] == "pairwise"
            assert body["training_session_id"] == "ts-2"
    finally:
        app.dependency_overrides = {}


def test_introspection_capture_success():
    app.dependency_overrides[get_current_user] = _owner_user
    try:
        with patch("routers.decision_capture.verify_twin_ownership"), patch(
            "routers.decision_capture.ensure_twin_active"
        ), patch(
            "routers.decision_capture.require_owner_training_context",
            return_value=_training_context("ts-3"),
        ), patch(
            "routers.decision_capture.record_introspection_capture",
            return_value={
                "event": {"id": "evt-3"},
                "module": {"id": "mod-3", "module_id": "procedural.process.uncertainty"},
                "clause_ids": ["POL_PROCESS_GHI789"],
            },
        ):
            resp = client.post(
                "/twins/twin-1/decision-capture/introspection",
                json={
                    "training_session_id": "ts-3",
                    "question": "What do you do when uncertain?",
                    "answer": "I disclose uncertainty and ask one clarifying question.",
                    "thresholds": {"confidence_min": 0.85},
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["capture_type"] == "introspection"
            assert body["clause_ids"] == ["POL_PROCESS_GHI789"]
    finally:
        app.dependency_overrides = {}
