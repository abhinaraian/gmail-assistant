# Gmail Assistant

An AI agent that organizes your Gmail inbox. Powered by Claude (`claude-sonnet-4-6`), it samples your emails, designs a label taxonomy, applies labels in bulk, archives noise, marks old unread mail as read, and trashes clear junk — all from a natural-language instruction.

Runs as a **Chrome side panel** inside Gmail, or as a **CLI script**.

---

## How it works

1. You describe what you want: *"Clean up my inbox and label everything by category"*
2. Claude analyzes up to 500 emails and designs a plan
3. It creates labels, applies them (one per email), archives, marks read, and trashes — then reports back

Each email gets **at most one label**. Labels with fewer than 5 emails are automatically pruned.

---

## Requirements

- Python 3.9+
- Docker (optional, for the containerized path)
- A Gmail account
- An [Anthropic API key](https://console.anthropic.com/) with credits
- Google Cloud OAuth credentials (see [Setup](#setup))

---

## Quickstart

### Option A — Local (no Docker)

```bash
# 1. Clone and set up
git clone https://github.com/YOUR_USERNAME/gmail-assistant.git
cd gmail-assistant
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Add your Anthropic key
cp .env.example .env
# edit .env → ANTHROPIC_API_KEY=sk-ant-...

# 3. Add Gmail credentials  (see Setup section below)
# → credentials/credentials.json

# 4. Run
python main.py
```

First run opens a browser to authorize Gmail. After that, the token is cached.

---

### Option B — Docker

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/gmail-assistant.git
cd gmail-assistant

# 2. Add your Anthropic key
cp .env.example .env
# edit .env → ANTHROPIC_API_KEY=sk-ant-...

# 3. Add Gmail credentials  (see Setup section below)
# → credentials/credentials.json

# 4. First-run: authorize Gmail (copy-paste flow in terminal)
docker-compose run --rm gmail-assistant python main.py

# 5. Start the server
docker-compose up -d
```

---

## Setup

### Gmail credentials (~5 min, one time)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create a project
2. **APIs & Services → Library** → search *Gmail API* → Enable
3. **APIs & Services → OAuth consent screen** → External → fill in app name + your email → add your email as a test user
4. **APIs & Services → Credentials** → Create Credentials → OAuth client ID → Desktop app → Download JSON
5. Rename the file to `credentials.json` and place it at:

```
gmail-assistant/credentials/credentials.json
```

> This file is gitignored and never shared.

Full walkthrough: [SETUP.md](SETUP.md)

---

## Chrome Extension

The extension adds a side panel to Gmail so you don't need a terminal.

**Start the backend first:**
```bash
# Local
source venv/bin/activate && python server.py

# Docker
docker-compose up -d
```

**Load the extension:**
1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** → select the `extension/` folder
4. Open [Gmail](https://mail.google.com), click the extension icon

The side panel opens inside Gmail. Type an instruction or pick a quick-action chip, then click **Organize Inbox**.

---

## CLI Usage

```bash
# Default: full organization
python main.py

# Custom instruction
python main.py -i "Archive all newsletters and label finance emails"
python main.py -i "Clean up the last 30 days only: in:inbox newer_than:30d"
python main.py -i "Dry run — sample 50 emails and describe what you'd do, don't apply anything"
```

---

## Project Structure

```
gmail-assistant/
├── main.py               # CLI entry point
├── server.py             # Backend server launcher (for Chrome extension)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── credentials/
│   ├── credentials.json  # ← you provide this (gitignored)
│   └── token.json        # ← auto-generated after first auth (gitignored)
├── src/
│   ├── agent.py          # Agentic loop + Claude tool dispatcher
│   ├── gmail_client.py   # Gmail API wrapper
│   ├── tools.py          # Tool schemas for Claude
│   └── server.py         # FastAPI: /status /run /stream
├── extension/
│   ├── manifest.json
│   ├── panel.html / panel.js
│   └── background.js
└── docs/
    ├── OVERVIEW.md       # Architecture and design decisions
    ├── BACKEND.md        # Full Python source reference
    └── EXTENSION.md      # Full extension source reference
```

---

## Sharing with a friend

Each person needs their own Gmail credentials and Anthropic key — the agent runs against their own inbox.

1. They clone the repo
2. They follow the [Setup](#setup) steps above to get their own `credentials.json`
3. They add their own `ANTHROPIC_API_KEY` to `.env`
4. They run via Docker or locally

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `credentials.json not found` | Complete the Gmail setup steps above |
| `ANTHROPIC_API_KEY not set` | Create `.env` from `.env.example` and add your key |
| Credit balance too low | Add credits at [console.anthropic.com/settings/billing](https://console.anthropic.com/settings/billing) |
| "Access blocked" on OAuth screen | OAuth consent screen → Test users → add your email |
| Token expired | Delete `credentials/token.json` and re-run |
| Extension shows "Offline" | Make sure `python server.py` (or `docker-compose up`) is running |
| Extension icon greyed out | Must be on `https://mail.google.com` |
