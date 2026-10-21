"""Tests for services/contact_resolver.py (Phase F.2/F.3/F.4 — identity linking
+ contact_meetings join + soft-delete respect)."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from tests._supabase_mock import fluent as _fluent, result as _result

from services.contact_resolver import link_meeting_contacts, upsert_name_only_contacts


MEETING_ID = "meet-1"
TENANT_ID = "tenant-1"
TWIN_ID = "twin-1"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def _make_participants_chain(participants: list[dict[str, Any]]) -> MagicMock:
    """Build a fluent mock for the meeting_participants SELECT chain."""
    c = MagicMock()
    c.select.return_value = c
    c.eq.return_value = c
    c.execute.return_value = _result(participants)
    return c


def _make_existing_chain(existing_rows: list[Any]) -> MagicMock:
    """Build a fluent mock for the contacts SELECT (lookup) chain."""
    c = MagicMock()
    c.select.return_value = c
    c.eq.return_value = c
    c.ilike.return_value = c
    c.limit.return_value = c
    c.execute.return_value = _result(existing_rows)
    return c


def _make_update_chain() -> MagicMock:
    """Build a fluent mock for the contacts UPDATE chain."""
    c = MagicMock()
    c.update.return_value = c
    c.eq.return_value = c
    c.execute.return_value = _result([])
    return c


def _make_backfill_chain() -> MagicMock:
    """Build a fluent mock for the meeting_participants UPDATE (backfill) chain."""
    c = MagicMock()
    c.update.return_value = c
    c.eq.return_value = c
    c.execute.return_value = _result([])
    return c


def _make_cm_insert_chain() -> MagicMock:
    """Build a fluent mock for contact_meetings INSERT chain."""
    c = MagicMock()
    c.insert.return_value = c
    c.execute.return_value = _result([{"id": "cm-new"}])
    return c


def _generic_mock() -> MagicMock:
    """A generic MagicMock that returns itself for all chained calls."""
    m = MagicMock()
    m.insert.return_value = m
    m.update.return_value = m
    m.select.return_value = m
    m.eq.return_value = m
    m.execute.return_value = _result([])
    return m


def test_link_meeting_contacts_creates_new():
    """Meeting has 1 participant with email; existing lookup returns empty;
    assert insert called and returns created=1."""
    participants = [
        {"id": "p1", "participant_name": "Alice", "participant_email": "alice@example.com",
         "contact_id": None},
    ]

    with patch("services.contact_resolver.supabase") as mock_sb:
        participants_chain = _make_participants_chain(participants)
        existing_chain = _make_existing_chain([])

        insert_chain = MagicMock()
        insert_chain.insert.return_value = insert_chain
        insert_chain.execute.return_value = _result([{"id": "new-contact-id"}])

        backfill_chain = _make_backfill_chain()

        call_count = {"n": 0}

        def _table(name: str):
            call_count["n"] += 1
            if name == "meeting_participants" and call_count["n"] == 1:
                return participants_chain
            if name == "contacts" and call_count["n"] == 2:
                return existing_chain
            if name == "contacts" and call_count["n"] == 3:
                return insert_chain
            if name == "meeting_participants" and call_count["n"] == 4:
                return backfill_chain
            # contact_meetings insert (phase F.4) — return generic
            return _generic_mock()

        mock_sb.table.side_effect = _table

        result = link_meeting_contacts(MEETING_ID, TENANT_ID, TWIN_ID)

    assert result["created"] == 1
    assert result["updated"] == 0
    assert result["skipped"] == 0
    insert_chain.insert.assert_called_once()
    insert_args = insert_chain.insert.call_args[0][0]
    assert insert_args["email"] == "alice@example.com"
    assert insert_args["name"] == "Alice"
    assert insert_args["tenant_id"] == TENANT_ID
    assert insert_args["twin_id"] == TWIN_ID


def test_link_meeting_contacts_updates_existing():
    """Existing contact found; participant was not previously linked (contact_id=None);
    assert UPDATE called with last_seen_at + incremented meeting_count; returns updated=1."""
    participants = [
        {"id": "p2", "participant_name": "Bob", "participant_email": "bob@example.com",
         "contact_id": None},
    ]
    existing_contact = {"id": "existing-c1", "meeting_count": 5, "deleted_at": None}

    with patch("services.contact_resolver.supabase") as mock_sb:
        participants_chain = _make_participants_chain(participants)
        existing_chain = _make_existing_chain([existing_contact])
        update_chain = _make_update_chain()
        backfill_chain = _make_backfill_chain()

        call_count = {"n": 0}

        def _table(name: str):
            call_count["n"] += 1
            if name == "meeting_participants" and call_count["n"] == 1:
                return participants_chain
            if name == "contacts" and call_count["n"] == 2:
                return existing_chain
            if name == "contacts" and call_count["n"] == 3:
                return update_chain
            if name == "meeting_participants" and call_count["n"] == 4:
                return backfill_chain
            return _generic_mock()

        mock_sb.table.side_effect = _table

        result = link_meeting_contacts(MEETING_ID, TENANT_ID, TWIN_ID)

    assert result["updated"] == 1
    assert result["created"] == 0
    assert result["skipped"] == 0
    update_chain.update.assert_called_once()
    update_args = update_chain.update.call_args[0][0]
    assert update_args["meeting_count"] == 6  # 5 + 1
    assert "last_seen_at" in update_args


def test_link_meeting_contacts_skips_no_email():
    """Participant with no email is skipped; returns skipped=1."""
    participants = [
        {"id": "p3", "participant_name": "Charlie", "participant_email": None,
         "contact_id": None},
    ]

    with patch("services.contact_resolver.supabase") as mock_sb:
        participants_chain = _make_participants_chain(participants)
        mock_sb.table.return_value = participants_chain

        result = link_meeting_contacts(MEETING_ID, TENANT_ID, TWIN_ID)

    assert result["skipped"] == 1
    assert result["created"] == 0
    assert result["updated"] == 0


def test_link_meeting_contacts_missing_args():
    """Empty meeting_id/tenant_id/twin_id returns all zeros without hitting DB."""
    with patch("services.contact_resolver.supabase") as mock_sb:
        result = link_meeting_contacts("", TENANT_ID, TWIN_ID)
    assert result == {"created": 0, "updated": 0, "skipped": 0}
    mock_sb.table.assert_not_called()


# ---------------------------------------------------------------------------
# BUG-1 regression: meeting_count must not double-count on re-run
# ---------------------------------------------------------------------------

def test_link_meeting_contacts_does_not_double_count_meeting_count_on_rerun():
    """BUG-1 regression: participant already has contact_id set (previously linked);
    existing contact has meeting_count=3; running resolver again must NOT bump to 4.
    Expected: updated=1 (last_seen_at still updates), meeting_count NOT in UPDATE data."""
    # contact_id is already populated — this is a re-run / retry / backfill
    participants = [
        {"id": "p10", "participant_name": "Dana", "participant_email": "dana@corp.io",
         "contact_id": "existing-c10"},
    ]
    existing_contact = {"id": "existing-c10", "meeting_count": 3, "deleted_at": None}

    with patch("services.contact_resolver.supabase") as mock_sb:
        participants_chain = _make_participants_chain(participants)
        existing_chain = _make_existing_chain([existing_contact])
        update_chain = _make_update_chain()
        # No backfill call expected: contact_id already matches

        call_count = {"n": 0}

        def _table(name: str):
            call_count["n"] += 1
            if name == "meeting_participants" and call_count["n"] == 1:
                return participants_chain
            if name == "contacts" and call_count["n"] == 2:
                return existing_chain
            if name == "contacts" and call_count["n"] == 3:
                return update_chain
            return _generic_mock()

        mock_sb.table.side_effect = _table

        result = link_meeting_contacts(MEETING_ID, TENANT_ID, TWIN_ID)

    assert result["updated"] == 1
    assert result["created"] == 0
    assert result["skipped"] == 0
    update_chain.update.assert_called_once()
    update_args = update_chain.update.call_args[0][0]
    # meeting_count must NOT be present in the update — no double-counting
    assert "meeting_count" not in update_args, (
        f"BUG-1: meeting_count should not be bumped on re-run, got: {update_args}"
    )
    assert "last_seen_at" in update_args


def test_link_meeting_contacts_counts_meeting_only_when_participant_was_null_contact_id():
    """BUG-1 complement: participant has contact_id=None (first-time link);
    existing contact has meeting_count=3; running resolver MUST bump to 4.
    Expected: meeting_count=4 in UPDATE call."""
    participants = [
        {"id": "p11", "participant_name": "Eve", "participant_email": "eve@corp.io",
         "contact_id": None},  # first-time link
    ]
    existing_contact = {"id": "existing-c11", "meeting_count": 3, "deleted_at": None}

    with patch("services.contact_resolver.supabase") as mock_sb:
        participants_chain = _make_participants_chain(participants)
        existing_chain = _make_existing_chain([existing_contact])
        update_chain = _make_update_chain()
        backfill_chain = _make_backfill_chain()

        call_count = {"n": 0}

        def _table(name: str):
            call_count["n"] += 1
            if name == "meeting_participants" and call_count["n"] == 1:
                return participants_chain
            if name == "contacts" and call_count["n"] == 2:
                return existing_chain
            if name == "contacts" and call_count["n"] == 3:
                return update_chain
            if name == "meeting_participants" and call_count["n"] == 4:
                return backfill_chain
            return _generic_mock()

        mock_sb.table.side_effect = _table

        result = link_meeting_contacts(MEETING_ID, TENANT_ID, TWIN_ID)

    assert result["updated"] == 1
    assert result["created"] == 0
    assert result["skipped"] == 0
    update_chain.update.assert_called_once()
    update_args = update_chain.update.call_args[0][0]
    assert update_args["meeting_count"] == 4, (
        f"Expected meeting_count=4 for first-time link, got: {update_args.get('meeting_count')}"
    )
    assert "last_seen_at" in update_args


# ---------------------------------------------------------------------------
# BUG-4 regression: case-insensitive email match
# ---------------------------------------------------------------------------

def test_link_meeting_contacts_case_insensitive_email_match():
    """BUG-4 regression: existing contact stored with mixed-case email 'Jordan@Acme.co';
    new participant has email 'jordan@acme.co'; should find the existing row
    (via ilike) and update — NOT insert a duplicate."""
    # Participant email is lowercase; existing contact was stored mixed-case.
    # The resolver lowercases participant_email before querying, so the lookup
    # uses 'jordan@acme.co' with .ilike — which should match 'Jordan@Acme.co'.
    participants = [
        {"id": "p20", "participant_name": "Jordan", "participant_email": "Jordan@Acme.co",
         "contact_id": None},
    ]
    # Simulate that the DB returns the existing row (ilike matched mixed-case)
    existing_contact = {"id": "existing-c20", "meeting_count": 2, "deleted_at": None}

    with patch("services.contact_resolver.supabase") as mock_sb:
        participants_chain = _make_participants_chain(participants)
        existing_chain = _make_existing_chain([existing_contact])
        update_chain = _make_update_chain()
        backfill_chain = _make_backfill_chain()

        call_count = {"n": 0}

        def _table(name: str):
            call_count["n"] += 1
            if name == "meeting_participants" and call_count["n"] == 1:
                return participants_chain
            if name == "contacts" and call_count["n"] == 2:
                return existing_chain
            if name == "contacts" and call_count["n"] == 3:
                return update_chain
            if name == "meeting_participants" and call_count["n"] == 4:
                return backfill_chain
            return _generic_mock()

        mock_sb.table.side_effect = _table

        result = link_meeting_contacts(MEETING_ID, TENANT_ID, TWIN_ID)

    # Should update (found by ilike), not insert
    assert result["updated"] == 1
    assert result["created"] == 0
    assert result["skipped"] == 0
    # Confirm ilike was called with the lowercased email
    existing_chain.ilike.assert_called_once_with("email", "jordan@acme.co")
    update_chain.update.assert_called_once()
    update_args = update_chain.update.call_args[0][0]
    assert update_args["meeting_count"] == 3  # 2 + 1 (first-time link)


# ---------------------------------------------------------------------------
# Phase F.4: soft-delete respect in link_meeting_contacts
# ---------------------------------------------------------------------------

def test_link_meeting_contacts_skips_soft_deleted_email_contact():
    """Phase F.4 regression: existing email contact with deleted_at set →
    should be skipped (not resurrected), no update, no join insert."""
    participants = [
        {"id": "p30", "participant_name": "Deleted Person",
         "participant_email": "deleted@corp.io", "contact_id": None},
    ]
    # Existing contact is soft-deleted
    existing_contact = {
        "id": "existing-c30",
        "meeting_count": 2,
        "deleted_at": "2026-05-01T00:00:00+00:00",
    }

    with patch("services.contact_resolver.supabase") as mock_sb:
        participants_chain = _make_participants_chain(participants)
        existing_chain = _make_existing_chain([existing_contact])

        call_count = {"n": 0}

        def _table(name: str):
            call_count["n"] += 1
            if name == "meeting_participants" and call_count["n"] == 1:
                return participants_chain
            if name == "contacts" and call_count["n"] == 2:
                return existing_chain
            return _generic_mock()

        mock_sb.table.side_effect = _table

        result = link_meeting_contacts(MEETING_ID, TENANT_ID, TWIN_ID)

    assert result["skipped"] == 1
    assert result["created"] == 0
    assert result["updated"] == 0
    # No update, no contact_meetings insert
    existing_chain.update.assert_not_called()


# ---------------------------------------------------------------------------
# Phase F.3 — upsert_name_only_contacts
# ---------------------------------------------------------------------------

def _make_name_only_lookup(existing_rows: list[Any]) -> MagicMock:
    """Fluent mock for the name-only contacts SELECT chain (is_ + ilike)."""
    c = MagicMock()
    c.select.return_value = c
    c.eq.return_value = c
    c.is_.return_value = c
    c.ilike.return_value = c
    c.limit.return_value = c
    c.execute.return_value = _result(existing_rows)
    return c


def _make_shadow_lookup(existing_rows: list[Any]) -> MagicMock:
    """Fluent mock for the BUG-A shadow lookup: same shape as the name-only
    lookup but for email-bearing contacts (uses .not_.is_("email","null"))."""
    c = MagicMock()
    c.select.return_value = c
    c.eq.return_value = c
    c.not_.is_.return_value = c
    c.ilike.return_value = c
    c.limit.return_value = c
    c.execute.return_value = _result(existing_rows)
    return c


def _make_name_only_insert() -> MagicMock:
    """Fluent mock for the contacts INSERT chain."""
    c = MagicMock()
    c.insert.return_value = c
    c.execute.return_value = _result([{"id": "new-name-contact"}])
    return c


def _make_name_only_update() -> MagicMock:
    """Fluent mock for the contacts UPDATE chain."""
    c = MagicMock()
    c.update.return_value = c
    c.eq.return_value = c
    c.execute.return_value = _result([])
    return c


def test_upsert_name_only_creates_when_none_exists():
    """No existing contact found (name-null AND email-bearing shadow both empty)
    → INSERT called; returns created=1."""
    people = [{"name": "Sooraj", "role_hint": "engineer"}]

    with patch("services.contact_resolver.supabase") as mock_sb:
        lookup_chain = _make_name_only_lookup([])
        shadow_chain = _make_shadow_lookup([])
        insert_chain = _make_name_only_insert()

        call_count = {"n": 0}

        def _table(name: str):
            call_count["n"] += 1
            if name == "contacts" and call_count["n"] == 1:
                return lookup_chain  # email-null name lookup
            if name == "contacts" and call_count["n"] == 2:
                return shadow_chain  # BUG-A shadow lookup
            if name == "contacts" and call_count["n"] == 3:
                return insert_chain
            # contact_meetings insert
            return _generic_mock()

        mock_sb.table.side_effect = _table

        result = upsert_name_only_contacts(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            people=people,
            meeting_id="m-1",
            meeting_started_iso="2026-05-01T10:00:00+00:00",
        )

    assert result["created"] == 1
    assert result["updated"] == 0
    assert result["skipped"] == 0
    insert_chain.insert.assert_called_once()
    insert_args = insert_chain.insert.call_args[0][0]
    assert insert_args["name"] == "Sooraj"
    assert insert_args["email"] is None
    assert insert_args["tenant_id"] == TENANT_ID
    assert insert_args["twin_id"] == TWIN_ID
    assert insert_args["meeting_count"] == 1


def test_upsert_name_only_skips_when_email_bearing_shadow_exists():
    """BUG-A regression: if an EMAIL-BEARING contact with the same name already
    exists, the name-only upsert MUST NOT insert a duplicate. It bumps the
    email-bearing contact's last_seen_at instead and counts as 'updated'."""
    people = [{"name": "Sooraj"}]
    shadow_row = {"id": "email-sooraj-id", "deleted_at": None}

    with patch("services.contact_resolver.supabase") as mock_sb:
        lookup_chain = _make_name_only_lookup([])              # email-null → empty
        shadow_chain = _make_shadow_lookup([shadow_row])       # email-bearing → present
        update_chain = _make_name_only_update()                # bump on the shadow

        call_count = {"n": 0}

        def _table(_name: str):
            call_count["n"] += 1
            n = call_count["n"]
            if n == 1:
                return lookup_chain
            if n == 2:
                return shadow_chain
            if n == 3:
                return update_chain
            return _generic_mock()

        mock_sb.table.side_effect = _table

        result = upsert_name_only_contacts(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            people=people,
            meeting_id="m-1",
        )

    assert result["created"] == 0, "must NOT create duplicate when email contact exists"
    assert result["updated"] == 1
    update_chain.update.assert_called_once()


def test_upsert_name_only_updates_last_seen_without_bumping_meeting_count():
    """Existing name-only contact found → UPDATE last_seen_at; meeting_count NOT bumped."""
    people = [{"name": "Ajai", "role_hint": None}]
    existing = {"id": "existing-name-c1", "meeting_count": 3, "deleted_at": None}

    with patch("services.contact_resolver.supabase") as mock_sb:
        lookup_chain = _make_name_only_lookup([existing])
        update_chain = _make_name_only_update()

        call_count = {"n": 0}

        def _table(name: str):
            call_count["n"] += 1
            if name == "contacts" and call_count["n"] == 1:
                return lookup_chain
            if name == "contacts" and call_count["n"] == 2:
                return update_chain
            return _generic_mock()

        mock_sb.table.side_effect = _table

        result = upsert_name_only_contacts(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            people=people,
            meeting_id="m-1",
        )

    assert result["updated"] == 1
    assert result["created"] == 0
    assert result["skipped"] == 0
    update_chain.update.assert_called_once()
    update_args = update_chain.update.call_args[0][0]
    assert "last_seen_at" in update_args
    assert "updated_at" in update_args
    # meeting_count must NOT be bumped — no double-count rule
    assert "meeting_count" not in update_args, (
        f"meeting_count should not be bumped on name-only update, got: {update_args}"
    )


def test_upsert_name_only_skips_empty_name():
    """Empty string name is skipped; returns skipped=1."""
    people = [{"name": "", "role_hint": None}]

    with patch("services.contact_resolver.supabase") as mock_sb:
        result = upsert_name_only_contacts(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            people=people,
            meeting_id="m-1",
        )

    assert result["skipped"] == 1
    assert result["created"] == 0
    assert result["updated"] == 0
    mock_sb.table.assert_not_called()


def test_upsert_name_only_skips_too_short_name():
    """Single-character name ('A') is skipped."""
    people = [{"name": "A"}]

    with patch("services.contact_resolver.supabase") as mock_sb:
        result = upsert_name_only_contacts(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            people=people,
            meeting_id="m-1",
        )

    assert result["skipped"] == 1
    mock_sb.table.assert_not_called()


def test_upsert_name_only_returns_correct_counts_for_mixed_batch():
    """Batch with one new, one existing, one skipped → {created:1, updated:1, skipped:1}."""
    people = [
        {"name": "Sooraj"},      # new
        {"name": "Ajai"},        # existing
        {"name": ""},            # skipped
    ]
    existing_ajai = {"id": "c-ajai", "meeting_count": 2, "deleted_at": None}

    with patch("services.contact_resolver.supabase") as mock_sb:
        # Sooraj: lookup empty → shadow empty → insert
        sooraj_lookup = _make_name_only_lookup([])
        sooraj_shadow = _make_shadow_lookup([])
        sooraj_insert = _make_name_only_insert()
        # Ajai: lookup returns existing → update (no shadow check needed —
        # shadow is only consulted when the email-null lookup is empty)
        ajai_lookup = _make_name_only_lookup([existing_ajai])
        ajai_update = _make_name_only_update()

        call_count = {"n": 0}

        def _table(_name: str):
            call_count["n"] += 1
            n = call_count["n"]
            if n == 1:
                return sooraj_lookup    # Sooraj email-null SELECT
            if n == 2:
                return sooraj_shadow    # Sooraj BUG-A shadow SELECT
            if n == 3:
                return sooraj_insert    # Sooraj INSERT
            if n == 4:
                # contact_meetings insert for Sooraj
                return _generic_mock()
            if n == 5:
                return ajai_lookup      # Ajai email-null SELECT
            if n == 6:
                return ajai_update      # Ajai UPDATE
            return _generic_mock()

        mock_sb.table.side_effect = _table

        result = upsert_name_only_contacts(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            people=people,
            meeting_id="m-1",
        )

    assert result["created"] == 1
    assert result["updated"] == 1
    assert result["skipped"] == 1


def test_upsert_name_only_returns_zeros_on_empty_people():
    """Empty people list → all zeros, no DB calls."""
    with patch("services.contact_resolver.supabase") as mock_sb:
        result = upsert_name_only_contacts(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            people=[],
            meeting_id="m-1",
        )
    assert result == {"created": 0, "updated": 0, "skipped": 0}
    mock_sb.table.assert_not_called()


def test_upsert_name_only_returns_zeros_on_missing_args():
    """Missing tenant_id or twin_id → all zeros, no DB calls."""
    with patch("services.contact_resolver.supabase") as mock_sb:
        result = upsert_name_only_contacts(
            tenant_id="",
            twin_id=TWIN_ID,
            people=[{"name": "Sooraj"}],
            meeting_id="m-1",
        )
    assert result == {"created": 0, "updated": 0, "skipped": 0}
    mock_sb.table.assert_not_called()


# ---------------------------------------------------------------------------
# Phase F.4: soft-delete respect in upsert_name_only_contacts
# ---------------------------------------------------------------------------

def test_upsert_name_only_skips_soft_deleted():
    """Phase F.4: existing email-null contact found with deleted_at set →
    returns skipped=1, no update, no join insert."""
    people = [{"name": "GhostPerson"}]
    deleted_existing = {
        "id": "ghost-id",
        "meeting_count": 1,
        "deleted_at": "2026-05-01T00:00:00+00:00",
    }

    with patch("services.contact_resolver.supabase") as mock_sb:
        lookup_chain = _make_name_only_lookup([deleted_existing])

        call_count = {"n": 0}

        def _table(name: str):
            call_count["n"] += 1
            if name == "contacts" and call_count["n"] == 1:
                return lookup_chain
            return _generic_mock()

        mock_sb.table.side_effect = _table

        result = upsert_name_only_contacts(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            people=people,
            meeting_id="m-1",
        )

    assert result["skipped"] == 1
    assert result["created"] == 0
    assert result["updated"] == 0
    # No update, no contact_meetings insert
    lookup_chain.update.assert_not_called()


def test_upsert_name_only_links_join_on_create():
    """Phase F.4: after a successful create, contact_meetings insert is called
    with source='recap'."""
    people = [{"name": "NewPerson"}]

    with patch("services.contact_resolver.supabase") as mock_sb:
        lookup_chain = _make_name_only_lookup([])
        shadow_chain = _make_shadow_lookup([])
        insert_chain = _make_name_only_insert()
        cm_insert_chain = _make_cm_insert_chain()

        call_count = {"n": 0}
        tables_called = []

        def _table(name: str):
            call_count["n"] += 1
            tables_called.append(name)
            if name == "contacts" and call_count["n"] == 1:
                return lookup_chain
            if name == "contacts" and call_count["n"] == 2:
                return shadow_chain
            if name == "contacts" and call_count["n"] == 3:
                return insert_chain
            if name == "contact_meetings":
                return cm_insert_chain
            return _generic_mock()

        mock_sb.table.side_effect = _table

        result = upsert_name_only_contacts(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            people=people,
            meeting_id="m-1",
        )

    assert result["created"] == 1
    # contact_meetings table must have been called
    assert "contact_meetings" in tables_called
    # Verify insert was called with correct source
    cm_insert_args = cm_insert_chain.insert.call_args[0][0]
    assert cm_insert_args["source"] == "recap"
    assert cm_insert_args["meeting_id"] == "m-1"
    assert cm_insert_args["tenant_id"] == TENANT_ID
    assert cm_insert_args["twin_id"] == TWIN_ID
