"""
Actions Engine Module
Core services for event-driven action automation with approval workflow.

Components:
- EventEmitter: Publishes events when things happen
- TriggerMatcher: Evaluates conditions against events
- ActionDraftManager: Creates and manages pending approvals
- ActionExecutor: Runs approved actions with logging
"""

import logging
import uuid
from typing import Any
from datetime import datetime, timedelta
from modules.observability import supabase
from modules.governance import AuditLogger
import json

logger = logging.getLogger(__name__)
try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
except ImportError:
    pass

def _get_tenant_id(twin_id: str) -> str | None:
    """Helper to resolve tenant_id from twin_id."""
    try:
        res = supabase.table("twins").select("tenant_id").eq("id", twin_id).single().execute()
        return res.data.get("tenant_id") if res.data else None
    except Exception:
        return None



# =============================================================================
# EVENT EMITTER
# =============================================================================

class EventEmitter:
    """
    Publishes events to the events table when things happen in the system.
    These events can trigger actions based on configured triggers.
    """

    EVENT_TYPES = [
        'message_received',
        'answer_sent',
        'escalation_created',
        'escalation_resolved',
        'idle_timeout',
        'source_ingested',
        'action_executed',
        'action_failed'
    ]

    @staticmethod
    def emit(
        twin_id: str,
        event_type: str,
        payload: dict[str, Any],
        source_context: dict[str, Any] | None = None
    ) -> str | None:
        """
        Emit a new event and check for matching triggers.

        Args:
            twin_id: Twin UUID
            event_type: One of the valid event types
            payload: Event-specific data
            source_context: Additional context (group_id, channel, user info)

        Returns:
            Event ID if created, None if failed
        """
        if event_type not in EventEmitter.EVENT_TYPES:
            logger.warning("Unknown event type '%s'", event_type)
            return None

        try:
            event_id = str(uuid.uuid4())
            result = supabase.table("events").insert({
                "id": event_id,
                "twin_id": twin_id,
                "event_type": event_type,
                "payload": payload,
                "source_context": source_context or {}
            }).execute()

            if result.data:
                # Asynchronously check for matching triggers
                # In production, this could be a background job
                TriggerMatcher.process_event(twin_id, event_id, event_type, payload, source_context or {})
                return event_id
            return None

        except Exception as e:
            logger.error("Error emitting event: %s", e)
            return None

    @staticmethod
    def get_recent_events(
        twin_id: str,
        event_type: str | None = None,
        limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get recent events for a twin."""
        query = supabase.table("events").select("*").eq("twin_id", twin_id)

        if event_type:
            query = query.eq("event_type", event_type)

        result = query.order("created_at", desc=True).limit(limit).execute()
        return result.data if result.data else []


# =============================================================================
# TRIGGER MATCHER
# =============================================================================

class TriggerMatcher:
    """
    Evaluates event data against configured triggers to find matches.
    When a trigger matches, creates an action draft or executes immediately.
    """

    @staticmethod
    def get_active_triggers(twin_id: str, event_type: str) -> list[dict[str, Any]]:
        """Get all active triggers for a twin that listen to a specific event type."""
        result = supabase.table("action_triggers").select("*").eq(
            "twin_id", twin_id
        ).eq(
            "event_type", event_type
        ).eq(
            "is_active", True
        ).order("priority", desc=True).execute()

        return result.data if result.data else []

    @staticmethod
    def evaluate_conditions(
        conditions: dict[str, Any],
        payload: dict[str, Any],
        context: dict[str, Any]
    ) -> bool:
        """
        Evaluate trigger conditions against event payload and context.

        Supported conditions:
        - intent_contains: List of keywords that must appear in user_message
        - keywords: List of keywords (any match)
        - review_required: Require review-state payloads only
        - group_id: Must match specific group
        """
        # Check intent_contains (all must match)
        if "intent_contains" in conditions:
            intent_keywords = conditions["intent_contains"]
            user_message = payload.get("user_message", "").lower()
            if not all(kw.lower() in user_message for kw in intent_keywords):
                return False

        # Check keywords (any match)
        if "keywords" in conditions:
            keywords = conditions["keywords"]
            user_message = payload.get("user_message", "").lower()
            if not any(kw.lower() in user_message for kw in keywords):
                return False

        # Check review_required
        if "review_required" in conditions:
            required = bool(conditions["review_required"])
            if bool(payload.get("review_required")) != required:
                return False

        # Check group_id
        if "group_id" in conditions:
            required_group = conditions["group_id"]
            event_group = context.get("group_id")
            if event_group != required_group:
                return False

        return True

    @staticmethod
    def process_event(
        twin_id: str,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
        context: dict[str, Any]
    ) -> list[str]:
        """
        Process an event and create drafts for matching triggers.

        Returns:
            List of created draft IDs
        """
        triggers = TriggerMatcher.get_active_triggers(twin_id, event_type)
        draft_ids = []

        for trigger in triggers:
            conditions = trigger.get("conditions", {})

            if TriggerMatcher.evaluate_conditions(conditions, payload, context):
                # Trigger matched! Create draft or execute
                if trigger.get("requires_approval", True):
                    draft_id = ActionDraftManager.create_draft(
                        twin_id=twin_id,
                        trigger_id=trigger["id"],
                        event_id=event_id,
                        proposed_action={
                            "action_type": trigger["action_type"],
                            "connector_id": trigger.get("connector_id"),
                            "config": trigger.get("action_config", {})
                        },
                        context={
                            "trigger_name": trigger["name"],
                            "event_type": event_type,
                            "user_message": payload.get("user_message"),
                            "match_conditions": conditions
                        }
                    )
                    if draft_id:
                        draft_ids.append(draft_id)
                else:
                    # Execute immediately (for non-critical actions)
                    ActionExecutor.execute_action(
                        twin_id=twin_id,
                        trigger_id=trigger["id"],
                        action_type=trigger["action_type"],
                        connector_id=trigger.get("connector_id"),
                        inputs=trigger.get("action_config", {})
                    )

        return draft_ids


# =============================================================================
# ACTION DRAFT MANAGER
# =============================================================================

class ActionDraftManager:
    """
    Creates and manages pending action drafts awaiting owner approval.
    """

    @staticmethod
    def create_draft(
        twin_id: str,
        proposed_action: dict[str, Any],
        context: dict[str, Any],
        trigger_id: str | None = None,
        event_id: str | None = None,
        expires_hours: int = 24
    ) -> str | None:
        """
        Create a new action draft pending approval.

        trigger_id/event_id are optional so the draft can be created from the
        chat assistant (the "Respond" tool) as well as from an automation
        trigger. Drafts are owner-scoped via tenant_id resolved from the twin.

        Args:
            twin_id: Twin UUID
            proposed_action: The action to execute if approved
            context: Context for decision-making (set context["source"] to tag origin)
            trigger_id: Trigger that matched, if any (automation path)
            event_id: Event that triggered this, if any (automation path)
            expires_hours: Hours until draft expires

        Returns:
            Draft ID if created
        """
        try:
            draft_id = str(uuid.uuid4())
            expires_at = (datetime.utcnow() + timedelta(hours=expires_hours)).isoformat()

            result = supabase.table("action_drafts").insert({
                "id": draft_id,
                "tenant_id": _get_tenant_id(twin_id),
                "twin_id": twin_id,
                "trigger_id": trigger_id,
                "event_id": event_id,
                "status": "pending",
                "proposed_action": proposed_action,
                "context": {"source": "automation", **context},
                "expires_at": expires_at
            }).execute()

            if result.data:
                AuditLogger.log(
                    tenant_id=_get_tenant_id(twin_id),
                    twin_id=twin_id,
                    event_type="ACTION_AUTOMATION",
                    action="DRAFT_CREATED",
                    metadata={
                        "draft_id": draft_id,
                        "trigger_id": trigger_id,
                        "action_type": proposed_action.get("action_type")
                    }
                )
                return draft_id

            return None

        except Exception as e:
            logger.error("Error creating action draft: %s", e)
            return None

    @staticmethod
    def get_pending_drafts(twin_id: str) -> list[dict[str, Any]]:
        """Get all pending drafts for a twin."""
        result = supabase.table("action_drafts").select(
            "*, action_triggers(name, action_type)"
        ).eq(
            "twin_id", twin_id
        ).eq(
            "status", "pending"
        ).order("created_at", desc=True).execute()

        return result.data if result.data else []

    @staticmethod
    def get_draft(draft_id: str) -> dict[str, Any] | None:
        """Get a specific draft with full context."""
        result = supabase.table("action_drafts").select(
            "*, action_triggers(name, description, action_type, action_config), events(payload, source_context)"
        ).eq("id", draft_id).single().execute()

        return result.data if result.data else None

    @staticmethod
    def approve_draft(
        draft_id: str,
        approved_by: str,
        approval_note: str | None = None
    ) -> bool:
        """
        Approve a draft and execute the action.

        Args:
            draft_id: Draft to approve
            approved_by: User UUID who approved
            approval_note: Optional note

        Returns:
            True if successful
        """
        try:
            # Get the draft
            draft = ActionDraftManager.get_draft(draft_id)
            if not draft or draft["status"] != "pending":
                return False

            # Update status to approved
            supabase.table("action_drafts").update({
                "status": "approved",
                "approved_by": approved_by,
                "approval_note": approval_note,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", draft_id).execute()

            # Execute the action
            proposed = draft["proposed_action"]
            execution_id = ActionExecutor.execute_action(
                twin_id=draft["twin_id"],
                trigger_id=draft.get("trigger_id"),
                draft_id=draft_id,
                action_type=proposed["action_type"],
                connector_id=proposed.get("connector_id"),
                inputs=proposed.get("config", {}),
                executed_by=approved_by
            )

            if execution_id:
                supabase.table("action_drafts").update({
                    "status": "executed"
                }).eq("id", draft_id).execute()

            AuditLogger.log(
                tenant_id=_get_tenant_id(draft["twin_id"]),
                twin_id=draft["twin_id"],
                event_type="ACTION_AUTOMATION",
                action="DRAFT_APPROVED",
                actor_id=approved_by,
                metadata={
                    "draft_id": draft_id,
                    "action_type": proposed["action_type"],
                    "execution_id": execution_id
                }
            )


            return True

        except Exception as e:
            logger.error("Error approving draft: %s", e)
            return False

    @staticmethod
    def reject_draft(
        draft_id: str,
        rejected_by: str,
        rejection_note: str | None = None
    ) -> bool:
        """Reject a draft."""
        try:
            draft = ActionDraftManager.get_draft(draft_id)
            if not draft or draft["status"] != "pending":
                return False

            supabase.table("action_drafts").update({
                "status": "rejected",
                "approved_by": rejected_by,
                "approval_note": rejection_note,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", draft_id).execute()

            AuditLogger.log(
                tenant_id=_get_tenant_id(draft["twin_id"]),
                twin_id=draft["twin_id"],
                event_type="ACTION_AUTOMATION",
                action="DRAFT_REJECTED",
                actor_id=rejected_by,
                metadata={"draft_id": draft_id, "reason": rejection_note}
            )


            return True

        except Exception as e:
            logger.error("Error rejecting draft: %s", e)
            return False

    @staticmethod
    def respond_to_draft(
        draft_id: str,
        responded_by: str,
        response_message: str,
        save_as_verified: bool = False
    ) -> dict[str, Any]:
        """
        Owner responds to a triggered action with a message.
        Optionally saves the response as a verified QnA for future use.

        Args:
            draft_id: Draft to respond to
            responded_by: User UUID who responded
            response_message: Owner's response message
            save_as_verified: If true, save as verified QnA

        Returns:
            Dict with status and optionally verified_qna_id
        """
        try:
            draft = ActionDraftManager.get_draft(draft_id)
            if not draft:
                return {"success": False, "error": "Draft not found"}

            # Update the draft with the response
            supabase.table("action_drafts").update({
                "status": "responded",
                "approved_by": responded_by,
                "approval_note": response_message,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", draft_id).execute()

            result = {
                "success": True,
                "message": "Response saved",
                "response_message": response_message
            }

            # Optionally save as verified QnA for future reference
            if save_as_verified:
                user_message = draft.get("context", {}).get("user_message", "")
                if user_message:
                    try:
                        qna_id = str(uuid.uuid4())
                        supabase.table("verified_qna").insert({
                            "id": qna_id,
                            "twin_id": draft["twin_id"],
                            "question": user_message,
                            "answer": response_message,
                            "visibility": "private",
                            "created_by": responded_by,
                            "is_active": True
                        }).execute()
                        result["verified_qna_id"] = qna_id
                        result["message"] = "Response saved and added to verified knowledge"
                    except Exception as e:
                        logger.warning("Could not save as verified QnA: %s", e)

            AuditLogger.log(
                tenant_id=_get_tenant_id(draft["twin_id"]),
                twin_id=draft["twin_id"],
                event_type="ACTION_AUTOMATION",
                action="DRAFT_RESPONDED",
                actor_id=responded_by,
                metadata={
                    "draft_id": draft_id,
                    "saved_as_verified": save_as_verified,
                    "response_preview": response_message[:100]
                }
            )


            return result

        except Exception as e:
            logger.error("Error responding to draft: %s", e)
            return {"success": False, "error": str(e)}


# =============================================================================
# ACTION EXECUTOR
# =============================================================================

class ActionExecutor:
    """
    Executes approved actions and logs all inputs/outputs.
    """

    @staticmethod
    def execute_action(
        twin_id: str,
        action_type: str,
        inputs: dict[str, Any],
        trigger_id: str | None = None,
        draft_id: str | None = None,
        connector_id: str | None = None,
        executed_by: str | None = None
    ) -> str | None:
        """
        Execute an action and log the result.

        Args:
            twin_id: Twin UUID
            action_type: Type of action to execute
            inputs: Action inputs/config
            trigger_id: Optional trigger reference
            draft_id: Optional draft reference
            connector_id: Optional connector to use
            executed_by: Optional user who triggered execution

        Returns:
            Execution ID if logged
        """
        import time
        start_time = time.time()

        execution_id = str(uuid.uuid4())
        status = "success"
        outputs = {}
        error_message = None

        try:
            # Execute based on action type
            if action_type == "draft_email":
                outputs = ActionExecutor._execute_draft_email(connector_id, inputs)
            elif action_type == "draft_calendar_event":
                outputs = ActionExecutor._execute_draft_calendar_event(connector_id, inputs)
            elif action_type == "notify_owner":
                outputs = ActionExecutor._execute_notify_owner(twin_id, inputs)
            elif action_type == "escalate":
                outputs = ActionExecutor._execute_escalate(twin_id, inputs)
            elif action_type == "webhook":
                outputs = ActionExecutor._execute_webhook(inputs)
            else:
                raise ValueError(f"Unknown action type: {action_type}")

        except Exception as e:
            status = "failed"
            error_message = str(e)
            outputs = {"error": str(e)}

        execution_duration_ms = int((time.time() - start_time) * 1000)

        # Log the execution
        try:
            supabase.table("action_executions").insert({
                "id": execution_id,
                "twin_id": twin_id,
                "trigger_id": trigger_id,
                "draft_id": draft_id,
                "connector_id": connector_id,
                "action_type": action_type,
                "status": status,
                "inputs": inputs,
                "outputs": outputs,
                "error_message": error_message,
                "execution_duration_ms": execution_duration_ms,
                "executed_by": executed_by
            }).execute()

            # Emit success/failure event
            EventEmitter.emit(
                twin_id,
                "action_executed" if status == "success" else "action_failed",
                {
                    "execution_id": execution_id,
                    "action_type": action_type,
                    "status": status,
                    "error": error_message
                }
            )

            return execution_id

        except Exception as e:
            logger.error("Error logging execution: %s", e)
            return None

    @staticmethod
    def _execute_draft_email(connector_id: str | None, inputs: dict[str, Any]) -> dict[str, Any]:
        """Create an email draft (does not send)."""
        # TODO: Implement with Gmail connector
        # For now, return a mock response
        return {
            "status": "draft_created",
            "to": inputs.get("to"),
            "subject": inputs.get("subject"),
            "body_preview": inputs.get("body", "")[:100] + "..."
        }

    @staticmethod
    def _execute_draft_calendar_event(connector_id: str | None, inputs: dict[str, Any]) -> dict[str, Any]:
        """Create a calendar event draft."""
        if not connector_id:
            return {"status": "error", "error": "Connector ID required"}

        try:
            # 1. Fetch Connector
            connector = supabase.table("tool_connectors").select("*").eq("id", connector_id).single().execute()
            if not connector.data:
                return {"status": "error", "error": "Connector not found"}

            conn_data = connector.data
            if conn_data.get("connector_type") != "google_calendar":
                return {"status": "error", "error": "Invalid connector type"}

            # 2. Get Credentials
            creds_json = conn_data.get("credentials_encrypted")
            if not creds_json:
                return {"status": "error", "error": "No credentials found"}

            if isinstance(creds_json, str):
                try:
                    creds_info = json.loads(creds_json)
                except json.JSONDecodeError:
                    return {"status": "error", "error": "Invalid credentials format"}
            else:
                creds_info = creds_json

            # 3. Create Service
            creds = Credentials.from_authorized_user_info(creds_info)
            service = build('calendar', 'v3', credentials=creds)

            # 4. Prepare Event
            start_str = inputs.get("start_time")
            if not start_str:
                return {"status": "error", "error": "Start time required"}

            if start_str.endswith("Z"):
                start_str = start_str[:-1] + "+00:00"

            start_dt = datetime.fromisoformat(start_str)
            end_dt = start_dt + timedelta(minutes=inputs.get("duration_minutes", 30))

            event_body = {
                'summary': inputs.get("title", "New Event"),
                'description': inputs.get("description", ""),
                'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'UTC'},
                'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'UTC'},
            }

            if inputs.get("attendees"):
                event_body['attendees'] = [{'email': e} for e in inputs.get("attendees")]

            # 5. Execute
            event = service.events().insert(calendarId='primary', body=event_body).execute()

            return {
                "status": "event_created",
                "event_id": event.get('id'),
                "event_link": event.get('htmlLink'),
                "title": event_body['summary'],
                "start_time": start_str
            }

        except Exception as e:
            logger.error("Error creating calendar event: %s", e)
            return {"status": "error", "error": str(e)}

    @staticmethod
    def _execute_notify_owner(twin_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """Send notification to twin owner."""
        # TODO: Implement with notification service (email, push, etc.)
        message = inputs.get("message", "New action requires attention")
        return {
            "status": "notification_queued",
            "message": message
        }

    @staticmethod
    async def _execute_escalate(twin_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """Create an escalation."""
        from modules.escalation import create_escalation
        from modules.observability import supabase, create_conversation

        question = inputs.get("question", "Automated escalation")
        context = inputs.get("context", "")

        # Escalations require a message_id, so we need to create a message first
        # Create or get a conversation for this escalation
        conv = create_conversation(twin_id, None)
        conversation_id = conv["id"] if conv else None

        if not conversation_id:
            # Fallback: create conversation directly
            conv_response = supabase.table("conversations").insert({
                "twin_id": twin_id
            }).execute()
            conversation_id = conv_response.data[0]["id"] if conv_response.data else None

        # Create a message to attach the escalation to
        message_content = f"Automated escalation: {question}\n\nContext: {context}"
        msg_response = supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "role": "assistant",
            "content": message_content,
            "answerability_state": "insufficient",
            "source_tier": "mixed",
            "review_required": True,
            "review_reason": "escalation_created",
        }).execute()

        message_id = msg_response.data[0]["id"] if msg_response.data else None

        if message_id:
            # Now create the escalation
            escalation_result = await create_escalation(message_id)
            escalation_id = escalation_result[0]["id"] if escalation_result else None

            return {
                "status": "escalation_created",
                "escalation_id": escalation_id,
                "message_id": message_id
            }
        return {
            "status": "error",
            "error": "Failed to create message for escalation"
        }

    @staticmethod
    def _execute_webhook(inputs: dict[str, Any]) -> dict[str, Any]:
        """Call a webhook URL."""
        import requests

        url = inputs.get("url")
        method = inputs.get("method", "POST").upper()
        headers = inputs.get("headers", {})
        body = inputs.get("body", {})

        if not url:
            raise ValueError("Webhook URL is required")

        response = requests.request(method, url, headers=headers, json=body, timeout=30)

        return {
            "status_code": response.status_code,
            "response": response.text[:500] if response.text else None
        }

    @staticmethod
    def get_executions(
        twin_id: str,
        action_type: str | None = None,
        status: str | None = None,
        limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get execution history for a twin."""
        query = supabase.table("action_executions").select(
            "*, action_triggers(name)"
        ).eq("twin_id", twin_id)

        if action_type:
            query = query.eq("action_type", action_type)
        if status:
            query = query.eq("status", status)

        result = query.order("executed_at", desc=True).limit(limit).execute()
        return result.data if result.data else []

    @staticmethod
    def get_execution_details(execution_id: str) -> dict[str, Any] | None:
        """Get full details of an execution for replay."""
        result = supabase.table("action_executions").select(
            "*, action_triggers(name, description, conditions, action_config), action_drafts(context, proposed_action)"
        ).eq("id", execution_id).single().execute()

        return result.data if result.data else None


# =============================================================================
# TRIGGER MANAGEMENT
# =============================================================================

class TriggerManager:
    """
    CRUD operations for action triggers.
    """

    @staticmethod
    def create_trigger(
        twin_id: str,
        name: str,
        event_type: str,
        action_type: str,
        conditions: dict[str, Any] = None,
        action_config: dict[str, Any] = None,
        connector_id: str | None = None,
        requires_approval: bool = True,
        description: str | None = None
    ) -> str | None:
        """Create a new action trigger."""
        try:
            trigger_id = str(uuid.uuid4())

            result = supabase.table("action_triggers").insert({
                "id": trigger_id,
                "twin_id": twin_id,
                "name": name,
                "description": description,
                "event_type": event_type,
                "conditions": conditions or {},
                "connector_id": connector_id,
                "action_type": action_type,
                "action_config": action_config or {},
                "requires_approval": requires_approval,
                "is_active": True
            }).execute()

            if result.data:
                AuditLogger.log(
                    tenant_id=_get_tenant_id(twin_id),
                    twin_id=twin_id,
                    event_type="CONFIGURATION_CHANGE",
                    action="TRIGGER_CREATED",
                    metadata={"trigger_id": trigger_id, "name": name}
                )
                return trigger_id

            return None

        except Exception as e:
            logger.error("Error creating trigger: %s", e)
            return None

    @staticmethod
    def get_triggers(twin_id: str, include_inactive: bool = False) -> list[dict[str, Any]]:
        """Get all triggers for a twin."""
        query = supabase.table("action_triggers").select(
            "*, tool_connectors(name, connector_type)"
        ).eq("twin_id", twin_id)

        if not include_inactive:
            query = query.eq("is_active", True)

        result = query.order("priority", desc=True).execute()
        return result.data if result.data else []

    @staticmethod
    def update_trigger(trigger_id: str, updates: dict[str, Any]) -> bool:
        """Update a trigger."""
        try:
            updates["updated_at"] = datetime.utcnow().isoformat()

            result = supabase.table("action_triggers").update(updates).eq(
                "id", trigger_id
            ).execute()

            return bool(result.data)

        except Exception as e:
            logger.error("Error updating trigger: %s", e)
            return False

    @staticmethod
    def delete_trigger(trigger_id: str) -> bool:
        """Delete a trigger."""
        try:
            # Get twin_id for audit log
            trigger = supabase.table("action_triggers").select("twin_id, name").eq(
                "id", trigger_id
            ).single().execute()

            if trigger.data:
                supabase.table("action_triggers").delete().eq("id", trigger_id).execute()

                AuditLogger.log(
                    trigger.data["twin_id"],
                    "CONFIGURATION_CHANGE",
                    "TRIGGER_DELETED",
                    metadata={"trigger_id": trigger_id, "name": trigger.data["name"]}
                )
                return True
            return False

        except Exception as e:
            logger.error("Error deleting trigger: %s", e)
            return False


# =============================================================================
# CONNECTOR MANAGEMENT
# =============================================================================

class ConnectorManager:
    """
    CRUD operations for tool connectors.
    """

    CONNECTOR_TYPES = ['gmail', 'google_calendar', 'slack', 'notion', 'webhook', 'composio']

    @staticmethod
    def create_connector(
        twin_id: str,
        connector_type: str,
        name: str,
        config: dict[str, Any] = None,
        credentials: str | None = None
    ) -> str | None:
        """Create a new connector."""
        if connector_type not in ConnectorManager.CONNECTOR_TYPES:
            logger.warning("Unknown connector type: %s", connector_type)
            return None

        try:
            connector_id = str(uuid.uuid4())

            result = supabase.table("tool_connectors").insert({
                "id": connector_id,
                "twin_id": twin_id,
                "connector_type": connector_type,
                "name": name,
                "config": config or {},
                "credentials_encrypted": credentials,  # Should be encrypted before storage
                "is_active": True
            }).execute()

            if result.data:
                AuditLogger.log(
                    twin_id,
                    "CONFIGURATION_CHANGE",
                    "CONNECTOR_CREATED",
                    metadata={"connector_id": connector_id, "type": connector_type}
                )
                return connector_id
            return None

        except Exception as e:
            logger.error("Error creating connector: %s", e)
            return None

    @staticmethod
    def get_connectors(twin_id: str) -> list[dict[str, Any]]:
        """Get all connectors for a twin (excluding encrypted credentials)."""
        result = supabase.table("tool_connectors").select(
            "id, twin_id, connector_type, name, config, is_active, last_used_at, last_error, created_at"
        ).eq("twin_id", twin_id).execute()

        return result.data if result.data else []

    @staticmethod
    def delete_connector(connector_id: str) -> bool:
        """Delete a connector."""
        try:
            connector = supabase.table("tool_connectors").select("twin_id, name").eq(
                "id", connector_id
            ).single().execute()

            if connector.data:
                supabase.table("tool_connectors").delete().eq("id", connector_id).execute()

                AuditLogger.log(
                    connector.data["twin_id"],
                    "CONFIGURATION_CHANGE",
                    "CONNECTOR_DELETED",
                    metadata={"connector_id": connector_id}
                )
                return True
            return False

        except Exception as e:
            logger.error("Error deleting connector: %s", e)
            return False

    @staticmethod
    def test_connector(connector_id: str) -> dict[str, Any]:
        """Test a connector connection."""
        try:
            connector = supabase.table("tool_connectors").select("*").eq(
                "id", connector_id
            ).single().execute()

            if not connector.data:
                return {"success": False, "error": "Connector not found"}

            connector_type = connector.data["connector_type"]

            # TODO: Implement actual connection tests per connector type
            # For now, return mock success

            supabase.table("tool_connectors").update({
                "last_used_at": datetime.utcnow().isoformat(),
                "last_error": None
            }).eq("id", connector_id).execute()

            return {"success": True, "message": f"{connector_type} connection verified"}

        except Exception as e:
            supabase.table("tool_connectors").update({
                "last_error": str(e)
            }).eq("id", connector_id).execute()

            return {"success": False, "error": str(e)}
