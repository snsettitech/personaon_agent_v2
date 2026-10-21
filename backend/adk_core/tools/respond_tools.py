"""ADK FunctionTool factory for the Home v1 "Respond" write-tool.

The owner can ask their assistant to draft a follow-up message; the tool writes
a PENDING draft (a fast DB op) — it is NEVER sent here. The owner approves it
via the drafts API, which enqueues the send on graph_outbox. Keeping the tool a
pure DB write avoids any SMTP/Resend call inside the SSE chat stream.
"""

import logging

from google.adk.tools import FunctionTool

from modules.email_validation import is_valid_email

logger = logging.getLogger(__name__)


def _make_followup_draft_tool(twin_id: str) -> FunctionTool:
    """Return a FunctionTool that drafts a follow-up email for owner approval.

    twin_id is bound via closure — the owner runner is already owner-scoped, so
    the tool can only ever draft for this twin (a prompt-injected twin id is
    impossible). The recipient is validated to block a relay address smuggled in
    via prompt injection.
    """

    async def create_followup_draft(recipient: str, subject: str, body: str) -> dict:
        """Draft a follow-up email for the owner to review and approve.

        Call this when the owner asks you to draft, write, or respond to
        someone by email. The draft is saved as PENDING and is never sent until
        the owner explicitly approves it from their dashboard. Do not claim the
        message was sent.

        Args:
            recipient: The recipient's email address.
            subject: A short subject line.
            body: The full message body.
        """
        clean_recipient = (recipient or "").strip()
        if not is_valid_email(clean_recipient):
            logger.warning("[TOOL] create_followup_draft invalid recipient twin=%s", twin_id)
            return {
                "status": "invalid_recipient",
                "message": "That recipient doesn't look like a valid email address.",
            }

        if not (body or "").strip():
            return {"status": "empty", "message": "The draft needs a message body."}

        # Lazy import: actions_engine pulls supabase; keep tool construction light.
        from modules.actions_engine import ActionDraftManager

        draft_id = ActionDraftManager.create_draft(
            twin_id=twin_id,
            proposed_action={
                "action_type": "draft_email",
                "params": {
                    "to": clean_recipient,
                    "subject": (subject or "").strip(),
                    "body": body.strip(),
                },
            },
            context={"source": "chat"},
        )

        if not draft_id:
            logger.error("[TOOL] create_followup_draft failed to persist twin=%s", twin_id)
            return {"status": "error", "message": "Could not save the draft. Please try again."}

        logger.info("[TOOL] create_followup_draft draft_id=%s twin=%s", draft_id, twin_id)
        return {
            "status": "drafted",
            "draft_id": draft_id,
            "message": "Draft saved — review and approve it from your dashboard to send.",
        }

    return FunctionTool(func=create_followup_draft)
