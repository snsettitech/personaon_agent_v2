"""ADK FunctionTool factories for knowledge capture and question queuing."""

import logging
import os
import time

from google.adk.tools import FunctionTool

from adk_core.services.vector_store import upsert_text_chunks
from modules.observability import get_supabase_client

logger = logging.getLogger(__name__)


def _make_capture_tool(twin_id: str) -> FunctionTool:
    """Return a FunctionTool that captures owner knowledge to pgvector."""

    async def capture_knowledge(topic: str, content: str, is_boundary: bool = False) -> dict:
        """Capture knowledge or a boundary to the persona's knowledge base.

        Call this when the owner shares substantive information about a topic
        (is_boundary=False) OR explicitly says they don't cover a topic
        (is_boundary=True). Do NOT call for vague or one-word responses.

        Args:
            topic: The topic or subject area being captured.
            content: The substantive answer or explanation from the owner.
            is_boundary: True if the owner says this topic is not their area.
        """
        if is_boundary:
            text = f"[BOUNDARY] The persona has explicitly stated they don't cover: {topic}"
        else:
            text = content

        # Use topic-based source for deterministic ID uniqueness per topic
        source = f"captured_{topic.lower().replace(' ', '_')[:30]}_{int(time.time())}"

        logger.info("[TOOL] capture_knowledge topic=%r boundary=%s twin=%s", topic, is_boundary, twin_id)

        # Captured knowledge is content the owner shared privately with their
        # twin. Mark as `team` so it stays out of the marketplace global search
        # (which filters to `public`) while remaining available in the owner's
        # own meeting context prep (which allows `public`+`team`).
        await upsert_text_chunks(
            text=text,
            twin_id=twin_id,
            source=source,
            metadata={"topic": topic},
            privacy_level="team",
        )
        # Lazy import to avoid circular dependency (agent_service imports capture_tools)
        from adk_core.services.agent_service import invalidate_agent
        invalidate_agent(twin_id)
        return {"status": "captured", "topic": topic, "is_boundary": is_boundary}

    return FunctionTool(func=capture_knowledge)


def _make_queue_tool(
    twin_id: str,
    conversation_id: str,
    visitor_user_id: str,
    tenant_id: str | None = None,
) -> FunctionTool:
    """Return a FunctionTool that logs unanswered visitor questions."""

    async def queue_question(question: str, topic: str) -> dict:
        """Log a visitor's unanswered question for the owner to review later.

        Call this when a visitor asks about a topic you don't have indexed
        content for (Bucket 3 — topic gap). Do not call for biographical
        gaps (Bucket 2).

        Args:
            question: The exact question the visitor asked.
            topic: The topic or subject area of the question.
        """
        import datetime

        logger.info("[TOOL] queue_question topic=%r twin=%s", topic, twin_id)

        sb = get_supabase_client()
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=30)).isoformat()

        # D10: link the question to its transcript ONLY when the conversation row
        # exists. _handle_chat creates it up-front, but other callers (e.g. voice)
        # may not — verify existence and fall back to NULL to avoid a dangling FK
        # (queued_questions.conversation_id -> adk_conversations.id).
        linked_conversation_id = None
        if conversation_id:
            try:
                _conv = (
                    sb.table("adk_conversations")
                    .select("id")
                    .eq("id", conversation_id)
                    .maybe_single()
                    .execute()
                )
                if _conv and _conv.data:
                    linked_conversation_id = conversation_id
            except Exception as _exc:
                # Non-404 DB/permission errors must be observable, not silently
                # masked as "not found"; still fall back to NULL (FK-safe, non-fatal).
                logger.warning(
                    "[TOOL] queue_question conversation existence check failed conv=%s: %s — linking NULL",
                    conversation_id, _exc,
                )
                linked_conversation_id = None

        # Dedup: check for same topic + twin within 30 days
        existing = (
            sb.table("queued_questions")
            .select("id, ask_count")
            .eq("twin_id", twin_id)
            .eq("topic", topic)
            .eq("status", "pending")
            .gte("created_at", cutoff)
            .execute()
        )

        if existing.data:
            row_id = existing.data[0]["id"]
            new_count = existing.data[0]["ask_count"] + 1
            sb.table("queued_questions").update(
                {"ask_count": new_count, "updated_at": "now()"}
            ).eq("id", row_id).execute()
        else:
            sb.table("queued_questions").insert(
                {
                    "twin_id": twin_id,
                    "tenant_id": tenant_id,
                    "question": question,
                    "topic": topic,
                    "conversation_id": linked_conversation_id,
                    "visitor_user_id": visitor_user_id,
                    "ask_count": 1,
                    "status": "pending",
                }
            ).execute()

        return {"status": "queued", "topic": topic}

    return FunctionTool(func=queue_question)


def _make_capture_lead_tool(twin_id: str, lead_id: str) -> FunctionTool:
    """Return a FunctionTool that captures visitor contact info to widget_leads.

    twin_id and lead_id are bound via closure — one tool instance per widget
    conversation. Follow the same factory pattern as _make_capture_tool.
    """

    async def capture_lead_contact(
        email: str,
        name: str = "",
        inferred_visitor_type: str = "",
        inferred_intent: str = "",
    ) -> dict:
        """Capture the visitor's email when they voluntarily share it.

        Call this ONLY when the visitor provides their email address.
        Normalize any spelling variant before storing.
        Do NOT call this to prompt for email — only to record it after they share it.

        Args:
            email: Email in any format. Normalize: "john at acme dot com" -> "john@acme.com".
            name: Visitor's name if they mentioned it during conversation (optional).
            inferred_visitor_type: SHORT coarse category you inferred from the
                conversation (e.g. "recruiter", "customer", "investor", "collaborator",
                "peer"). Inferred silently — NEVER ask the visitor for it. Optional.
            inferred_intent: SHORT phrase for what they wanted (e.g. "backend contract
                work", "pricing", "partnership"). Inferred from the conversation. Optional.
        """
        import re

        normalized = (
            email.strip()
            .lower()
            .replace(" at ", "@").replace("[at]", "@").replace("(at)", "@")
            .replace(" dot ", ".").replace("[dot]", ".").replace("(dot)", ".")
            .replace(" ", "")
        )

        if not re.match(r'^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$', normalized):
            logger.warning("[TOOL] capture_lead_contact invalid email=%r lead=%s", email, lead_id)
            return {
                "status": "invalid",
                "message": "That doesn't look like a valid email address. Could you share it again?",
            }

        sb = get_supabase_client()

        # Idempotency guard: capture_lead_contact may be invoked twice for the
        # same lead (e.g. a retry mechanism replaying the tool call). The DB
        # UPDATE below and the two lifecycle-email enqueues are already safe
        # to run twice - but the ph_capture(event="lead_email_captured", ...)
        # telemetry call near the end of this function is NOT: a second call
        # would double-count the conversion in PostHog. Check offer_state up
        # front and short-circuit before the UPDATE (and therefore before the
        # enqueues and the ph_capture call) if this lead was already captured.
        try:
            existing_state = (
                sb.table("widget_leads")
                .select("offer_state")
                .eq("id", lead_id)
                .eq("twin_id", twin_id)
                .maybe_single()
                .execute()
            )
        except Exception:
            # Fail open: if the pre-flight check itself errors, log loudly and
            # fall through to the normal capture path below (which has its own
            # error handling) rather than blocking a legitimate first capture.
            logger.exception(
                "[TOOL] capture_lead_contact pre-flight SELECT failed lead_id=%s twin_id=%s - proceeding",
                lead_id, twin_id,
            )
        else:
            if existing_state.data and existing_state.data.get("offer_state") == "email_captured":
                logger.info(
                    "[TOOL] capture_lead_contact idempotent no-op (already captured) lead_id=%s twin_id=%s",
                    lead_id, twin_id,
                )
                return {"status": "captured", "message": "Contact info saved."}

        update_payload: dict = {
            "visitor_email": normalized,
            "offer_state": "email_captured",
        }
        if name:
            update_payload["visitor_name"] = name.strip()
        # Coarse, length-bounded categories only (data minimization — never a dossier).
        if inferred_visitor_type:
            update_payload["inferred_visitor_type"] = inferred_visitor_type.strip()[:60]
        if inferred_intent:
            update_payload["inferred_intent"] = inferred_intent.strip()[:120]

        # This write is the entire point of the tool call — unlike the best-effort
        # notification enqueues below, it must never fail silently. An uncaught
        # exception here would otherwise propagate out of the ADK tool invocation
        # with no application-level log line, and the model would have no signal
        # that the capture did not happen (it may narrate a confident-sounding
        # acknowledgement anyway). Catch, log loudly, and report failure explicitly
        # so the caller (and the model) can react instead of assuming success.
        try:
            update_result = (
                sb.table("widget_leads")
                .update(update_payload)
                .eq("id", lead_id)
                .eq("twin_id", twin_id)
                .execute()
            )
        except Exception:
            logger.exception(
                "[TOOL] capture_lead_contact DB update failed lead_id=%s twin_id=%s", lead_id, twin_id
            )
            return {
                "status": "error",
                "message": "I wasn't able to save that just now — could you share your email again?",
            }

        if not update_result.data:
            # eq("id", lead_id).eq("twin_id", twin_id) matched zero rows — the write
            # silently no-op'd (stale/mismatched lead_id, wrong twin scope, etc.).
            # Surface this loudly instead of returning a false "captured" status.
            logger.error(
                "[TOOL] capture_lead_contact update matched 0 rows lead_id=%s twin_id=%s — email NOT persisted",
                lead_id, twin_id,
            )
            return {
                "status": "error",
                "message": "I wasn't able to save that just now — could you share your email again?",
            }

        try:
            from services.lifecycle_email_service import enqueue_hot_lead_alert

            enqueue_hot_lead_alert(twin_id=twin_id, lead_id=lead_id)
        except Exception as exc:
            logger.warning("[TOOL] hot lead alert enqueue failed lead=%s: %s", lead_id, exc)
        try:
            from services.lifecycle_email_service import enqueue_visitor_confirmation

            frontend_url = (
                os.environ.get("NEXT_PUBLIC_FRONTEND_URL")
                or os.environ.get("FRONTEND_URL")
                or os.environ.get("PUBLIC_SITE_URL")
                or "https://www.personaon.com"
            ).rstrip("/")
            enqueue_visitor_confirmation(
                twin_id=twin_id,
                lead_id=lead_id,
                visitor_email=normalized,
                visitor_name=update_payload.get("visitor_name", ""),
                inferred_intent=update_payload.get("inferred_intent"),
                frontend_url=frontend_url,
            )
        except Exception as exc:
            logger.warning("[TOOL] visitor confirmation enqueue failed lead=%s: %s", lead_id, exc)
        logger.info("[TOOL] capture_lead_contact lead_id=%s email=%s", lead_id, normalized)
        # Funnel telemetry: the conversion event. Wrapped — telemetry must never
        # break a successful capture.
        try:
            from modules.posthog_analytics import ph_capture

            ph_capture(
                user_id=f"twin:{twin_id}",
                event="lead_email_captured",
                properties={
                    "twin_id": twin_id,
                    "lead_id": lead_id,
                    "inferred_visitor_type": inferred_visitor_type or None,
                    "inferred_intent": inferred_intent or None,
                },
            )
        except Exception as exc:
            logger.warning("[TOOL] lead_email_captured analytics failed lead=%s: %s", lead_id, exc)
        return {"status": "captured", "message": "Contact info saved."}

    return FunctionTool(func=capture_lead_contact)
