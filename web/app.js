const state = { status: null };
const $ = (id) => document.getElementById(id);

function setBusy(button, busy, text) {
  if (!button) return;
  if (busy) {
    button.dataset.label = button.textContent;
    button.textContent = text || "Working…";
    button.disabled = true;
  } else {
    button.textContent = button.dataset.label || button.textContent;
    button.disabled = false;
  }
}

function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast visible${isError ? " error" : ""}`;
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => { el.className = "toast"; }, 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
}

function badge(el, text, kind) {
  el.textContent = text;
  el.className = `badge ${kind}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  }[char]));
}

function renderAlerts(status) {
  const items = [
    ...(status.errors || []).map((text) => ({ type: "error", text })),
    ...(status.warnings || []).map((text) => ({ type: "warning", text })),
  ];
  $("alerts").innerHTML = items.map((item) => `<div class="alert ${item.type}">${escapeHtml(item.text)}</div>`).join("");
}

function renderProfiles(profiles) {
  const grid = $("profileGrid");
  if (!profiles.length) {
    grid.innerHTML = '<div class="empty">No provider profiles found in config/gateway.yaml.</div>';
    return;
  }
  grid.innerHTML = profiles.map((profile) => {
    const configured = profile.key_configured;
    const keyName = profile.api_key_env;
    const modelTags = profile.models.map((model) => `<span class="tag">${escapeHtml(model.alias)}</span>`).join("");
    const input = keyName ? `
      <div class="key-form">
        <input class="key-input" type="password" autocomplete="new-password" data-key-input="${escapeHtml(keyName)}" placeholder="${configured ? "Key configured — enter a new value to replace" : "Paste API key"}">
        <button class="button secondary small" data-save-key="${escapeHtml(keyName)}">Save</button>
        <button class="button danger small" data-clear-key="${escapeHtml(keyName)}">Clear</button>
      </div>` : "";
    return `
      <article class="profile-card${profile.enabled ? "" : " disabled"}">
        <div class="profile-top">
          <div>
            <h3>${escapeHtml(profile.label)}</h3>
            <p class="muted">${escapeHtml(profile.id)}</p>
          </div>
          <span class="badge ${configured ? "success" : "warning"}">${configured ? "Key set" : "Missing key"}</span>
        </div>
        <div class="model-tags">${modelTags}</div>
        ${input}
      </article>`;
  }).join("");

  document.querySelectorAll("[data-save-key]").forEach((button) => button.addEventListener("click", () => saveKey(button.dataset.saveKey, false, button)));
  document.querySelectorAll("[data-clear-key]").forEach((button) => button.addEventListener("click", () => saveKey(button.dataset.clearKey, true, button)));
}

function renderModels(aliases, online) {
  const grid = $("modelGrid");
  if (!aliases.length) {
    grid.innerHTML = '<div class="empty">No active models. Add at least one provider API key above.</div>';
    return;
  }
  grid.innerHTML = aliases.map((item) => `
    <article class="model-card">
      <h3>${escapeHtml(item.name)}</h3>
      <div class="model-meta">
        <span>${item.deployments} deployment${item.deployments === 1 ? "" : "s"}</span>
        <button class="button secondary small" data-test-model="${escapeHtml(item.name)}" ${online ? "" : "disabled"}>Test model</button>
      </div>
    </article>`).join("");
  document.querySelectorAll("[data-test-model]").forEach((button) => button.addEventListener("click", () => testModel(button.dataset.testModel, button)));
}

function render(status) {
  state.status = status;
  const gateway = status.gateway || {};
  const online = Boolean(gateway.online);
  badge($("gatewayBadge"), online ? "Gateway online" : "Gateway offline", online ? "success" : "danger");
  badge($("authBadge"), gateway.auth_enabled ? "Auth enabled" : "Auth disabled", gateway.auth_enabled ? "success" : "warning");
  $("endpointText").textContent = gateway.url ? `${gateway.url}/v1` : "Not configured";
  $("vsEndpoint").textContent = gateway.url || "—";
  $("modelCount").textContent = status.aliases?.length || 0;
  $("deploymentCount").textContent = status.deployments?.length || 0;
  const keyProfiles = (status.profiles || []).filter((profile) => profile.api_key_env);
  const configured = keyProfiles.filter((profile) => profile.key_configured).length;
  $("keyCount").textContent = `${configured}/${keyProfiles.length}`;
  $("apiStatus").textContent = online ? "Online" : "Offline";
  const managed = gateway.managed_process || {};
  $("processStatus").textContent = managed.running ? `Running (PID ${managed.pid})` : "Not running";
  $("startButton").disabled = online;
  $("stopButton").disabled = !managed.running;
  renderAlerts(status);
  renderProfiles(status.profiles || []);
  renderModels(status.aliases || [], online);
}

async function refresh() {
  setBusy($("refreshButton"), true, "Refreshing…");
  try {
    render(await api("/api/status"));
  } catch (error) {
    toast(error.message, true);
  } finally {
    setBusy($("refreshButton"), false);
  }
}

async function saveKey(name, clear, button) {
  const input = document.querySelector(`[data-key-input="${CSS.escape(name)}"]`);
  const value = clear ? "" : input.value.trim();
  if (!clear && !value) return toast("Enter a key value first.", true);
  setBusy(button, true, clear ? "Clearing…" : "Saving…");
  try {
    await api("/api/keys", { method: "POST", body: JSON.stringify({ name, value }) });
    input.value = "";
    toast(clear ? `${name} cleared.` : `${name} saved locally.`);
    await refresh();
  } catch (error) {
    toast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function action(path, button, busyText, successText) {
  setBusy(button, true, busyText);
  try {
    await api(path, { method: "POST", body: "{}" });
    toast(successText);
    await refresh();
    await refreshLog();
  } catch (error) {
    toast(error.message, true);
    await refreshLog();
  } finally {
    setBusy(button, false);
  }
}

async function testModel(model, button) {
  setBusy(button, true, "Testing…");
  try {
    const result = await api("/api/test", { method: "POST", body: JSON.stringify({ model }) });
    toast(result.ok ? `${model}: OK in ${result.elapsed_ms} ms` : `${model}: ${result.message}`, !result.ok);
  } catch (error) {
    toast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function refreshLog() {
  try {
    const result = await api("/api/logs?lines=220");
    $("logOutput").textContent = result.text || "No log output yet.";
  } catch (error) {
    $("logOutput").textContent = error.message;
  }
}

async function copyText(value, label) {
  if (!value) return toast(`${label} is not available.`, true);
  await navigator.clipboard.writeText(value);
  toast(`${label} copied.`);
}

$("refreshButton").addEventListener("click", refresh);
$("logRefreshButton").addEventListener("click", refreshLog);
$("startButton").addEventListener("click", () => action("/api/gateway/start", $("startButton"), "Starting…", "Gateway started."));
$("stopButton").addEventListener("click", () => action("/api/gateway/stop", $("stopButton"), "Stopping…", "Gateway stopped."));
$("renderButton").addEventListener("click", () => action("/api/render", $("renderButton"), "Rendering…", "Runtime configuration generated."));
$("copyEndpointButton").addEventListener("click", () => copyText(state.status?.gateway?.url || "", "Endpoint"));
$("copyMasterKeyButton").addEventListener("click", async () => {
  try {
    const result = await api("/api/master-key");
    await copyText(result.value, "Gateway key");
  } catch (error) {
    toast(error.message, true);
  }
});

refresh();
refreshLog();
setInterval(refresh, 10000);
