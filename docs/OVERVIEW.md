# Gmail Assistant — Architecture Overview

## Purpose

An agentic Gmail inbox organizer with a **dual AI provider** design. The user picks their
preferred model in the Chrome extension side panel:

| Provider | Model | Cost | When to use |
|---|---|---|---|
| **Claude Sonnet** | `claude-sonnet-4-6` | Paid (Anthropic credits) | Highest quality reasoning |
| **Gemini Flash** | `gemini-2.0-flash` | Free (Google AI Studio) | No credit card, great for most inboxes |

Given a natural-language instruction, the selected AI autonomously organizes, labels, archives,
and cleans the inbox through a multi-turn agentic loop (up to 60 iterations).

## What the Agent Does

1. Calls `get_inbox_stats` and `sample_inbox` to understand inbox scale and patterns
2. Calls `list_labels` to find existing labels (avoids duplicates)
3. Optionally calls `get_email_body` on ambiguous emails before making decisions
4. Creates labels and applies them with `apply_label_to_search` (one label per email, enforced at the API layer)
5. Marks bulk unread noise as read with `mark_as_read`
6. Archives processed emails with `archive_emails`
7. Trashes clear junk with `trash_emails` (capped at 100/call, recoverable for 30 days)
8. Prunes labels that end up with fewer than 5 emails (`search_messages` + `delete_label`)
9. Reports a full summary

## System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                   Chrome Extension (UI)                        │
│   panel.html + panel.js        background.js (service worker) │
│   Side panel in Gmail           Opens panel on Gmail tabs only │
│   Model selector: [✦ Claude Sonnet] [◈ Gemini Flash]         │
└───────────────────────┬──────────────────────────────────────┘
                        │ HTTP / SSE  (localhost:8000)
                        │ POST /run  { instruction, model }
┌───────────────────────▼──────────────────────────────────────┐
│                FastAPI Server  (src/server.py)                 │
│   GET /status    POST /run    GET /stream (SSE)                │
│   Agent runs in daemon thread; log lines flow via queue.Queue  │
└───────────────────────┬──────────────────────────────────────┘
                        │  provider = "claude" | "gemini"
              ┌─────────┴──────────────┐
              ▼                        ▼
  ┌─────────────────────┐  ┌──────────────────────┐
  │  Anthropic Claude   │  │  Google Gemini Flash │
  │  claude-sonnet-4-6  │  │  gemini-2.0-flash    │
  │  Tool use / SSE     │  │  Function calling    │
  │  8192 max_tokens    │  │  1M context window   │
  └─────────────────────┘  └──────────────────────┘
              │  tool calls (shared _execute_tool)  │
              └────────── GmailAgent ───────────────┘
                          (src/agent.py)
                          Agentic loop (≤60 iters)
                                    │
                          ┌─────────▼──────────────┐
                          │  GmailClient            │
                          │  (src/gmail_client.py)  │
                          │  OAuth2, batch ops      │
                          │  12 Gmail API methods   │
                          └─────────────────────────┘
```

## Key Design Decisions

### 1. Dual AI Provider (Claude + Gemini)
`GmailAgent.__init__(provider="claude"|"gemini")` selects the backend at construction time.
The Chrome extension POSTs `{ instruction, model }` to `/run`; the server passes `provider=`
to `GmailAgent`. Both providers share the same `_execute_tool()` dispatcher and Gmail client.

- **Claude path** (`_run_claude`): uses `client.messages.stream()` with prompt caching and
  exponential backoff on 429s
- **Gemini path** (`_run_gemini`): uses `genai.GenerativeModel.start_chat()` with function
  declarations derived from the same `TOOL_DEFINITIONS`. Tool responses are sent back as
  `genai.protos.Part(function_response=...)` objects

The `TOOL_DEFINITIONS` list in `tools.py` is the single source of truth for tool schemas.
Claude receives them as `input_schema`; Gemini receives them as `parameters` (same JSON Schema
format, renamed field). Tools with no parameters omit the `parameters` key for Gemini
compatibility.

### 2. Streaming API (`messages.stream`) instead of `messages.create()`
Long agentic runs (60 iterations × multiple tool calls each) can exceed HTTP request
timeouts on a single blocking call. `client.messages.stream()` keeps the TCP connection
alive throughout the full run via chunked transfer encoding.

**Critical note:** prompt caching with streaming requires
`extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"}`. The `betas` parameter
only works with `messages.create()`, not `messages.stream()` — passing `betas=` to
`stream()` raises `TypeError`.

### 2. Prompt Caching
The system prompt (~3,500 tokens) is cached by passing
`{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}` as
the `system` block on every turn. The last tool definition in `_TOOLS_CACHED` is also
marked with `cache_control`. Cached tokens cost ~10% of normal input tokens and do
**not** count toward the per-minute token limit (TPM). This was the primary fix for
429 rate limit errors during long runs.

### 3. Context Trimming for Large Tool Results
`sample_inbox` can return 40,000–100,000 characters of JSON. After Claude processes a
`sample_inbox` or `get_email_body` result, it is trimmed to 500 characters in the
message history (`_TRIM_AFTER_TOOLS`, `_TRIM_KEEP_CHARS`). Without trimming, the
context grows unboundedly across iterations, causing slow API calls and TPM exhaustion.

### 4. One Label Per Email (Enforced at the Data Layer)
`GmailClient.apply_label_to_search()` automatically appends `-has:userlabels` to every
query before calling the Gmail API. Already-labeled emails are excluded at search time.
This is enforced in the client layer — not just in the system prompt — so it holds
regardless of Claude's reasoning. The system prompt instructs Claude to apply labels in
priority order (most specific first: Finance, Work before Newsletters, Promotions).

### 5. Sparse Label Pruning
After the labeling pass, Claude verifies each label with `search_messages label:LabelName`.
Labels with fewer than 5 emails are deleted. Micro-categories with 1–4 emails are not
meaningful and clutter the Gmail sidebar.

### 6. Threading + Queue for the FastAPI Server
The Gmail agent is synchronous (blocking I/O: Gmail API calls, Claude streaming). FastAPI
is async. The agent runs in a `daemon=True` thread so it doesn't block the event loop. A
`queue.Queue` bridges the agent thread and the SSE endpoint. The SSE generator polls the
queue and emits each message as it arrives, pinging every 500ms when idle.

### 7. Exponential Backoff on Rate Limit Errors
When Claude returns a 429 (`RateLimitError`), the agent retries up to 5 times with waits
of 30s, 60s, 120s, 240s, 480s. Prompt caching significantly reduces the frequency of
rate limit hits by reducing billable input token count.

## Data Flow (One Agent Run)

```
1. User picks model (Claude Sonnet / Gemini Flash) in side panel
2. User types instruction, clicks "Organize Inbox"
3. panel.js → POST /run { instruction: "...", model: "claude"|"gemini" }
4. FastAPI /run validates model, spawns daemon thread
   → GmailAgent(provider=...).run(instruction)
5. panel.js opens EventSource → GET /stream (persistent SSE connection)

── Claude path ────────────────────────────────────────────────────────
Loop (up to 60 iterations):
  a. Build: messages list + system block (cache_control for prompt caching)
  b. client.messages.stream() → Claude generates response
  c. Emit text blocks → _emit("text") → queue → SSE → AI Response box
  d. stop_reason == "end_turn"? → emit "done", exit
  e. stop_reason == "tool_use":
     - _execute_tool() → GmailClient → Gmail API
     - Trim large results (sample_inbox, get_email_body)
     - Append tool_results, continue loop

── Gemini path ────────────────────────────────────────────────────────
Loop (up to 60 iterations):
  a. chat.send_message(message)  [message = str first turn, list of Parts thereafter]
  b. Emit text parts → _emit("text") → queue → SSE → AI Response box
  c. No function_call parts? → done, exit
  d. For each function_call part:
     - _execute_tool() → GmailClient → Gmail API
     - Build genai.protos.Part(function_response=...)
  e. message = [tool response parts], continue loop

6. Thread exits → _agent_running = False
7. _enqueue("✓ Organization complete!", "done") → panel.js setRunningState(false)
```

## Tool Inventory

| Tool | Category | Purpose |
|---|---|---|
| `get_inbox_stats` | Read | Total messages, unread count, inbox count, label count |
| `sample_inbox` | Read | Up to 500 email metadata records (from, subject, snippet, date, labels) |
| `get_email_body` | Read | Full plain-text body of one email (capped at 4000 chars) |
| `search_messages` | Read | Count emails matching a Gmail query |
| `list_labels` | Label | List all system + user labels with IDs |
| `create_label` | Label | Create a new label; returns label ID |
| `update_label` | Label | Rename or recolor an existing label |
| `delete_label` | Label | Delete a user label (emails are kept, just lose the label) |
| `apply_label_to_search` | Label | Bulk-apply label to unlabeled matching emails; optional archive |
| `mark_as_read` | Action | Remove UNREAD from matched emails |
| `archive_emails` | Action | Remove INBOX from matched emails (move to All Mail) |
| `trash_emails` | Action | Move to TRASH, 100/call hard cap (recoverable 30 days) |

## Directory Structure

```
GmailAssistant/
├── main.py                    # CLI entry point (python main.py -i "...")
├── server.py                  # uvicorn launcher — reads SERVER_HOST env var
├── requirements.txt           # Python dependencies (Anthropic + Gemini + Gmail)
├── Dockerfile                 # Container image (python:3.11-slim)
├── docker-compose.yml         # Mounts credentials/, maps port 8000
├── .dockerignore              # Excludes venv, .env, credentials, extension, docs
├── .env                       # ANTHROPIC_API_KEY + GOOGLE_API_KEY (gitignored)
├── .env.example               # Template with both keys
├── .gitignore
├── credentials/
│   ├── credentials.json       # Google OAuth client secret (gitignored)
│   └── token.json             # Auto-generated OAuth token (gitignored)
├── src/
│   ├── __init__.py            # Empty package marker
│   ├── agent.py               # Dual-provider agentic loop (Claude + Gemini), tool dispatcher
│   ├── gmail_client.py        # Gmail API wrapper (OAuth2, headless Docker flow, 12 operations)
│   ├── tools.py               # Tool JSON schemas — single source of truth for both providers
│   └── server.py              # FastAPI: /status, /run (accepts model field), /stream (SSE)
├── extension/
│   ├── manifest.json          # Chrome MV3: sidePanel, host_permissions for localhost:8000
│   ├── background.js          # Service worker: enables panel only on Gmail tabs
│   ├── panel.html             # UI: instruction card, model selector, AI box, collapsible log
│   ├── panel.js               # SSE client, model selector logic, run button, log rendering
│   └── icons/
│       ├── icon16.png
│       ├── icon32.png
│       ├── icon48.png
│       └── icon128.png
└── docs/
    ├── OVERVIEW.md            # Architecture, design decisions, data flow (this file)
    ├── BACKEND.md             # Complete Python source reference
    └── EXTENSION.md           # Complete extension source reference
```
