const SERVER = "http://localhost:8000";

// ── DOM refs ────────────────────────────────────────────────────────────────
const statusDot     = document.getElementById("statusDot");
const statusText    = document.getElementById("statusText");
const offlineBanner = document.getElementById("offlineBanner");
const instructionEl = document.getElementById("instruction");
const runBtn        = document.getElementById("runBtn");
const spinner       = document.getElementById("spinner");
const btnText       = document.getElementById("btnText");

const aiBox         = document.getElementById("aiBox");
const aiSparkle     = document.getElementById("aiSparkle");
const aiBoxTitle    = document.getElementById("aiBoxTitle");
const aiThinking    = document.getElementById("aiThinking");
const aiContent     = document.getElementById("aiContent");

const logSection    = document.getElementById("logSection");
const logToggle     = document.getElementById("logToggle");
const logBody       = document.getElementById("logBody");
const logBadge      = document.getElementById("logBadge");
const chevron       = document.getElementById("chevron");
const clearBtn      = document.getElementById("clearBtn");

const btnClaude     = document.getElementById("btnClaude");
const btnGemini     = document.getElementById("btnGemini");

// ── State ───────────────────────────────────────────────────────────────────
let isRunning    = false;
let serverOnline = false;
let eventSource  = null;
let logLineCount = 0;
let logsExpanded = true;
let aiTurnEl     = null;   // current <div.ai-turn> receiving text
let hasAIText    = false;  // whether any text has arrived this run
let selectedModel = "claude";  // "claude" or "gemini"

// ── Status ──────────────────────────────────────────────────────────────────
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

// ── Model selector ───────────────────────────────────────────────────────────
const MODEL_META = {
  claude: { icon: "✦", title: "Claude Sonnet" },
  gemini: { icon: "◈", title: "Gemini Flash"  },
};

function selectModel(model) {
  selectedModel = model;
  btnClaude.classList.toggle("active", model === "claude");
  btnGemini.classList.toggle("active", model === "gemini");
  const meta = MODEL_META[model];
  aiSparkle.textContent  = meta.icon;
  aiBoxTitle.textContent = meta.title;
}

btnClaude.addEventListener("click", () => selectModel("claude"));
btnGemini.addEventListener("click", () => selectModel("gemini"));

// ── Running state ────────────────────────────────────────────────────────────
function setRunningState(running) {
  isRunning = running;
  runBtn.disabled = running || !serverOnline;
  spinner.classList.toggle("hidden", !running);
  btnText.textContent = running ? "Running…" : "Organize Inbox";
}

// ── AI Response box ──────────────────────────────────────────────────────────
function appendAIText(text) {
  // Show the box and hide the thinking indicator on first text
  aiBox.classList.remove("hidden");
  if (!hasAIText) {
    aiThinking.classList.add("hidden");
    hasAIText = true;
  }

  // Empty lines create a visual break within the current turn
  if (text.trim() === "") {
    if (aiTurnEl && aiTurnEl.textContent) {
      aiTurnEl.textContent += "\n";
    }
    return;
  }

  // Start a new turn block if needed
  if (!aiTurnEl) {
    aiTurnEl = document.createElement("div");
    aiTurnEl.className = "ai-turn";
    aiContent.appendChild(aiTurnEl);
  }

  aiTurnEl.textContent += (aiTurnEl.textContent ? "\n" : "") + text;
  aiContent.parentElement.scrollTop = aiContent.parentElement.scrollHeight;
}

function endAITurn() {
  // Signal that Claude has finished a text block (tool calls are next)
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

// ── Activity Log ─────────────────────────────────────────────────────────────
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

// ── Log collapse toggle ───────────────────────────────────────────────────────
logToggle.addEventListener("click", (e) => {
  // Don't collapse when clicking the Clear button
  if (e.target === clearBtn) return;

  logsExpanded = !logsExpanded;
  logBody.classList.toggle("is-collapsed", !logsExpanded);
  chevron.classList.toggle("collapsed", !logsExpanded);
});

// ── SSE stream ───────────────────────────────────────────────────────────────
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

    // All other types (tool, success, error, log, header) → Activity Log
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

// ── Run ──────────────────────────────────────────────────────────────────────
runBtn.addEventListener("click", async () => {
  const inst = instructionEl.value.trim() ||
    "Analyze my inbox and organize it with smart, meaningful labels. Be comprehensive and aim to label at least 75% of my emails.";

  // Reset state
  aiContent.innerHTML = "";
  logBody.innerHTML = "";
  logLineCount = 0;
  logBadge.textContent = "0";
  aiTurnEl = null;
  hasAIText = false;
  logsExpanded = true;
  logBody.classList.remove("is-collapsed");
  chevron.classList.remove("collapsed");

  // Show AI box with thinking indicator
  aiBox.classList.remove("hidden");
  aiThinking.classList.remove("hidden");
  logSection.classList.add("hidden");

  setRunningState(true);

  try {
    const res = await fetch(`${SERVER}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction: inst, model: selectedModel }),
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

// ── Chips ────────────────────────────────────────────────────────────────────
document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    instructionEl.value = chip.dataset.text;
    instructionEl.focus();
  });
});

// ── Clear ────────────────────────────────────────────────────────────────────
clearBtn.addEventListener("click", (e) => {
  e.stopPropagation(); // prevent collapsing the log section
  logBody.innerHTML = "";
  logLineCount = 0;
  logBadge.textContent = "0";
});

// ── Init ─────────────────────────────────────────────────────────────────────
checkStatus();
connectStream();
setInterval(checkStatus, 5000);
