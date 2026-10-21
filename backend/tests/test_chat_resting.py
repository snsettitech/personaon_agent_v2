"""PUBLIC_CHAT_ENABLED=false resting-mode session continuity.

Phase 0 review fix: _resting_chat_response()/_resting_chat_stream() used to
always mint a brand-new random conversation_id/session_id via uuid.uuid4(),
ignoring the conversation_id the client actually sent. That silently orphaned
a visitor's in-progress session across a kill-switch flip (frontend overwrites
its real conversationId with the throwaway one; the next real turn after the
switch flips back on starts a brand-new agent session with no memory of the
pre-pause conversation).

These tests assert the resting responses now echo back an existing
conversation_id when the client provides one, and only mint a fresh uuid when
the client has none (first-ever message).
"""
from __future__ import annotations

import uuid

import pytest

from routers.chat import _resting_chat_response, _resting_chat_stream


def test_resting_chat_response_echoes_existing_conversation_id():
    existing_id = str(uuid.uuid4())
    resp = _resting_chat_response("widget", existing_id)
    assert resp.conversation_id == existing_id


def test_resting_chat_response_mints_new_id_when_none_provided():
    resp = _resting_chat_response("public", None)
    assert resp.conversation_id
    # Should be a valid uuid4 string, not empty/None.
    uuid.UUID(resp.conversation_id)


@pytest.mark.asyncio
async def test_resting_chat_stream_echoes_existing_conversation_id():
    existing_id = str(uuid.uuid4())
    resp = _resting_chat_stream(existing_id)
    chunks = [chunk async for chunk in resp.body_iterator]
    session_event = "".join(
        chunk.decode() if isinstance(chunk, (bytes, bytearray)) else chunk
        for chunk in chunks
    )
    assert f'"session_id": "{existing_id}"' in session_event


@pytest.mark.asyncio
async def test_resting_chat_stream_mints_new_id_when_none_provided():
    resp = _resting_chat_stream(None)
    chunks = [chunk async for chunk in resp.body_iterator]
    session_event = "".join(
        chunk.decode() if isinstance(chunk, (bytes, bytearray)) else chunk
        for chunk in chunks
    )
    assert '"session_id": "' in session_event
    assert '"session_id": "None"' not in session_event
