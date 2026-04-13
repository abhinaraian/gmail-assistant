# Gmail Assistant — Setup Guide

## What This Does

An agentic Gmail inbox organizer powered by **Claude** (`claude-sonnet-4-6`). Given a
natural-language instruction, the agent autonomously:

1. Samples your inbox (200–500 emails) to identify patterns
2. Designs a label taxonomy (6–14 labels) tailored to your email habits
3. Creates/reuses labels and applies them in bulk (one label per email)
4. Marks old unread noise as read, archives processed emails, trashes clear junk
5. Prunes labels with fewer than 5 emails (not meaningful as categories)
6. Reports a full summary of everything it did

**Your emails are never permanently deleted** — trash has a 30-day recovery window.

---

## Prerequisites

| Requirement | Check |
|---|---|
| Python 3.9+ | `python3 --version` |
| Gmail account | — |
| Anthropic API key | [console.anthropic.com](https://console.anthropic.com/) → API Keys |
| Credit balance | [console.anthropic.com/settings/billing](https://console.anthropic.com/settings/billing) |

---

## Step 1 — Create a Python Virtual Environment

```bash
cd GmailAssistant
python3 -m venv venv
source venv/bin/activate       # macOS / Linux
# venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

> Always activate the venv (`source venv/bin/activate`) before running the assistant.

---

## Step 2 — Create Gmail API Credentials

> **Time required: ~5 minutes.** You only do this once.

### 2a. Go to Google Cloud Console

Open [console.cloud.google.com](https://console.cloud.google.com/) and sign in.

### 2b. Create a New Project

1. Click the **project dropdown** at the top → **"New Project"**
2. Name it `gmail-assistant` → click **"Create"**
3. Select the new project from the dropdown

### 2c. Enable the Gmail API

1. Left sidebar: **"APIs & Services"** → **"Library"**
2. Search **"Gmail API"** → click result → **"Enable"**

### 2d. Configure OAuth Consent Screen

1. Left sidebar: **"APIs & Services"** → **"OAuth consent screen"**
2. Select **"External"** → **"Create"**
3. Fill required fields: App name (`Gmail Assistant`), support email, developer contact
4. Click **"Save and Continue"** through all steps
5. On the **"Test users"** step: **"+ Add Users"** → add your Gmail address → **"Save and Continue"**

### 2e. Create OAuth 2.0 Credentials

1. Left sidebar: **"APIs & Services"** → **"Credentials"**
2. **"+ Create Credentials"** → **"OAuth client ID"**
3. Application type: **"Desktop app"** → Name: `Gmail Assistant Desktop` → **"Create"**
4. Click **"Download JSON"** in the confirmation popup
5. Rename and move the file to:

```
GmailAssistant/credentials/credentials.json
```

> **Never commit this file.** It is already in `.gitignore`.

---

## Step 3 — Configure Your Anthropic API Key

1. Get your key at [console.anthropic.com](https://console.anthropic.com/) → **"API Keys"**
2. Copy the env template:
   ```bash
   cp .env.example .env
   ```
3. Edit `.env` and paste your key:
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-...
   ```

---

## Step 4a — Run via Command Line

```bash
source venv/bin/activate
python main.py
```

**First run only:** A browser window opens asking you to authorize Gmail access. Sign in
and click **"Allow"**. The token is saved to `credentials/token.json` for future runs.

**Custom instructions:**
```bash
python main.py -i "Organize my inbox with focus on work and finance. Use 6–8 labels."
python main.py -i "Archive all newsletters and mark old promos as read."
python main.py -i "Clean up my inbox — label the obvious stuff and archive processed emails."
python main.py -i "Only look at the last 30 days: in:inbox newer_than:30d"
```

**Runtime:** Typically **2–6 minutes** for a medium inbox. The agent uses up to 60
iterations and retries on rate limits automatically.

---

## Step 4b — Run via Chrome Extension (Side Panel in Gmail)

### Start the backend server

```bash
source venv/bin/activate
python server.py
```

Leave this terminal running. The server listens on `http://localhost:8000`.

### Load the extension in Chrome

1. Open `chrome://extensions`
2. Enable **Developer mode** (top-right toggle)
3. Click **"Load unpacked"**
4. Select the `extension/` folder inside this project
5. Navigate to `https://mail.google.com`
6. Click the Gmail Assistant icon in the Chrome toolbar → the side panel opens
7. Type an instruction (or pick a quick-action chip) and click **"Organize Inbox"**

The activity log streams live as the agent runs.

---

## File Structure

```
GmailAssistant/
├── main.py                    ← CLI entry point
├── server.py                  ← uvicorn launcher for Chrome extension mode
├── requirements.txt
├── .env                       ← your Anthropic API key (gitignored)
├── .env.example
├── .gitignore
├── SETUP.md
├── credentials/
│   ├── credentials.json       ← OAuth client secret (gitignored, download from Google)
│   └── token.json             ← auto-generated after first login (gitignored)
├── src/
│   ├── gmail_client.py        ← Gmail API wrapper (auth, labels, batch ops)
│   ├── tools.py               ← Tool schemas passed to Claude (12 tools)
│   ├── agent.py               ← Agentic loop (Claude + tool dispatcher + system prompt)
│   └── server.py              ← FastAPI: /status, /run, /stream (SSE)
├── extension/
│   ├── manifest.json          ← Chrome MV3 manifest
│   ├── background.js          ← Service worker (opens panel on Gmail tabs)
│   ├── panel.html             ← Side panel UI
│   ├── panel.js               ← Panel logic (SSE client, run button, log)
│   └── icons/
└── docs/
    ├── OVERVIEW.md            ← Architecture, design decisions, data flow
    ├── BACKEND.md             ← Full Python source for all backend files
    └── EXTENSION.md           ← Full Chrome extension source
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `credentials.json not found` | Download OAuth credentials (Step 2e) → save to `credentials/credentials.json` |
| `ANTHROPIC_API_KEY not set` | Create `.env` from `.env.example` and add your key |
| `credit balance too low` | Add credits at [console.anthropic.com/settings/billing](https://console.anthropic.com/settings/billing) |
| Browser doesn't open for auth | Run `python3 -c "from src.gmail_client import GmailClient; GmailClient()"` |
| "Access blocked: app's request is invalid" | Google Cloud → OAuth consent screen → Test users → add your email |
| "Token has been expired or revoked" | Delete `credentials/token.json` and re-run to re-authenticate |
| Rate limit errors (429) | The agent retries automatically with backoff. If persistent, wait a few minutes. |
| Extension shows "Offline" | Make sure `python server.py` is running in a terminal |
| Extension icon is greyed out | You must be on `https://mail.google.com` — the panel is Gmail-only |
| Labels not visible in Gmail | Refresh your Gmail tab. Labels appear in the left sidebar. |

---

## Notes

- **Re-running is safe** — existing labels are reused (never duplicated), already-labeled emails are skipped
- **One label per email** — enforced at the API layer; apply most specific labels first
- **Undo**: Gmail Settings → Labels → delete any label this tool created
- **Gmail label limit**: 500 user-created labels (the agent targets 6–14)
- **Estimated cost**: ~$0.05–$0.20 per run with `claude-sonnet-4-6` and prompt caching
