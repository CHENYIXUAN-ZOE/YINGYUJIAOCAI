const PRACTICE_CONFIG = window.APP_CONFIG || {};

let practiceMessageSequence = 0;

const practiceState = {
  jobs: [],
  units: [],
  context: null,
  selectedJobId: PRACTICE_CONFIG.initialJobId || "",
  selectedUnitId: PRACTICE_CONFIG.initialUnitId || "",
  loadingJobs: false,
  loadingContext: false,
  prompt: {
    defaultTemplate: "",
    currentTemplate: "",
    finalPrompt: "",
    finalInstruction: "",
    dirty: false,
  },
  chat: {
    started: false,
    sending: false,
    messages: [],
    roundCount: 0,
    statusHint: "",
    input: "",
  },
  support: {
    activeTab: "tips",
    selectedTipMessageId: "",
    report: null,
    loadingReport: false,
  },
};

function practiceStorageKey(gradeBand) {
  if (!gradeBand) {
    return "";
  }
  return `practice_prompt_draft_${String(gradeBand).replaceAll("-", "_")}`;
}

function loadPromptDraft(gradeBand) {
  const key = practiceStorageKey(gradeBand);
  if (!key) {
    return "";
  }
  try {
    return window.localStorage.getItem(key) || "";
  } catch (_) {
    return "";
  }
}

function savePromptDraft(gradeBand, value) {
  const key = practiceStorageKey(gradeBand);
  if (!key) {
    return;
  }
  try {
    window.localStorage.setItem(key, value);
  } catch (_) {
    // Ignore localStorage write failures.
  }
}

function setPracticeFeedback(message, tone = "status") {
  const shell = document.getElementById("practice-feedback");
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

function practiceGradeLabel(gradeBand) {
  if (gradeBand === "3-4") {
    return "3-4年级";
  }
  if (gradeBand === "5-6") {
    return "5-6年级";
  }
  return "未识别";
}

function formatPracticeContextBlock(context) {
  if (!context) {
    return "";
  }
  const lines = ["Current unit context:"];
  lines.push(`- Textbook: ${context.job.file_name.replace(/\.pdf$/i, "")}`);
  lines.push(`- Unit: ${context.unit.unit_code} - ${context.unit.unit_name}`);
  lines.push(`- Unit theme: ${context.unit.unit_theme || context.unit.unit_name}`);
  lines.push(`- Key vocabulary: ${(context.summary.vocabulary || []).join(", ")}`);
  lines.push(`- Key sentence patterns: ${(context.summary.sentence_patterns || []).join(" | ")}`);
  if (context.unit.unit_task) {
    lines.push(`- Optional unit task: ${context.unit.unit_task}`);
  }
  return lines.join("\n");
}

function buildPracticeFinalPrompt() {
  if (!practiceState.context) {
    return "";
  }
  const template = (practiceState.prompt.currentTemplate || "").trim();
  if (!template) {
    return "";
  }
  const parts = [template, formatPracticeContextBlock(practiceState.context)];
  if (practiceState.prompt.finalInstruction) {
    parts.push(practiceState.prompt.finalInstruction.trim());
  }
  return parts.filter(Boolean).join("\n\n").trim();
}

function nextPracticeMessageId() {
  practiceMessageSequence += 1;
  return `practice_msg_${practiceMessageSequence}`;
}

function createPracticeMessage(role, content, extras = {}) {
  return {
    id: nextPracticeMessageId(),
    role,
    content,
    turnTip: null,
    ...extras,
  };
}

function serializePracticeMessages() {
  return practiceState.chat.messages.map((message) => ({
    role: message.role,
    content: message.content,
  }));
}

function availableTipMessages() {
  return practiceState.chat.messages.filter((message) => message.role === "user" && message.turnTip?.has_tip);
}

function selectedTipMessage() {
  if (!practiceState.support.selectedTipMessageId) {
    return null;
  }
  return (
    practiceState.chat.messages.find((message) => message.id === practiceState.support.selectedTipMessageId && message.turnTip?.has_tip) ||
    null
  );
}

function renderPracticeSummary(context) {
  if (!context) {
    return '<div class="empty-state compact-empty">选择单元后，这里会显示单元主题、任务、重点词汇和重点句型。</div>';
  }
  return `
    <div class="practice-summary-card">
      <div class="practice-summary-block">
        <span class="meta-label">单元主题</span>
        <strong>${escapeHtml(context.unit.unit_theme || context.unit.unit_name)}</strong>
      </div>
      ${
        context.unit.unit_task
          ? `
            <div class="practice-summary-block">
              <span class="meta-label">单元任务</span>
              <strong>${escapeHtml(context.unit.unit_task)}</strong>
            </div>
          `
          : ""
      }
      <div class="practice-summary-block">
        <span class="meta-label">重点词汇</span>
        <div class="practice-tag-list">
          ${(context.summary.vocabulary || []).map((item) => `<span class="practice-tag">${escapeHtml(item)}</span>`).join("")}
        </div>
      </div>
      <div class="practice-summary-block">
        <span class="meta-label">重点句型</span>
        <div class="practice-tag-list">
          ${(context.summary.sentence_patterns || []).map((item) => `<span class="practice-tag">${escapeHtml(item)}</span>`).join("")}
        </div>
      </div>
    </div>
  `;
}

function renderPracticeMessages() {
  if (!practiceState.chat.messages.length) {
    return '<div class="empty-state">请选择单元并点击“开始测试”，由 AI 先开场。</div>';
  }
  return `
    <div class="practice-message-list">
      ${practiceState.chat.messages
        .map((message) => {
          const hasTip = message.role === "user" && message.turnTip?.has_tip;
          const isSelectedTip = hasTip && practiceState.support.selectedTipMessageId === message.id;
          return `
            <article class="practice-bubble practice-bubble-${escapeHtml(message.role)}${hasTip ? " has-tip" : ""}${isSelectedTip ? " is-tip-action-visible" : ""}">
              <div class="practice-bubble-head">
                <span class="practice-bubble-role">${message.role === "assistant" ? "AI Teacher" : "Student"}</span>
                ${
                  hasTip
                    ? `<button
                        type="button"
                        class="practice-tip-button${isSelectedTip ? " is-active" : ""}"
                        data-tip-message-id="${escapeHtml(message.id)}"
                      >tips${message.turnTip.tips?.length > 1 ? ` ${message.turnTip.tips.length}` : ""}</button>`
                    : ""
                }
              </div>
              <p>${escapeHtml(message.content)}</p>
            </article>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderPracticeTipsPanel() {
  const tipMessages = availableTipMessages();
  const selectedMessage = selectedTipMessage();
  if (!tipMessages.length) {
    return '<div class="empty-state compact-empty">学生回答后，如果这一轮有有价值的提示，这里会显示对应的轻提示。</div>';
  }
  if (!selectedMessage) {
    return `<div class="empty-state compact-empty">当前共有 ${tipMessages.length} 条 tips，点击对话中的 tips 图标查看。</div>`;
  }
  return `
    <div class="practice-insight-card-list">
      <article class="practice-insight-card">
        <span class="meta-label">对应学生回答</span>
        <p class="practice-insight-quote">${escapeHtml(selectedMessage.content)}</p>
      </article>
      ${(selectedMessage.turnTip.tips || [])
        .map(
          (tip) => `
            <article class="practice-insight-card">
              <h4>${escapeHtml(tip.title || "这一步可以试试")}</h4>
              ${tip.message_cn ? `<p>${escapeHtml(tip.message_cn)}</p>` : ""}
              ${tip.example_en ? `<div class="practice-example-block"><span class="meta-label">英文参考</span><strong>${escapeHtml(tip.example_en)}</strong></div>` : ""}
              ${tip.reason_cn ? `<p class="meta-text">${escapeHtml(tip.reason_cn)}</p>` : ""}
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderPatternProgress(patternProgress) {
  if (!Array.isArray(patternProgress) || !patternProgress.length) {
    return "";
  }
  return `
    <div class="practice-insight-card">
      <h4>重点句型使用情况</h4>
      <div class="practice-report-list">
        ${patternProgress
          .map(
            (item) => `
              <article class="practice-report-item">
                <strong>${escapeHtml(item.pattern || "")}</strong>
                ${item.note_cn ? `<p class="meta-text">${escapeHtml(item.note_cn)}</p>` : ""}
              </article>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderStringListCard(title, items) {
  if (!Array.isArray(items) || !items.length) {
    return "";
  }
  return `
    <article class="practice-insight-card">
      <h4>${escapeHtml(title)}</h4>
      <div class="practice-report-list">
        ${items.map((item) => `<p class="practice-report-item">${escapeHtml(item)}</p>`).join("")}
      </div>
    </article>
  `;
}

function renderPracticeReportPanel() {
  if (practiceState.support.loadingReport) {
    return '<div class="empty-state compact-empty">正在生成对话报告...</div>';
  }
  if (!practiceState.support.report) {
    return '<div class="empty-state compact-empty">完成几轮对话后，点击“查看对话报告”生成本次练习的总结。</div>';
  }
  const report = practiceState.support.report;
  return `
    <div class="practice-insight-card-list">
      <article class="practice-insight-card">
        <h4>本次总结</h4>
        <p>${escapeHtml(report.summary || "本次对话已经围绕当前单元展开。")}</p>
      </article>
      ${renderStringListCard("本次亮点", report.strengths)}
      ${renderStringListCard("可以继续加强", report.improvements)}
      ${renderPatternProgress(report.pattern_progress)}
      ${renderStringListCard("后续建议", report.next_steps)}
    </div>
  `;
}

function renderPracticeInsightPanel() {
  return practiceState.support.activeTab === "report" ? renderPracticeReportPanel() : renderPracticeTipsPanel();
}

function syncPracticeLinks() {
  const resultLink = document.getElementById("practice-result-link");
  const reviewLink = document.getElementById("practice-review-link");
  const openResult = document.getElementById("practice-open-result");
  const openReview = document.getElementById("practice-open-review");
  const jobId = practiceState.selectedJobId;
  const resultHref = jobId ? `/results/${encodeURIComponent(jobId)}` : "/overview";
  const reviewHref = jobId ? `/review/${encodeURIComponent(jobId)}` : "/overview";

  for (const node of [resultLink, openResult]) {
    if (node) {
      node.href = resultHref;
    }
  }
  for (const node of [reviewLink, openReview]) {
    if (node) {
      node.href = reviewHref;
    }
  }
}

function renderPracticePage() {
  const context = practiceState.context;
  const jobSelect = document.getElementById("practice-job-select");
  const unitSelect = document.getElementById("practice-unit-select");
  const promptInput = document.getElementById("practice-prompt-template");
  const finalPromptInput = document.getElementById("practice-final-prompt");
  const currentJob = document.getElementById("practice-current-job");
  const currentUnit = document.getElementById("practice-current-unit");
  const providerStatus = document.getElementById("practice-provider-status");
  const gradeBadge = document.getElementById("practice-grade-badge");
  const summaryShell = document.getElementById("practice-summary-shell");
  const chatShell = document.getElementById("practice-chat-shell");
  const insightShell = document.getElementById("practice-insight-shell");
  const insightCaption = document.getElementById("practice-insight-caption");
  const statusHint = document.getElementById("practice-status-hint");
  const studentInput = document.getElementById("practice-student-input");
  const sessionStatus = document.getElementById("practice-session-status");
  const roundLabel = document.getElementById("practice-round-label");
  const startButton = document.getElementById("practice-start-button");
  const sendButton = document.getElementById("practice-send-button");
  const resetButton = document.getElementById("practice-reset-chat-button");
  const restoreButton = document.getElementById("practice-restore-prompt-button");
  const clearInputButton = document.getElementById("practice-clear-input-button");
  const reportButton = document.getElementById("practice-report-button");
  const reportTrigger = document.getElementById("practice-report-trigger");
  const tipTabButton = document.getElementById("practice-tab-tips");
  const reportTabButton = document.getElementById("practice-tab-report");

  if (jobSelect) {
    jobSelect.innerHTML = [
      '<option value="">请选择项目</option>',
      ...practiceState.jobs.map(
        (job) =>
          `<option value="${escapeHtml(job.job_id)}"${job.job_id === practiceState.selectedJobId ? " selected" : ""}>${escapeHtml(job.file_name)} · ${escapeHtml(job.job_id)}</option>`,
      ),
    ].join("");
    jobSelect.disabled = practiceState.loadingJobs || !practiceState.jobs.length;
  }

  if (unitSelect) {
    unitSelect.innerHTML = [
      `<option value="">${practiceState.selectedJobId ? "请选择单元" : "请先选择项目"}</option>`,
      ...practiceState.units.map(
        (unitPackage) =>
          `<option value="${escapeHtml(unitPackage.unit.unit_id)}"${unitPackage.unit.unit_id === practiceState.selectedUnitId ? " selected" : ""}>${escapeHtml(
            `${unitPackage.unit.classification.unit_code} · ${unitPackage.unit.classification.unit_name}`,
          )}</option>`,
      ),
    ].join("");
    unitSelect.disabled = !practiceState.selectedJobId || !practiceState.units.length;
  }

  if (promptInput) {
    promptInput.value = practiceState.prompt.currentTemplate;
    promptInput.disabled = !context || practiceState.chat.sending;
  }

  if (finalPromptInput) {
    finalPromptInput.value = practiceState.prompt.finalPrompt;
  }

  if (currentJob) {
    currentJob.textContent = context ? context.job.file_name : practiceState.selectedJobId || "未选择项目";
  }
  if (currentUnit) {
    currentUnit.textContent = context
      ? `${context.unit.unit_code} · ${context.unit.unit_name}`
      : "请选择一个已完成内容生成的项目和单元。";
  }
  if (providerStatus) {
    providerStatus.textContent = context
      ? context.provider.configured
        ? `${context.provider.name || "provider"} 已配置${context.provider.model ? ` · ${context.provider.model}` : ""}`.trim()
        : `${context.provider.name || "provider"} 未配置，当前无法开始测试。`
      : "选择单元后检查模型配置。";
  }
  if (gradeBadge) {
    gradeBadge.textContent = context ? `自动识别：${practiceGradeLabel(context.grade_band)}` : "未识别";
  }
  if (summaryShell) {
    summaryShell.innerHTML = renderPracticeSummary(context);
  }
  if (chatShell) {
    chatShell.innerHTML = renderPracticeMessages();
  }
  if (insightShell) {
    insightShell.innerHTML = renderPracticeInsightPanel();
  }
  if (insightCaption) {
    if (practiceState.support.activeTab === "report") {
      insightCaption.textContent = "对话结束后，可在这里查看本次练习的总结与后续建议。";
    } else if (practiceState.support.selectedTipMessageId) {
      insightCaption.textContent = "当前正在查看这条学生回答对应的轻提示。";
    } else {
      insightCaption.textContent = "点击学生消息旁的 tips 按钮查看轻提示。";
    }
  }
  if (tipTabButton) {
    tipTabButton.classList.toggle("is-active", practiceState.support.activeTab === "tips");
  }
  if (reportTabButton) {
    reportTabButton.classList.toggle("is-active", practiceState.support.activeTab === "report");
  }
  if (statusHint) {
    statusHint.textContent = practiceState.chat.statusHint;
    statusHint.classList.toggle("is-visible", Boolean(practiceState.chat.statusHint));
  }
  if (studentInput) {
    studentInput.value = practiceState.chat.input;
    studentInput.disabled = !practiceState.chat.started || practiceState.chat.sending;
  }
  if (sessionStatus) {
    const statusText = practiceState.chat.sending
      ? "运行中"
      : practiceState.chat.started
        ? "对话中"
        : "未开始";
    sessionStatus.textContent = statusText;
    sessionStatus.className = `status-pill ${practiceState.chat.started ? "review-approved" : "review-pending"}`;
  }
  if (roundLabel) {
    roundLabel.textContent = `当前轮次 ${practiceState.chat.roundCount} / 目标 7-8轮`;
  }

  const canStart =
    Boolean(context) && Boolean(practiceState.prompt.finalPrompt) && Boolean(context.provider?.configured) && !practiceState.chat.sending;
  const canSend = practiceState.chat.started && Boolean(practiceState.chat.input.trim()) && !practiceState.chat.sending;
  const canReport = !practiceState.chat.sending && practiceState.chat.roundCount > 0;

  if (startButton) {
    startButton.disabled = !canStart;
    startButton.textContent = practiceState.chat.sending && !practiceState.chat.started ? "正在生成开场语..." : "开始测试";
  }
  if (sendButton) {
    sendButton.disabled = !canSend;
    sendButton.textContent = practiceState.chat.sending && practiceState.chat.started ? "AI 正在回复..." : "发送";
  }
  if (resetButton) {
    resetButton.disabled = practiceState.chat.sending || !practiceState.chat.messages.length;
  }
  if (restoreButton) {
    restoreButton.disabled = !context || practiceState.chat.sending;
  }
  if (clearInputButton) {
    clearInputButton.disabled = practiceState.chat.sending || !practiceState.chat.input;
  }
  if (reportButton) {
    reportButton.disabled = !canReport || practiceState.support.loadingReport;
    reportButton.textContent = practiceState.support.loadingReport ? "正在生成报告..." : "生成对话报告";
  }
  if (reportTrigger) {
    reportTrigger.disabled = !canReport || practiceState.support.loadingReport;
    reportTrigger.textContent = practiceState.support.loadingReport ? "正在生成报告..." : "查看对话报告";
  }

  syncPracticeLinks();
}

function resetPracticeSupport() {
  practiceState.support = {
    activeTab: "tips",
    selectedTipMessageId: "",
    report: null,
    loadingReport: false,
  };
}

function resetPracticeChat() {
  practiceMessageSequence = 0;
  practiceState.chat = {
    started: false,
    sending: false,
    messages: [],
    roundCount: 0,
    statusHint: "",
    input: "",
  };
  resetPracticeSupport();
}

async function loadPracticeJobs() {
  practiceState.loadingJobs = true;
  renderPracticePage();
  try {
    const overview = await requestJson(`${PRACTICE_CONFIG.apiPrefix}/overview?limit=20`);
    practiceState.jobs = (overview.recent_jobs || []).filter((job) => job.has_result);
  } finally {
    practiceState.loadingJobs = false;
    renderPracticePage();
  }
}

async function loadPracticeUnits(jobId) {
  practiceState.units = [];
  practiceState.context = null;
  practiceState.prompt = {
    defaultTemplate: "",
    currentTemplate: "",
    finalPrompt: "",
    finalInstruction: "",
    dirty: false,
  };
  resetPracticeChat();
  renderPracticePage();

  if (!jobId) {
    return;
  }

  const payload = await requestJson(
    `${PRACTICE_CONFIG.apiPrefix}/results/${encodeURIComponent(jobId)}?include_review_records=false`,
  );
  practiceState.units = payload.units || [];

  if (practiceState.selectedUnitId && practiceState.units.some((item) => item.unit.unit_id === practiceState.selectedUnitId)) {
    await loadPracticeContext(jobId, practiceState.selectedUnitId);
  } else {
    practiceState.selectedUnitId = "";
    renderPracticePage();
  }
}

async function loadPracticeContext(jobId, unitId) {
  if (!jobId || !unitId) {
    practiceState.context = null;
    practiceState.prompt = {
      defaultTemplate: "",
      currentTemplate: "",
      finalPrompt: "",
      finalInstruction: "",
      dirty: false,
    };
    resetPracticeChat();
    renderPracticePage();
    return;
  }

  practiceState.loadingContext = true;
  resetPracticeChat();
  setPracticeFeedback("正在加载单元摘要与默认 Prompt...");
  try {
    const context = await requestJson(
      `${PRACTICE_CONFIG.apiPrefix}/practice/context?job_id=${encodeURIComponent(jobId)}&unit_id=${encodeURIComponent(unitId)}`,
    );
    practiceState.context = context;
    const draft = loadPromptDraft(context.grade_band);
    practiceState.prompt.defaultTemplate = context.prompt.default_template || "";
    practiceState.prompt.currentTemplate = draft || context.prompt.default_template || "";
    practiceState.prompt.finalInstruction = context.prompt.final_instruction || "";
    practiceState.prompt.dirty = Boolean(draft);
    practiceState.prompt.finalPrompt = buildPracticeFinalPrompt();
    setPracticeFeedback("");
  } catch (error) {
    practiceState.context = null;
    practiceState.prompt.finalPrompt = "";
    setPracticeFeedback(error.message, "error");
  } finally {
    practiceState.loadingContext = false;
    renderPracticePage();
  }
}

function handlePracticePromptInput(value) {
  practiceState.prompt.currentTemplate = value;
  practiceState.prompt.dirty = value !== practiceState.prompt.defaultTemplate;
  practiceState.prompt.finalPrompt = buildPracticeFinalPrompt();
  if (practiceState.context) {
    savePromptDraft(practiceState.context.grade_band, value);
  }
  renderPracticePage();
}

async function startPracticeConversation() {
  if (!practiceState.context || !practiceState.prompt.finalPrompt || practiceState.chat.sending) {
    return;
  }
  practiceState.chat.sending = true;
  renderPracticePage();
  setPracticeFeedback("正在生成开场语...");

  try {
    const response = await postJson(`${PRACTICE_CONFIG.apiPrefix}/practice/chat`, {
      job_id: practiceState.selectedJobId,
      unit_id: practiceState.selectedUnitId,
      grade_band: practiceState.context.grade_band,
      prompt_template: practiceState.prompt.currentTemplate,
      final_prompt: practiceState.prompt.finalPrompt,
      messages: [],
      student_message: "",
      is_opening_turn: true,
    });
    practiceState.chat.started = true;
    practiceState.chat.messages = [createPracticeMessage("assistant", response.assistant_message.content)];
    practiceState.chat.roundCount = response.round_count || 0;
    practiceState.chat.statusHint = response.status_hint || "";
    setPracticeFeedback("");
  } catch (error) {
    setPracticeFeedback(error.message, "error");
  } finally {
    practiceState.chat.sending = false;
    renderPracticePage();
  }
}

async function sendPracticeStudentMessage() {
  const studentMessage = practiceState.chat.input.trim();
  if (!practiceState.context || !practiceState.chat.started || !studentMessage || practiceState.chat.sending) {
    return;
  }
  practiceState.chat.sending = true;
  renderPracticePage();
  setPracticeFeedback("AI 正在回复...");

  try {
    const response = await postJson(`${PRACTICE_CONFIG.apiPrefix}/practice/chat`, {
      job_id: practiceState.selectedJobId,
      unit_id: practiceState.selectedUnitId,
      grade_band: practiceState.context.grade_band,
      prompt_template: practiceState.prompt.currentTemplate,
      final_prompt: practiceState.prompt.finalPrompt,
      messages: serializePracticeMessages(),
      student_message: studentMessage,
      is_opening_turn: false,
    });
    const userMessage = createPracticeMessage("user", studentMessage, { turnTip: response.turn_tip || null });
    const assistantMessage = createPracticeMessage("assistant", response.assistant_message.content);
    practiceState.chat.messages = [...practiceState.chat.messages, userMessage, assistantMessage];
    practiceState.chat.input = "";
    practiceState.chat.roundCount = response.round_count || practiceState.chat.roundCount + 1;
    practiceState.chat.statusHint = response.status_hint || "";
    practiceState.support.report = null;
    setPracticeFeedback("");
  } catch (error) {
    setPracticeFeedback(error.message, "error");
  } finally {
    practiceState.chat.sending = false;
    renderPracticePage();
  }
}

async function loadPracticeReport() {
  if (!practiceState.context || practiceState.support.loadingReport || practiceState.chat.roundCount <= 0) {
    return;
  }
  practiceState.support.activeTab = "report";
  practiceState.support.loadingReport = true;
  renderPracticePage();
  try {
    const report = await postJson(`${PRACTICE_CONFIG.apiPrefix}/practice/report`, {
      job_id: practiceState.selectedJobId,
      unit_id: practiceState.selectedUnitId,
      messages: serializePracticeMessages(),
    });
    practiceState.support.report = report;
    setPracticeFeedback("");
  } catch (error) {
    practiceState.support.activeTab = "tips";
    setPracticeFeedback(error.message, "error");
  } finally {
    practiceState.support.loadingReport = false;
    renderPracticePage();
  }
}

function bindPracticeEvents() {
  document.getElementById("practice-job-select")?.addEventListener("change", async (event) => {
    practiceState.selectedJobId = event.target.value;
    practiceState.selectedUnitId = "";
    setPracticeFeedback("");
    try {
      await loadPracticeUnits(practiceState.selectedJobId);
    } catch (error) {
      setPracticeFeedback(error.message, "error");
      renderPracticePage();
    }
  });

  document.getElementById("practice-unit-select")?.addEventListener("change", async (event) => {
    practiceState.selectedUnitId = event.target.value;
    setPracticeFeedback("");
    try {
      await loadPracticeContext(practiceState.selectedJobId, practiceState.selectedUnitId);
    } catch (error) {
      setPracticeFeedback(error.message, "error");
      renderPracticePage();
    }
  });

  document.getElementById("practice-prompt-template")?.addEventListener("input", (event) => {
    handlePracticePromptInput(event.target.value);
  });

  document.getElementById("practice-student-input")?.addEventListener("input", (event) => {
    practiceState.chat.input = event.target.value;
    renderPracticePage();
  });

  document.getElementById("practice-start-button")?.addEventListener("click", () => {
    startPracticeConversation().catch((error) => {
      setPracticeFeedback(error.message, "error");
    });
  });

  document.getElementById("practice-send-button")?.addEventListener("click", () => {
    sendPracticeStudentMessage().catch((error) => {
      setPracticeFeedback(error.message, "error");
    });
  });

  document.getElementById("practice-reset-chat-button")?.addEventListener("click", () => {
    resetPracticeChat();
    setPracticeFeedback("");
    renderPracticePage();
  });

  document.getElementById("practice-restore-prompt-button")?.addEventListener("click", () => {
    if (!practiceState.context) {
      return;
    }
    if (practiceState.prompt.dirty) {
      const confirmed = window.confirm("确认恢复当前年级段的默认 Prompt 吗？当前修改将被覆盖。");
      if (!confirmed) {
        return;
      }
    }
    practiceState.prompt.currentTemplate = practiceState.prompt.defaultTemplate;
    practiceState.prompt.dirty = false;
    practiceState.prompt.finalPrompt = buildPracticeFinalPrompt();
    savePromptDraft(practiceState.context.grade_band, practiceState.prompt.currentTemplate);
    renderPracticePage();
  });

  document.getElementById("practice-clear-input-button")?.addEventListener("click", () => {
    practiceState.chat.input = "";
    renderPracticePage();
  });

  document.getElementById("practice-chat-shell")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-tip-message-id]");
    if (button) {
      practiceState.support.activeTab = "tips";
      practiceState.support.selectedTipMessageId = button.dataset.tipMessageId || "";
      renderPracticePage();
    }
  });

  document.getElementById("practice-tab-tips")?.addEventListener("click", () => {
    practiceState.support.activeTab = "tips";
    renderPracticePage();
  });

  document.getElementById("practice-tab-report")?.addEventListener("click", () => {
    if (practiceState.chat.roundCount > 0 && !practiceState.support.report) {
      loadPracticeReport().catch((error) => {
        setPracticeFeedback(error.message, "error");
      });
      return;
    }
    practiceState.support.activeTab = "report";
    renderPracticePage();
  });

  const triggerReport = () => {
    loadPracticeReport().catch((error) => {
      setPracticeFeedback(error.message, "error");
    });
  };
  document.getElementById("practice-report-button")?.addEventListener("click", triggerReport);
  document.getElementById("practice-report-trigger")?.addEventListener("click", triggerReport);
}

async function initPracticePage() {
  bindPracticeEvents();
  renderPracticePage();
  try {
    await loadPracticeJobs();
    if (practiceState.selectedJobId) {
      await loadPracticeUnits(practiceState.selectedJobId);
    }
  } catch (error) {
    setPracticeFeedback(error.message, "error");
  }
}

initPracticePage().catch((error) => {
  setPracticeFeedback(error.message, "error");
});
