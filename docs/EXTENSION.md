# Gmail Assistant — Chrome Extension Source

Complete source for all Chrome extension files. Recreate each at the path shown.
After creating files, load the extension in Chrome via `chrome://extensions` → "Load unpacked".

## How the Extension Works

1. `background.js` (service worker) detects when the user navigates to Gmail and
   enables the side panel for that tab only
2. Clicking the extension icon opens the side panel (`panel.html`)
3. `panel.js` connects a persistent `EventSource` to `http://localhost:8000/stream`
   and polls `/status` every 5 seconds to show the connection pill
4. Clicking "Organize Inbox" POSTs to `/run` with the instruction text
5. Agent output is split by destination:
   - **Claude text responses** (`type === "text"`) → AI Response box
   - **Tool calls, results, logs** → collapsible Activity Log
   - **Completion** (`type === "done"`) → green badge in AI Response box

## UI Layout

```
┌─────────────────────────────────────────┐
│  ✉ Gmail Assistant          ● Connected │  ← sticky header
├─────────────────────────────────────────┤
│  INSTRUCTION                            │
│  ┌───────────────────────────────────┐  │
│  │ Describe how you'd like…          │  │  ← textarea
│  └───────────────────────────────────┘  │
│  [Full organize] [Dry run] [Finance] …  │  ← quick-action chips
├─────────────────────────────────────────┤
│  [ Organize Inbox ]                     │  ← primary action button
├─────────────────────────────────────────┤
│  ✦ Claude                               │  ← AI Response box
│  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
│  Analyzing ● ● ●          (while waiting)│
│  - or -                                 │
│  I've analyzed your inbox…  (text turns) │
│  ✓ Organization complete                 │  ← green badge when done
├─────────────────────────────────────────┤
│  ACTIVITY LOG   12   [Clear]   ▾        │  ← collapsible header
│  ┌───────────────────────────────────┐  │
│  │  → get_inbox_stats({})            │  │  ← dark terminal log
│  │    ✓ {"inbox_count": 312, …}      │  │
│  │  → sample_inbox({"max_results":…  │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

---

## Message Routing

| SSE `type` | Destination |
|---|---|
| `"text"` | AI Response box (accumulated, `pre-wrap`) |
| `"done"` | AI Response box (green completion badge) |
| `"tool"` | Activity Log (blue) |
| `"success"` | Activity Log (green) |
| `"error"` | Activity Log (red) + stops running state |
| `"log"` / `"header"` | Activity Log (classified by prefix) |
| `"ping"` | Ignored (keep-alive) |

Text classification for `"log"` type messages (legacy fallback):
- Lines starting with `  →` → `tool` class (blue)
- Lines starting with `     ✓` → `success` class (green)
- Lines starting with `     ✗` → `error` class (red)
- Lines containing `===` → `header` class (orange)

---

## `extension/manifest.json`

Chrome Manifest V3. Key decisions:
- `sidePanel` permission + `side_panel` declaration enables the Gmail side panel
- `host_permissions` for `localhost:8000` is required to call the local FastAPI server
- CSP: `connect-src http://localhost:8000` allows fetch to localhost; `'unsafe-inline'`
  is in `style-src` only (not `script-src`) — all JS is in the external `panel.js` file

```json
{
  "manifest_version": 3,
  "name": "Gmail Assistant",
  "version": "1.0",
  "description": "AI-powered Gmail inbox organizer — powered by Claude",

  "permissions": ["sidePanel", "tabs"],
  "host_permissions": [
    "https://mail.google.com/*",
    "http://localhost:8000/*"
  ],

  "background": {
    "service_worker": "background.js"
  },

  "side_panel": {
    "default_path": "panel.html"
  },

  "action": {
    "default_title": "Gmail Assistant",
    "default_icon": {
      "16": "icons/icon16.png",
      "32": "icons/icon32.png",
      "48": "icons/icon48.png",
      "128": "icons/icon128.png"
    }
  },

  "content_security_policy": {
    "extension_pages": "default-src 'self'; connect-src http://localhost:8000; style-src 'self' 'unsafe-inline'"
  }
}
```

---

## `extension/background.js`

Service worker. Enables the side panel only on Gmail tabs, and opens it when the
extension icon is clicked.

```javascript
// Enable the side panel only when the user is on Gmail
chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (!tab.url) return;
  const onGmail = tab.url.startsWith("https://mail.google.com");
  await chrome.sidePanel.setOptions({
    tabId,
    path: "panel.html",
    enabled: onGmail,
  });
});

// Open the side panel when the extension icon is clicked
chrome.action.onClicked.addListener(async (tab) => {
  await chrome.sidePanel.open({ tabId: tab.id });
});
```

---

## `extension/panel.html`

Side panel UI. Google-style light theme with a dark terminal log at the bottom.
No inline scripts (MV3 CSP requirement) — all JS is in `panel.js`.

Design tokens (CSS custom properties):
- `--blue: #1a73e8` — primary actions, AI box accent
- `--green: #188038` — connected status, success lines, completion badge
- `--red: #d93025` — offline/error states
- `--gray-*` — surface, border, and text hierarchy

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Gmail Assistant</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --blue:         #1a73e8;
      --blue-dark:    #1557b0;
      --blue-light:   #e8f0fe;
      --green:        #188038;
      --green-light:  #e6f4ea;
      --red:          #d93025;
      --red-light:    #fce8e6;
      --gray-50:      #f8f9fa;
      --gray-100:     #f1f3f4;
      --gray-200:     #e8eaed;
      --gray-300:     #dadce0;
      --gray-500:     #9aa0a6;
      --gray-600:     #80868b;
      --gray-700:     #5f6368;
      --black:        #202124;
      --radius:       10px;
    }

    body {
      font-family: 'Google Sans', Roboto, system-ui, -apple-system, sans-serif;
      background: var(--gray-50);
      color: var(--black);
      font-size: 14px;
      line-height: 1.5;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }

    /* ─── Header ─────────────────────────────────────────────────── */
    .header {
      background: #fff;
      height: 56px;
      padding: 0 16px;
      border-bottom: 1px solid var(--gray-200);
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 10;
      flex-shrink: 0;
    }
    .brand { display: flex; align-items: center; gap: 9px; }
    .brand-logo { width: 26px; height: 26px; flex-shrink: 0; }
    .brand-name {
      font-size: 15.5px;
      color: var(--gray-700);
      font-weight: 400;
      letter-spacing: -0.2px;
      line-height: 1;
    }
    .brand-name strong { color: var(--black); font-weight: 500; }
    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 4px 10px;
      border-radius: 12px;
      background: var(--gray-100);
      font-size: 11.5px;
      color: var(--gray-700);
      white-space: nowrap;
    }
    .status-dot {
      width: 6px; height: 6px;
      border-radius: 50%;
      background: var(--gray-300);
      flex-shrink: 0;
      transition: background 0.3s;
    }
    .status-dot.connected { background: var(--green); }
    .status-dot.error     { background: var(--red); }

    /* ─── Main scroll area ───────────────────────────────────────── */
    .main {
      flex: 1;
      padding: 12px 12px 24px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    /* ─── Offline banner ─────────────────────────────────────────── */
    .offline-banner {
      background: var(--red-light);
      color: var(--red);
      border-radius: 8px;
      padding: 10px 13px;
      font-size: 12.5px;
      line-height: 1.55;
    }
    .offline-banner strong { font-weight: 600; }
    .offline-banner code {
      background: rgba(217,48,37,.1);
      border-radius: 3px;
      padding: 1px 5px;
      font-family: 'Roboto Mono', ui-monospace, monospace;
      font-size: 11.5px;
    }
    .hidden { display: none !important; }

    /* ─── Instruction card ───────────────────────────────────────── */
    .card {
      background: #fff;
      border: 1px solid var(--gray-200);
      border-radius: var(--radius);
      padding: 13px;
    }
    .card-label {
      font-size: 10.5px;
      font-weight: 600;
      color: var(--gray-600);
      text-transform: uppercase;
      letter-spacing: 0.8px;
      margin-bottom: 8px;
    }
    textarea {
      width: 100%;
      border: 1.5px solid var(--gray-300);
      border-radius: 6px;
      padding: 8px 11px;
      font-size: 13px;
      font-family: inherit;
      color: var(--black);
      resize: vertical;
      min-height: 72px;
      outline: none;
      line-height: 1.55;
      transition: border-color 0.2s, box-shadow 0.2s;
      background: #fff;
    }
    textarea:focus {
      border-color: var(--blue);
      box-shadow: 0 0 0 3px rgba(26,115,232,.1);
    }
    textarea::placeholder { color: var(--gray-500); }

    /* ─── Chips ──────────────────────────────────────────────────── */
    .chips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 9px; }
    .chip {
      border: 1.5px solid var(--gray-300);
      background: #fff;
      color: var(--blue);
      border-radius: 14px;
      padding: 3px 10px;
      font-size: 11.5px;
      font-family: inherit;
      cursor: pointer;
      line-height: 1.5;
      white-space: nowrap;
      transition: background 0.15s, border-color 0.15s;
    }
    .chip:hover { background: var(--blue-light); border-color: var(--blue); }

    /* ─── Run button ─────────────────────────────────────────────── */
    .run-btn {
      width: 100%;
      padding: 10px 16px;
      background: var(--blue);
      color: #fff;
      border: none;
      border-radius: 8px;
      font-size: 13.5px;
      font-weight: 500;
      font-family: inherit;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      letter-spacing: 0.15px;
      transition: background 0.15s, box-shadow 0.15s;
      flex-shrink: 0;
    }
    .run-btn:hover:not(:disabled) {
      background: var(--blue-dark);
      box-shadow: 0 1px 4px rgba(26,115,232,.35);
    }
    .run-btn:disabled { background: var(--gray-300); cursor: not-allowed; }
    .spinner {
      width: 14px; height: 14px;
      border: 2px solid rgba(255,255,255,.35);
      border-top-color: #fff;
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
      flex-shrink: 0;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* ─── AI Response box ────────────────────────────────────────── */
    .ai-box {
      background: #fff;
      border: 1px solid var(--gray-200);
      border-radius: var(--radius);
      overflow: hidden;
    }
    .ai-box-header {
      display: flex;
      align-items: center;
      gap: 7px;
      padding: 9px 13px;
      border-bottom: 1px solid var(--gray-100);
      background: #fafbff;
    }
    .ai-sparkle { font-size: 13px; color: var(--blue); line-height: 1; }
    .ai-box-title { font-size: 11.5px; font-weight: 600; color: var(--blue); letter-spacing: 0.1px; }
    .ai-box-body {
      padding: 12px 13px;
      max-height: 260px;
      overflow-y: auto;
    }
    .ai-box-body::-webkit-scrollbar { width: 4px; }
    .ai-box-body::-webkit-scrollbar-track { background: transparent; }
    .ai-box-body::-webkit-scrollbar-thumb { background: var(--gray-300); border-radius: 2px; }

    /* Thinking dots */
    .ai-thinking {
      display: flex;
      align-items: center;
      gap: 7px;
      color: var(--gray-600);
      font-size: 12.5px;
      padding: 2px 0;
    }
    .dots { display: flex; gap: 3px; align-items: center; }
    .dots span {
      width: 5px; height: 5px;
      border-radius: 50%;
      background: var(--gray-500);
      animation: dotpulse 1.3s ease-in-out infinite;
    }
    .dots span:nth-child(2) { animation-delay: 0.18s; }
    .dots span:nth-child(3) { animation-delay: 0.36s; }
    @keyframes dotpulse {
      0%, 80%, 100% { opacity: 0.25; transform: scale(0.85); }
      40%            { opacity: 1;    transform: scale(1); }
    }

    /* AI text content */
    .ai-turn {
      font-size: 13px;
      line-height: 1.65;
      color: var(--black);
      white-space: pre-wrap;
      word-break: break-word;
    }
    .ai-turn + .ai-turn {
      margin-top: 11px;
      padding-top: 11px;
      border-top: 1px solid var(--gray-100);
    }
    .ai-done {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-top: 12px;
      padding: 8px 11px;
      background: var(--green-light);
      color: var(--green);
      border-radius: 6px;
      font-size: 12.5px;
      font-weight: 500;
    }

    /* ─── Log section ────────────────────────────────────────────── */
    .log-section { border: 1px solid #3a3a50; border-radius: var(--radius); overflow: hidden; }
    .log-header {
      background: #2a2a3e;
      padding: 8px 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
      user-select: none;
    }
    .log-header:hover { background: #31314a; }
    .log-header-left { display: flex; align-items: center; gap: 7px; }
    .log-title {
      font-size: 10.5px;
      font-weight: 600;
      color: #a0a8c0;
      text-transform: uppercase;
      letter-spacing: 0.8px;
    }
    .log-badge {
      font-size: 10px;
      background: #3a3a56;
      color: #7a82a0;
      padding: 1px 6px;
      border-radius: 8px;
      font-family: ui-monospace, monospace;
      line-height: 1.6;
    }
    .log-header-right { display: flex; align-items: center; gap: 8px; }
    .clear-btn {
      font-size: 11px;
      color: #6b6f8a;
      background: none;
      border: none;
      cursor: pointer;
      font-family: inherit;
      padding: 2px 4px;
      border-radius: 3px;
      transition: color 0.15s;
    }
    .clear-btn:hover { color: #cdd6f4; }
    .chevron {
      color: #6b6f8a;
      font-size: 11px;
      line-height: 1;
      display: inline-block;
      transition: transform 0.22s ease;
    }
    .chevron.collapsed { transform: rotate(-90deg); }
    .log-body {
      background: #1e1e2e;
      padding: 9px 12px;
      font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', ui-monospace, monospace;
      font-size: 11.5px;
      max-height: 260px;
      overflow-y: auto;
      overflow-x: hidden;
      line-height: 1.6;
      transition: max-height 0.22s ease, padding 0.22s ease;
    }
    .log-body.is-collapsed { max-height: 0; padding-top: 0; padding-bottom: 0; }
    .log-body::-webkit-scrollbar { width: 4px; }
    .log-body::-webkit-scrollbar-track { background: transparent; }
    .log-body::-webkit-scrollbar-thumb { background: #45475a; border-radius: 2px; }

    .line { color: #cdd6f4; word-break: break-all; white-space: pre-wrap; }
    .line.tool    { color: #89b4fa; }
    .line.success { color: #a6e3a1; }
    .line.error   { color: #f38ba8; }
    .line.header  { color: #fab387; }
    .line.empty   { height: 3px; }
  </style>
</head>
<body>

  <header class="header">
    <div class="brand">
      <svg class="brand-logo" viewBox="0 0 26 26" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect width="26" height="26" rx="6" fill="#fff" stroke="#e8eaed" stroke-width="1.2"/>
        <rect x="3.5" y="6.5" width="19" height="13" rx="1.5" stroke="#5f6368" stroke-width="1.2" fill="none"/>
        <path d="M3.5 8.5L13 14.5L22.5 8.5" stroke="#EA4335" stroke-width="1.4" stroke-linejoin="round" fill="none"/>
      </svg>
      <span class="brand-name">Gmail <strong>Assistant</strong></span>
    </div>
    <div class="status-pill">
      <span class="status-dot" id="statusDot"></span>
      <span id="statusText">Checking…</span>
    </div>
  </header>

  <main class="main">

    <div class="offline-banner hidden" id="offlineBanner">
      <strong>Server offline.</strong> Start it with:<br>
      <code>python server.py</code>
    </div>

    <div class="card">
      <div class="card-label">Instruction</div>
      <textarea id="instruction" placeholder="Describe how you'd like your inbox organized…" rows="3"></textarea>
      <div class="chips">
        <button class="chip" data-text="Analyze my inbox and organize it with smart, meaningful labels. Be comprehensive and aim to label at least 75% of my emails.">Full organize</button>
        <button class="chip" data-text="Sample my inbox (max 50 emails) and create just 3 labels. Do not apply any labels yet — only report what you would do.">Dry run</button>
        <button class="chip" data-text="Create a Newsletters label and archive all newsletter and subscription emails. Keep everything else untouched.">Newsletters</button>
        <button class="chip" data-text="Create a Finance label for receipts, invoices, bank statements, and payment confirmations. Keep them in inbox.">Finance</button>
        <button class="chip" data-text="Look at emails from the last 30 days only: in:inbox newer_than:30d. Organize with 5 simple labels.">Last 30 days</button>
      </div>
    </div>

    <button class="run-btn" id="runBtn" disabled>
      <span class="spinner hidden" id="spinner"></span>
      <span id="btnText">Organize Inbox</span>
    </button>

    <!-- AI Response box (hidden until content arrives) -->
    <div class="ai-box hidden" id="aiBox">
      <div class="ai-box-header">
        <span class="ai-sparkle">✦</span>
        <span class="ai-box-title">Claude</span>
      </div>
      <div class="ai-box-body">
        <div id="aiThinking" class="ai-thinking hidden">
          Analyzing
          <span class="dots"><span></span><span></span><span></span></span>
        </div>
        <div id="aiContent" class="ai-content"></div>
      </div>
    </div>

    <!-- Activity Log (collapsible, hidden until content arrives) -->
    <div class="log-section hidden" id="logSection">
      <div class="log-header" id="logToggle">
        <div class="log-header-left">
          <span class="log-title">Activity Log</span>
          <span class="log-badge" id="logBadge">0</span>
        </div>
        <div class="log-header-right">
          <button class="clear-btn" id="clearBtn">Clear</button>
          <span class="chevron" id="chevron">▾</span>
        </div>
      </div>
      <div class="log-body" id="logBody"></div>
    </div>

  </main>

  <script src="panel.js"></script>
</body>
</html>
```

---

## `extension/panel.js`

All panel interactivity. Extracted into a separate file (MV3 CSP requires no inline scripts).

Key behaviors:
- `type === "text"` messages accumulate in the AI box, grouped into turn blocks separated by `border-top` dividers
- `endAITurn()` is called when tool calls arrive, so the next text creates a visually distinct block
- The Activity Log shows only on first log line and supports click-to-collapse via max-height CSS transition
- `type === "done"` renders a green completion badge in the AI box
- The run button resets both boxes on every new run

```javascript
const SERVER = "http://localhost:8000";

// ── DOM refs ──────────────────────────────────────────────────────────────
const statusDot     = document.getElementById("statusDot");
const statusText    = document.getElementById("statusText");
const offlineBanner = document.getElementById("offlineBanner");
const instructionEl = document.getElementById("instruction");
const runBtn        = document.getElementById("runBtn");
const spinner       = document.getElementById("spinner");
const btnText       = document.getElementById("btnText");

const aiBox         = document.getElementById("aiBox");
const aiThinking    = document.getElementById("aiThinking");
const aiContent     = document.getElementById("aiContent");

const logSection    = document.getElementById("logSection");
const logToggle     = document.getElementById("logToggle");
const logBody       = document.getElementById("logBody");
const logBadge      = document.getElementById("logBadge");
const chevron       = document.getElementById("chevron");
const clearBtn      = document.getElementById("clearBtn");

// ── State ─────────────────────────────────────────────────────────────────
let isRunning    = false;
let serverOnline = false;
let eventSource  = null;
let logLineCount = 0;
let logsExpanded = true;
let aiTurnEl     = null;   // current <div.ai-turn> receiving text
let hasAIText    = false;  // whether any text has arrived this run

// ── Status ────────────────────────────────────────────────────────────────
function setOnline(online) {
  serverOnline = online;
  statusDot.className = "status-dot " + (online ? "connected" : "error");
  statusText.textContent = online ? "Connected" : "Offline";
  offlineBanner.classList.toggle("hidden", online);
  runBtn.disabled = !online || isRunning;
}

async function checkStatus() {
  try {
    const res = await fetch(`${SERVER}/status`, { signal: AbortSignal.timeout(2000) });
    const data = await res.json();
    setOnline(true);
    if (data.running && !isRunning) setRunningState(true);
  } catch {
    setOnline(false);
  }
}

// ── Running state ──────────────────────────────────────────────────────────
function setRunningState(running) {
  isRunning = running;
  runBtn.disabled = running || !serverOnline;
  spinner.classList.toggle("hidden", !running);
  btnText.textContent = running ? "Running…" : "Organize Inbox";
}

// ── AI Response box ────────────────────────────────────────────────────────
function appendAIText(text) {
  aiBox.classList.remove("hidden");
  if (!hasAIText) {
    aiThinking.classList.add("hidden");
    hasAIText = true;
  }

  // Empty lines create paragraph breaks within the current turn
  if (text.trim() === "") {
    if (aiTurnEl && aiTurnEl.textContent) aiTurnEl.textContent += "\n";
    return;
  }

  // Start a new turn block if needed (after tool calls, or at the start)
  if (!aiTurnEl) {
    aiTurnEl = document.createElement("div");
    aiTurnEl.className = "ai-turn";
    aiContent.appendChild(aiTurnEl);
  }

  aiTurnEl.textContent += (aiTurnEl.textContent ? "\n" : "") + text;
  aiContent.parentElement.scrollTop = aiContent.parentElement.scrollHeight;
}

function endAITurn() {
  // Called when tool calls arrive; forces next text into a new visual block
  aiTurnEl = null;
}

function appendAIDone() {
  endAITurn();
  aiBox.classList.remove("hidden");
  aiThinking.classList.add("hidden");
  const el = document.createElement("div");
  el.className = "ai-done";
  el.textContent = "✓  Organization complete";
  aiContent.appendChild(el);
  aiContent.parentElement.scrollTop = aiContent.parentElement.scrollHeight;
}

// ── Activity Log ───────────────────────────────────────────────────────────
function classifyText(text) {
  if (text.startsWith("  →"))    return "tool";
  if (text.startsWith("     ✓")) return "success";
  if (text.startsWith("     ✗")) return "error";
  if (text.includes("==="))      return "header";
  return "log";
}

function appendLog(text, type) {
  logSection.classList.remove("hidden");
  const el = document.createElement("div");
  if (text.trim() === "") {
    el.className = "line empty";
  } else {
    el.className = "line " + (type || "log");
    el.textContent = text;
    logLineCount++;
    logBadge.textContent = logLineCount;
  }
  logBody.appendChild(el);
  logBody.scrollTop = logBody.scrollHeight;
}

// ── Log collapse toggle ────────────────────────────────────────────────────
logToggle.addEventListener("click", (e) => {
  if (e.target === clearBtn) return; // don't collapse when clicking Clear
  logsExpanded = !logsExpanded;
  logBody.classList.toggle("is-collapsed", !logsExpanded);
  chevron.classList.toggle("collapsed", !logsExpanded);
});

// ── SSE stream ─────────────────────────────────────────────────────────────
function connectStream() {
  if (eventSource) { eventSource.close(); eventSource = null; }
  eventSource = new EventSource(`${SERVER}/stream`);

  eventSource.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "ping") return;

    if (msg.type === "done") {
      appendAIDone();
      setRunningState(false);
      return;
    }
    if (msg.type === "text") {
      appendAIText(msg.text);
      return;
    }

    // tool / success / error / log / header → Activity Log
    endAITurn();
    if (msg.type === "error") {
      appendLog(msg.text, "error");
      aiThinking.classList.add("hidden");
      setRunningState(false);
      return;
    }
    appendLog(msg.text, msg.type === "log" ? classifyText(msg.text) : msg.type);
  };

  eventSource.onerror = () => {
    setOnline(false);
    if (eventSource) { eventSource.close(); eventSource = null; }
    setTimeout(connectStream, 3000);
  };
}

// ── Run ────────────────────────────────────────────────────────────────────
runBtn.addEventListener("click", async () => {
  const inst = instructionEl.value.trim() ||
    "Analyze my inbox and organize it with smart, meaningful labels. Be comprehensive and aim to label at least 75% of my emails.";

  // Reset both boxes
  aiContent.innerHTML = "";
  logBody.innerHTML = "";
  logLineCount = 0;
  logBadge.textContent = "0";
  aiTurnEl = null;
  hasAIText = false;
  logsExpanded = true;
  logBody.classList.remove("is-collapsed");
  chevron.classList.remove("collapsed");
  logSection.classList.add("hidden");

  // Show AI box with thinking indicator
  aiBox.classList.remove("hidden");
  aiThinking.classList.remove("hidden");

  setRunningState(true);

  try {
    const res = await fetch(`${SERVER}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction: inst }),
    });
    const data = await res.json();
    if (data.error) {
      appendLog(data.error, "error");
      aiThinking.classList.add("hidden");
      setRunningState(false);
    }
  } catch {
    appendLog("Could not reach server. Is it running?", "error");
    aiThinking.classList.add("hidden");
    setRunningState(false);
    setOnline(false);
  }
});

// ── Chips ──────────────────────────────────────────────────────────────────
document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    instructionEl.value = chip.dataset.text;
    instructionEl.focus();
  });
});

// ── Clear ──────────────────────────────────────────────────────────────────
clearBtn.addEventListener("click", (e) => {
  e.stopPropagation(); // prevent toggling collapse
  logBody.innerHTML = "";
  logLineCount = 0;
  logBadge.textContent = "0";
});

// ── Init ───────────────────────────────────────────────────────────────────
checkStatus();
connectStream();
setInterval(checkStatus, 5000);
```

---

## Icons

The extension requires four icon sizes at these paths:

```
extension/icons/icon16.png    (16×16 px)
extension/icons/icon32.png    (32×32 px)
extension/icons/icon48.png    (48×48 px)
extension/icons/icon128.png   (128×128 px)
```

---

## Loading in Chrome

1. Open `chrome://extensions`
2. Enable **Developer mode** (top-right toggle)
3. Click **"Load unpacked"**
4. Select the `extension/` folder inside this project
5. Navigate to `https://mail.google.com` and click the extension icon
