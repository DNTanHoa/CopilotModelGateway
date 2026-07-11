(() => {
  const refreshButton = document.getElementById("quotaRefreshButton");
  const grid = document.getElementById("quotaGrid");
  const checkedAt = document.getElementById("quotaCheckedAt");
  if (!refreshButton || !grid) return;

  function esc(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "'": "&#39;",
      '"': "&quot;",
    }[char]));
  }

  function statusInfo(status) {
    const values = {
      available: ["Available", "success"],
      connected: ["Connected", "success"],
      unavailable: ["Unavailable", "danger"],
      missing_key: ["Missing key", "warning"],
      unsupported: ["Not exposed", "neutral"],
      error: ["Check failed", "danger"],
    };
    const item = values[status] || ["Unknown", "neutral"];
    return { text: item[0], kind: item[1] };
  }

  function renderMetrics(metrics) {
    if (!metrics?.length) return "";
    return `<div class="quota-metrics">${metrics.map((metric) => `
      <div class="quota-metric">
        <span>${esc(metric.label)}</span>
        <strong>${esc(metric.value)}</strong>
        ${metric.detail ? `<small>${esc(metric.detail)}</small>` : ""}
      </div>`).join("")}</div>`;
  }

  function render(items) {
    if (!items.length) {
      grid.innerHTML = '<div class="empty">No provider profiles are available.</div>';
      return;
    }

    grid.innerHTML = items.map((item) => {
      const status = statusInfo(item.status);
      return `
        <article class="quota-card">
          <div class="quota-card-top">
            <div>
              <h3>${esc(item.label)}</h3>
              <p class="muted">${esc(item.provider)}</p>
            </div>
            <span class="badge ${status.kind}">${status.text}</span>
          </div>
          <p class="quota-summary">${esc(item.summary)}</p>
          ${renderMetrics(item.metrics)}
          <p class="quota-note">${esc(item.note)}</p>
        </article>`;
    }).join("");
  }

  async function refreshQuotas() {
    refreshButton.disabled = true;
    const oldLabel = refreshButton.textContent;
    refreshButton.textContent = "Checking…";
    try {
      const result = await api("/api/provider-quotas");
      if (result.error) throw new Error(result.error);
      render(result.items || []);
      if (checkedAt) {
        const date = result.checked_at ? new Date(result.checked_at) : new Date();
        checkedAt.textContent = `Checked ${date.toLocaleTimeString()}`;
      }
    } catch (error) {
      grid.innerHTML = `<div class="empty">${esc(error.message)}</div>`;
      toast(error.message, true);
    } finally {
      refreshButton.textContent = oldLabel;
      refreshButton.disabled = false;
    }
  }

  refreshButton.addEventListener("click", refreshQuotas);
  window.setTimeout(refreshQuotas, 350);
})();
