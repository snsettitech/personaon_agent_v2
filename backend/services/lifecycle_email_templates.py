"""Lifecycle email categories, preferences, and template definitions."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PRODUCT_EDUCATION = "product_education"
DAILY_ACTIVITY = "daily_activity"
WEEKLY_REPORT = "weekly_report"
HOT_LEAD_ALERT = "hot_lead_alert"
MEETING_RECAP = "meeting_recap"
MEETING_BRIEF = "meeting_brief"
ACCOUNT = "account"
ANNOUNCEMENTS = "announcements"

CATEGORY_PREF_FIELD = {
    PRODUCT_EDUCATION: "product_education_enabled",
    DAILY_ACTIVITY: "daily_activity_enabled",
    WEEKLY_REPORT: "weekly_report_enabled",
    HOT_LEAD_ALERT: "hot_lead_alerts_enabled",
    ANNOUNCEMENTS: "announcements_enabled",
}

DEFAULT_PREFERENCES = {
    "product_education_enabled": True,
    "daily_activity_enabled": True,
    "weekly_report_enabled": True,
    "hot_lead_alerts_enabled": True,
    "announcements_enabled": True,
    "timezone": "UTC",
}

EMAIL_DEFINITIONS: dict[str, dict[str, str]] = {
    "welcome_first_persona": {
        "category": PRODUCT_EDUCATION,
        "subject": "Make your persona useful today",
        "preview": "Start with one job, one source, and one test conversation.",
        "help_path": "/help/start-with-your-persona",
        "cta_label": "Open your dashboard",
        "cta_path": "/dashboard",
        "body": (
            "Your persona works best when it has a clear first job. Start with "
            "one strong source, ask a few real questions, and improve the gaps "
            "you find."
        ),
    },
    "day1_add_sources": {
        "category": PRODUCT_EDUCATION,
        "subject": "Add one source that makes your persona smarter",
        "preview": "A resume, FAQ, website, or writing sample can improve answers quickly.",
        "help_path": "/help/add-sources-that-improve-answers",
        "cta_label": "Add knowledge",
        "cta_path": "/dashboard/knowledge",
        "body": (
            "Useful answers come from useful context. Add one source that answers "
            "the questions people are most likely to ask."
        ),
    },
    "first_chat_review": {
        "category": PRODUCT_EDUCATION,
        "subject": "Your first chat is training signal",
        "preview": "Review what worked, what was missing, and what to teach next.",
        "help_path": "/help/review-chats-and-improve-responses",
        "cta_label": "Review conversations",
        "cta_path": "/dashboard/conversations",
        "body": (
            "A real conversation shows what your persona knows and where it needs "
            "better source material. Review the chat and add the missing context."
        ),
    },
    "publishing_prompt": {
        "category": PRODUCT_EDUCATION,
        "subject": "Ready to publish your persona?",
        "preview": "Review public details first, then share the link where people ask questions.",
        "help_path": "/help/publish-and-share-your-persona",
        "cta_label": "Review publishing",
        "cta_path": "/dashboard/share",
        "body": (
            "Before publishing, review what visitors will see, test the public link, "
            "and share it in the places where people already evaluate your work."
        ),
    },
    "widget_adoption": {
        "category": PRODUCT_EDUCATION,
        "subject": "Put your persona where visitors already have questions",
        "preview": "Your website is often stronger than a standalone link.",
        "help_path": "/help/add-persona-to-your-website",
        "cta_label": "Open Share Studio",
        "cta_path": "/dashboard/widget",
        "body": (
            "Install the widget on one high-intent page first, then review the "
            "questions visitors ask and improve your persona from that signal."
        ),
    },
    "daily_persona_activity": {
        "category": DAILY_ACTIVITY,
        "subject": "Your persona had activity yesterday",
        "preview": "Review chats, leads, and gaps while they are fresh.",
        "help_path": "/help/review-chats-and-improve-responses",
        "cta_label": "Open conversations",
        "cta_path": "/dashboard/conversations",
        "body": "Your persona had new activity. Review the summary and choose the next update.",
    },
    "weekly_improvement_report": {
        "category": WEEKLY_REPORT,
        "subject": "Three updates that would make your persona better this week",
        "preview": "Use recent activity to keep your persona current.",
        "help_path": "/help/keep-your-persona-current",
        "cta_label": "Review knowledge",
        "cta_path": "/dashboard/knowledge",
        "body": "A short weekly review keeps your persona aligned with your current work.",
    },
    "hot_lead_alert": {
        "category": HOT_LEAD_ALERT,
        "subject": "New lead for your persona",
        "preview": "A website visitor shared contact information.",
        "help_path": "/help/add-persona-to-your-website",
        "cta_label": "View leads",
        "cta_path": "/dashboard/widget",
        "body": "A visitor shared contact details with your persona. Review the conversation before following up.",
    },
    "meeting_recap_ready": {
        "category": MEETING_RECAP,
        "subject": "Recap of your meeting",
        "preview": "Action items, commitments, decisions, and your stated positions.",
        "help_path": "/help/meeting-recaps",
        "cta_label": "View full recap",
        "cta_path": "/dashboard/meetings",
        "body": "Your meeting recap is ready.",
    },
    "meeting_brief_ready": {
        "category": MEETING_BRIEF,
        "subject": "Brief for your meeting",
        "preview": "Hooks to lead with, open commitments, and what to bring.",
        "help_path": "/help/meeting-briefs",
        "cta_label": "Read the full brief",
        "cta_path": "/dashboard/meetings",
        "body": "Your pre-meeting brief is ready.",
    },
    "access_granted": {
        "category": ACCOUNT,
        "subject": "You're in — your PersonaOn access is ready",
        "preview": "Your account has been unlocked. Click to get started.",
        "help_path": "/help/get-started",
        "cta_label": "Open PersonaOn",
        "cta_path": "/dashboard",
        "body": (
            "Your PersonaOn access is ready. Sign in to open your workspace "
            "and start using the enabled features."
        ),
    },
    "account_suspended": {
        "category": ACCOUNT,
        "subject": "Your PersonaOn account has been suspended",
        "preview": "Action required. Contact support if you believe this is an error.",
        "help_path": "/help/account-access",
        "cta_label": "Contact Support",
        "cta_path": "mailto:support@personaon.com",
        "body": (
            "Your PersonaOn account has been suspended. If you believe this is "
            "an error, contact support and include the email address on your account."
        ),
    },
    "feature_launch": {
        "category": ANNOUNCEMENTS,
        "subject": "New in PersonaOn: {feature_name}",
        "preview": "Something new just landed. Here's what changed for you.",
        "help_path": "/help/product-updates",
        "cta_label": "Try it now",
        "cta_path": "/dashboard",
        "body": "{feature_summary}",
    },
}
