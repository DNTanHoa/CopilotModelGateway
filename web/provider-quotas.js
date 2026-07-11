(() => {
  const refreshButton = document.getElementById("quotaRefreshButton");
  const grid = document.getElementById("quotaGrid");
  const checkedAt = document.getElementById("quotaCheckedAt");
  const summary = document.getElementById("quotaSummary");
  if (!refreshButton || !grid) return;

  const AUTO_REFRESH_MS = 5 * 60 * 1000;

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
      low: ["Low balance", "warning"],
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

  function renderSummary(values, threshold) {
    if (!summary) return;
    const items = [
      ["Providers", values?.total ?? 0, "neutral"],
      ["Healthy", values?.healthy ?? 0, "success"],
      ["Low", values?.low ?? 0, "warning"],
      ["Unavailable", values?.unavailable ?? 0, "danger"],
      ["Errors", values?.errors ?? 0, "danger"],
    ];
    summary.innerHTML = items.map(([label, value, kind]) => `
      <div class="quota-summary-item ${kind}">
        <span>${esc(label)}</span>
        <strong>${esc(value)}</strong>
      </div>`).join("") + `
      <div class="quota-threshold">Low-balance warning ≤ ${esc(threshold ?? "1")}</div>`;
  }

  function render(items) {
    if (!items.length) {
      grid.innerHTML = '<div class="empty">No provider profiles are available.</div>';
      return;
    }

    grid.innerHTML = items.map((item) => {
      const status = statusInfo(item.status);
      return `
        <article class="quota-card ${esc(item.status)}">
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

  function checkedTime(result) {
    if (result.checked_at_unix) return new Date(result.checked_at_unix * 1000);
    if (result.checked_at) return new Date(result.checked_at);
    return new Date();
  }

  async function refreshQuotas(force = false) {
    refreshButton.disabled = true;
    const oldLabel = refreshButton.textContent;
    refreshButton.textContent = force ? "Refreshing…" : "Checking…";
    try {
      const path = force
        ? "/api/provider-quota-dashboard?refresh=true"
        : "/api/provider-quota-dashboard";
      const result = await api(path);
      if (result.error) throw new Error(result.error);
      renderSummary(result.summary || {}, result.low_balance_threshold);
      render(result.items || []);
      if (checkedAt) {
        const date = checkedTime(result);
        const cacheText = result.cached ? ` · cached ${result.cache_age_seconds || 0}s` : " · live";
        checkedAt.textContent = `Checked ${date.toLocaleTimeString()}${cacheText}`;
      }
    } catch (error) {
      grid.innerHTML = `<div class="empty">${esc(error.message)}</div>`;
      toast(error.message, true);
    } finally {
      refreshButton.textContent = oldLabel;
      refreshButton.disabled = false;
    }
  }

  refreshButton.addEventListener("click", () => refreshQuotas(true));
  window.setTimeout(() => refreshQuotas(false), 350);
  window.setInterval(() => refreshQuotas(false), AUTO_REFRESH_MS);

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refreshQuotas(false);
  });
})();
