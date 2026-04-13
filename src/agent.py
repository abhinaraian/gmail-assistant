"""
Gmail organization agent — agentic loop powered by Claude or Gemini with tool use.
The AI analyzes the inbox, designs a label taxonomy, and applies it.
"""

import json
import os
import time
from typing import Any, Callable, Optional
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

_DEFAULT_INSTRUCTION = (
    "Analyze my inbox and organize it with smart, meaningful labels. "
    "Be comprehensive and aim to label at least 75% of my emails."
)


def _default_log(text: str, msg_type: str = "log") -> None:
    print(text)


class GmailAgent:
    """Drives the agentic loop: Claude or Gemini decides what tools to call, this class executes them."""

    def __init__(self, log_callback: Optional[LogCallback] = None, provider: str = "claude"):
        self.provider = provider  # "claude" or "gemini"
        self.client = Anthropic() if provider == "claude" else None
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
    #  Agentic loop dispatcher                                             #
    # ------------------------------------------------------------------ #

    def run(self, instruction: str = _DEFAULT_INSTRUCTION) -> None:
        """Run the inbox organization agent using the selected provider."""
        if self.provider == "gemini":
            self._run_gemini(instruction)
        else:
            self._run_claude(instruction)

    # ------------------------------------------------------------------ #
    #  Claude loop                                                          #
    # ------------------------------------------------------------------ #

    def _run_claude(self, instruction: str) -> None:
        """Run the agentic loop powered by Claude Sonnet."""
        self._emit("\n" + "=" * 62, "header")
        self._emit("  Gmail Assistant  —  Powered by Claude Sonnet", "header")
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

    # ------------------------------------------------------------------ #
    #  Gemini loop                                                          #
    # ------------------------------------------------------------------ #

    def _sanitize_schema_for_gemini(self, schema: Any) -> Any:
        """Remove JSON Schema fields Gemini rejects (e.g. `default`)."""
        if isinstance(schema, dict):
            cleaned: dict[str, Any] = {}
            for key, value in schema.items():
                if key == "default":
                    continue
                cleaned[key] = self._sanitize_schema_for_gemini(value)
            return cleaned
        if isinstance(schema, list):
            return [self._sanitize_schema_for_gemini(item) for item in schema]
        return schema

    def _run_gemini(self, instruction: str) -> None:
        """Run the agentic loop powered by Gemini Flash (free tier)."""
        try:
            import google.generativeai as genai
        except ImportError:
            raise RuntimeError(
                "google-generativeai not installed. Run: pip install google-generativeai"
            )

        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY not set. Add GOOGLE_API_KEY=your_key to your .env file. "
                "Get a free key at https://aistudio.google.com/app/apikey"
            )

        genai.configure(api_key=api_key)

        # Build Gemini function declarations from the shared TOOL_DEFINITIONS.
        # Gemini uses "parameters" (JSON Schema) where Anthropic uses "input_schema".
        function_declarations = []
        for t in TOOL_DEFINITIONS:
            schema = self._sanitize_schema_for_gemini(
                t.get("input_schema", {"type": "object", "properties": {}})
            )
            decl: dict = {"name": t["name"], "description": t["description"]}
            # Only include parameters when there are actual properties to declare
            if schema.get("properties"):
                decl["parameters"] = schema
            function_declarations.append(decl)

        model = genai.GenerativeModel(
            "gemini-2.0-flash",
            tools=[{"function_declarations": function_declarations}],
            system_instruction=SYSTEM_PROMPT,
        )

        self._emit("\n" + "=" * 62, "header")
        self._emit("  Gmail Assistant  —  Powered by Gemini Flash (free)", "header")
        self._emit("=" * 62, "header")
        self._emit(f"\nTask: {instruction}\n", "log")
        self._emit("Connecting to Gmail and starting analysis...\n", "log")

        chat = model.start_chat()
        message: object = instruction
        max_iterations = 60

        for iteration in range(1, max_iterations + 1):
            response = chat.send_message(message)

            # Emit any text the model produced this turn
            for part in response.parts:
                if hasattr(part, "text") and part.text:
                    self._emit(f"\n{part.text}", "text")

            # Collect function calls from this response
            fn_calls = [
                part.function_call
                for part in response.parts
                if hasattr(part, "function_call") and part.function_call.name
            ]

            if not fn_calls:
                # No more tool calls — the model is done
                break

            # Execute each tool and build the response parts
            tool_response_parts = []
            for fc in fn_calls:
                result_json = self._execute_tool(fc.name, dict(fc.args))
                try:
                    result_data = json.loads(result_json)
                except (json.JSONDecodeError, ValueError):
                    result_data = {"text": result_json}

                tool_response_parts.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=fc.name,
                            response={"result": result_data},
                        )
                    )
                )

            message = tool_response_parts

        self._emit("\n" + "=" * 62, "header")
        self._emit("  Organization complete!", "header")
        self._emit("=" * 62, "header")
