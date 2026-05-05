const state = {
  sessionId: "",
  datasets: [],
  currentDataset: "",
  uploadedDatasets: [],
  sending: false,
};

const chatLog = document.getElementById("chat-log");
const datasetSelect = document.getElementById("dataset-select");
const datasetSelectDisplay = document.getElementById("dataset-select-display");
const sessionList = document.getElementById("session-list");
const composer = document.getElementById("composer");
const questionInput = document.getElementById("question-input");
const sendButton = document.getElementById("send-button");
const uploadInput = document.getElementById("upload-input");
const newSessionButton = document.getElementById("new-session-button");
const sidebarToggle = document.getElementById("sidebar-toggle");
const sidebarToggleIcon = sidebarToggle.querySelector(".sidebar-toggle-icon");
const datasetMenuButton = document.getElementById("dataset-menu-button");
const datasetMenu = document.getElementById("dataset-menu");
const deleteDatasetButton = document.getElementById("delete-dataset-button");
const messageTemplate = document.getElementById("message-template");
const SESSION_STORAGE_KEY = "csv-agent-sessions-v1";

state.sessions = [];
state.currentSessionId = "";
state.sidebarOpen = true;
state.openSessionMenuId = "";
state.datasetMenuOpen = false;

function setSending(isSending) {
  state.sending = isSending;
  sendButton.disabled = isSending;
  questionInput.disabled = isSending;
  datasetSelect.disabled = isSending;
  uploadInput.disabled = isSending;
  newSessionButton.disabled = isSending;
  datasetMenuButton.disabled = isSending;
  syncDatasetControls();
}

function toggleDatasetMenu(forceOpen = null) {
  state.datasetMenuOpen = forceOpen === null ? !state.datasetMenuOpen : forceOpen;
  datasetMenu.classList.toggle("open", state.datasetMenuOpen);
}

function syncSidebarToggle() {
  const nextActionLabel = state.sidebarOpen ? "Close sidebar" : "Open sidebar";
  sidebarToggle.setAttribute("aria-label", nextActionLabel);
  sidebarToggle.title = nextActionLabel;
  sidebarToggleIcon.textContent = state.sidebarOpen ? "←" : "→";
}

function canDeleteCurrentDataset() {
  if (!state.currentDataset) {
    return false;
  }
  return state.uploadedDatasets.includes(state.currentDataset);
}

function syncDatasetControls() {
  datasetSelect.value = state.currentDataset;
  datasetSelect.title = state.currentDataset || "";
  datasetSelectDisplay.textContent = state.currentDataset || "Choose a dataset";
  datasetSelectDisplay.title = state.currentDataset || "";
  deleteDatasetButton.disabled = state.sending || !canDeleteCurrentDataset();
}

function appendMessage(role, contentNode) {
  const emptyState = chatLog.querySelector(".empty-state");
  if (emptyState) {
    emptyState.remove();
  }

  const fragment = messageTemplate.content.cloneNode(true);
  const article = fragment.querySelector(".message");
  const roleNode = fragment.querySelector(".message-role");
  const bodyNode = fragment.querySelector(".message-body");

  article.classList.add(role);
  roleNode.textContent = role === "user" ? "You" : "Agent";
  bodyNode.appendChild(contentNode);

  chatLog.appendChild(fragment);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function currentSession() {
  return state.sessions.find((session) => session.id === state.currentSessionId) || null;
}

function findSession(sessionId) {
  return state.sessions.find((session) => session.id === sessionId) || null;
}

function serializeSessions() {
  return state.sessions.map((session) => ({
    id: session.id,
    dataset: session.dataset,
    customTitle: session.customTitle || "",
    messages: session.messages
      .filter((message) => !message.pending)
      .map((message) => ({
        role: message.role,
        text: String(message.text || ""),
        visualizationHtml: message.visualizationHtml || "",
      })),
  }));
}

function persistSessions() {
  try {
    window.localStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({
        sessions: serializeSessions(),
      })
    );
  } catch (error) {
    // Local storage is best-effort; the app can still run without persistence.
  }
}

function loadStoredSessions() {
  try {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) {
      return [];
    }

    const payload = JSON.parse(raw);
    const sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
    return sessions
      .filter((session) => session?.id && session?.dataset)
      .map((session) => ({
        id: String(session.id),
        dataset: String(session.dataset),
        customTitle: String(session.customTitle || ""),
        messages: Array.isArray(session.messages)
          ? session.messages
              .filter((message) => message?.role === "user" || message?.role === "agent")
              .map((message) => ({
                role: message.role,
                text: String(message.text || ""),
                visualizationHtml: String(message.visualizationHtml || ""),
                pending: false,
              }))
          : [],
      }));
  } catch (error) {
    return [];
  }
}

function sessionLabel(session, index) {
  if (session.customTitle) {
    return session.customTitle;
  }
  const firstUserMessage = session.messages.find((message) => message.role === "user");
  if (firstUserMessage?.text) {
    return firstUserMessage.text;
  }
  return `Session ${index + 1}`;
}

function addSessionMessage(sessionId, role, text, visualizationHtml = "", options = {}) {
  const session = findSession(sessionId);
  if (!session) {
    return;
  }

  session.messages.push({
    role,
    text: String(text || ""),
    visualizationHtml,
    pending: Boolean(options.pending),
  });
  persistSessions();
  renderSessionList();
}

function removeSessionPendingMessage(sessionId) {
  const session = findSession(sessionId);
  if (!session) {
    return;
  }

  const pendingIndex = session.messages.findIndex((message) => message.pending);
  if (pendingIndex >= 0) {
    session.messages.splice(pendingIndex, 1);
    persistSessions();
  }
}

function renderSessionList() {
  sessionList.innerHTML = "";

  if (state.sessions.length === 0) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "No sessions yet.";
    sessionList.appendChild(empty);
    return;
  }

  state.sessions.forEach((session, index) => {
    const row = document.createElement("div");
    row.className = `session-item ${session.id === state.currentSessionId ? "active" : ""}`;
    const menuOpen = state.openSessionMenuId === session.id;
    row.innerHTML = `
      <button type="button" class="session-main">
        <span class="history-role">${escapeHtml(session.dataset || "Dataset")}</span>
        <span class="history-text">${escapeHtml(sessionLabel(session, index))}</span>
      </button>
      <div class="session-actions">
        <button type="button" class="session-menu-button" aria-label="Session actions" title="Session actions">⋯</button>
        <div class="session-menu ${menuOpen ? "open" : ""}">
          <button type="button" class="session-menu-item rename-session">Rename session</button>
          <button type="button" class="session-menu-item delete-session danger">Delete</button>
        </div>
      </div>
    `;

    row.querySelector(".session-main").addEventListener("click", () => {
      switchSession(session.id);
    });
    row.querySelector(".session-menu-button").addEventListener("click", (event) => {
      event.stopPropagation();
      state.openSessionMenuId = menuOpen ? "" : session.id;
      renderSessionList();
    });
    row.querySelector(".rename-session").addEventListener("click", (event) => {
      event.stopPropagation();
      renameSession(session.id, index);
    });
    row.querySelector(".delete-session").addEventListener("click", async (event) => {
      event.stopPropagation();
      await deleteSession(session.id);
    });
    sessionList.appendChild(row);
  });
}

function renameSession(sessionId, index) {
  const session = state.sessions.find((item) => item.id === sessionId);
  if (!session) {
    return;
  }

  const currentLabel = session.customTitle || sessionLabel(session, index);
  const nextLabel = window.prompt("Rename session", currentLabel);
  state.openSessionMenuId = "";
  if (nextLabel === null) {
    renderSessionList();
    return;
  }

  session.customTitle = nextLabel.trim();
  persistSessions();
  renderSessionList();
}

function paragraph(text) {
  const p = document.createElement("p");
  p.textContent = text;
  return p;
}

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function renderInlineFormatting(text) {
  let html = escapeHtml(text);
  html = html.replace(/\\\(\\le\s*([^)]+)\\\)/g, "≤ $1");
  html = html.replace(/\\\(\\ge\s*([^)]+)\\\)/g, "≥ $1");
  html = html.replace(/\\\(<=\s*([^)]+)\\\)/g, "≤ $1");
  html = html.replace(/\\\(>=\s*([^)]+)\\\)/g, "≥ $1");
  html = html.replace(/\\\(([^)]+)\\\)/g, "$1");
  html = html.replace(/\\le/g, "≤");
  html = html.replace(/\\ge/g, "≥");
  html = html.replace(/\\textit\{([^{}]+)\}/g, "<em>$1</em>");
  html = html.replace(/\\textbf\{([^{}]+)\}/g, "<strong>$1</strong>");
  html = html.replace(/\\mathbf\{([^{}]+)\}/g, "<strong>$1</strong>");
  html = html.replace(/\\emph\{([^{}]+)\}/g, "<em>$1</em>");
  html = html.replace(/\\underline\{([^{}]+)\}/g, "<span class=\"inline-underline\">$1</span>");
  html = html.replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  html = html.replace(/(^|[\s(])\*([^*]+)\*(?=[\s).,!?;:]|$)/g, "$1<em>$2</em>");
  html = html.replace(/(^|[\s(])_([^_]+)_(?=[\s).,!?;:]|$)/g, "$1<em>$2</em>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  return html;
}

function appendFormattedBlocks(container, text) {
  const blocks = String(text || "").split(/\n{2,}/);

  for (const rawBlock of blocks) {
    const block = rawBlock.trim();
    if (!block) {
      continue;
    }

    const lines = block.split("\n").map((line) => line.trimEnd());
    const firstLine = lines[0].trim();
    const headingMatch = firstLine.match(/^(#{1,3})\s+(.*)$/);
    if (headingMatch && lines.length === 1) {
      const heading = document.createElement(
        headingMatch[1].length === 1 ? "h2" : "h3"
      );
      heading.className = "rich-heading";
      heading.innerHTML = renderInlineFormatting(headingMatch[2]);
      container.appendChild(heading);
      continue;
    }

    const quoteLines = [];
    let isQuote = true;
    for (const line of lines) {
      const match = line.match(/^>\s?(.*)$/);
      if (!match) {
        isQuote = false;
        break;
      }
      quoteLines.push(match[1]);
    }

    if (isQuote && quoteLines.length > 0) {
      const quote = document.createElement("blockquote");
      quote.className = "rich-quote";
      quote.innerHTML = quoteLines
        .map((line) => renderInlineFormatting(line))
        .join("<br>");
      container.appendChild(quote);
      continue;
    }

    const listItems = [];
    let isList = true;

    for (const line of lines) {
      const match = line.match(/^([-*]|\d+\.)\s+(.*)$/);
      if (!match) {
        isList = false;
        break;
      }
      listItems.push(match[2]);
    }

    if (isList && listItems.length > 0) {
      const list = document.createElement("ul");
      list.className = "rich-list";
      for (const item of listItems) {
        const li = document.createElement("li");
        li.innerHTML = renderInlineFormatting(item);
        list.appendChild(li);
      }
      container.appendChild(list);
      continue;
    }

    const p = document.createElement("p");
    p.innerHTML = lines.map((line) => renderInlineFormatting(line)).join("<br>");
    container.appendChild(p);
  }
}

function buildPendingBubble() {
  const wrapper = document.createElement("div");
  const bubble = document.createElement("div");
  bubble.className = "typing-bubble";
  bubble.innerHTML =
    "<span></span><span></span><span></span><span class=\"typing-label\">Thinking...</span>";
  wrapper.appendChild(bubble);
  return wrapper;
}

function renderUserMessage(text, sessionId = state.currentSessionId) {
  const wrapper = document.createElement("div");
  wrapper.appendChild(paragraph(text));
  addSessionMessage(sessionId, "user", text);
  if (sessionId === state.currentSessionId) {
    appendMessage("user", wrapper);
  }
}

function renderAgentMessage(message, sessionId = state.currentSessionId) {
  const wrapper = document.createElement("div");
  appendFormattedBlocks(wrapper, message.answer || "No answer returned.");

  if (message.visualization_html) {
    const frame = document.createElement("iframe");
    frame.className = "viz-frame";
    frame.srcdoc = message.visualization_html;
    frame.loading = "lazy";
    wrapper.appendChild(frame);
  }

  addSessionMessage(
    sessionId,
    "agent",
    message.answer || "No answer returned.",
    message.visualization_html || ""
  );
  if (sessionId === state.currentSessionId) {
    appendMessage("agent", wrapper);
  }
}

function renderPendingAgentMessage(sessionId = state.currentSessionId) {
  removeSessionPendingMessage(sessionId);
  addSessionMessage(sessionId, "agent", "Thinking...", "", { pending: true });
  if (sessionId === state.currentSessionId) {
    appendMessage("agent", buildPendingBubble());
  }
}

function removePendingAgentMessage(sessionId = state.currentSessionId) {
  removeSessionPendingMessage(sessionId);
  if (sessionId === state.currentSessionId) {
    renderSessionMessages();
  } else {
    renderSessionList();
  }
}

function renderEmptyState() {
  chatLog.innerHTML = "";
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.textContent = "Pick A Dataset, Ask Questions.";
  chatLog.appendChild(empty);
}

function renderSessionMessages() {
  renderEmptyState();
  const session = currentSession();
  if (!session || session.messages.length === 0) {
    return;
  }

  chatLog.innerHTML = "";
  session.messages.forEach((message) => {
    const wrapper = document.createElement("div");
    if (message.role === "user") {
      wrapper.appendChild(paragraph(message.text));
      appendMessage("user", wrapper);
      return;
    }

    if (message.pending) {
      appendMessage("agent", buildPendingBubble());
      return;
    }

    appendFormattedBlocks(wrapper, message.text || "No answer returned.");
    if (message.visualizationHtml) {
      const frame = document.createElement("iframe");
      frame.className = "viz-frame";
      frame.srcdoc = message.visualizationHtml;
      frame.loading = "lazy";
      wrapper.appendChild(frame);
    }
    appendMessage("agent", wrapper);
  });
}

async function requestSession() {
  const response = await fetch("/api/session");
  const payload = await response.json();
  return payload.session_id;
}

async function createSession(dataset = state.currentDataset) {
  const sessionId = await requestSession();
  const session = {
    id: sessionId,
    dataset,
    messages: [],
    customTitle: "",
  };
  state.sessions.unshift(session);
  state.currentSessionId = sessionId;
  state.currentDataset = dataset;
  persistSessions();
  syncDatasetControls();
  renderSessionList();
  renderSessionMessages();
  return session;
}

function switchSession(sessionId) {
  const session = state.sessions.find((item) => item.id === sessionId);
  if (!session) {
    return;
  }

  state.currentSessionId = sessionId;
  state.currentDataset = session.dataset;
  persistSessions();
  syncDatasetControls();
  renderSessionList();
  renderSessionMessages();
}

async function deleteSession(sessionId) {
  try {
    await fetch("/api/session/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
  } catch (error) {
    // The local UI can still remove the session even if backend cleanup fails.
  }

  state.sessions = state.sessions.filter((session) => session.id !== sessionId);
  persistSessions();
  state.openSessionMenuId = "";
  if (state.currentSessionId === sessionId) {
    if (state.sessions.length === 0) {
      await createSession(state.currentDataset);
      return;
    }
    state.currentSessionId = state.sessions[0].id;
    state.currentDataset = state.sessions[0].dataset;
    syncDatasetControls();
    renderSessionMessages();
  }
  renderSessionList();
}

async function bootstrap() {
  const response = await fetch("/api/bootstrap");
  const payload = await response.json();

  state.datasets = payload.datasets || [];
  state.uploadedDatasets = payload.uploaded_datasets || [];
  state.currentDataset = payload.default_dataset || state.datasets[0] || "";
  state.sessions = loadStoredSessions().filter((session) =>
    state.datasets.includes(session.dataset)
  );

  datasetSelect.innerHTML = "";
  for (const dataset of state.datasets) {
    const option = document.createElement("option");
    option.value = dataset;
    option.textContent = dataset;
    datasetSelect.appendChild(option);
  }
  syncDatasetControls();
  renderEmptyState();
  await createSession(state.currentDataset);
}

async function uploadDataset() {
  const file = uploadInput.files?.[0];
  if (!file || state.sending) {
    return;
  }

  const content = await file.text();
  setSending(true);
  try {
    const response = await fetch("/api/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: file.name,
        content,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Upload failed.");
    }

    state.datasets = payload.datasets || [];
    state.uploadedDatasets = payload.uploaded_datasets || [];
    state.currentDataset = payload.dataset || state.currentDataset;
    datasetSelect.innerHTML = "";
    for (const dataset of state.datasets) {
      const option = document.createElement("option");
      option.value = dataset;
      option.textContent = dataset;
      datasetSelect.appendChild(option);
    }
    syncDatasetControls();
    const session = currentSession();
    if (session) {
      session.dataset = state.currentDataset;
      persistSessions();
    }
    await resetConversation();
  } catch (error) {
    removePendingAgentMessage();
    const wrapper = document.createElement("div");
    wrapper.appendChild(paragraph(error.message));
    appendMessage("agent", wrapper);
  } finally {
    uploadInput.value = "";
    setSending(false);
  }
}

async function resetConversation() {
  if (!state.currentSessionId) {
    return;
  }

  setSending(true);
  try {
    await fetch("/api/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.currentSessionId,
        dataset: state.currentDataset,
      }),
    });
    const session = currentSession();
    if (session) {
      session.messages = [];
      persistSessions();
    }
    renderSessionList();
    renderEmptyState();
  } finally {
    setSending(false);
  }
}

async function sendQuestion(question) {
  const requestSessionId = state.currentSessionId;
  const requestDataset = state.currentDataset;
  if (!requestSessionId || !requestDataset) {
    return;
  }

  setSending(true);
  renderUserMessage(question, requestSessionId);
  renderPendingAgentMessage(requestSessionId);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: requestSessionId,
        dataset: requestDataset,
        question,
      }),
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.error || "Request failed.");
    }

    removePendingAgentMessage(requestSessionId);
    renderAgentMessage(payload.message, requestSessionId);
  } catch (error) {
    removePendingAgentMessage(requestSessionId);
    renderAgentMessage(
      {
        answer: error.message,
        visualization_html: "",
      },
      requestSessionId
    );
  } finally {
    setSending(false);
  }
}

datasetSelect.addEventListener("change", async (event) => {
  state.currentDataset = event.target.value;
  const session = currentSession();
  if (session) {
    session.dataset = state.currentDataset;
    persistSessions();
  }
  toggleDatasetMenu(false);
  renderSessionList();
  await resetConversation();
});

uploadInput.addEventListener("change", async () => {
  await uploadDataset();
});

newSessionButton.addEventListener("click", async () => {
  if (state.sending) {
    return;
  }
  await createSession(state.currentDataset);
});

sidebarToggle.addEventListener("click", () => {
  state.sidebarOpen = !state.sidebarOpen;
  document.body.classList.toggle("sidebar-collapsed", !state.sidebarOpen);
  syncSidebarToggle();
});

datasetMenuButton.addEventListener("click", (event) => {
  event.stopPropagation();
  toggleDatasetMenu();
});

deleteDatasetButton.addEventListener("click", async (event) => {
  event.stopPropagation();
  const dataset = state.currentDataset;
  if (!dataset) {
    return;
  }

  const confirmed = window.confirm(`Delete dataset "${dataset}"?`);
  if (!confirmed) {
    toggleDatasetMenu(false);
    return;
  }

  setSending(true);
  try {
    const response = await fetch("/api/dataset/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataset }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Dataset deletion failed.");
    }

    state.datasets = payload.datasets || [];
    state.uploadedDatasets = payload.uploaded_datasets || [];
    state.currentDataset = payload.default_dataset || state.datasets[0] || "";
    datasetSelect.innerHTML = "";
    for (const name of state.datasets) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      datasetSelect.appendChild(option);
    }
    syncDatasetControls();

    state.sessions = state.sessions.filter((session) => session.dataset !== dataset);
    persistSessions();
    if (state.sessions.length === 0 && state.currentDataset) {
      await createSession(state.currentDataset);
    } else if (state.sessions.length > 0) {
      switchSession(state.sessions[0].id);
    } else {
      state.currentSessionId = "";
      syncDatasetControls();
      renderSessionList();
      renderEmptyState();
    }
  } catch (error) {
    const wrapper = document.createElement("div");
    wrapper.appendChild(paragraph(error.message));
    appendMessage("agent", wrapper);
  } finally {
    toggleDatasetMenu(false);
    setSending(false);
  }
});

document.addEventListener("click", () => {
  if (state.datasetMenuOpen) {
    toggleDatasetMenu(false);
  }
  if (!state.openSessionMenuId) {
    return;
  }
  state.openSessionMenuId = "";
  renderSessionList();
});

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionInput.value.trim();
  if (!question || state.sending) {
    return;
  }
  questionInput.value = "";
  await sendQuestion(question);
});

questionInput.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter" || event.shiftKey) {
    return;
  }

  event.preventDefault();
  if (state.sending) {
    return;
  }

  const question = questionInput.value.trim();
  if (!question) {
    return;
  }

  questionInput.value = "";
  await sendQuestion(question);
});

bootstrap().catch((error) => {
  const wrapper = document.createElement("div");
  wrapper.appendChild(paragraph(error.message));
  appendMessage("agent", wrapper);
});

syncSidebarToggle();
