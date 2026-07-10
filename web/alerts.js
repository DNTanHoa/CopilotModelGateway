(() => {
  const storageKey = "copilot-model-gateway.dismissed-alerts.v1";

  function loadDismissedAlerts() {
    try {
      const values = JSON.parse(sessionStorage.getItem(storageKey) || "[]");
      return new Set(Array.isArray(values) ? values : []);
    } catch {
      return new Set();
    }
  }

  const dismissedAlerts = loadDismissedAlerts();

  function saveDismissedAlerts() {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify([...dismissedAlerts]));
    } catch {
      // The close button should still work when browser storage is unavailable.
    }
  }

  function alertKey(item) {
    return `${item.type}:${item.text}`;
  }

  function escapeAlertHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "'": "&#39;",
      '"': "&quot;",
    }[char]));
  }

  renderAlerts = function renderDismissibleAlerts(status) {
    const items = [
      ...(status.errors || []).map((text) => ({ type: "error", text })),
      ...(status.warnings || []).map((text) => ({ type: "warning", text })),
    ].filter((item) => !dismissedAlerts.has(alertKey(item)));

    const container = document.getElementById("alerts");
    if (!container) return;

    container.innerHTML = items.map((item) => {
      const encodedKey = encodeURIComponent(alertKey(item));
      return `
        <div class="alert ${item.type}">
          <div class="alert-text">${escapeAlertHtml(item.text)}</div>
          <button
            type="button"
            class="alert-close"
            data-dismiss-alert="${encodedKey}"
            aria-label="Close notification"
            title="Close"
          >×</button>
        </div>`;
    }).join("");

    container.querySelectorAll("[data-dismiss-alert]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = decodeURIComponent(button.dataset.dismissAlert || "");
        if (key) {
          dismissedAlerts.add(key);
          saveDismissedAlerts();
        }
        button.closest(".alert")?.remove();
      });
    });
  };
})();
