"""
Gmail API client — handles authentication and all Gmail operations.
Uses batch HTTP requests for efficiency when fetching metadata.
"""

import base64
import os
import sys
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

                # In Docker or any headless environment there is no browser to
                # open, so fall back to the console (copy-paste) OAuth flow.
                headless = (
                    bool(os.environ.get("DOCKER_ENV"))
                    or (sys.platform == "linux" and not os.environ.get("DISPLAY"))
                )
                if headless:
                    print("\n─── Gmail Authorization Required ───────────────────────")
                    print("  1. Open the URL printed below in your browser")
                    print("  2. Sign in and click Allow")
                    print("  3. Copy the authorization code and paste it here\n")
                    creds = flow.run_console()
                else:
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
