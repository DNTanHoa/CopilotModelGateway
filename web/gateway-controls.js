(() => {
  const originalRender = render;
  const originalRenderModels = renderModels;

  function statusText(item, online) {
    if (!online) return { text: "Gateway offline", className: "offline" };
    if (item.loaded === true) return { text: "Loaded", className: "online" };
    if (item.loaded === false) return { text: "Not loaded", className: "offline" };
    return { text: "Checking", className: "offline" };
  }

  renderModels = function renderLoadedModels(aliases, online) {
    const grid = $("modelGrid");
    if (!aliases.length) {
      grid.innerHTML = '<tr><td colspan="4" class="empty">No active models. Add at least one provider API key above.</td></tr>';
      return;
    }

    grid.innerHTML = aliases.map((item) => {
      const modelStatus = statusText(item, online);
      const testDisabled = online && item.loaded !== false ? "" : "disabled";
      return `
        <tr>
          <td><span class="model-alias">${escapeHtml(item.name)}</span></td>
          <td>${item.deployments} deployment${item.deployments === 1 ? "" : "s"}</td>
          <td><span class="table-status ${modelStatus.className}">${modelStatus.text}</span></td>
          <td class="model-action"><button class="button secondary small" data-test-model="${escapeHtml(item.name)}" ${testDisabled}>Test</button></td>
        </tr>`;
    }).join("");

    document.querySelectorAll("[data-test-model]").forEach((button) => {
      button.addEventListener("click", () => testModel(button.dataset.testModel, button));
    });
  };

  const oldStartButton = $("startButton");
  const startButton = oldStartButton.cloneNode(true);
  oldStartButton.replaceWith(startButton);

  function syncGatewayControl(status) {
    const gateway = status?.gateway || {};
    const online = Boolean(gateway.online);
    const managed = Boolean(gateway.managed_process?.running);

    startButton.textContent = online ? "Restart gateway" : "Start gateway";
    startButton.disabled = online && !managed;
    startButton.title = online && !managed
      ? "Port is online but the process is not managed by this dashboard"
      : "";
  }

  render = function renderWithGatewayControl(status) {
    originalRender(status);
    syncGatewayControl(status);
  };

  startButton.addEventListener("click", () => {
    const online = Boolean(state.status?.gateway?.online);
    action(
      online ? "/api/gateway/restart" : "/api/gateway/start",
      startButton,
      online ? "Restarting…" : "Starting…",
      online ? "Gateway restarted with the latest runtime configuration." : "Gateway started.",
    );
  });

  if (state.status) syncGatewayControl(state.status);
})();
