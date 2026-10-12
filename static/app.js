(() => {
  const doctorInput = document.querySelector('input[name="doctor_id"]');
  if (!doctorInput) return;

  const storageKey = "clinic-antiviral.doctor-id";
  if (!doctorInput.value) {
    doctorInput.value = window.localStorage.getItem(storageKey) || "";
  }

  document.querySelectorAll('form input[name="doctor_id"]').forEach((input) => {
    input.form?.addEventListener("submit", () => {
      if (input.value) window.localStorage.setItem(storageKey, input.value);
    });
  });
})();

document.querySelectorAll(".add-lot").forEach((button) => {
  button.addEventListener("click", () => {
    const editor = button.closest(".row-form")?.querySelector(".lots-editor");
    const firstRow = editor?.querySelector(".lot-row");
    if (!editor || !firstRow) return;
    const row = firstRow.cloneNode(true);
    row.querySelectorAll("input").forEach((input) => { input.value = ""; });
    editor.appendChild(row);
  });
});

(() => {
  const operatorInputs = document.querySelectorAll('input[name="operator"]');
  if (!operatorInputs.length) return;
  const storageKey = "clinic-antiviral.operator-id";
  const remembered = window.localStorage.getItem(storageKey) || "";
  operatorInputs.forEach((input) => {
    if (!input.value) input.value = remembered;
    input.form?.addEventListener("submit", () => {
      if (input.value) window.localStorage.setItem(storageKey, input.value);
    });
  });
})();

(() => {
  const panel = document.querySelector(".index-panel");
  if (!panel) return;

  const statusUrl = panel.dataset.indexStatusUrl;
  const message = panel.querySelector("#today-index-message");
  const state = panel.querySelector("#today-index-state");
  const progress = panel.querySelector("#today-index-progress");
  const progressValue = panel.querySelector("#today-index-progress-value");
  const phase = panel.querySelector("#today-index-phase");
  const counts = panel.querySelector("#today-index-counts");
  const times = panel.querySelector("#today-index-times");
  const success = panel.querySelector("#today-index-success");
  const error = panel.querySelector("#today-index-error");
  const rebuild = panel.querySelector(".index-action");
  const searchButtons = document.querySelectorAll(".his-search");
  const stateLabels = {
    not_started: "尚未開始",
    building: "建立中",
    ready: "已完成",
    stale: "需要更新",
    error: "建立失敗",
  };
  const phaseLabels = {
    prepare: "準備讀取資料",
    headers: "讀取今日處方主檔",
    items: "配對抗病毒處方",
    patients: "補齊病人資料",
    finalize: "整理索引",
    incremental_read: "讀取新增資料",
    incremental_headers: "配對新增處方",
    incremental_items: "整理新增藥品",
    incremental_patients: "補齊新增病人資料",
    incremental_finalize: "完成快速更新",
    ready: "已完成",
    stale: "需要完整更新",
    error: "建立失敗",
  };
  const initialState = panel.dataset.indexState || "not_started";
  let lastStatus = { state: initialState };
  let pollTimer = null;
  let pollFailures = 0;

  const isWaiting = (current) => current !== "ready";

  const schedulePoll = (delay) => {
    if (pollTimer) window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(poll, delay);
  };

  const applyStatus = (status) => {
    const current = status?.state || "error";
    const progressMode = status?.progress_mode || (status?.progress == null ? "indeterminate" : "determinate");
    const numericProgress = Number(status?.progress);
    const currentProgress = Number.isFinite(numericProgress)
      ? Math.max(0, Math.min(100, numericProgress))
      : 0;
    lastStatus = { ...status, state: current };

    if (message) message.textContent = status?.message || "今日索引狀態無法取得";
    if (state) {
      state.textContent = stateLabels[current] || current;
      state.dataset.state = current;
    }
    if (progress) {
      if (progressMode === "determinate") {
        progress.value = currentProgress;
        progress.setAttribute("aria-valuenow", String(currentProgress));
        progress.setAttribute("aria-valuetext", `${currentProgress}%`);
        progress.classList.remove("is-indeterminate");
      } else {
        progress.removeAttribute("value");
        progress.removeAttribute("aria-valuenow");
        progress.setAttribute("aria-valuetext", status?.message || "處理中");
        progress.classList.add("is-indeterminate");
      }
      progress.classList.toggle("is-complete", current === "ready");
    }
    if (progressValue) {
      progressValue.textContent = progressMode === "determinate" || current === "ready"
        ? `${currentProgress}%`
        : "處理中";
    }
    if (phase) {
      const phaseText = phaseLabels[status?.phase] || status?.phase || "";
      phase.textContent = phaseText && current !== "ready" ? `階段：${phaseText}` : "";
    }
    if (counts) {
      const processed = Number(status?.processed);
      const total = Number(status?.total);
      counts.textContent = Number.isFinite(processed) && Number.isFinite(total) && total > 0
        ? `已處理 ${processed.toLocaleString()} / ${total.toLocaleString()} 筆`
        : "";
    }
    if (times) {
      times.textContent = `首次完成：${status?.first_completed_at || "尚未完成"}；最近完成：${status?.completed_at || "尚未完成"}`;
    }
    if (success) {
      success.hidden = current !== "ready";
      if (current === "ready") {
        success.textContent = status?.message === "今日索引已快速更新"
          ? "今日索引已更新，可以開始搜尋。"
          : "今日索引已完成，可以開始搜尋。";
      }
    }
    if (error) {
      error.hidden = !status?.error;
      error.textContent = status?.error || "";
    }
    panel.dataset.indexState = current;
    searchButtons.forEach((button) => { button.disabled = isWaiting(current); });
    if (rebuild) rebuild.disabled = current === "building";
    rebuild?.classList.toggle("highlight", current !== "ready");
  };

  const poll = async () => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(statusUrl, {
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const status = await response.json();
      applyStatus(status);
      pollFailures = 0;
      if (status.state === "building" || status.state === "not_started") {
        schedulePoll(1000);
      }
    } catch (_error) {
      pollFailures += 1;
      const stillWaiting = lastStatus.state === "building" || lastStatus.state === "not_started";
      if (stillWaiting) {
        searchButtons.forEach((button) => { button.disabled = true; });
        if (message) message.textContent = `索引狀態暫時無法更新，正在重試（第 ${pollFailures} 次）`;
        schedulePoll(Math.min(5000, 1000 + pollFailures * 500));
      } else if (message) {
        message.textContent = "索引狀態暫時無法更新，請重新整理頁面。";
      }
    } finally {
      window.clearTimeout(timeout);
    }
  };

  if (isWaiting(initialState)) {
    searchButtons.forEach((button) => { button.disabled = true; });
  }
  poll();
})();
