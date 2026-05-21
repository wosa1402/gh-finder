const state = {
  rows: [],
  statusTimer: null,
};

const el = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `请求失败：${response.status}`);
  }
  return payload;
}

function formNumber(id) {
  const value = el(id).value.trim();
  return value === "" ? null : Number(value);
}

function scanPayload() {
  return {
    token: el("token").value.trim(),
    tokenEnv: el("tokenEnv").value.trim() || "GITHUB_TOKEN",
    pages: formNumber("pages"),
    perPage: formNumber("perPage"),
    minDelaySeconds: formNumber("minDelaySeconds"),
    maxFileBytes: formNumber("maxFileBytes"),
    includeNonPublic: el("includeNonPublic").checked,
    queries: el("queries").value,
  };
}

function verifyPayload() {
  return {
    checkUrl: el("checkUrl").value.trim(),
    timeoutSeconds: formNumber("timeoutSeconds"),
    limit: formNumber("verifyLimit"),
  };
}

async function loadConfig() {
  const config = await api("/api/config");
  el("queries").value = (config.queries || []).join("\n");
  el("pages").value = config.pages || 1;
  el("perPage").value = config.perPage || 50;
  el("minDelaySeconds").value = config.minDelaySeconds || 2;
  el("maxFileBytes").value = config.maxFileBytes || 524288;
  el("tokenEnv").value = config.tokenEnv || "GITHUB_TOKEN";
}

async function startScan() {
  try {
    await api("/api/scan", {
      method: "POST",
      body: JSON.stringify(scanPayload()),
    });
    await refreshAll();
  } catch (error) {
    showError(error.message);
  }
}

async function startVerify() {
  try {
    await api("/api/verify", {
      method: "POST",
      body: JSON.stringify(verifyPayload()),
    });
    await refreshAll();
  } catch (error) {
    showError(error.message);
  }
}

async function stopJob() {
  try {
    await api("/api/stop", {
      method: "POST",
      body: JSON.stringify({}),
    });
    await refreshStatus();
  } catch (error) {
    showError(error.message);
  }
}

async function refreshAll() {
  await Promise.all([refreshStatus(), refreshResults()]);
}

async function refreshStatus() {
  const status = await api("/api/status");
  const job = status.job || {};
  const metrics = job.metrics || {};
  const runningText = job.running ? "运行中" : statusText(job.status || "idle");

  el("statusLine").textContent = `${jobText(job.kind || "idle")} / ${runningText}`;
  setBadge(el("scanBadge"), job.kind === "scan" ? runningText : "空闲", job.status);
  setBadge(el("verifyBadge"), job.kind === "verify" ? runningText : "手动", job.status);

  el("newCount").textContent = metrics.new || 0;
  el("extractedCount").textContent = metrics.extracted || 0;
  el("checkedCount").textContent = metrics.checked || 0;
  el("logs").textContent = (status.logs || []).join("\n");
  el("startScan").disabled = Boolean(job.running);
  el("startVerify").disabled = Boolean(job.running);
  el("stopJob").disabled = !job.running;

  const logPanel = el("logs");
  logPanel.scrollTop = logPanel.scrollHeight;
}

async function refreshResults() {
  const payload = await api("/api/results?limit=500");
  state.rows = payload.rows || [];
  el("totalCount").textContent = payload.count || 0;
  renderRows();
}

function renderRows() {
  const filter = el("resultFilter").value.trim().toLowerCase();
  const rows = filter
    ? state.rows.filter((row) => JSON.stringify(row).toLowerCase().includes(filter))
    : state.rows;
  const body = el("resultsBody");
  body.replaceChildren();

  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.textContent = "暂无结果";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }

  for (const row of rows) {
    const tr = document.createElement("tr");
    appendCell(tr, row.value || "", "mono");
    appendCell(tr, row.scheme || "host:port");
    appendSourceCell(tr, row);
    appendCell(tr, row.line || "");
    appendCell(tr, row.discovered_at || "");
    body.appendChild(tr);
  }
}

function appendCell(tr, text, className = "") {
  const td = document.createElement("td");
  td.textContent = text;
  if (className) {
    td.className = className;
  }
  tr.appendChild(td);
}

function appendSourceCell(tr, row) {
  const td = document.createElement("td");
  const link = document.createElement("a");
  link.className = "source-link";
  link.href = row.source_url || "#";
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = `${row.repository || ""}/${row.path || ""}`;
  td.appendChild(link);
  tr.appendChild(td);
}

function setBadge(node, text, status) {
  node.textContent = text;
  node.className = "badge";
  if (status === "failed") {
    node.classList.add("danger");
  } else if (status === "running" || status === "stopped") {
    node.classList.add("warning");
  }
}

function showError(message) {
  const current = el("logs").textContent;
  el("logs").textContent = `${current}\n错误：${message}`.trim();
}

function statusText(value) {
  const labels = {
    idle: "空闲",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    stopped: "已停止",
  };
  return labels[value] || value || "";
}

function jobText(value) {
  const labels = {
    idle: "空闲",
    scan: "扫描",
    verify: "验证",
  };
  return labels[value] || value || "";
}

function bindEvents() {
  el("startScan").addEventListener("click", startScan);
  el("startVerify").addEventListener("click", startVerify);
  el("stopJob").addEventListener("click", stopJob);
  el("refresh").addEventListener("click", refreshAll);
  el("resultFilter").addEventListener("input", renderRows);
}

async function boot() {
  bindEvents();
  await loadConfig();
  await refreshAll();
  state.statusTimer = window.setInterval(refreshAll, 2500);
}

boot().catch((error) => showError(error.message));
