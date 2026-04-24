const WORKSPACE_CONFIG = window.APP_CONFIG || {};
const WORKSPACE_VIEWS = ["overview", "upload", "status", "results", "review", "export"];
const WORKSPACE_PROCESSING = new Set(["queued", "parsing", "structuring", "generating"]);

const workspaceState = {
  activeView: WORKSPACE_VIEWS.includes(WORKSPACE_CONFIG.initialView) ? WORKSPACE_CONFIG.initialView : "overview",
  currentJobId: WORKSPACE_CONFIG.jobId || "",
  overview: null,
  job: null,
  result: null,
  unitFilter: "all",
  pollTimer: null,
};

function sortWorkspaceRecentJobs(jobs) {
  return [...jobs].sort((left, right) => {
    const resultDelta = Number(Boolean(right?.has_result)) - Number(Boolean(left?.has_result));
    if (resultDelta !== 0) {
      return resultDelta;
    }
    const leftTime = Date.parse(left?.created_at || "") || 0;
    const rightTime = Date.parse(right?.created_at || "") || 0;
    return rightTime - leftTime;
  });
}

function buildWorkspaceUrl(jobId = "", view = workspaceState.activeView) {
  const query = new URLSearchParams();
  if (jobId) {
    query.set("job_id", jobId);
  }
  if (view && view !== "overview") {
    query.set("view", view);
  }
  const queryString = query.toString();
  return queryString ? `/?${queryString}` : "/";
}

function updateWorkspaceUrl() {
  const nextUrl = buildWorkspaceUrl(workspaceState.currentJobId, workspaceState.activeView);
  window.history.replaceState({}, "", nextUrl);
}

function setWorkspaceFeedback(message, tone = "status") {
  const shell = document.getElementById("workspace-feedback");
  if (!shell) {
    return;
  }
  if (!message) {
    shell.innerHTML = "";
    return;
  }
  const klass = tone === "error" ? "inline-error" : "status-banner";
  shell.innerHTML = `<div class="${klass}">${escapeHtml(message)}</div>`;
}

function renderOverviewSummary(payload) {
  const summary = payload.summary || {};
  const contentTotals = payload.content_totals || {};
  const statusCounts = payload.status_counts || [];
  const reviewTotals = payload.review_status_totals || [];

  return `
    <section class="stats-grid">
      <article class="stat-card">
        <p class="stat-label">总任务数</p>
        <p class="stat-value">${summary.total_jobs || 0}</p>
        <p class="stat-meta">已有结果 ${summary.jobs_with_results || 0} 个</p>
      </article>
      <article class="stat-card">
        <p class="stat-label">处理中 / 待审核</p>
        <p class="stat-value">${summary.processing_jobs || 0}/${summary.reviewing_jobs || 0}</p>
        <p class="stat-meta">失败任务 ${summary.failed_jobs || 0} 个</p>
      </article>
      <article class="stat-card">
        <p class="stat-label">内容条目</p>
        <p class="stat-value">${contentTotals.vocabulary_items || 0}/${contentTotals.sentence_patterns || 0}</p>
        <p class="stat-meta">词汇 / 句型，总对话 ${contentTotals.dialogue_samples || 0}</p>
      </article>
      <article class="stat-card">
        <p class="stat-label">导出 / 审核记录</p>
        <p class="stat-value">${summary.total_exports || 0}/${summary.review_records || 0}</p>
        <p class="stat-meta">最近更新时间 ${escapeHtml(formatDateTime(payload.generated_at))}</p>
      </article>
    </section>
    <div class="stack-grid">
      <section class="panel">
        <div class="section-head section-head-compact">
          <div>
            <p class="eyebrow">Status Mix</p>
            <h3>任务状态分布</h3>
          </div>
        </div>
        <div class="chip-list">
          ${statusCounts
            .map(
              (item) => `
                <div class="metric-chip">
                  <span>${escapeHtml(item.label)}</span>
                  <strong>${escapeHtml(item.count)}</strong>
                </div>
              `,
            )
            .join("")}
        </div>
      </section>
      <section class="panel">
        <div class="section-head section-head-compact">
          <div>
            <p class="eyebrow">Review Mix</p>
            <h3>审核状态分布</h3>
          </div>
        </div>
        <div class="chip-list">
          ${reviewTotals
            .map(
              (item) => `
                <div class="metric-chip">
                  <span>${escapeHtml(item.label)}</span>
                  <strong>${escapeHtml(item.count)}</strong>
                </div>
              `,
            )
            .join("")}
        </div>
      </section>
    </div>
  `;
}

function renderRecentJobsTable(jobs) {
  if (!jobs.length) {
    return '<div class="empty-state compact-empty">当前还没有任务记录。</div>';
  }
  return `
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>任务 ID</th>
            <th>文件</th>
            <th>状态</th>
            <th>产出概览</th>
            <th>审核进度</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          ${jobs
            .map(
              (job) => `
                <tr>
                  <td><code>${escapeHtml(job.job_id)}</code></td>
                  <td>
                    <strong>${escapeHtml(job.file_name)}</strong>
                    <p class="table-meta">${escapeHtml(formatDateTime(job.created_at))}</p>
                  </td>
                  <td>${statusBadge(job.status)}</td>
                  <td>
                    <p class="table-meta">单元 ${escapeHtml(job.result_counts.units)}</p>
                    <p class="table-meta">词汇 ${escapeHtml(job.result_counts.vocabulary_items)} / 句型 ${escapeHtml(job.result_counts.sentence_patterns)}</p>
                  </td>
                  <td>
                    <p class="table-meta">${escapeHtml(job.review_state_label)}</p>
                    <p class="table-meta">${escapeHtml(job.review_progress_text)}</p>
                  </td>
                  <td class="link-cell">
                    <button type="button" class="small" data-load-job-id="${escapeHtml(job.job_id)}" data-target-view="status">载入工作台</button>
                    <button
                      type="button"
                      class="small danger"
                      data-delete-job-id="${escapeHtml(job.job_id)}"
                      data-delete-job-name="${escapeHtml(job.file_name)}"
                    >
                      删除任务
                    </button>
                  </td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderSidebarRecentJobs(jobs) {
  if (!jobs.length) {
    return '<div class="empty-state compact-empty">暂无最近任务。</div>';
  }
  return jobs
    .map(
      (job) => `
        <button
          type="button"
          class="sidebar-job-button${job.job_id === workspaceState.currentJobId ? " is-active" : ""}"
          data-load-job-id="${escapeHtml(job.job_id)}"
          data-target-view="status"
        >
          <strong>${escapeHtml(job.file_name)}</strong>
          <span><code>${escapeHtml(job.job_id)}</code></span>
          <span>${escapeHtml(job.status_label)} · ${escapeHtml(job.review_progress_text)}</span>
        </button>
      `,
    )
    .join("");
}

function renderRecentExports(exports) {
  if (!exports.length) {
    return '<div class="empty-state compact-empty">还没有导出记录。</div>';
  }
  return `
    <div class="export-list">
      ${exports
        .map(
          (item) => `
            <article class="export-item">
              <div>
                <strong>${escapeHtml(item.export_id)}</strong>
                <p class="table-meta">
                  任务 <code>${escapeHtml(item.job_id)}</code> · ${escapeHtml(item.format.toUpperCase())}
                </p>
                <p class="table-meta">${escapeHtml(formatDateTime(item.created_at))}</p>
              </div>
              <div class="action-row">
                <a class="button-link secondary" href="${escapeHtml(item.download_url)}">下载</a>
                <button type="button" class="small" data-load-job-id="${escapeHtml(item.job_id)}" data-target-view="export">查看任务</button>
              </div>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

function collectVisibleTargetIds(payload) {
  const ids = new Set();
  if (!payload) {
    return ids;
  }
  if (payload.book?.book_id) {
    ids.add(payload.book.book_id);
  }
  for (const unitPackage of payload.units || []) {
    if (unitPackage.unit?.unit_id) {
      ids.add(unitPackage.unit.unit_id);
    }
    for (const item of unitPackage.vocabulary || []) {
      ids.add(item.item_id);
    }
    for (const item of unitPackage.sentence_patterns || []) {
      ids.add(item.item_id);
    }
    for (const item of unitPackage.dialogue_samples || []) {
      ids.add(item.item_id);
    }
    if (unitPackage.unit_task?.item_id) {
      ids.add(unitPackage.unit_task.item_id);
    }
    if (unitPackage.unit_prompt?.item_id) {
      ids.add(unitPackage.unit_prompt.item_id);
    }
  }
  return ids;
}

function filterPayloadByUnit(payload, unitId) {
  if (!payload || !unitId || unitId === "all") {
    return payload;
  }
  const units = (payload.units || []).filter((unitPackage) => unitPackage.unit.unit_id === unitId);
  const filtered = {
    ...payload,
    units,
  };
  const visibleIds = collectVisibleTargetIds(filtered);
  filtered.review_records = (payload.review_records || []).filter((record) => visibleIds.has(record.target_id));
  return filtered;
}

function filterPayloadByApproved(payload) {
  if (!payload) {
    return payload;
  }
  return {
    ...payload,
    units: (payload.units || []).flatMap((unitPackage) => {
      if (unitPackage.unit.review_status !== "approved") {
        return [];
      }
      if (unitPackage.unit_task.review_status !== "approved" || unitPackage.unit_prompt.review_status !== "approved") {
        return [];
      }
      return [
        {
          ...unitPackage,
          vocabulary: (unitPackage.vocabulary || []).filter((item) => item.review_status === "approved"),
          sentence_patterns: (unitPackage.sentence_patterns || []).filter((item) => item.review_status === "approved"),
          dialogue_samples: (unitPackage.dialogue_samples || []).filter((item) => item.review_status === "approved"),
        },
      ];
    }),
    review_records: (payload.review_records || []).filter((record) => record.review_status === "approved"),
  };
}

function getFilteredResultPayload() {
  const approvedOnly = document.getElementById("result-approved-toggle")?.checked || false;
  const basePayload = approvedOnly ? filterPayloadByApproved(workspaceState.result) : workspaceState.result;
  return filterPayloadByUnit(basePayload, workspaceState.unitFilter);
}

function getFilteredReviewPayload() {
  return filterPayloadByUnit(workspaceState.result, workspaceState.unitFilter);
}

function syncUnitFilterOptions() {
  const select = document.getElementById("workspace-unit-filter");
  if (!select) {
    return;
  }
  const units = workspaceState.result?.units || [];
  const nextOptions = ['<option value="all">整本教材</option>']
    .concat(
      units.map(
        (unitPackage) => `
          <option value="${escapeHtml(unitPackage.unit.unit_id)}">
            ${escapeHtml(`${unitPackage.unit.classification.unit_code} · ${unitPackage.unit.classification.unit_name}`)}
          </option>
        `,
      ),
    )
    .join("");
  select.innerHTML = nextOptions;
  const hasCurrentValue = workspaceState.unitFilter === "all" || units.some((item) => item.unit.unit_id === workspaceState.unitFilter);
  if (!hasCurrentValue) {
    workspaceState.unitFilter = "all";
  }
  select.value = workspaceState.unitFilter;
  select.disabled = !units.length;
}

function renderWorkspaceResultSection() {
  const shell = document.getElementById("result-shell");
  if (!shell) {
    return;
  }
  if (!workspaceState.currentJobId) {
    shell.innerHTML = '<div class="empty-state">请先在左侧载入任务，或上传新的教材。</div>';
    return;
  }
  if (!workspaceState.job) {
    shell.innerHTML = '<div class="empty-state">正在读取任务状态...</div>';
    return;
  }
  if (!workspaceState.result) {
    if (WORKSPACE_PROCESSING.has(workspaceState.job.status)) {
      shell.innerHTML = '<div class="empty-state">任务仍在处理中，结果区会在解析完成后自动刷新。</div>';
      return;
    }
    shell.innerHTML = '<div class="empty-state">当前任务还没有结果数据。</div>';
    return;
  }

  const payload = getFilteredResultPayload();
  shell.innerHTML = renderResultView(payload);
}

function renderWorkspaceReviewSection() {
  const summaryShell = document.getElementById("review-summary");
  const shell = document.getElementById("review-shell");
  if (!summaryShell || !shell) {
    return;
  }
  if (!workspaceState.currentJobId) {
    summaryShell.innerHTML = '<div class="empty-state compact-empty">请先载入任务。</div>';
    shell.innerHTML = '<div class="empty-state">当前没有可审核内容。</div>';
    return;
  }
  if (!workspaceState.result) {
    summaryShell.innerHTML = '<div class="empty-state compact-empty">结果还未生成，暂时无法审核。</div>';
    shell.innerHTML = '<div class="empty-state">请先完成解析与内容生成。</div>';
    return;
  }

  const payload = getFilteredReviewPayload();
  const reviewView = renderReviewView(payload);
  summaryShell.innerHTML = reviewView.summary;
  shell.innerHTML = reviewView.content;
}

function renderWorkspaceStatus(job) {
  const statusShell = document.getElementById("job-status");
  const actionsShell = document.getElementById("job-actions");
  if (!statusShell || !actionsShell) {
    return;
  }
  if (!job) {
    statusShell.innerHTML = '<div class="empty-state">请先在左侧载入任务。</div>';
    actionsShell.innerHTML = "";
    return;
  }

  const canTriggerParse = ["uploaded", "failed", "reviewing", "completed"].includes(job.status);
  statusShell.innerHTML = `
    ${renderJobSnapshot(job, "当前任务已经绑定到工作台，处理状态会自动刷新。")}
    <div class="action-row">
      <a class="button-link secondary" href="${escapeHtml(buildWorkspaceUrl(job.job_id, "status"))}">状态</a>
      <a class="button-link secondary" href="${escapeHtml(buildWorkspaceUrl(job.job_id, "results"))}">产出</a>
      <a class="button-link secondary" href="${escapeHtml(buildWorkspaceUrl(job.job_id, "review"))}">审核</a>
      <a class="button-link secondary" href="${escapeHtml(buildWorkspaceUrl(job.job_id, "export"))}">导出</a>
      <button
        type="button"
        class="danger"
        data-delete-job-id="${escapeHtml(job.job_id)}"
        data-delete-job-name="${escapeHtml(job.file_name)}"
      >
        删除任务
      </button>
      ${
        canTriggerParse
          ? `<button type="button" id="workspace-parse-trigger" ${["reviewing", "completed"].includes(job.status) ? 'data-force="true"' : ""}>
              ${["reviewing", "completed"].includes(job.status) ? "重新解析" : "开始解析"}
            </button>`
          : ""
      }
    </div>
  `;

  if (WORKSPACE_PROCESSING.has(job.status)) {
    actionsShell.innerHTML = '<div class="status-banner">任务仍在处理中，工作台会自动轮询刷新。</div>';
  } else if (job.status === "reviewing") {
    actionsShell.innerHTML = '<div class="status-banner">结果已经生成，可以直接切到“内容产出”或“审核面板”。</div>';
  } else if (job.error_message) {
    actionsShell.innerHTML = `<div class="inline-error">${escapeHtml(job.error_message)}</div>`;
  } else {
    actionsShell.innerHTML = "";
  }

  const trigger = document.getElementById("workspace-parse-trigger");
  if (trigger) {
    trigger.addEventListener("click", async () => {
      trigger.disabled = true;
      try {
        await triggerWorkspaceParse(trigger.dataset.force === "true");
      } finally {
        trigger.disabled = false;
      }
    });
  }
}

function updateSidebarCurrentJob(job) {
  const jobLabel = document.getElementById("workspace-current-job");
  const fileLabel = document.getElementById("workspace-current-file");
  const shareLink = document.getElementById("workspace-share-link");
  const practiceLink = document.getElementById("workspace-practice-link");
  const input = document.getElementById("job-id-input");

  if (input) {
    input.value = workspaceState.currentJobId || "";
  }

  if (!jobLabel || !fileLabel || !shareLink) {
    return;
  }

  if (!workspaceState.currentJobId) {
    jobLabel.textContent = "未选择任务";
    fileLabel.textContent = "可从最近任务直接载入，或先上传新的教材 PDF。";
    shareLink.href = "/";
    shareLink.textContent = "/?job_id=...";
    if (practiceLink) {
      practiceLink.href = "/practice";
    }
    return;
  }

  const currentFile = job?.file_name || "正在加载任务信息...";
  jobLabel.textContent = workspaceState.currentJobId;
  fileLabel.textContent = currentFile;
  shareLink.href = buildWorkspaceUrl(workspaceState.currentJobId, workspaceState.activeView);
  shareLink.textContent = shareLink.getAttribute("href");
  if (practiceLink) {
    practiceLink.href = `/practice?job_id=${encodeURIComponent(workspaceState.currentJobId)}`;
  }
}

function clearCurrentWorkspaceJobState(targetView = "overview") {
  workspaceState.currentJobId = "";
  workspaceState.job = null;
  workspaceState.result = null;
  workspaceState.unitFilter = "all";
  clearWorkspacePollTimer();
  updateSidebarCurrentJob(null);
  syncUnitFilterOptions();
  renderWorkspaceStatus(null);
  renderWorkspaceResultSection();
  renderWorkspaceReviewSection();
  switchWorkspaceView(targetView);
  updateWorkspaceUrl();
}

function clearWorkspacePollTimer() {
  if (workspaceState.pollTimer) {
    window.clearTimeout(workspaceState.pollTimer);
    workspaceState.pollTimer = null;
  }
}

function scheduleWorkspacePolling(job) {
  clearWorkspacePollTimer();
  if (!job || !WORKSPACE_PROCESSING.has(job.status)) {
    return;
  }
  workspaceState.pollTimer = window.setTimeout(() => {
    refreshWorkspaceCurrentJob().catch((error) => {
      setWorkspaceFeedback(error.message, "error");
    });
  }, 2500);
}

async function loadWorkspaceOverview() {
  const payload = await requestJson(`${WORKSPACE_CONFIG.apiPrefix}/overview?limit=500`);
  workspaceState.overview = payload;
  const displayJobs = sortWorkspaceRecentJobs(payload.recent_jobs || []);
  setHtml("overview-summary", renderOverviewSummary(payload));
  setHtml("overview-jobs", renderRecentJobsTable(displayJobs));
  setHtml("sidebar-recent-jobs", renderSidebarRecentJobs(displayJobs));
  setHtml("overview-exports", renderRecentExports(payload.recent_exports || []));
}

async function refreshWorkspaceCurrentJob(options = {}) {
  const { refreshOverview = false } = options;
  if (!workspaceState.currentJobId) {
    clearCurrentWorkspaceJobState("overview");
    if (refreshOverview) {
      await loadWorkspaceOverview();
    }
    return;
  }

  let job;
  try {
    job = await requestJson(`${WORKSPACE_CONFIG.apiPrefix}/jobs/${encodeURIComponent(workspaceState.currentJobId)}`);
  } catch (error) {
    if (error.status === 404) {
      const missingJobId = workspaceState.currentJobId;
      clearCurrentWorkspaceJobState("overview");
      if (refreshOverview) {
        await loadWorkspaceOverview();
      }
      setWorkspaceFeedback(`任务 ${missingJobId} 不存在，可能已被删除。`, "error");
      return;
    }
    throw error;
  }
  workspaceState.job = job;
  updateSidebarCurrentJob(job);
  renderWorkspaceStatus(job);

  if (job.status === "reviewing" || job.status === "completed") {
    try {
      workspaceState.result = await requestJson(
        `${WORKSPACE_CONFIG.apiPrefix}/results/${encodeURIComponent(workspaceState.currentJobId)}`,
      );
    } catch (error) {
      workspaceState.result = null;
      setWorkspaceFeedback(error.message, "error");
    }
  } else {
    workspaceState.result = null;
  }

  syncUnitFilterOptions();
  renderWorkspaceResultSection();
  renderWorkspaceReviewSection();
  scheduleWorkspacePolling(job);

  if (refreshOverview) {
    await loadWorkspaceOverview();
  }
}

function switchWorkspaceView(view) {
  if (!WORKSPACE_VIEWS.includes(view)) {
    return;
  }
  workspaceState.activeView = view;
  document.querySelectorAll("[data-workspace-view]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.workspaceView === view);
  });
  document.querySelectorAll("[data-workspace-panel]").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.workspacePanel === view);
  });
  updateWorkspaceUrl();
  updateSidebarCurrentJob(workspaceState.job);
}

function setCurrentWorkspaceJob(jobId, targetView = workspaceState.activeView) {
  workspaceState.currentJobId = jobId || "";
  updateSidebarCurrentJob(workspaceState.job);
  switchWorkspaceView(targetView);
  return refreshWorkspaceCurrentJob();
}

async function triggerWorkspaceParse(forceReparse = false) {
  if (!workspaceState.currentJobId) {
    setWorkspaceFeedback("请先载入任务。", "error");
    return;
  }
  setWorkspaceFeedback(forceReparse ? "正在重新提交当前教材，后台会重新解析..." : "正在提交后台解析任务...");
  switchWorkspaceView("status");
  window.setTimeout(() => {
    refreshWorkspaceCurrentJob().catch(() => undefined);
  }, 800);
  try {
    const job = await postJson(`${WORKSPACE_CONFIG.apiPrefix}/parse/${encodeURIComponent(workspaceState.currentJobId)}`, {
      force_reparse: forceReparse,
    });
    workspaceState.job = job;
    await refreshWorkspaceCurrentJob({ refreshOverview: true });
    setWorkspaceFeedback("后台任务已启动，工作台会自动刷新当前进度。");
  } catch (error) {
    await refreshWorkspaceCurrentJob({ refreshOverview: true });
    setWorkspaceFeedback(error.message, "error");
    throw error;
  }
}

async function deleteWorkspaceJob(jobId, jobName = "") {
  if (!jobId) {
    return;
  }
  const resolvedName = jobName || (workspaceState.currentJobId === jobId ? workspaceState.job?.file_name : "");
  const jobLabel = resolvedName ? `${resolvedName} (${jobId})` : jobId;
  const confirmed = window.confirm(`确认删除任务 ${jobLabel}？这会同时删除上传文件、解析结果、审核记录和导出文件。`);
  if (!confirmed) {
    return;
  }
  setWorkspaceFeedback(`正在删除任务 ${jobId} ...`);
  await requestJson(`${WORKSPACE_CONFIG.apiPrefix}/jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
  });
  if (workspaceState.currentJobId === jobId) {
    clearCurrentWorkspaceJobState("overview");
  }
  await loadWorkspaceOverview();
  setWorkspaceFeedback(`任务 ${jobId} 已删除。`);
}

function buildWorkspaceBatchTargets(unitPackage) {
  return [
    { target_type: "unit", target_id: unitPackage.unit.unit_id },
    ...(unitPackage.vocabulary || []).map((item) => ({ target_type: "vocabulary_item", target_id: item.item_id })),
    ...(unitPackage.sentence_patterns || []).map((item) => ({ target_type: "sentence_pattern", target_id: item.item_id })),
    ...(unitPackage.dialogue_samples || []).map((item) => ({ target_type: "dialogue_sample", target_id: item.item_id })),
    { target_type: "unit_task", target_id: unitPackage.unit_task.item_id },
    { target_type: "unit_prompt", target_id: unitPackage.unit_prompt.item_id },
  ];
}

function workspaceReviewRequestBody(reviewStatus) {
  return {
    review_status: reviewStatus,
    review_notes: document.getElementById("review-note")?.value.trim() || null,
    reviewer: document.getElementById("reviewer-name")?.value.trim() || null,
    patched_fields: {},
  };
}

async function handleWorkspaceReviewAction(button) {
  const targetType = button.dataset.reviewTargetType;
  const targetId = button.dataset.reviewTargetId;
  const reviewStatus = button.dataset.reviewStatus;
  const batchUnitId = button.dataset.batchUnitId;

  button.disabled = true;
  setText("review-feedback", "正在提交审核结果...");

  try {
    if (batchUnitId) {
      const unitPackage = workspaceState.result?.units?.find((item) => item.unit.unit_id === batchUnitId);
      if (!unitPackage) {
        throw new Error("找不到对应单元");
      }
      await postJson(`${WORKSPACE_CONFIG.apiPrefix}/review/units/${encodeURIComponent(batchUnitId)}/batch`, {
        review_status: reviewStatus,
        review_notes: document.getElementById("review-note")?.value.trim() || null,
        reviewer: document.getElementById("reviewer-name")?.value.trim() || null,
        targets: buildWorkspaceBatchTargets(unitPackage),
      });
    } else if (targetType && targetId && reviewStatus) {
      await patchJson(
        `${WORKSPACE_CONFIG.apiPrefix}/review/items/${encodeURIComponent(targetType)}/${encodeURIComponent(targetId)}`,
        workspaceReviewRequestBody(reviewStatus),
      );
    }
    await refreshWorkspaceCurrentJob({ refreshOverview: true });
    setText("review-feedback", "审核结果已更新。");
  } catch (error) {
    setText("review-feedback", error.message);
  } finally {
    button.disabled = false;
  }
}

async function handleWorkspaceExport(format, button) {
  if (!workspaceState.currentJobId) {
    setText("export-feedback", "请先载入任务。");
    return;
  }
  button.disabled = true;
  setText("export-feedback", "正在准备导出文件...");
  try {
    const selectedUnitIds = workspaceState.unitFilter === "all" ? [] : [workspaceState.unitFilter];
    const metadata = await postJson(`${WORKSPACE_CONFIG.apiPrefix}/export`, {
      job_id: workspaceState.currentJobId,
      format,
      approved_only: document.getElementById("export-approved-toggle")?.checked || false,
      export_scope: selectedUnitIds.length ? "unit" : "book",
      unit_ids: selectedUnitIds,
    });
    setHtml(
      "export-feedback",
      `导出完成：<a href="${escapeHtml(metadata.download_url)}">${escapeHtml(metadata.export_id)}</a>`,
    );
    await loadWorkspaceOverview();
  } catch (error) {
    const blockedCount = Array.isArray(error.details?.blocked_items) ? error.details.blocked_items.length : 0;
    setText(
      "export-feedback",
      blockedCount ? `${error.message}，仍有 ${blockedCount} 个条目未通过审核。` : error.message,
    );
  } finally {
    button.disabled = false;
  }
}

function bindWorkspaceEvents() {
  document.getElementById("workspace-nav")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-workspace-view]");
    if (!button) {
      return;
    }
    switchWorkspaceView(button.dataset.workspaceView);
  });

  document.getElementById("refresh-overview-button")?.addEventListener("click", async () => {
    try {
      setWorkspaceFeedback("正在刷新任务总览...");
      await loadWorkspaceOverview();
      setWorkspaceFeedback("任务总览已刷新。");
    } catch (error) {
      setWorkspaceFeedback(error.message, "error");
    }
  });

  document.getElementById("refresh-current-button")?.addEventListener("click", async () => {
    try {
      setWorkspaceFeedback("正在刷新当前任务...");
      await refreshWorkspaceCurrentJob({ refreshOverview: true });
      setWorkspaceFeedback("当前任务已刷新。");
    } catch (error) {
      setWorkspaceFeedback(error.message, "error");
    }
  });

  const loadCurrentJob = async () => {
    const jobId = document.getElementById("job-id-input")?.value.trim() || "";
    if (!jobId) {
      setWorkspaceFeedback("请输入任务 ID。", "error");
      return;
    }
    try {
      setWorkspaceFeedback(`正在载入任务 ${jobId} ...`);
      await setCurrentWorkspaceJob(jobId, "status");
      setWorkspaceFeedback(`任务 ${jobId} 已载入工作台。`);
    } catch (error) {
      setWorkspaceFeedback(error.message, "error");
    }
  };

  document.getElementById("load-job-button")?.addEventListener("click", () => {
    loadCurrentJob().catch(() => undefined);
  });
  document.getElementById("job-id-input")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      loadCurrentJob().catch(() => undefined);
    }
  });

  document.getElementById("clear-job-button")?.addEventListener("click", async () => {
    clearCurrentWorkspaceJobState("overview");
    setWorkspaceFeedback("");
  });

  document.getElementById("delete-current-job-button")?.addEventListener("click", () => {
    if (!workspaceState.currentJobId) {
      setWorkspaceFeedback("当前没有已载入任务。", "error");
      return;
    }
    deleteWorkspaceJob(workspaceState.currentJobId, workspaceState.job?.file_name || "").catch((error) => {
      setWorkspaceFeedback(error.message, "error");
    });
  });

  document.body.addEventListener("click", (event) => {
    const deleteButton = event.target.closest("[data-delete-job-id]");
    if (deleteButton) {
      deleteWorkspaceJob(deleteButton.dataset.deleteJobId, deleteButton.dataset.deleteJobName || "").catch((error) => {
        setWorkspaceFeedback(error.message, "error");
      });
      return;
    }

    const button = event.target.closest("[data-load-job-id]");
    if (!button) {
      return;
    }
    const jobId = button.dataset.loadJobId;
    const targetView = button.dataset.targetView || "status";
    setWorkspaceFeedback(`正在载入任务 ${jobId} ...`);
    setCurrentWorkspaceJob(jobId, targetView)
      .then(() => {
        setWorkspaceFeedback(`任务 ${jobId} 已载入工作台。`);
      })
      .catch((error) => {
        setWorkspaceFeedback(error.message, "error");
      });
  });

  document.getElementById("workspace-unit-filter")?.addEventListener("change", (event) => {
    workspaceState.unitFilter = event.target.value || "all";
    renderWorkspaceResultSection();
    renderWorkspaceReviewSection();
    setText("export-feedback", workspaceState.unitFilter === "all" ? "" : "导出会限制为当前选中的单元。");
  });

  document.getElementById("result-approved-toggle")?.addEventListener("change", () => {
    renderWorkspaceResultSection();
  });

  document.getElementById("review-shell")?.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) {
      return;
    }
    if (button.dataset.reviewTargetType || button.dataset.batchUnitId) {
      handleWorkspaceReviewAction(button).catch(() => undefined);
    }
  });

  document.querySelectorAll("[data-workspace-export-format]").forEach((button) => {
    button.addEventListener("click", () => {
      handleWorkspaceExport(button.dataset.workspaceExportFormat, button).catch(() => undefined);
    });
  });

  document.getElementById("upload-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = document.getElementById("pdf-file")?.files?.[0];
    if (!file) {
      setText("upload-stage", "请先选择 PDF 文件");
      return;
    }

    const maxUploadSizeMb = Number(WORKSPACE_CONFIG.maxUploadSizeMb || 0);
    if (maxUploadSizeMb > 0 && file.size > maxUploadSizeMb * 1024 * 1024) {
      setText("upload-stage", "文件超过上传上限");
      setHtml(
        "upload-summary",
        `<div class="inline-error">当前文件大小 ${escapeHtml(formatFileSize(file.size))}，已超过当前上限 ${escapeHtml(String(maxUploadSizeMb))} MB。</div>`,
      );
      setHtml("upload-links", "");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    setText("upload-stage", "正在上传并创建任务...");
    setHtml("upload-summary", '<div class="loading-state">上传成功后，系统会先完成 PDF 预检，再启动整本教材解析。</div>');
    setHtml("upload-links", "");
    setWorkspaceFeedback("正在上传教材并创建任务...");

    try {
      const job = await requestJson(`${WORKSPACE_CONFIG.apiPrefix}/upload`, {
        method: "POST",
        body: formData,
      });
      workspaceState.currentJobId = job.job_id;
      workspaceState.job = job;
      updateSidebarCurrentJob(job);
      switchWorkspaceView("status");
      setText("upload-stage", "上传完成，正在读取预检结果...");
      setHtml("upload-summary", renderJobSnapshot(job, "任务已创建，已完成 PDF 预检，工作台会自动轮询当前处理进度。"));
      setHtml(
        "upload-links",
        `
          <a class="button-link secondary" href="${escapeHtml(buildWorkspaceUrl(job.job_id, "status"))}">查看状态</a>
          <a class="button-link secondary" href="${escapeHtml(buildWorkspaceUrl(job.job_id, "results"))}">查看产出</a>
          <a class="button-link secondary" href="${escapeHtml(buildWorkspaceUrl(job.job_id, "review"))}">查看审核</a>
        `,
      );
      await loadWorkspaceOverview();
      window.setTimeout(() => {
        refreshWorkspaceCurrentJob().catch(() => undefined);
      }, 800);
      await triggerWorkspaceParse(false);
      setText("upload-stage", "后台任务已启动，正在解析教材...");
      setWorkspaceFeedback("当前教材已进入后台处理，工作台会自动刷新状态。");
      switchWorkspaceView("status");
    } catch (error) {
      setText("upload-stage", "处理失败");
      const limitMb = error.details?.limit_mb;
      const actualMb = error.details?.actual_mb;
      setHtml(
        "upload-summary",
        `<div class="inline-error">${escapeHtml(error.message)}</div>${
          limitMb && actualMb
            ? `<p class="meta-text">当前文件约 ${escapeHtml(String(actualMb))} MB，系统上限 ${escapeHtml(String(limitMb))} MB。</p>`
            : ""
        }`,
      );
      setWorkspaceFeedback(error.message, "error");
    }
  });
}

async function initWorkspacePage() {
  if (WORKSPACE_CONFIG.page !== "workspace") {
    return;
  }
  bindWorkspaceEvents();
  switchWorkspaceView(workspaceState.activeView);
  updateSidebarCurrentJob(null);
  try {
    await loadWorkspaceOverview();
    if (workspaceState.currentJobId) {
      await refreshWorkspaceCurrentJob();
      setWorkspaceFeedback(`任务 ${workspaceState.currentJobId} 已载入工作台。`);
    }
  } catch (error) {
    setWorkspaceFeedback(error.message, "error");
  }
}

initWorkspacePage().catch(() => undefined);
