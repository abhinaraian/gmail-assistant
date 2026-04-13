# Gmail Assistant — Backend Source

Complete source for all Python files. Recreate each file at the path shown.

---

## `requirements.txt`

```
anthropic>=0.40.0
google-auth-oauthlib>=1.2.0
google-auth-httplib2>=0.2.0
google-api-python-client>=2.150.0
python-dotenv>=1.0.0
fastapi>=0.110.0
uvicorn>=0.27.0
```

---

## `.env.example`

```
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

---

## `.gitignore`

```
.env
credentials/credentials.json
credentials/token.json
__pycache__/
*.pyc
*.pyo
.DS_Store
*.egg-info/
dist/
build/
.venv/
venv/
```

---

## `main.py`

CLI entry point. Run directly with `python main.py` or pass a custom instruction with `-i`.

```python
"""
Gmail Assistant — entry point.

Run with default settings:
    python main.py

Run with a custom instruction:
    python main.py --instruction "Create 5 labels focused on work and finance."
"""

import os
import sys
import argparse
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gmail Assistant — AI-powered inbox organizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python main.py
  python main.py -i "Organize my inbox with work, finance, and newsletter labels"
  python main.py -i "Clean up newsletters only and archive them"
  python main.py -i "Keep it simple — 5 broad labels covering 80% of my inbox"
  python main.py -i "Only look at the last 90 days in:inbox after:2024/01/01"
        """,
    )
    parser.add_argument(
        "--instruction",
        "-i",
        type=str,
        default=(
            "Analyze my inbox and organize it with smart, meaningful labels. "
            "Be comprehensive and aim to label at least 75% of my emails."
        ),
        help="Natural-language instruction for the assistant",
    )
    args = parser.parse_args()

    # ── Preflight checks ────────────────────────────────────────────────
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set.")
        print("  1. Copy .env.example to .env")
        print("  2. Add your key:  ANTHROPIC_API_KEY=sk-ant-...")
        print("  See SETUP.md Step 3 for details.")
        sys.exit(1)

    if not os.path.exists("credentials/credentials.json"):
        print("Error: credentials/credentials.json not found.")
        print("  Follow SETUP.md Step 2 to create Gmail API credentials.")
        sys.exit(1)

    # ── Run ─────────────────────────────────────────────────────────────
    try:
        from src.agent import GmailAgent
        agent = GmailAgent()
        agent.run(args.instruction)
    except KeyboardInterrupt:
        print("\n\nInterrupted — goodbye.")
        sys.exit(0)
    except FileNotFoundError as exc:
        print(f"\nSetup error: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\nUnexpected error: {exc}")
        raise


if __name__ == "__main__":
    main()
```

---

## `server.py` (root)

uvicorn launcher for Chrome extension mode. Run with `python server.py`.

```python
"""
Start the Gmail Assistant local server.
Run this before using the Chrome extension.

    python server.py
"""

import os
import sys


def main():
    if not os.getenv("ANTHROPIC_API_KEY"):
        # Try loading .env manually before giving up
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set.")
        print("  1. Copy .env.example to .env")
        print("  2. Add your key:  ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    if not os.path.exists("credentials/credentials.json"):
        print("Error: credentials/credentials.json not found.")
        print("  Follow SETUP.md Step 2 to create Gmail API credentials.")
        sys.exit(1)

    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    print("=" * 50)
    print("  Gmail Assistant — Local Server")
    print("=" * 50)
    print("\n  Server:    http://localhost:8000")
    print("  Open Gmail, then click the extension icon.\n")

    uvicorn.run(
        "src.server:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
```

---

## `src/__init__.py`

Empty file — makes `src/` a Python package.

```python
```

---

## `src/gmail_client.py`

Gmail API wrapper. Handles OAuth2 auth, all 12 inbox operations, and batch API calls.

Key implementation notes:
- Uses `batchModify` (up to 1000 messages/call) for bulk label operations
- Uses `new_batch_http_request` (up to 100 messages/chunk) for metadata fetching
- `apply_label_to_search` enforces one-label-per-email via `-has:userlabels` appended to every query
- `trash_emails` is intentionally hard-capped at 100/call as a safety measure

```python
"""
Gmail API client — handles authentication and all Gmail operations.
Uses batch HTTP requests for efficiency when fetching metadata.
"""

import base64
import os
from typing import Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailClient:
    """Gmail API wrapper with OAuth2 authentication and full inbox management."""

    def __init__(
        self,
        credentials_path: str = "credentials/credentials.json",
        token_path: str = "credentials/token.json",
    ):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = self._authenticate()

    # ------------------------------------------------------------------ #
    #  Authentication                                                       #
    # ------------------------------------------------------------------ #

    def _authenticate(self):
        """Run OAuth2 flow and return an authenticated Gmail service."""
        creds = None
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(
                        f"\ncredentials.json not found at '{self.credentials_path}'.\n"
                        "Please complete Step 2 in SETUP.md to download your OAuth credentials."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)

            os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
            with open(self.token_path, "w") as token_file:
                token_file.write(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    # ------------------------------------------------------------------ #
    #  Reading / sampling                                                   #
    # ------------------------------------------------------------------ #

    def get_inbox_stats(self) -> dict:
        """Return a high-level overview of the inbox."""
        try:
            profile = self.service.users().getProfile(userId="me").execute()
            unread_ids = self._list_message_ids(max_results=500, query="in:inbox is:unread")
            inbox_ids  = self._list_message_ids(max_results=500, query="in:inbox")
            labels     = self.list_labels()
            user_labels = [l for l in labels if l.get("type") == "user"]
            return {
                "messages_total": profile.get("messagesTotal", 0),
                "threads_total":  profile.get("threadsTotal", 0),
                "inbox_count":    len(inbox_ids),
                "inbox_unread":   len(unread_ids),
                "user_label_count": len(user_labels),
                "note": "inbox_count and inbox_unread are capped at 500; use search_messages for exact counts.",
            }
        except HttpError as exc:
            return {"error": str(exc)}

    def sample_inbox(
        self, max_results: int = 200, query: str = "in:inbox"
    ) -> list[dict]:
        """
        Return metadata for up to `max_results` messages matching `query`.
        Uses batch HTTP requests — much faster than sequential calls.
        Each record: {id, from, subject, snippet, date, labelIds}
        """
        try:
            msg_ids = self._list_message_ids(max_results=max_results, query=query)
            if not msg_ids:
                return []
            return self._batch_get_metadata(msg_ids)
        except HttpError as exc:
            return [{"error": str(exc)}]

    def _list_message_ids(self, max_results: int = 500, query: str = "") -> list[str]:
        """Return a list of message IDs matching `query` (paginated)."""
        collected: list[dict] = []
        kwargs: dict = {"userId": "me", "maxResults": min(max_results, 500)}
        if query:
            kwargs["q"] = query

        try:
            resp = self.service.users().messages().list(**kwargs).execute()
            collected.extend(resp.get("messages", []))

            while "nextPageToken" in resp and len(collected) < max_results:
                kwargs["pageToken"] = resp["nextPageToken"]
                resp = self.service.users().messages().list(**kwargs).execute()
                collected.extend(resp.get("messages", []))

            return [m["id"] for m in collected[:max_results]]
        except HttpError as exc:
            print(f"  [Error listing messages] {exc}")
            return []

    def _batch_get_metadata(self, msg_ids: list[str]) -> list[dict]:
        """
        Batch-fetch metadata for multiple message IDs.
        Processes 100 at a time (Google API batch limit).
        """
        results: dict[str, dict] = {}

        def callback(request_id, response, exception):
            if exception is None and response:
                headers = {
                    h["name"]: h["value"]
                    for h in response.get("payload", {}).get("headers", [])
                }
                results[request_id] = {
                    "id": response["id"],
                    "from": headers.get("From", "")[:120],
                    "subject": headers.get("Subject", "")[:150],
                    "snippet": response.get("snippet", "")[:150],
                    "date": headers.get("Date", ""),
                    "labelIds": response.get("labelIds", []),
                }

        for chunk_start in range(0, len(msg_ids), 100):
            chunk = msg_ids[chunk_start : chunk_start + 100]
            batch = self.service.new_batch_http_request(callback=callback)
            for msg_id in chunk:
                batch.add(
                    self.service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg_id,
                        format="metadata",
                        metadataHeaders=["From", "Subject", "Date"],
                    ),
                    request_id=msg_id,
                )
            batch.execute()

        return [results[mid] for mid in msg_ids if mid in results]

    def search_messages(self, query: str, max_results: int = 500) -> dict:
        """
        Search messages and return the count matching the query.
        Claude uses this to verify coverage before applying labels.
        """
        ids = self._list_message_ids(max_results=max_results, query=query)
        return {
            "count": len(ids),
            "query": query,
            "note": (
                f"Found {len(ids)} messages"
                + (" (result capped at limit)" if len(ids) >= max_results else "")
            ),
        }

    def get_email_body(self, message_id: str) -> dict:
        """
        Fetch the full content of a single email.
        Returns from, subject, date, plain-text body (capped at 4000 chars), and labelIds.
        Use this when metadata alone isn't enough to make an organization decision.
        """
        try:
            msg = (
                self.service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            payload = msg.get("payload", {})
            headers = {
                h["name"]: h["value"]
                for h in payload.get("headers", [])
            }
            body = self._extract_text_body(payload)
            return {
                "id": message_id,
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "body": body[:4000],
                "body_truncated": len(body) > 4000,
                "labelIds": msg.get("labelIds", []),
            }
        except HttpError as exc:
            return {"error": str(exc)}

    def _extract_text_body(self, payload: dict) -> str:
        """Recursively extract plain-text body from an email payload."""
        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            # No plain-text part found — recurse into sub-parts
            for part in payload["parts"]:
                result = self._extract_text_body(part)
                if result:
                    return result
        else:
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        return ""

    # ------------------------------------------------------------------ #
    #  Label CRUD                                                           #
    # ------------------------------------------------------------------ #

    def list_labels(self) -> list[dict]:
        """List all Gmail labels (system + user-created)."""
        try:
            resp = self.service.users().labels().list(userId="me").execute()
            return [
                {
                    "id": lbl["id"],
                    "name": lbl["name"],
                    "type": lbl.get("type", "user"),
                }
                for lbl in resp.get("labels", [])
            ]
        except HttpError as exc:
            return [{"error": str(exc)}]

    def create_label(
        self,
        name: str,
        background_color: Optional[str] = None,
        text_color: Optional[str] = None,
    ) -> dict:
        """Create a new Gmail label and return its ID."""
        try:
            body: dict = {"name": name}
            if background_color and text_color:
                body["color"] = {
                    "backgroundColor": background_color,
                    "textColor": text_color,
                }
            result = self.service.users().labels().create(userId="me", body=body).execute()
            return {"success": True, "id": result["id"], "name": result["name"]}
        except HttpError as exc:
            return {"error": str(exc)}

    def delete_label(self, label_id: str) -> dict:
        """Delete a user-created label. Emails are NOT deleted."""
        try:
            self.service.users().labels().delete(userId="me", id=label_id).execute()
            return {"success": True, "deleted_label_id": label_id}
        except HttpError as exc:
            return {"error": str(exc)}

    def update_label(
        self,
        label_id: str,
        name: Optional[str] = None,
        background_color: Optional[str] = None,
        text_color: Optional[str] = None,
    ) -> dict:
        """Update an existing label's name and/or color."""
        try:
            body: dict = {}
            if name:
                body["name"] = name
            if background_color and text_color:
                body["color"] = {
                    "backgroundColor": background_color,
                    "textColor": text_color,
                }
            result = (
                self.service.users()
                .labels()
                .update(userId="me", id=label_id, body=body)
                .execute()
            )
            return {"success": True, "id": result["id"], "name": result["name"]}
        except HttpError as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------ #
    #  Bulk label application                                              #
    # ------------------------------------------------------------------ #

    def apply_label_to_search(
        self,
        query: str,
        label_id: str,
        archive: bool = False,
        max_results: int = 500,
    ) -> dict:
        """
        Apply `label_id` to every message matching `query`.
        Enforces one-label-per-email: emails that already have a user label are skipped.
        If `archive=True`, also removes the INBOX label (archives the message).
        Processes in batches of 1000 (Gmail batchModify limit).
        """
        # Enforce one-label-per-email: only touch emails without an existing user label.
        exclusive_query = f"({query}) -has:userlabels"
        msg_ids = self._list_message_ids(max_results=max_results, query=exclusive_query)

        if not msg_ids:
            return {
                "success": True,
                "modified": 0,
                "message": "No unlabeled messages matched the query (already-labeled emails are skipped).",
                "query": exclusive_query,
            }

        add_ids = [label_id]
        remove_ids = ["INBOX"] if archive else None
        total = 0

        for i in range(0, len(msg_ids), 1000):
            batch = msg_ids[i : i + 1000]
            result = self._batch_modify_labels(batch, add_ids=add_ids, remove_ids=remove_ids)
            if "error" in result:
                return result
            total += len(batch)

        return {
            "success": True,
            "modified": total,
            "query": exclusive_query,
            "label_id": label_id,
            "archived": archive,
        }

    # ------------------------------------------------------------------ #
    #  Inbox actions                                                        #
    # ------------------------------------------------------------------ #

    def mark_as_read(self, query: str, max_results: int = 500) -> dict:
        """Remove the UNREAD label from all messages matching `query`."""
        msg_ids = self._list_message_ids(
            max_results=max_results, query=f"({query}) is:unread"
        )
        if not msg_ids:
            return {"success": True, "modified": 0, "message": "No unread messages matched.", "query": query}

        total = 0
        for i in range(0, len(msg_ids), 1000):
            result = self._batch_modify_labels(msg_ids[i : i + 1000], remove_ids=["UNREAD"])
            if "error" in result:
                return result
            total += len(msg_ids[i : i + 1000])

        return {"success": True, "modified": total, "query": query}

    def archive_emails(self, query: str, max_results: int = 500) -> dict:
        """Remove the INBOX label (archive) from all messages matching `query`."""
        msg_ids = self._list_message_ids(
            max_results=max_results, query=f"({query}) in:inbox"
        )
        if not msg_ids:
            return {"success": True, "modified": 0, "message": "No inbox messages matched.", "query": query}

        total = 0
        for i in range(0, len(msg_ids), 1000):
            result = self._batch_modify_labels(msg_ids[i : i + 1000], remove_ids=["INBOX"])
            if "error" in result:
                return result
            total += len(msg_ids[i : i + 1000])

        return {"success": True, "modified": total, "query": query}

    def trash_emails(self, query: str, max_results: int = 100) -> dict:
        """
        Move messages to trash (recoverable for 30 days).
        Intentionally limited to 100 per call — use multiple calls for large batches.
        """
        msg_ids = self._list_message_ids(max_results=max_results, query=query)
        if not msg_ids:
            return {"success": True, "modified": 0, "message": "No messages matched.", "query": query}

        total = 0
        for i in range(0, len(msg_ids), 1000):
            result = self._batch_modify_labels(
                msg_ids[i : i + 1000],
                add_ids=["TRASH"],
                remove_ids=["INBOX", "UNREAD"],
            )
            if "error" in result:
                return result
            total += len(msg_ids[i : i + 1000])

        return {"success": True, "modified": total, "query": query}

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _batch_modify_labels(
        self,
        msg_ids: list[str],
        add_ids: Optional[list[str]] = None,
        remove_ids: Optional[list[str]] = None,
    ) -> dict:
        """Add/remove labels from up to 1000 messages in a single API call."""
        try:
            body: dict = {"ids": msg_ids}
            if add_ids:
                body["addLabelIds"] = add_ids
            if remove_ids:
                body["removeLabelIds"] = remove_ids
            self.service.users().messages().batchModify(userId="me", body=body).execute()
            return {"success": True, "count": len(msg_ids)}
        except HttpError as exc:
            return {"error": str(exc)}
```

---

## `src/tools.py`

JSON schemas for all 12 tools passed to Claude. These define tool names, descriptions,
and parameter schemas in the format the Anthropic API expects.

Key notes:
- The last tool definition in `TOOL_DEFINITIONS` gets `cache_control` added in `agent.py`
  to cache all tool schemas after the first API call
- Descriptions are carefully written to guide Claude's decision-making, not just describe parameters

```python
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
```

---

## `src/agent.py`

The core of the system. Contains:
1. `SYSTEM_PROMPT` — the full instruction set for Claude
2. `_TOOLS_CACHED` — tool definitions with prompt caching on the last entry
3. `GmailAgent` — the agentic loop class with tool dispatcher

```python
"""
Gmail organization agent — agentic loop powered by Claude with tool use.
Claude analyzes the inbox, designs a label taxonomy, and applies it.
"""

import json
import time
from typing import Callable, Optional
from anthropic import Anthropic, RateLimitError
from .gmail_client import GmailClient
from .tools import TOOL_DEFINITIONS

# ── Prompt-caching wrapper ──────────────────────────────────────────────────
# Marking the last tool definition with cache_control tells the API to cache
# all tool schemas. Cached tokens are billed at ~10% of normal input cost and
# don't count toward the per-minute token limit (the main cause of 429 errors).
# The system prompt is cached inline each iteration (see system_block in run()).
_TOOLS_CACHED = [
    *TOOL_DEFINITIONS[:-1],
    {**TOOL_DEFINITIONS[-1], "cache_control": {"type": "ephemeral"}},
]

# Large tool results (sample_inbox / get_email_body) are trimmed in history
# after Claude has processed them so they don't balloon the context on every turn.
_TRIM_AFTER_TOOLS = {"sample_inbox", "get_email_body"}
_TRIM_KEEP_CHARS  = 500   # keep a short reminder of what was returned


SYSTEM_PROMPT = """You are an intelligent Gmail inbox assistant with full inbox management capabilities.
Your mission: deeply analyze the user's inbox and take meaningful action — not just labeling, but truly cleaning and organizing so the inbox becomes a pleasure to use.

## Full Capability Set

| Tool | What it does |
|---|---|
| `get_inbox_stats` | Overview: total messages, unread count, inbox size |
| `sample_inbox` | Fetch email metadata (from, subject, snippet, date, labels) |
| `get_email_body` | Read a specific email's full content |
| `search_messages` | Count how many emails match a query |
| `list_labels` / `create_label` / `update_label` / `delete_label` | Label management |
| `apply_label_to_search` | Bulk-apply a label (optionally archive at the same time) |
| `mark_as_read` | Mark matched emails as read |
| `archive_emails` | Move emails out of inbox (kept in All Mail) |
| `trash_emails` | Move clear junk to trash (recoverable 30 days) |

## Recommended Workflow

**Step 1 — Orient**
Call `get_inbox_stats` to understand the inbox scale.
Then `sample_inbox` (200+ emails) to identify patterns.
Call `list_labels` to see what already exists.

**Step 2 — Deep-read edge cases**
When subject/snippet isn't enough to classify an email, call `get_email_body` on a few samples.
This is especially useful for: ambiguous senders, deciding trash vs. archive, identifying personal vs. automated.

**Step 3 — Design your plan**
Based on what you saw, plan all actions across three dimensions:

*Labels (6–14 total):*
- Reuse existing good labels by ID
- Create new ones for clear categories: Finance, Newsletters, Shopping, Work, Travel, etc.
- Use sublabels: `Work/GitHub`, `Work/Meetings`
- **Priority order matters**: each email gets at most ONE label — `apply_label_to_search` skips already-labeled emails. Apply the most specific/valuable labels first (e.g. Finance before Newsletters).

*Cleanup actions:*
- `mark_as_read`: old promos, notifications, newsletters that piled up unread
- `archive_emails`: processed/old emails that don't need inbox presence
- `trash_emails`: unsubscribe confirmations, mailer-daemon bounces, obvious junk

*Priority emails to KEEP in inbox:*
- Personal emails, anything needing a reply, recent finance/bills, job offers

**Step 4 — Execute systematically**
For each label: `create_label` → `apply_label_to_search`
For bulk noise: `mark_as_read` and `archive_emails` with age filters (older_than:30d, older_than:60d)
For clear junk: `trash_emails` with conservative, precise queries

**Step 4.5 — Prune sparse labels**
After applying all labels, verify each one: `search_messages` with query `label:LabelName`.
Delete any label with fewer than **5 emails** using `delete_label` — a category with 1–4 emails is not meaningful.

**Step 5 — Report**
Summarize: labels created, labels deleted (sparse), emails labeled, emails archived, marked read, trashed, and what the inbox looks like now.

## Decision Guide

**Archive (not trash) when:**
- It's a newsletter or promo that's been read or is old
- It's a notification (shipping, login alert, social) that's been processed
- It might be useful to search for later (receipts, confirmations)
- You're even slightly unsure

**Trash only when ALL of these are true:**
- It's clearly automated (no personal content)
- It has zero future reference value
- It's older than a reasonable threshold (or is an obvious bounce/unsubscribe)
- Examples: mailer-daemon bounces, "you've been unsubscribed" confirmations, duplicate notifications

**Mark as read when:**
- Emails are clearly informational and the user doesn't need to act on them
- Promotional/newsletter emails that have piled up unread
- Old notification digests

**Keep in inbox when:**
- Email appears personal or requires a response
- Recent financial statements or important receipts
- Active job opportunities
- Anything ambiguous — default to keeping

## Gmail Search Syntax

```
from:domain.com                     all mail from a domain
from:a@x.com OR from:b@y.com       multiple senders
subject:invoice OR subject:receipt  keyword in subject
category:promotions                 Gmail's auto-category
list:newsletter                     mailing lists
older_than:30d / older_than:1y      age filters
is:unread                           only unread
in:inbox                            only inbox (not archived)
```

## Absolute Rules

- **NEVER permanently delete** — trash is fine (30-day recovery window); skipping trash is always safer
- **NEVER trash personal emails**, receipts, financial docs, or anything with future reference value
- **Check list_labels before create_label** — reuse existing IDs, never create duplicates
- **Be conservative with trash** — when in doubt, archive instead
- **Use get_email_body** before trashing anything ambiguous
- **One label per email** — `apply_label_to_search` enforces this automatically. Apply most specific labels first so priority emails (Finance, Work) claim their emails before broader ones (Newsletters, Promotions).
- **Delete sparse labels** — after labeling, check counts with `search_messages label:LabelName`. Delete any label with fewer than 5 emails using `delete_label`."""


LogCallback = Callable[[str, str], None]


def _default_log(text: str, msg_type: str = "log") -> None:
    print(text)


class GmailAgent:
    """Drives the agentic loop: Claude decides what tools to call, this class executes them."""

    def __init__(self, log_callback: Optional[LogCallback] = None):
        self.client = Anthropic()
        self.gmail = GmailClient()
        self.messages: list[dict] = []
        self._log_cb = log_callback or _default_log

    def _emit(self, text: str, msg_type: str = "log") -> None:
        self._log_cb(text, msg_type)

    # ------------------------------------------------------------------ #
    #  Tool execution dispatcher                                            #
    # ------------------------------------------------------------------ #

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """Route a tool call to the correct GmailClient method and return JSON."""
        preview = json.dumps(tool_input)
        if len(preview) > 100:
            preview = preview[:100] + "..."
        self._emit(f"  → {tool_name}({preview})", "tool")

        try:
            if tool_name == "get_inbox_stats":
                result = self.gmail.get_inbox_stats()

            elif tool_name == "sample_inbox":
                result = self.gmail.sample_inbox(
                    max_results=tool_input.get("max_results", 200),
                    query=tool_input.get("query", "in:inbox"),
                )

            elif tool_name == "get_email_body":
                result = self.gmail.get_email_body(tool_input["message_id"])

            elif tool_name == "search_messages":
                result = self.gmail.search_messages(
                    query=tool_input["query"],
                    max_results=tool_input.get("max_results", 500),
                )

            elif tool_name == "list_labels":
                result = self.gmail.list_labels()

            elif tool_name == "create_label":
                result = self.gmail.create_label(
                    name=tool_input["name"],
                    background_color=tool_input.get("background_color"),
                    text_color=tool_input.get("text_color"),
                )

            elif tool_name == "delete_label":
                result = self.gmail.delete_label(tool_input["label_id"])

            elif tool_name == "update_label":
                result = self.gmail.update_label(
                    label_id=tool_input["label_id"],
                    name=tool_input.get("name"),
                    background_color=tool_input.get("background_color"),
                    text_color=tool_input.get("text_color"),
                )

            elif tool_name == "apply_label_to_search":
                result = self.gmail.apply_label_to_search(
                    query=tool_input["query"],
                    label_id=tool_input["label_id"],
                    archive=tool_input.get("archive", False),
                    max_results=tool_input.get("max_results", 500),
                )

            elif tool_name == "mark_as_read":
                result = self.gmail.mark_as_read(
                    query=tool_input["query"],
                    max_results=tool_input.get("max_results", 500),
                )

            elif tool_name == "archive_emails":
                result = self.gmail.archive_emails(
                    query=tool_input["query"],
                    max_results=tool_input.get("max_results", 500),
                )

            elif tool_name == "trash_emails":
                result = self.gmail.trash_emails(
                    query=tool_input["query"],
                    max_results=min(tool_input.get("max_results", 100), 100),
                )

            else:
                result = {"error": f"Unknown tool: {tool_name}"}

            result_json = json.dumps(result)
            self._emit(
                f"     ✓ {result_json[:180]}{'...' if len(result_json) > 180 else ''}",
                "success",
            )
            return result_json

        except Exception as exc:
            error = {"error": f"Tool execution failed: {exc}"}
            self._emit(f"     ✗ {error}", "error")
            return json.dumps(error)

    # ------------------------------------------------------------------ #
    #  Agentic loop                                                         #
    # ------------------------------------------------------------------ #

    def run(
        self,
        instruction: str = (
            "Analyze my inbox and organize it with smart, meaningful labels. "
            "Be comprehensive and aim to label at least 75% of my emails."
        ),
    ) -> None:
        """Run the inbox organization agent until Claude signals it is done."""
        self._emit("\n" + "=" * 62, "header")
        self._emit("  Gmail Assistant  —  AI-Powered Inbox Organizer", "header")
        self._emit("=" * 62, "header")
        self._emit(f"\nTask: {instruction}\n", "log")
        self._emit("Connecting to Gmail and starting analysis...\n", "log")

        self.messages = [{"role": "user", "content": instruction}]
        max_iterations = 60

        for iteration in range(1, max_iterations + 1):
            # Build the cached system block with the current SYSTEM_PROMPT text.
            system_block = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]

            # Use streaming (avoids hard request timeouts) + prompt caching (reduces TPM spend).
            # Retry on rate-limit errors with exponential backoff.
            for attempt in range(6):
                try:
                    with self.client.messages.stream(
                        model="claude-sonnet-4-6",
                        max_tokens=8192,
                        system=system_block,
                        tools=_TOOLS_CACHED,
                        messages=self.messages,
                        extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
                    ) as stream:
                        response = stream.get_final_message()
                    break
                except RateLimitError:
                    if attempt == 5:
                        raise
                    wait = 30 * (2 ** attempt)   # 30 s, 60 s, 120 s, 240 s, 480 s
                    self._emit(f"Rate limit reached — retrying in {wait}s…", "log")
                    time.sleep(wait)

            # Preserve full content for multi-turn consistency
            self.messages.append({"role": "assistant", "content": response.content})

            # Emit any text Claude produced this turn
            for block in response.content:
                if hasattr(block, "type") and block.type == "text":
                    self._emit(f"\n{block.text}", "text")

            # Done — Claude finished without requesting more tools
            if response.stop_reason == "end_turn":
                self._emit("\n" + "=" * 62, "header")
                self._emit("  Organization complete!", "header")
                self._emit("=" * 62, "header")
                return

            # Claude wants to call tools
            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if hasattr(block, "type") and block.type == "tool_use":
                        result = self._execute_tool(block.name, block.input)

                        # Trim large results (sample_inbox, get_email_body) so they
                        # don't blow up the context on every subsequent turn.
                        if block.name in _TRIM_AFTER_TOOLS and len(result) > _TRIM_KEEP_CHARS:
                            trimmed = result[:_TRIM_KEEP_CHARS]
                            result = trimmed + f' ... [truncated — {len(result) - _TRIM_KEEP_CHARS} chars omitted to save context]'

                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result,
                            }
                        )
                self.messages.append({"role": "user", "content": tool_results})
                continue

            # Any other stop reason (pause_turn, max_tokens, etc.)
            self._emit(f"\n[Agent stopped: {response.stop_reason}]", "log")
            break

        self._emit("\n[Warning: maximum iterations reached — stopping.]", "log")
```

---

## `src/server.py`

FastAPI backend. Exposes three endpoints to the Chrome extension and streams agent
output in real-time via Server-Sent Events (SSE).

Architecture notes:
- Agent is sync (blocking), FastAPI is async → agent runs in `daemon=True` thread
- `queue.Queue` bridges the agent thread and the async SSE generator
- SSE pings every 500ms when idle to keep the connection alive through proxies
- `/run` drains stale queue messages before starting a new run

```python
"""
FastAPI server — runs the Gmail agent and streams output to the Chrome extension via SSE.
"""

import asyncio
import json
import queue
import threading
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Gmail Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global agent state ──────────────────────────────────────────────────────
_message_queue: queue.Queue = queue.Queue()
_agent_running: bool = False
_agent_thread: Optional[threading.Thread] = None


def _enqueue(text: str, msg_type: str = "log") -> None:
    """Called by the agent to push a message into the SSE queue."""
    # Split multi-line messages so each line is a discrete event
    for line in text.split("\n"):
        _message_queue.put({"type": msg_type, "text": line})


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/status")
async def get_status():
    return {"running": _agent_running, "ready": True}


class RunRequest(BaseModel):
    instruction: str = (
        "Analyze my inbox and organize it with smart, meaningful labels. "
        "Be comprehensive and aim to label at least 75% of my emails."
    )


@app.post("/run")
async def run_agent(req: RunRequest):
    global _agent_running, _agent_thread

    if _agent_running:
        return {"error": "Agent is already running"}

    # Drain stale messages from a previous run
    while not _message_queue.empty():
        try:
            _message_queue.get_nowait()
        except queue.Empty:
            break

    def _run_in_thread():
        global _agent_running
        _agent_running = True
        try:
            from src.agent import GmailAgent
            agent = GmailAgent(log_callback=_enqueue)
            agent.run(req.instruction)
            _enqueue("✓ Organization complete!", "done")
        except Exception as exc:
            _enqueue(f"Error: {exc}", "error")
        finally:
            _agent_running = False

    _agent_thread = threading.Thread(target=_run_in_thread, daemon=True)
    _agent_thread.start()
    return {"status": "started"}


@app.get("/stream")
async def stream_events(request: Request):
    """SSE endpoint — stays open and pushes messages as the agent runs."""

    async def generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = _message_queue.get_nowait()
                yield f"data: {json.dumps(msg)}\n\n"
            except queue.Empty:
                # Keep-alive ping every 500 ms
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"
                await asyncio.sleep(0.5)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
```
