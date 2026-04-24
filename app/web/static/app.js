const APP_CONFIG = window.APP_CONFIG || {};

const STATUS_LABELS = {
  uploaded: "已上传",
  queued: "排队中",
  parsing: "解析中",
  structuring: "结构化中",
  generating: "生成中",
  reviewing: "待审核",
  completed: "已完成",
  failed: "失败",
};

const REVIEW_LABELS = {
  pending: "待审核",
  approved: "已通过",
  rejected: "已驳回",
  revised: "已返修",
};

const PROCESSING_STATUSES = new Set(["queued", "parsing", "structuring", "generating"]);

let reviewPayloadCache = null;
let jobPollTimer = null;

function formatFileSize(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 MB";
  }
  const mb = bytes / 1024 / 1024;
  if (mb >= 100) {
    return `${mb.toFixed(0)} MB`;
  }
  if (mb >= 1) {
    return `${mb.toFixed(1)} MB`;
  }
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDateTime(value) {
  if (!value) {
    return "暂未完成";
  }
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));
  } catch (_) {
    return value;
  }
}

function statusBadge(status) {
  return `<span class="status-pill status-${escapeHtml(status)}">${escapeHtml(STATUS_LABELS[status] || status)}</span>`;
}

function reviewBadge(status) {
  return `<span class="status-pill review-${escapeHtml(status)}">${escapeHtml(REVIEW_LABELS[status] || status)}</span>`;
}

function setHtml(id, html) {
  const element = document.getElementById(id);
  if (element) {
    element.innerHTML = html;
  }
}

function setText(id, text) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = text;
  }
}

function exportFormatLabel(format) {
  if (format === "xlsx") {
    return "Excel";
  }
  if (format === "markdown") {
    return "Markdown";
  }
  return "JSON";
}

function triggerFileDownload(downloadUrl, fileName = "") {
  if (!downloadUrl) {
    return;
  }
  const anchor = document.createElement("a");
  anchor.href = downloadUrl;
  if (fileName) {
    anchor.download = fileName;
  }
  anchor.rel = "noopener";
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

function buildJobLinks(jobId) {
  const safeJobId = encodeURIComponent(jobId);
  return `
    <a class="button-link secondary" href="/jobs/${safeJobId}">状态页</a>
    <a class="button-link secondary" href="/results/${safeJobId}">结果页</a>
    <a class="button-link secondary" href="/review/${safeJobId}">审核页</a>
    <a class="button-link secondary" href="/practice?job_id=${safeJobId}">口语对练测试</a>
  `;
}

function getPreflightTypeLabel(preflight) {
  const detectedType = preflight?.detected_pdf_type;
  if (detectedType === "text") {
    return "文字层 PDF";
  }
  if (detectedType === "mixed") {
    return "混合 PDF";
  }
  if (detectedType === "scan") {
    return "扫描版 PDF";
  }
  return "未识别";
}

function buildPreflightDetails(preflight) {
  if (!preflight) {
    return [];
  }
  const details = [];
  if (Number.isFinite(preflight.file_size_mb) && preflight.file_size_mb > 0) {
    details.push(`大小 ${preflight.file_size_mb} MB`);
  }
  if (Number.isFinite(preflight.page_count) && preflight.page_count > 0) {
    details.push(`页数 ${preflight.page_count}`);
  }
  details.push(`类型 ${getPreflightTypeLabel(preflight)}`);
  if (preflight.estimated_duration_range) {
    details.push(`预估 ${preflight.estimated_duration_range}`);
  }
  if (preflight.within_duration_budget === false && Number.isFinite(preflight.duration_budget_sec)) {
    details.push(`可能超过 ${Math.round(preflight.duration_budget_sec / 60)} 分钟`);
  }
  return details;
}

function renderJobSnapshot(job, detail) {
  const progressDetails = [];
  if (job.phase_label || job.phase) {
    progressDetails.push(`阶段 ${job.phase_label || job.phase}`);
  }
  if (Number.isFinite(job.page_total) && job.page_total > 0) {
    progressDetails.push(`页数 ${job.page_done || 0}/${job.page_total}`);
  }
  if (Number.isFinite(job.unit_total) && job.unit_total > 0) {
    progressDetails.push(`单元 ${job.unit_done || 0}/${job.unit_total}`);
  }
  if (Number.isFinite(job.retry_count) && job.retry_count > 0) {
    progressDetails.push(`重试 ${job.retry_count} 次`);
  }
  if (job.retryable) {
    progressDetails.push("可重试");
  }
  const preflightDetails = buildPreflightDetails(job.preflight);

  return `
    <div class="info-grid">
      <article class="info-card">
        <span class="meta-label">任务 ID</span>
        <strong>${escapeHtml(job.job_id)}</strong>
        <p class="meta-text">${statusBadge(job.status)}</p>
      </article>
      <article class="info-card">
        <span class="meta-label">文件</span>
        <strong>${escapeHtml(job.file_name)}</strong>
        <p class="meta-text">进度 ${escapeHtml(job.progress)}%${progressDetails.length ? ` · ${escapeHtml(progressDetails.join(" · "))}` : ""}</p>
      </article>
      <article class="info-card">
        <span class="meta-label">创建时间</span>
        <strong>${escapeHtml(formatDateTime(job.created_at))}</strong>
        <p class="meta-text">更新时间 ${escapeHtml(formatDateTime(job.updated_at || job.finished_at))}</p>
      </article>
    </div>
    ${detail ? `<p class="meta-text">${escapeHtml(detail)}</p>` : ""}
    ${preflightDetails.length ? `<p class="meta-text">预检 ${escapeHtml(preflightDetails.join(" · "))}</p>` : ""}
    ${
      Array.isArray(job.preflight?.warnings) && job.preflight.warnings.length
        ? `<p class="meta-text">${escapeHtml(job.preflight.warnings.join(" "))}</p>`
        : ""
    }
    ${job.phase_message ? `<p class="meta-text">${escapeHtml(job.phase_message)}</p>` : ""}
    ${job.last_error_code ? `<p class="meta-text">错误码：${escapeHtml(job.last_error_code)}</p>` : ""}
    ${job.error_message ? `<div class="inline-error">${escapeHtml(job.error_message)}</div>` : ""}
  `;
}

async function requestJson(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const response = await fetch(url, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : null;

  if (!response.ok) {
    const error = new Error(payload?.error?.message || payload?.message || `request failed (${response.status})`);
    error.status = response.status;
    error.code = payload?.error?.code || null;
    error.details = payload?.error?.details || {};
    error.retryable = Boolean(payload?.error?.retryable);
    error.phase = payload?.error?.phase || null;
    error.technicalMessage = payload?.error?.technical_message || null;
    throw error;
  }
  return payload?.data ?? payload;
}

function postJson(url, body) {
  return requestJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function patchJson(url, body) {
  return requestJson(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function summarizeResult(payload) {
  const units = payload?.units || [];
  return {
    units: units.length,
    vocabulary: units.reduce((total, item) => total + item.vocabulary.length, 0),
    patterns: units.reduce((total, item) => total + item.sentence_patterns.length, 0),
    dialogues: units.reduce((total, item) => total + item.dialogue_samples.length, 0),
  };
}

function summarizeReview(payload) {
  const counts = { pending: 0, approved: 0, rejected: 0, revised: 0, total: 0 };
  for (const target of iterateReviewTargets(payload)) {
    const status = target.review_status || "pending";
    if (counts[status] !== undefined) {
      counts[status] += 1;
    }
    counts.total += 1;
  }
  return counts;
}

function iterateReviewTargets(payload) {
  if (!payload) {
    return [];
  }
  const targets = [];
  if (payload.book) {
    targets.push(payload.book);
  }
  for (const unitPackage of payload.units || []) {
    targets.push(unitPackage.unit);
    targets.push(...unitPackage.vocabulary);
    targets.push(...unitPackage.sentence_patterns);
    targets.push(...unitPackage.dialogue_samples);
    targets.push(unitPackage.unit_task);
    targets.push(unitPackage.unit_prompt);
  }
  return targets;
}

function renderVocabularyItems(items) {
  if (!items.length) {
    return '<div class="empty-state compact-empty">没有可展示的词汇。</div>';
  }
  return `
    <div class="item-grid">
      ${items
        .map(
          (item) => `
            <article class="item-card">
              <div class="item-header">
                <div>
                  <p class="item-title">${escapeHtml(item.word)}</p>
                  <p class="item-subtitle">${escapeHtml(item.part_of_speech || "词性未标注")}</p>
                </div>
                ${reviewBadge(item.review_status)}
              </div>
              <p class="item-body">${escapeHtml(item.meaning_zh || "暂无中文释义")}</p>
              <p class="item-note">${escapeHtml((item.example_sentences || []).join(" / ") || "暂无例句")}</p>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderSentencePatterns(items) {
  if (!items.length) {
    return '<div class="empty-state compact-empty">没有可展示的句型。</div>';
  }
  return `
    <div class="item-grid">
      ${items
        .map(
          (item) => `
            <article class="item-card">
              <div class="item-header">
                <div>
                  <p class="item-title">${escapeHtml(item.pattern)}</p>
                  <p class="item-subtitle">${escapeHtml(item.usage_note || "未填写用法说明")}</p>
                </div>
                ${reviewBadge(item.review_status)}
              </div>
              <p class="item-note">${escapeHtml((item.examples || []).join(" / ") || "暂无示例")}</p>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderDialogueSamples(items) {
  if (!items.length) {
    return '<div class="empty-state compact-empty">没有可展示的对话。</div>';
  }
  return `
    <div class="dialogue-list">
      ${items
        .map(
          (item) => `
            <article class="item-card">
              <div class="item-header">
                <div>
                  <p class="item-title">${escapeHtml(item.title || "对话样例")}</p>
                  <p class="item-subtitle">${escapeHtml(item.source_excerpt || "无原文摘录")}</p>
                </div>
                ${reviewBadge(item.review_status)}
              </div>
              <div class="dialogue-turns">
                ${(item.turns || [])
                  .map(
                    (turn) => `
                      <div class="dialogue-turn">
                        <strong>${escapeHtml(turn.speaker)}</strong>
                        <span>${escapeHtml(turn.text_en)}</span>
                        <em>${escapeHtml(turn.text_zh)}</em>
                      </div>
                    `,
                  )
                  .join("")}
              </div>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderTaskCard(task) {
  return `
    <article class="item-card">
      <div class="item-header">
        <div>
          <p class="item-title">单元任务介绍</p>
          <p class="item-subtitle">${escapeHtml(task.task_intro || "未填写任务说明")}</p>
        </div>
        ${reviewBadge(task.review_status)}
      </div>
      <p class="item-note">${escapeHtml((task.source_basis || []).join(" / ") || "暂无来源依据")}</p>
    </article>
  `;
}

function renderPromptCard(prompt) {
  return `
    <article class="item-card">
      <div class="item-header">
        <div>
          <p class="item-title">生成提示</p>
          <p class="item-subtitle">${escapeHtml(prompt.unit_theme || "未填写主题")}</p>
        </div>
        ${reviewBadge(prompt.review_status)}
      </div>
      <p class="item-note">语法：${escapeHtml((prompt.grammar_rules || []).join(" / ") || "暂无")}</p>
      <p class="item-note">提示：${escapeHtml((prompt.prompt_notes || []).join(" / ") || "暂无")}</p>
    </article>
  `;
}

function unitQueueLabel(unit) {
  return `${unit.classification.unit_code} · ${unit.classification.unit_name}`;
}

function collectOutputQueues(payload) {
  const units = payload.units || [];
  return {
    vocabulary: units.flatMap((unitPackage) => unitPackage.vocabulary.map((item) => ({ unit: unitPackage.unit, item }))),
    sentencePatterns: units.flatMap((unitPackage) =>
      unitPackage.sentence_patterns.map((item) => ({ unit: unitPackage.unit, item })),
    ),
    dialogueSamples: units.flatMap((unitPackage) =>
      unitPackage.dialogue_samples.map((item) => ({ unit: unitPackage.unit, item })),
    ),
    unitTasks: units.map((unitPackage) => ({ unit: unitPackage.unit, item: unitPackage.unit_task })),
    unitPrompts: units.map((unitPackage) => ({ unit: unitPackage.unit, item: unitPackage.unit_prompt })),
  };
}

function renderQueueSection(title, description, count, bodyHtml) {
  return `
    <section class="queue-section">
      <div class="section-head">
        <div>
          <p class="eyebrow">Output Queue</p>
          <h3>${escapeHtml(title)}</h3>
        </div>
        <div class="queue-count">${escapeHtml(count)} 项</div>
      </div>
      <p class="section-note">${escapeHtml(description)}</p>
      ${bodyHtml}
    </section>
  `;
}

function renderVocabularyQueue(queue) {
  if (!queue.length) {
    return renderQueueSection("词汇队列", "按词汇项聚合当前任务产出。", 0, '<div class="empty-state compact-empty">当前没有词汇产出。</div>');
  }
  return renderQueueSection(
    "词汇队列",
    "按词汇项聚合当前任务产出，便于集中查看单词、释义、例句和审核状态。",
    queue.length,
    `
      <div class="item-grid">
        ${queue
          .map(
            ({ unit, item }) => `
              <article class="item-card queue-card">
                <div class="item-header">
                  <div>
                    <p class="item-title">${escapeHtml(item.word)}</p>
                    <p class="item-subtitle">${escapeHtml(unitQueueLabel(unit))} · ${escapeHtml(item.part_of_speech || "词性未标注")}</p>
                  </div>
                  ${reviewBadge(item.review_status)}
                </div>
                <p class="item-body">${escapeHtml(item.meaning_zh || "暂无中文释义")}</p>
                <p class="item-note">例句：${escapeHtml((item.example_sentences || []).join(" / ") || "暂无例句")}</p>
                <p class="item-note">摘录：${escapeHtml(item.source_excerpt || "暂无原文摘录")}</p>
              </article>
            `,
          )
          .join("")}
      </div>
    `,
  );
}

function renderSentenceQueue(queue) {
  if (!queue.length) {
    return renderQueueSection("句型队列", "按句型项聚合当前任务产出。", 0, '<div class="empty-state compact-empty">当前没有句型产出。</div>');
  }
  return renderQueueSection(
    "句型队列",
    "按句型项聚合当前任务产出，便于集中查看重点句型、说明、例句和审核状态。",
    queue.length,
    `
      <div class="item-grid">
        ${queue
          .map(
            ({ unit, item }) => `
              <article class="item-card queue-card">
                <div class="item-header">
                  <div>
                    <p class="item-title">${escapeHtml(item.pattern)}</p>
                    <p class="item-subtitle">${escapeHtml(unitQueueLabel(unit))} · ${escapeHtml(item.usage_note || "未填写用法说明")}</p>
                  </div>
                  ${reviewBadge(item.review_status)}
                </div>
                <p class="item-note">例句：${escapeHtml((item.examples || []).join(" / ") || "暂无例句")}</p>
                <p class="item-note">摘录：${escapeHtml(item.source_excerpt || "暂无原文摘录")}</p>
              </article>
            `,
          )
          .join("")}
      </div>
    `,
  );
}

function renderDialogueQueue(queue) {
  if (!queue.length) {
    return renderQueueSection("对话样例队列", "按对话样例聚合当前任务产出。", 0, '<div class="empty-state compact-empty">当前没有对话样例产出。</div>');
  }
  return renderQueueSection(
    "对话样例队列",
    "按对话样例聚合当前任务产出，便于集中查看双语轮次和审核状态。",
    queue.length,
    `
      <div class="dialogue-list">
        ${queue
          .map(
            ({ unit, item }) => `
              <article class="item-card queue-card">
                <div class="item-header">
                  <div>
                    <p class="item-title">${escapeHtml(item.title || "对话样例")}</p>
                    <p class="item-subtitle">${escapeHtml(unitQueueLabel(unit))} · ${escapeHtml(item.source_excerpt || "暂无原文摘录")}</p>
                  </div>
                  ${reviewBadge(item.review_status)}
                </div>
                <div class="dialogue-turns">
                  ${(item.turns || [])
                    .map(
                      (turn) => `
                        <div class="dialogue-turn">
                          <strong>${escapeHtml(turn.speaker)}</strong>
                          <span>${escapeHtml(turn.text_en)}</span>
                          <em>${escapeHtml(turn.text_zh)}</em>
                        </div>
                      `,
                    )
                    .join("")}
                </div>
              </article>
            `,
          )
          .join("")}
      </div>
    `,
  );
}

function renderTaskQueue(queue) {
  if (!queue.length) {
    return renderQueueSection("单元任务队列", "按单元任务介绍聚合当前任务产出。", 0, '<div class="empty-state compact-empty">当前没有单元任务介绍产出。</div>');
  }
  return renderQueueSection(
    "单元任务队列",
    "按单元任务介绍聚合当前任务产出，便于集中查看当前单元的目标说明。",
    queue.length,
    `
      <div class="item-grid">
        ${queue
          .map(
            ({ unit, item }) => `
              <article class="item-card queue-card">
                <div class="item-header">
                  <div>
                    <p class="item-title">${escapeHtml(unitQueueLabel(unit))}</p>
                    <p class="item-subtitle">${escapeHtml(item.task_intro || "未填写任务说明")}</p>
                  </div>
                  ${reviewBadge(item.review_status)}
                </div>
                <p class="item-note">来源依据：${escapeHtml((item.source_basis || []).join(" / ") || "暂无来源依据")}</p>
              </article>
            `,
          )
          .join("")}
      </div>
    `,
  );
}

function renderPromptQueue(queue) {
  if (!queue.length) {
    return renderQueueSection("生成提示队列", "按生成提示聚合当前任务产出。", 0, '<div class="empty-state compact-empty">当前没有生成提示产出。</div>');
  }
  return renderQueueSection(
    "生成提示队列",
    "按生成提示聚合当前任务产出，便于集中查看主题、语法规则和补充说明。",
    queue.length,
    `
      <div class="item-grid">
        ${queue
          .map(
            ({ unit, item }) => `
              <article class="item-card queue-card">
                <div class="item-header">
                  <div>
                    <p class="item-title">${escapeHtml(unitQueueLabel(unit))}</p>
                    <p class="item-subtitle">${escapeHtml(item.unit_theme || "未填写主题")}</p>
                  </div>
                  ${reviewBadge(item.review_status)}
                </div>
                <p class="item-note">语法：${escapeHtml((item.grammar_rules || []).join(" / ") || "暂无")}</p>
                <p class="item-note">提示：${escapeHtml((item.prompt_notes || []).join(" / ") || "暂无")}</p>
              </article>
            `,
          )
          .join("")}
      </div>
    `,
  );
}

function renderUnitResultCard(unitPackage) {
  const unit = unitPackage.unit;
  return `
    <section class="panel unit-card">
      <div class="section-head">
        <div>
          <p class="eyebrow">${escapeHtml(unit.classification.unit_code)}</p>
          <h2>${escapeHtml(unit.classification.unit_name)}</h2>
        </div>
        ${reviewBadge(unit.review_status)}
      </div>
      <div class="info-grid">
        <article class="info-card">
          <span class="meta-label">教材版本</span>
          <strong>${escapeHtml(unit.classification.textbook_version)}</strong>
          <p class="meta-text">${escapeHtml(unit.classification.textbook_name)}</p>
        </article>
        <article class="info-card">
          <span class="meta-label">单元主题</span>
          <strong>${escapeHtml(unit.unit_theme || unit.classification.unit_name)}</strong>
          <p class="meta-text">来源页 ${escapeHtml((unit.source_pages || []).join(", ") || "1")}</p>
        </article>
      </div>

      <div class="section-stack">
        <div>
          <h3>词汇</h3>
          ${renderVocabularyItems(unitPackage.vocabulary)}
        </div>
        <div>
          <h3>句型</h3>
          ${renderSentencePatterns(unitPackage.sentence_patterns)}
        </div>
        <div>
          <h3>对话</h3>
          ${renderDialogueSamples(unitPackage.dialogue_samples)}
        </div>
        <div class="item-grid">
          ${renderTaskCard(unitPackage.unit_task)}
          ${renderPromptCard(unitPackage.unit_prompt)}
        </div>
      </div>
    </section>
  `;
}

function renderResultView(payload) {
  const summary = summarizeResult(payload);
  const review = summarizeReview(payload);
  const units = payload.units || [];
  const queues = collectOutputQueues(payload);

  return `
    <section class="stats-grid result-stats">
      <article class="stat-card">
        <p class="stat-label">单元数</p>
        <p class="stat-value">${summary.units}</p>
        <p class="stat-meta">当前结果中保留的单元数量</p>
      </article>
      <article class="stat-card">
        <p class="stat-label">词汇 / 句型</p>
        <p class="stat-value">${summary.vocabulary}/${summary.patterns}</p>
        <p class="stat-meta">当前任务生成出的核心语言材料</p>
      </article>
      <article class="stat-card">
        <p class="stat-label">对话样例</p>
        <p class="stat-value">${summary.dialogues}</p>
        <p class="stat-meta">含中英文对应轮次</p>
      </article>
      <article class="stat-card">
        <p class="stat-label">审核通过</p>
        <p class="stat-value">${review.approved}/${review.total}</p>
        <p class="stat-meta">按图书、单元和条目汇总</p>
      </article>
    </section>

    <section class="panel">
      <div class="section-head">
        <div>
          <p class="eyebrow">Book</p>
          <h2>${escapeHtml(payload.book.textbook_name)}</h2>
        </div>
        ${reviewBadge(payload.book.review_status)}
      </div>
      <div class="info-grid">
        <article class="info-card">
          <span class="meta-label">版本</span>
          <strong>${escapeHtml(payload.book.textbook_version)}</strong>
          <p class="meta-text">来源任务 ${escapeHtml(payload.book.source_job_id)}</p>
        </article>
        <article class="info-card">
          <span class="meta-label">出版社 / 学段</span>
          <strong>${escapeHtml(payload.book.publisher || "待确认")}</strong>
          <p class="meta-text">${escapeHtml(payload.book.grade || "年级待补充")} · ${escapeHtml(payload.book.term || "学期待补充")}</p>
        </article>
        <article class="info-card">
          <span class="meta-label">审核记录</span>
          <strong>${escapeHtml((payload.review_records || []).length)}</strong>
          <p class="meta-text">最近更新时间 ${escapeHtml(formatDateTime(payload.job.finished_at))}</p>
        </article>
      </div>
    </section>

    <section class="panel">
      <div class="section-head">
        <div>
          <p class="eyebrow">Output Queues</p>
          <h2>按内容队列查看产出</h2>
        </div>
        <p class="section-note">先按内容类型聚合当前任务产出，便于直接查看单词队列、句型队列和其他板块。</p>
      </div>
      <div class="queue-stack">
        ${renderVocabularyQueue(queues.vocabulary)}
        ${renderSentenceQueue(queues.sentencePatterns)}
        ${renderDialogueQueue(queues.dialogueSamples)}
        ${renderTaskQueue(queues.unitTasks)}
        ${renderPromptQueue(queues.unitPrompts)}
      </div>
    </section>

    <section class="panel">
      <div class="section-head">
        <div>
          <p class="eyebrow">Unit Packages</p>
          <h2>按单元查看产出明细</h2>
        </div>
        <p class="section-note">保留单元维度的完整明细，便于核对分类信息和上下文。</p>
      </div>
    </section>

    ${
      units.length
        ? units.map((unitPackage) => renderUnitResultCard(unitPackage)).join("")
        : '<div class="empty-state">当前筛选条件下没有内容可展示。</div>'
    }
  `;
}

function renderReviewCard(targetType, targetId, title, subtitle, bodyHtml, reviewStatus) {
  return `
    <article class="item-card review-card">
      <div class="item-header">
        <div>
          <p class="item-title">${escapeHtml(title)}</p>
          <p class="item-subtitle">${escapeHtml(subtitle)}</p>
        </div>
        ${reviewBadge(reviewStatus)}
      </div>
      <div class="item-body rich-body">${bodyHtml}</div>
      <div class="review-actions">
        <button type="button" class="small" data-review-target-type="${escapeHtml(targetType)}" data-review-target-id="${escapeHtml(targetId)}" data-review-status="approved">通过</button>
        <button type="button" class="small secondary" data-review-target-type="${escapeHtml(targetType)}" data-review-target-id="${escapeHtml(targetId)}" data-review-status="revised">返修</button>
        <button type="button" class="small danger" data-review-target-type="${escapeHtml(targetType)}" data-review-target-id="${escapeHtml(targetId)}" data-review-status="rejected">驳回</button>
      </div>
    </article>
  `;
}

function renderReviewView(payload) {
  const review = summarizeReview(payload);
  const units = payload.units || [];

  const bookSection = `
    <section class="panel">
      <div class="section-head">
        <div>
          <p class="eyebrow">Book Metadata</p>
          <h2>教材信息审核</h2>
        </div>
        ${reviewBadge(payload.book.review_status)}
      </div>
      ${renderReviewCard(
        "book",
        payload.book.book_id,
        payload.book.textbook_name,
        payload.book.textbook_version,
        `
          <p>出版社：${escapeHtml(payload.book.publisher || "待确认")}</p>
          <p>来源任务：${escapeHtml(payload.book.source_job_id)}</p>
          <p>来源页：${escapeHtml((payload.book.source_pages || []).join(", ") || "1")}</p>
        `,
        payload.book.review_status,
      )}
    </section>
  `;

  const unitSections = units.length
    ? units
        .map((unitPackage) => {
          const unit = unitPackage.unit;
          return `
            <section class="panel unit-card">
              <div class="section-head">
                <div>
                  <p class="eyebrow">${escapeHtml(unit.classification.unit_code)}</p>
                  <h2>${escapeHtml(unit.classification.unit_name)}</h2>
                </div>
                <div class="toolbar">
                  ${reviewBadge(unit.review_status)}
                  <button type="button" class="secondary small" data-batch-unit-id="${escapeHtml(unit.unit_id)}" data-review-status="approved">整单元通过</button>
                  <button type="button" class="secondary small" data-batch-unit-id="${escapeHtml(unit.unit_id)}" data-review-status="revised">整单元返修</button>
                </div>
              </div>
              <div class="review-grid">
                ${renderReviewCard(
                  "unit",
                  unit.unit_id,
                  `${unit.classification.unit_code} · ${unit.classification.unit_name}`,
                  unit.unit_theme || "未提取到主题",
                  `<p>单元主题：${escapeHtml(unit.unit_theme || unit.classification.unit_name)}</p><p>来源页：${escapeHtml((unit.source_pages || []).join(", ") || "1")}</p>`,
                  unit.review_status,
                )}
                ${unitPackage.vocabulary
                  .map((item) =>
                    renderReviewCard(
                      "vocabulary_item",
                      item.item_id,
                      item.word,
                      item.part_of_speech || "词汇",
                      `<p>${escapeHtml(item.meaning_zh || "暂无中文释义")}</p><p>${escapeHtml((item.example_sentences || []).join(" / ") || "暂无例句")}</p>`,
                      item.review_status,
                    ),
                  )
                  .join("")}
                ${unitPackage.sentence_patterns
                  .map((item) =>
                    renderReviewCard(
                      "sentence_pattern",
                      item.item_id,
                      item.pattern,
                      item.usage_note || "句型",
                      `<p>${escapeHtml((item.examples || []).join(" / ") || "暂无例句")}</p>`,
                      item.review_status,
                    ),
                  )
                  .join("")}
                ${unitPackage.dialogue_samples
                  .map((item) =>
                    renderReviewCard(
                      "dialogue_sample",
                      item.item_id,
                      item.title || "对话样例",
                      item.source_excerpt || "无原文摘录",
                      `
                        <div class="dialogue-turns">
                          ${(item.turns || [])
                            .map(
                              (turn) => `
                                <div class="dialogue-turn">
                                  <strong>${escapeHtml(turn.speaker)}</strong>
                                  <span>${escapeHtml(turn.text_en)}</span>
                                  <em>${escapeHtml(turn.text_zh)}</em>
                                </div>
                              `,
                            )
                            .join("")}
                        </div>
                      `,
                      item.review_status,
                    ),
                  )
                  .join("")}
                ${renderReviewCard(
                  "unit_task",
                  unitPackage.unit_task.item_id,
                  "单元任务介绍",
                  unitPackage.unit_task.task_intro,
                  `<p>${escapeHtml((unitPackage.unit_task.source_basis || []).join(" / ") || "暂无来源依据")}</p>`,
                  unitPackage.unit_task.review_status,
                )}
                ${renderReviewCard(
                  "unit_prompt",
                  unitPackage.unit_prompt.item_id,
                  "生成提示",
                  unitPackage.unit_prompt.unit_theme,
                  `<p>语法：${escapeHtml((unitPackage.unit_prompt.grammar_rules || []).join(" / ") || "暂无")}</p><p>提示：${escapeHtml((unitPackage.unit_prompt.prompt_notes || []).join(" / ") || "暂无")}</p>`,
                  unitPackage.unit_prompt.review_status,
                )}
              </div>
            </section>
          `;
        })
        .join("")
    : '<div class="empty-state">结果尚未生成，暂时无法审核。</div>';

  return {
    summary: `
      <section class="stats-grid result-stats">
        <article class="stat-card">
          <p class="stat-label">待审核</p>
          <p class="stat-value">${review.pending}</p>
          <p class="stat-meta">尚未处理的条目数量</p>
        </article>
        <article class="stat-card">
          <p class="stat-label">已通过</p>
          <p class="stat-value">${review.approved}</p>
          <p class="stat-meta">可以继续用于导出的条目</p>
        </article>
        <article class="stat-card">
          <p class="stat-label">返修 / 驳回</p>
          <p class="stat-value">${review.revised + review.rejected}</p>
          <p class="stat-meta">需要继续处理的条目</p>
        </article>
        <article class="stat-card">
          <p class="stat-label">审核记录</p>
          <p class="stat-value">${(payload.review_records || []).length}</p>
          <p class="stat-meta">累计 review records</p>
        </article>
      </section>
    `,
    content: `${bookSection}${unitSections}`,
  };
}

async function initIndexPage() {
  const uploadForm = document.getElementById("upload-form");
  const fileInput = document.getElementById("pdf-file");
  if (!uploadForm || !fileInput) {
    return;
  }

  uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = fileInput.files?.[0];
    if (!file) {
      setText("upload-stage", "请先选择 PDF 文件");
      return;
    }

    const maxUploadSizeMb = Number(APP_CONFIG.maxUploadSizeMb || 0);
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
    setHtml("upload-summary", '<div class="loading-state">文件上传成功后会先完成 PDF 预检，再进入后台解析与结构化生成。</div>');
    setHtml("upload-links", "");

    try {
      const job = await requestJson(`${APP_CONFIG.apiPrefix}/upload`, {
        method: "POST",
        body: formData,
      });
      setText("upload-stage", "上传完成，正在读取预检结果...");
      setHtml("upload-summary", renderJobSnapshot(job, "任务已创建，已完成 PDF 预检，正在准备进入后台解析。"));
      setHtml("upload-links", buildJobLinks(job.job_id));

      const queuedJob = await postJson(`${APP_CONFIG.apiPrefix}/parse/${encodeURIComponent(job.job_id)}`, {
        force_reparse: false,
      });
      setText("upload-stage", "任务已提交，正在后台处理中...");
      setHtml("upload-summary", renderJobSnapshot(queuedJob, "后台任务已经启动，请打开状态页查看实时进度。"));
      setHtml("upload-links", buildJobLinks(queuedJob.job_id));
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
        }<p class="meta-text">如果上传已经成功，可以先进入状态页查看失败原因后再重试。</p>`,
      );
    }
  });
}

async function loadJobStatus() {
  const job = await requestJson(`${APP_CONFIG.apiPrefix}/jobs/${encodeURIComponent(APP_CONFIG.jobId)}`);
  const isProcessing = PROCESSING_STATUSES.has(job.status);
  const canTriggerParse = ["uploaded", "failed", "reviewing", "completed"].includes(job.status);
  setHtml(
    "job-status",
    `
      ${renderJobSnapshot(job, "任务状态页适合排查失败原因，或在未开始时手动触发解析。")}
      <div class="action-row">
        ${buildJobLinks(job.job_id)}
        ${
          canTriggerParse
            ? `<button type="button" id="parse-trigger" ${["reviewing", "completed"].includes(job.status) ? 'data-force="true"' : ""}>${["reviewing", "completed"].includes(job.status) ? "重新解析" : "开始解析"}</button>`
            : ""
        }
      </div>
    `,
  );

  setHtml(
    "job-actions",
    isProcessing
      ? `<div class="status-banner">任务仍在处理中，页面会自动刷新。</div>`
      : job.status === "reviewing"
        ? `<div class="status-banner">结果已经准备好，可以直接打开结果页或审核页。</div>`
        : job.error_message
          ? `<div class="inline-error">${escapeHtml(job.error_message)}</div>`
          : "",
  );

  const parseTrigger = document.getElementById("parse-trigger");
  if (parseTrigger) {
    parseTrigger.addEventListener("click", async () => {
      parseTrigger.disabled = true;
      try {
        await postJson(`${APP_CONFIG.apiPrefix}/parse/${encodeURIComponent(APP_CONFIG.jobId)}`, {
          force_reparse: parseTrigger.dataset.force === "true",
        });
        await loadJobStatus();
      } catch (error) {
        setHtml("job-actions", `<div class="inline-error">${escapeHtml(error.message)}</div>`);
      }
    });
  }

  if (jobPollTimer) {
    window.clearTimeout(jobPollTimer);
    jobPollTimer = null;
  }
  if (isProcessing) {
    jobPollTimer = window.setTimeout(() => {
      loadJobStatus().catch((error) => {
        setHtml("job-actions", `<div class="inline-error">${escapeHtml(error.message)}</div>`);
      });
    }, 2500);
  }
}

async function initJobPage() {
  try {
    await loadJobStatus();
  } catch (error) {
    setHtml("job-status", `<div class="inline-error">${escapeHtml(error.message)}</div>`);
  }
}

async function loadResultPage() {
  const approvedOnly = document.getElementById("approved-only-toggle")?.checked || false;
  const query = approvedOnly ? "?approved_only=true" : "";
  const payload = await requestJson(`${APP_CONFIG.apiPrefix}/results/${encodeURIComponent(APP_CONFIG.jobId)}${query}`);
  setHtml("result-shell", renderResultView(payload));
}

async function initResultPage() {
  const approvedToggle = document.getElementById("approved-only-toggle");
  const exportButtons = document.querySelectorAll("[data-export-format]");

  const refresh = async () => {
    try {
      setText("export-feedback", "");
      await loadResultPage();
    } catch (error) {
      setHtml(
        "result-shell",
        `<div class="empty-state">结果暂时不可用：${escapeHtml(error.message)}。可以先回到 <a href="/jobs/${encodeURIComponent(APP_CONFIG.jobId)}">任务状态页</a> 查看。</div>`,
      );
    }
  };

  if (approvedToggle) {
    approvedToggle.addEventListener("change", () => {
      refresh().catch(() => undefined);
    });
  }

  for (const button of exportButtons) {
    button.addEventListener("click", async () => {
      button.disabled = true;
      setText("export-feedback", "正在准备导出文件...");
      try {
        const metadata = await postJson(`${APP_CONFIG.apiPrefix}/export`, {
          job_id: APP_CONFIG.jobId,
          format: button.dataset.exportFormat,
          approved_only: document.getElementById("approved-only-toggle")?.checked || false,
        });
        const fileName = `${metadata.export_id}.${metadata.format}`;
        triggerFileDownload(metadata.download_url, fileName);
        setHtml(
          "export-feedback",
          `${escapeHtml(exportFormatLabel(metadata.format))} 导出完成，已开始下载：<a href="${escapeHtml(metadata.download_url)}" download="${escapeHtml(fileName)}">${escapeHtml(fileName)}</a>`,
        );
      } catch (error) {
        const blockedCount = Array.isArray(error.details?.blocked_items) ? error.details.blocked_items.length : 0;
        setText(
          "export-feedback",
          blockedCount ? `${error.message}，仍有 ${blockedCount} 个条目未通过审核。` : error.message,
        );
      } finally {
        button.disabled = false;
      }
    });
  }

  await refresh();
}

function buildUnitBatchTargets(unitPackage) {
  return [
    { target_type: "unit", target_id: unitPackage.unit.unit_id },
    ...unitPackage.vocabulary.map((item) => ({ target_type: "vocabulary_item", target_id: item.item_id })),
    ...unitPackage.sentence_patterns.map((item) => ({ target_type: "sentence_pattern", target_id: item.item_id })),
    ...unitPackage.dialogue_samples.map((item) => ({ target_type: "dialogue_sample", target_id: item.item_id })),
    { target_type: "unit_task", target_id: unitPackage.unit_task.item_id },
    { target_type: "unit_prompt", target_id: unitPackage.unit_prompt.item_id },
  ];
}

function reviewRequestBody(reviewStatus) {
  return {
    review_status: reviewStatus,
    review_notes: document.getElementById("review-note")?.value.trim() || null,
    reviewer: document.getElementById("reviewer-name")?.value.trim() || null,
    patched_fields: {},
  };
}

async function loadReviewPage() {
  const payload = await requestJson(`${APP_CONFIG.apiPrefix}/results/${encodeURIComponent(APP_CONFIG.jobId)}`);
  reviewPayloadCache = payload;
  const reviewView = renderReviewView(payload);
  setHtml("review-summary", reviewView.summary);
  setHtml("review-shell", reviewView.content);
}

async function initReviewPage() {
  const shell = document.getElementById("review-shell");
  if (!shell) {
    return;
  }

  const refresh = async () => {
    try {
      setText("review-feedback", "");
      await loadReviewPage();
    } catch (error) {
      setHtml("review-shell", `<div class="empty-state">审核数据暂时不可用：${escapeHtml(error.message)}</div>`);
    }
  };

  shell.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) {
      return;
    }

    const targetType = button.dataset.reviewTargetType;
    const targetId = button.dataset.reviewTargetId;
    const reviewStatus = button.dataset.reviewStatus;
    const batchUnitId = button.dataset.batchUnitId;

    button.disabled = true;
    setText("review-feedback", "正在提交审核结果...");

    try {
      if (batchUnitId) {
        const unitPackage = reviewPayloadCache?.units?.find((item) => item.unit.unit_id === batchUnitId);
        if (!unitPackage) {
          throw new Error("找不到对应单元");
        }
        await postJson(`${APP_CONFIG.apiPrefix}/review/units/${encodeURIComponent(batchUnitId)}/batch`, {
          review_status: reviewStatus,
          review_notes: document.getElementById("review-note")?.value.trim() || null,
          reviewer: document.getElementById("reviewer-name")?.value.trim() || null,
          targets: buildUnitBatchTargets(unitPackage),
        });
      } else if (targetType && targetId && reviewStatus) {
        await patchJson(
          `${APP_CONFIG.apiPrefix}/review/items/${encodeURIComponent(targetType)}/${encodeURIComponent(targetId)}`,
          reviewRequestBody(reviewStatus),
        );
      }
      await refresh();
      setText("review-feedback", "审核结果已更新。");
    } catch (error) {
      setText("review-feedback", error.message);
    } finally {
      button.disabled = false;
    }
  });

  await refresh();
}

switch (APP_CONFIG.page) {
  case "index":
    initIndexPage().catch(() => undefined);
    break;
  case "job":
    initJobPage().catch(() => undefined);
    break;
  case "result":
    initResultPage().catch(() => undefined);
    break;
  case "review":
    initReviewPage().catch(() => undefined);
    break;
  default:
    break;
}
