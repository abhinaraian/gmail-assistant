"""
Tool definitions (JSON schemas) for the Claude agent.
These describe to Claude what each Gmail tool does and what parameters it accepts.
"""

TOOL_DEFINITIONS = [
    # ── Reading & analysis ────────────────────────────────────────────────
    {
        "name": "get_inbox_stats",
        "description": (
            "Get a high-level overview of the inbox: total message count, unread count, "
            "inbox size, and number of existing user labels. "
            "Call this FIRST to understand the scale of the inbox before sampling."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "sample_inbox",
        "description": (
            "Sample the Gmail inbox to get email metadata for pattern analysis. "
            "Returns a list of email records, each containing: id, from, subject, "
            "snippet (preview text), date, and current labelIds. "
            "Use get_inbox_stats first to know the inbox size, then sample accordingly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Number of emails to sample (default: 200, max: 500)",
                    "default": 200,
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Gmail search query (default: 'in:inbox'). "
                        "Use 'in:anywhere' to include all mail, "
                        "'is:unread' for unread only, "
                        "'older_than:1y' for old mail."
                    ),
                    "default": "in:inbox",
                },
            },
        },
    },
    {
        "name": "get_email_body",
        "description": (
            "Fetch the full plain-text body of a single email by its ID. "
            "Use this when the subject/snippet isn't enough to classify an email — "
            "e.g., to distinguish a real personal email from an automated one, "
            "or to decide whether to trash vs. archive. "
            "Body is capped at 4000 characters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "The message ID from sample_inbox or search_messages",
                },
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "search_messages",
        "description": (
            "Search Gmail messages with a query and return how many match. "
            "Use this to verify query coverage before applying bulk actions. "
            "Gmail query syntax examples:\n"
            "  from:amazon.com\n"
            "  from:github.com OR from:gitlab.com\n"
            "  subject:invoice OR subject:receipt\n"
            "  is:unread older_than:6m\n"
            "  list:(newsletter) OR category:promotions"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query string",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum messages to count (default: 500)",
                    "default": 500,
                },
            },
            "required": ["query"],
        },
    },

    # ── Label management ──────────────────────────────────────────────────
    {
        "name": "list_labels",
        "description": (
            "List all current Gmail labels. Returns id, name, and type for each label. "
            "type='system' for built-in labels (INBOX, SENT, etc.), "
            "type='user' for user-created labels. "
            "Always call this before creating labels to avoid duplicates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "create_label",
        "description": (
            "Create a new Gmail label. Returns the label ID — save it for apply_label_to_search. "
            "Use sublabels with '/': 'Work/GitHub', 'Work/Jira', 'Work/Meetings'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Label name (e.g., 'Finance', 'Newsletters', 'Work/GitHub')",
                },
                "background_color": {
                    "type": "string",
                    "description": (
                        "Optional background color hex. Gmail palette examples: "
                        "'#16a766' green, '#4986e7' blue, '#e07798' pink, "
                        "'#fad165' yellow, '#ff7537' orange, '#8e63ce' purple"
                    ),
                },
                "text_color": {
                    "type": "string",
                    "description": "Optional text color hex (e.g., '#ffffff' for white)",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "delete_label",
        "description": (
            "Delete a user-created Gmail label. System labels cannot be deleted. "
            "Emails with the deleted label are NOT deleted — they just lose the label."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "label_id": {
                    "type": "string",
                    "description": "The label ID to delete (from list_labels)",
                },
            },
            "required": ["label_id"],
        },
    },
    {
        "name": "update_label",
        "description": "Rename or recolor an existing label.",
        "input_schema": {
            "type": "object",
            "properties": {
                "label_id": {
                    "type": "string",
                    "description": "The label ID to update (from list_labels)",
                },
                "name": {
                    "type": "string",
                    "description": "New label name",
                },
                "background_color": {
                    "type": "string",
                    "description": "New background color hex",
                },
                "text_color": {
                    "type": "string",
                    "description": "New text color hex",
                },
            },
            "required": ["label_id"],
        },
    },
    {
        "name": "apply_label_to_search",
        "description": (
            "Apply a label to Gmail messages matching a search query. "
            "ONE LABEL PER EMAIL: already-labeled emails are automatically skipped — "
            "apply your most specific/high-priority labels FIRST. "
            "Craft COMPREHENSIVE queries using OR to catch all variations:\n"
            "  Finance: 'from:paypal.com OR from:chase.com OR subject:invoice OR subject:receipt'\n"
            "  Newsletters: 'category:promotions OR list:newsletter'\n"
            "  GitHub: 'from:github.com'\n\n"
            "Set archive=true to move emails OUT of inbox (keeps them under the label only)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query — be comprehensive with OR conditions",
                },
                "label_id": {
                    "type": "string",
                    "description": "Label ID to apply (from create_label or list_labels)",
                },
                "archive": {
                    "type": "boolean",
                    "description": (
                        "If true, also removes the INBOX label (archives emails). "
                        "Use for bulk categories like newsletters and promotions. Default: false."
                    ),
                    "default": False,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max messages to label (default: 500, increase for large inboxes)",
                    "default": 500,
                },
            },
            "required": ["query", "label_id"],
        },
    },

    # ── Inbox actions ─────────────────────────────────────────────────────
    {
        "name": "mark_as_read",
        "description": (
            "Mark all unread messages matching a query as read. "
            "Good for: old promotional emails, automated notifications, newsletters "
            "that have piled up unread. "
            "Only affects messages that are currently unread."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Gmail search query — is:unread is automatically added. "
                        "Examples: 'category:promotions older_than:30d', "
                        "'from:noreply@github.com', 'list:newsletter'"
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max messages to mark read (default: 500)",
                    "default": 500,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "archive_emails",
        "description": (
            "Archive messages (remove from inbox) matching a query. "
            "Emails are NOT deleted — they move to All Mail and stay searchable. "
            "Good for: old newsletters, processed notifications, read receipts, "
            "shipping updates for delivered orders, old job alerts. "
            "Only affects messages currently in the inbox."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Gmail search query — in:inbox is automatically added. "
                        "Examples: 'category:promotions older_than:60d', "
                        "'from:notifications@linkedin.com older_than:30d', "
                        "'subject:\"your order has shipped\" older_than:14d'"
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max messages to archive (default: 500)",
                    "default": 500,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "trash_emails",
        "description": (
            "Move messages to trash (recoverable for 30 days, then permanently deleted). "
            "Use ONLY for clear junk: unsubscribe confirmations, obvious spam, "
            "automated 'your account was logged in' alerts older than 1 year, "
            "duplicate or bounce notifications. "
            "DO NOT trash personal emails, receipts, or anything the user might need. "
            "Capped at 100 per call — call multiple times for larger batches."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Gmail search query for messages to trash. Be conservative and precise. "
                        "Examples: 'subject:\"unsubscribe confirmation\" older_than:1y', "
                        "'from:mailer-daemon older_than:6m'"
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max messages to trash per call (default: 100, hard cap: 100)",
                    "default": 100,
                },
            },
            "required": ["query"],
        },
    },
]
