import { fileDateStamp } from "./time.js";

// 🖥️ کلاینت API وب‌ادمین — same-origin با کوکی HttpOnly (wa_session)
// هیچ توکن در localStorage ذخیره نمی‌شود.

const _inflight = new Map();

function friendlyStatus(status) {
  if (status === 400)
    return "درخواست قابل پردازش نیست؛ ورودی‌ها را بررسی کنید.";
  if (status === 401) return "نشست شما منقضی شده است؛ دوباره وارد شوید.";
  if (status === 403) return "مجوز لازم برای انجام این عملیات را ندارید.";
  if (status === 404) return "مورد درخواستی پیدا نشد یا دیگر در دسترس نیست.";
  if (status === 409) return "این عملیات با وضعیت فعلی داده سازگار نیست.";
  if (status === 413) return "حجم فایل از سقف مجاز بیشتر است.";
  if (status === 422) return "بعضی ورودی‌ها معتبر نیستند؛ فرم را بازبینی کنید.";
  if (status === 429)
    return "تعداد درخواست‌ها زیاد است؛ کمی بعد دوباره تلاش کنید.";
  if (status >= 500)
    return "سرویس موقتاً با مشکل روبه‌رو شده است. دوباره تلاش کنید.";
  return "در انجام درخواست مشکلی پیش آمد.";
}

async function _request(path, { method = "GET", body, form } = {}) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 30000);
  const opt = {
    method,
    credentials: "include",
    headers: { Accept: "application/json" },
    signal: controller.signal,
  };
  if (form) opt.body = form;
  else if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  try {
    const r = await fetch(path, opt);
    if (r.status === 401 && !path.includes("/auth/"))
      window.dispatchEvent(new Event("wa:unauthorized"));
    let data = null;
    try {
      data = await r.json();
    } catch {
      /* پاسخ خالی/فایل */
    }
    if (!r.ok) {
      const raw = data?.detail;
      const technical =
        typeof raw === "string"
          ? raw
          : raw
            ? JSON.stringify(raw)
            : `HTTP ${r.status}`;
      const e = new Error(technical);
      e.status = r.status;
      e.technical = technical;
      e.friendly = friendlyStatus(r.status);
      e.errorId = data?.error_id || r.headers.get("x-request-id") || "";
      throw e;
    }
    return data;
  } catch (e) {
    if (e?.name === "AbortError") {
      const timeout = new Error("request_timeout");
      timeout.status = 408;
      timeout.friendly = "پاسخ سرویس بیش از حد طول کشید؛ دوباره تلاش کنید.";
      throw timeout;
    }
    throw e;
  } finally {
    window.clearTimeout(timer);
  }
}

async function req(path, options = {}) {
  const method = options.method || "GET";
  const dedupe = method === "GET" && !options.body && !options.form;
  if (!dedupe) return _request(path, options);
  const key = `${method}:${path}`;
  if (_inflight.has(key)) return _inflight.get(key);
  const promise = _request(path, options).finally(() => _inflight.delete(key));
  _inflight.set(key, promise);
  return promise;
}

async function downloadFile(path, filename) {
  // Browser-native navigation lets the response stream directly to disk; no full Blob/dataset hydration.
  const anchor = document.createElement("a");
  anchor.href = path;
  anchor.download = filename;
  anchor.rel = "noopener";
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  return { ok: true, streamed: true };
}

// 💍 Ring Street — helper کوچکِ query (فقط برای متدهای رینگ؛ بقیه دست‌نخورده)
const _ringQ = (p = {}) =>
  new URLSearchParams(
    Object.entries(p).filter(
      ([, v]) => v !== "" && v !== null && v !== undefined,
    ),
  ).toString();

export const api = {
  // ── auth ──
  requestCode: (identifier) =>
    req("/api/web-admin/auth/request-code", {
      method: "POST",
      body: { identifier },
    }),
  verify: (identifier, code) =>
    req("/api/web-admin/auth/verify", {
      method: "POST",
      body: { identifier, code },
    }),
  logout: () => req("/api/web-admin/auth/logout", { method: "POST" }),
  me: () => req("/api/web-admin/me"),
  overview: () => req("/api/web-admin/overview"),
  dashboardBundle: () => req("/api/web-admin/dashboard-bundle"),
  myWork: () => req("/api/web-admin/operations/my-work"),
  operationAlerts: () => req("/api/web-admin/operations/alerts"),
  dataQuality: () => req("/api/web-admin/operations/data-quality"),
  dataQualityItems: (kind, p = {}) =>
    req(
      `/api/web-admin/operations/data-quality/${encodeURIComponent(kind)}?` +
        new URLSearchParams(p),
    ),
  // 🌊 WA21 — اصلاح گونه‌های امن کیفیت داده (تأیید صریح لازم است؛ بک‌اند
  // بدون `confirm:true` با 400 رد می‌کند).
  dataQualityFix: (kind) =>
    req(
      `/api/web-admin/operations/data-quality/${encodeURIComponent(kind)}/fix`,
      { method: "POST", body: { kind, confirm: true } },
    ),
  // 🌊 W5 — اصلاح مستقیم آیتم کیفیت داده: ویرایش متادیتا، اتصال به والد، حذف تکی
  dataQualityRepair: (id, body) =>
    req(
      `/api/web-admin/operations/data-quality/files_missing_metadata/${encodeURIComponent(id)}/repair`,
      { method: "POST", body },
    ),
  dataQualityAttach: (kind, id, parent_id) =>
    req(
      `/api/web-admin/operations/data-quality/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/attach`,
      { method: "POST", body: { parent_id } },
    ),
  dataQualityRemove: (kind, id) =>
    req(
      `/api/web-admin/operations/data-quality/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/remove`,
      { method: "POST", body: { confirm: true } },
    ),
  dataQualityParents: (pk, q) =>
    req(
      `/api/web-admin/operations/quality-parents/${encodeURIComponent(pk)}?q=` +
        encodeURIComponent(q || ""),
    ),
  // ── users (WA سرورساید) ──
  users: (p) =>
    req(
      "/api/web-admin/users?" +
        new URLSearchParams(
          Object.entries(p).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
    ),
  exportUsersCsv: (p = {}) =>
    downloadFile(
      "/api/web-admin/exports/users.csv?" +
        new URLSearchParams(
          Object.entries({ ...p, human: true }).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
      `humsyar-users-${fileDateStamp()}.csv`,
    ),
  // 🛡 AUDIT-§۷۹ — `extra` برای اکشن‌هایی که پارامترِ ساختارمند می‌خواهند
  // (مثل اشتراک گروهی: days/plan_name/extend) — بدنه همان endpoint می‌ماند.
  usersBulk: (action, ids, value, extra = {}) =>
    req("/api/web-admin/users/bulk", {
      method: "POST",
      body: { action, ids, value, ...extra },
    }),
  // 🔍 §۸۷ — dry-run عملیات گروهی: همان بدنه، بدون هیچ نوشتنی.
  usersBulkPreview: (action, ids, value, extra = {}) =>
    req("/api/web-admin/users/bulk/preview", {
      method: "POST",
      body: { action, ids, value, ...extra },
    }),
  userDetail: (uid) => req(`/api/admin/users/${uid}`),
  userPatch: (uid, body) =>
    req(`/api/admin/users/${uid}`, { method: "PATCH", body }),
  userAction: (uid, act) =>
    req(`/api/admin/users/${uid}/${act}`, { method: "POST" }),
  // ── 🌊 WA2 core ──
  attention: () => req("/api/web-admin/attention"),
  activity: (limit = 40) => req(`/api/web-admin/activity?limit=${limit}`),
  waSearch: (q) => req("/api/web-admin/search?q=" + encodeURIComponent(q)),
  savedFilters: (scope) =>
    req("/api/web-admin/saved-filters" + (scope ? `?scope=${scope}` : "")),
  rolesPicker: () => req("/api/web-admin/rbac/roles-picker"),
  saveFilter: (body) =>
    req("/api/web-admin/saved-filters", { method: "POST", body }),
  updateFilter: (id, body) =>
    req(`/api/web-admin/saved-filters/${id}`, { method: "PUT", body }),
  touchFilter: (id) =>
    req(`/api/web-admin/saved-filters/${id}/touch`, { method: "POST" }),
  delFilter: (id) =>
    req(`/api/web-admin/saved-filters/${id}`, { method: "DELETE" }),
  user360: (uid) => req(`/api/web-admin/users/${uid}/360`),
  userRelations: (uid, section, p = {}) =>
    req(
      `/api/web-admin/users/${uid}/relations/${encodeURIComponent(section)}?` +
        new URLSearchParams(p),
    ),
  objectSummary: (type, id) =>
    req(
      `/api/web-admin/objects/${encodeURIComponent(type)}/${encodeURIComponent(id)}`,
    ),
  objectHistory: (type, id, limit = 30) =>
    req(
      `/api/web-admin/history/${encodeURIComponent(type)}/${encodeURIComponent(id)}?limit=${limit}`,
    ),
  correlationChain: (id) =>
    req(`/api/web-admin/audit/correlation/${encodeURIComponent(id)}`),
  ticketsBulk: (action, ids) =>
    req("/api/web-admin/tickets/bulk", {
      method: "POST",
      body: { action, ids },
    }),
  questions: (p = {}) =>
    req(
      "/api/web-admin/questions?" +
        new URLSearchParams(
          Object.entries(p).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
    ),
  exportQuestionsCsv: (p = {}) =>
    downloadFile(
      "/api/web-admin/exports/questions.csv?" +
        new URLSearchParams(
          Object.entries({ ...p, human: true }).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
      `humsyar-questions-${fileDateStamp()}.csv`,
    ),
  exportQuestionsPdf: async (ids, mode = "practice") => {
    const r = await fetch("/api/web-admin/questions/export/pdf", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/pdf",
      },
      body: JSON.stringify({ ids, mode }),
    });
    if (!r.ok) {
      let msg = `HTTP ${r.status}`;
      try {
        const j = await r.json();
        msg = j.detail || msg;
      } catch {}
      const e = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
      e.status = r.status;
      throw e;
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const disp = r.headers.get("Content-Disposition") || "";
    const m = disp.match(/filename="?([^"]+)"?/);
    a.download = (m && m[1]) || `humsyar-questions-${mode}-${ids.length}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    return { ok: true };
  },
  questionsBulk: (action, ids, patch, reason = "") =>
    req("/api/web-admin/questions/bulk", {
      method: "POST",
      body: { action, ids, patch, reason },
    }),
  questionCreate: (body) =>
    req("/api/web-admin/questions", { method: "POST", body }),
  questionTaxonomy: (intake = "") =>
    req(
      "/api/web-admin/questions/taxonomy" +
        (intake ? `?intake=${encodeURIComponent(intake)}` : ""),
    ),
  questionImportPrompt: () => req("/api/web-admin/questions/import/prompt"),
  questionImportUpload: (file) => {
    const form = new FormData();
    form.append("file", file);
    return req("/api/web-admin/questions/import/upload", {
      method: "POST",
      form,
    });
  },
  questionImportPreview: (jobId) =>
    req(`/api/web-admin/questions/import/${encodeURIComponent(jobId)}`),
  questionImportItems: (jobId, p = {}) =>
    req(
      `/api/web-admin/questions/import/${encodeURIComponent(jobId)}/items?` +
        new URLSearchParams(
          Object.entries(p).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
    ),
  questionImportMap: (jobId, itemId, lessonId, topicId) =>
    req(
      `/api/web-admin/questions/import/${encodeURIComponent(jobId)}/items/${encodeURIComponent(itemId)}/mapping`,
      { method: "PATCH", body: { lesson_id: lessonId, topic_id: topicId } },
    ),
  questionImportDecision: (jobId, itemId, decision) =>
    req(
      `/api/web-admin/questions/import/${encodeURIComponent(jobId)}/items/${encodeURIComponent(itemId)}/decision`,
      { method: "PATCH", body: { decision } },
    ),
  questionImportConfirm: (jobId) =>
    req(
      `/api/web-admin/questions/import/${encodeURIComponent(jobId)}/confirm`,
      { method: "POST" },
    ),
  // 🌊 WA22 — سلامت سؤال + نمای ۳۶۰
  questionHealth: (p = {}) =>
    req(
      "/api/web-admin/questions/health?" +
        new URLSearchParams(
          Object.entries(p).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
    ),
  question360: (qid) =>
    req(`/api/web-admin/questions/${encodeURIComponent(qid)}/360`),
  questionImportCancel: (jobId) =>
    req(`/api/web-admin/questions/import/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
    }),
  settingsCenter: () => req("/api/web-admin/settings/center"),
  patchSetting: (key, value, applyToExisting = false) =>
    req(`/api/web-admin/settings/center/${encodeURIComponent(key)}`, {
      method: "PATCH",
      body: { value, apply_to_existing: applyToExisting },
    }),
  identityPolicy: () => req("/api/web-admin/settings/identity-policy"),
  identityPolicyUpdate: (body) =>
    req("/api/web-admin/settings/identity-policy", { method: "PUT", body }),
  exams: (status) =>
    req("/api/web-admin/exams" + (status ? `?status=${status}` : "")),
  examCreate: (body) => req("/api/web-admin/exams", { method: "POST", body }),
  examUpdate: (id, body) =>
    req(`/api/web-admin/exams/${id}`, { method: "PATCH", body }),
  examDelete: (id) => req(`/api/web-admin/exams/${id}`, { method: "DELETE" }),
  examStats: () => req("/api/web-admin/exams/stats"),
  // 🌊 موج Analytics-Filters — بازه‌ی روزانه (۷ تا ۹۰)
  waAnalytics: (days) =>
    req("/api/web-admin/wa-analytics" + (days ? `?days=${days}` : "")),
  waInsights: () => req("/api/web-admin/wa-insights"),
  notifRuns: (job) =>
    req("/api/web-admin/notif/runs" + (job ? `?job_name=${job}` : "")),
  notifRunDetail: (id) =>
    req(`/api/web-admin/notif/runs/${encodeURIComponent(id)}`),
  notifRetry: (id) =>
    req(`/api/web-admin/notif/runs/${id}/retry`, { method: "POST" }),
  // ── 🌊 WA2.1 Content Command Center ──
  contentTree: (intake) =>
    req(
      "/api/web-admin/content/tree" +
        (intake ? `?intake=${encodeURIComponent(intake)}` : ""),
    ),
  studentPreviewStudents: (q) =>
    req(
      `/api/web-admin/content/student-preview/students?q=${encodeURIComponent(q)}`,
    ),
  studentPreview: (userId) =>
    req(
      `/api/web-admin/content/student-preview?user_id=${encodeURIComponent(userId)}`,
    ),
  studentPreviewLessons: (userId, term) =>
    req(
      `/api/web-admin/content/student-preview/lessons?user_id=${encodeURIComponent(userId)}&term=${encodeURIComponent(term)}`,
    ),
  studentPreviewSessions: (userId, lessonId) =>
    req(
      `/api/web-admin/content/student-preview/sessions?user_id=${encodeURIComponent(userId)}&lesson_id=${encodeURIComponent(lessonId)}`,
    ),
  studentPreviewFiles: (userId, sessionId) =>
    req(
      `/api/web-admin/content/student-preview/files?user_id=${encodeURIComponent(userId)}&session_id=${encodeURIComponent(sessionId)}`,
    ),
  contentImpact: (type, id) =>
    req(
      `/api/web-admin/content/impact/${encodeURIComponent(type)}/${encodeURIComponent(id)}`,
    ),
  contentHistory: (targetType, targetId) =>
    req(
      `/api/web-admin/content/history?target_type=${encodeURIComponent(targetType)}&target_id=${encodeURIComponent(targetId)}`,
    ),
  // 🌊 GIFT — مدیریت هدیه‌ها (همان روتر decide رسیدها)
  subGifts: (p) =>
    req("/api/subscription-admin/gifts?" + new URLSearchParams(p || {})),
  subGiftCancel: (pid) =>
    req(`/api/subscription-admin/gifts/${encodeURIComponent(pid)}/cancel`, {
      method: "POST",
    }),
  subGiftRetryNotify: (pid) =>
    req(
      `/api/subscription-admin/gifts/${encodeURIComponent(pid)}/retry-notify`,
      { method: "POST" },
    ),
  // 📥 URL-Import — پایپ‌لاین canonical درون‌ریزی محتوای راه‌دور
  urlImportCreate: (body) =>
    req("/api/content/url-import/jobs", { method: "POST", body }),
  urlImportJobs: (p) =>
    req("/api/content/url-import/jobs?" + new URLSearchParams(p || {})),
  urlImportJob: (id) =>
    req(`/api/content/url-import/jobs/${encodeURIComponent(id)}`),
  urlImportCancel: (id) =>
    req(`/api/content/url-import/jobs/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
    }),
  urlImportRetry: (id, force) =>
    req(`/api/content/url-import/jobs/${encodeURIComponent(id)}/retry`, {
      method: "POST",
      body: { force: !!force },
    }),
  dupSession: (sid) =>
    req(`/api/web-admin/content/sessions/${sid}/duplicate`, { method: "POST" }),
  sessionsBulk: (body) =>
    req("/api/web-admin/content/sessions/bulk", { method: "POST", body }),
  itemsBulk: (body) =>
    req("/api/web-admin/content/items/bulk", { method: "POST", body }),
  caSessionContent: (sid) =>
    req(`/api/content/basic-science/sessions/${sid}/content`),
  caAddContent: (sid, form) =>
    req(`/api/content/basic-science/sessions/${sid}/content`, {
      method: "POST",
      form,
    }),
  caDelContent: (cid) =>
    req(`/api/content/basic-science/content/${cid}`, { method: "DELETE" }),
  caAddSession: (lid, body) =>
    req(`/api/content/basic-science/lessons/${lid}/sessions`, {
      method: "POST",
      body,
    }),
  caEditSession: (sid, body) =>
    req(`/api/content/basic-science/sessions/${sid}`, {
      method: "PATCH",
      body,
    }),
  caDelSession: (sid) =>
    req(`/api/content/basic-science/sessions/${sid}`, { method: "DELETE" }),
  caForkSession: (sid, intake) =>
    req(
      `/api/content/basic-science/sessions/${sid}/fork?intake=${encodeURIComponent(intake)}`,
      { method: "POST" },
    ),
  caUnforkSession: (sid) =>
    req(`/api/content/basic-science/sessions/${sid}/fork`, {
      method: "DELETE",
    }),
  caAddLesson: (body) =>
    req("/api/content/basic-science/lessons", { method: "POST", body }),
  caEditLesson: (lid, body) =>
    req(`/api/content/basic-science/lessons/${lid}`, { method: "PATCH", body }),
  caMoveLessonRoot: (lid, intake) =>
    req(`/api/content/basic-science/lessons/${lid}/move`, {
      method: "POST",
      body: { intake },
    }),
  caDelLesson: (lid) =>
    req(`/api/content/basic-science/lessons/${lid}`, { method: "DELETE" }),
  caReports: (p = {}) =>
    req(
      "/api/web-admin/content/reports?" +
        new URLSearchParams(
          Object.entries(p).filter(
            ([, v]) => v !== undefined && v !== null && v !== "",
          ),
        ),
    ),
  caReportStats: () => req("/api/web-admin/content/reports/stats"),
  caReportStatus: (rid, status) =>
    req(`/api/web-admin/content/reports/${rid}/status`, {
      method: "POST",
      body: { status },
    }),
  // ── admin panel (owner) ──
  stats: () => req("/api/admin/stats"),
  botStatus: () => req("/api/web-admin/system/status"),
  // 🩺 دیاگنوستیک عمیق — API + ربات + Mongo + بیلدها + متریک مسیرها.
  // این endpoint از قبل در backend وجود داشت ولی هیچ مصرف‌کننده‌ای نداشت.
  healthDeep: () => req("/api/health/deep"),
  // 🛡 RBAC-Execution — عملیات System با مجوز دانه‌ای
  prestigeBackfill: () =>
    req("/api/web-admin/system/prestige/backfill", { method: "POST" }),
  prestigeConfig: () => req("/api/web-admin/system/prestige-config"),
  prestigeConfigUpdate: (values) =>
    req("/api/web-admin/system/prestige-config", {
      method: "PUT",
      body: { values },
    }),
  forceResNotif: () =>
    req("/api/web-admin/system/notifications/force-send", { method: "POST" }),
  logGroupsTest: () =>
    req("/api/web-admin/system/log-groups/test", { method: "POST" }),
  analytics: (days) =>
    req("/api/admin/analytics" + (days ? `?days=${days}` : "")),
  // 🛡 RBAC-Execution — مسیرهای permission-based (owner routeهای قدیمی دست‌نخورده)
  tickets: (p = {}) =>
    req(
      "/api/web-admin/tickets?" +
        new URLSearchParams(
          Object.entries(typeof p === "string" ? { status: p } : p).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
    ),
  exportTicketsCsv: (p = {}) =>
    downloadFile(
      "/api/web-admin/exports/tickets.csv?" +
        new URLSearchParams(
          Object.entries({ ...p, human: true }).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
      `humsyar-tickets-${fileDateStamp()}.csv`,
    ),
  ticket: (tid) => req(`/api/web-admin/tickets/${tid}`),
  ticketAssignees: () => req("/api/web-admin/tickets/assignees"),
  ticketAnalytics: () => req("/api/web-admin/tickets/analytics/summary"),
  ticketMeta: (tid, body) =>
    req(`/api/web-admin/tickets/${tid}/meta`, { method: "PATCH", body }),
  ticketNote: (tid, text) =>
    req(`/api/web-admin/tickets/${tid}/notes`, {
      method: "POST",
      body: { text },
    }),
  ticketReply: (tid, text) =>
    req(`/api/web-admin/tickets/${tid}/reply`, {
      method: "POST",
      body: { message: text },
    }),
  ticketClose: (tid) =>
    req(`/api/web-admin/tickets/${tid}/close`, { method: "POST" }),
  ticketReopen: (tid) =>
    req(`/api/web-admin/tickets/${tid}/reopen`, { method: "POST" }),
  // 🌊 W8/UX-04 — پاسخ‌های آماده
  cannedList: () => req("/api/web-admin/tickets/canned"),
  cannedAdd: (body) =>
    req("/api/web-admin/tickets/canned", { method: "POST", body }),
  cannedUpdate: (cid, body) =>
    req(`/api/web-admin/tickets/canned/${cid}`, { method: "PUT", body }),
  cannedDelete: (cid) =>
    req(`/api/web-admin/tickets/canned/${cid}`, { method: "DELETE" }),
  broadcast: (body) =>
    req("/api/web-admin/broadcast", { method: "POST", body }),
  broadcastPreview: (body) =>
    req("/api/web-admin/broadcast/preview", { method: "POST", body }),
  broadcastOptions: () => req("/api/web-admin/broadcast/options"),
  broadcastHistory: () => req("/api/web-admin/broadcast/history"),
  broadcastScheduled: () => req("/api/web-admin/broadcast/scheduled"),
  broadcastCancel: (campaignId) =>
    req("/api/web-admin/broadcast/cancel", {
      method: "POST",
      body: { campaign_id: campaignId },
    }),
  broadcastUpload: (form) =>
    req("/api/web-admin/broadcast/media", { method: "POST", form }),
  broadcastTest: (body) =>
    req("/api/web-admin/broadcast/test", { method: "POST", body }),
  broadcastCampaign: (id) =>
    req(`/api/web-admin/broadcast/campaigns/${encodeURIComponent(id)}`),
  broadcastRetryFailed: (id) =>
    req(
      `/api/web-admin/broadcast/campaigns/${encodeURIComponent(id)}/retry-failed`,
      { method: "POST" },
    ),
  waIntakes: () => req("/api/web-admin/intakes-picker"),
  pollStatus: () => req("/api/web-admin/poll/status"),
  pollSetChannel: (channel_id) =>
    req("/api/web-admin/poll/channel", {
      method: "POST",
      body: { channel_id },
    }),
  pollCreate: (question, options, anonymous) =>
    req("/api/web-admin/poll", {
      method: "POST",
      body: { question, options, anonymous },
    }),
  notifSettings: () => req("/api/web-admin/notifications/settings"),
  notifSetInterval: (interval_hours) =>
    req("/api/web-admin/notifications/settings", {
      method: "POST",
      body: { interval_hours },
    }),
  // 🌊 موج ChannelLock — قفل اجباری عضویت کانال (سطح مالک)
  channelLock: () => req("/api/admin/channel-lock"),
  channelLockAdd: (body) =>
    req("/api/admin/channel-lock", { method: "POST", body }),
  channelLockDel: (id) =>
    req(`/api/admin/channel-lock/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  auditLogs: (p) =>
    req(
      "/api/web-admin/audit-logs?" +
        new URLSearchParams(Object.entries(p).filter(([, v]) => v)),
    ),
  // ↩️ §۸۸ — بازگردانی یک تغییرِ ثبت‌شده (مجوز جدا: audit.undo).
  auditUndo: (logId, reason = "") =>
    req(`/api/web-admin/audit-logs/${logId}/undo`, {
      method: "POST",
      body: { reason },
    }),
  exportAuditCsv: (p = {}) =>
    downloadFile(
      "/api/web-admin/exports/audit.csv?" +
        new URLSearchParams(
          Object.entries({ ...p, human: true }).filter(([, v]) => v),
        ),
      `humsyar-audit-${fileDateStamp()}.csv`,
    ),
  systemJobs: () => req("/api/web-admin/system/jobs"),
  // 💀 DLQ — پیام‌هایی که پس از سقف تلاش مرده‌اند و از pending_queue بیرون افتاده‌اند.
  dlqList: (page = 1, perPage = 25) =>
    req(`/api/web-admin/system/dlq?page=${page}&per_page=${perPage}`),
  dlqRequeue: (body) =>
    req("/api/web-admin/system/dlq/requeue", { method: "POST", body }),
  dlqDiscard: (body) =>
    req("/api/web-admin/system/dlq/discard", { method: "POST", body }),
  systemTimeStandard: () => req("/api/web-admin/system/time-standard"),
  systemObservability: (hours = 24) =>
    req(`/api/web-admin/system/observability?hours=${hours}`),
  // 🌊 W5/REL-03
  systemClientErrors: (hours = 24, limit = 20) =>
    req(`/api/web-admin/system/client-errors?hours=${hours}&limit=${limit}`),
  // 🌊 W7 — دسترسی فیچرها
  featuresList: () => req('/api/web-admin/features'),
  featureUpdate: (key, body) =>
    req(`/api/web-admin/features/${encodeURIComponent(key)}`, { method: 'PUT', body }),
  featureRollback: (key) =>
    req(`/api/web-admin/features/${encodeURIComponent(key)}/rollback`, { method: 'POST', body: {} }),
  // 🌱 W13 / 💳 W14 — رشد
  growthConfig: () => req('/api/web-admin/growth/config'),
  growthUpdateConfig: (body) =>
    req('/api/web-admin/growth/config', { method: 'PUT', body }),
  growthReferrals: (p = {}) => {
    const q = new URLSearchParams(
      Object.entries(p).filter(([, v]) => v !== '' && v !== null && v !== undefined),
    ).toString();
    return req(`/api/web-admin/growth/referrals${q ? `?${q}` : ''}`);
  },
  growthReview: (id, approve) =>
    req(`/api/web-admin/growth/referrals/${encodeURIComponent(id)}/review`, { method: 'POST', body: { approve } }),
  growthStats: () => req('/api/web-admin/growth/stats'),
  securitySessions: (page = 1, limit = 30) =>
    req(`/api/web-admin/system/security/sessions?page=${page}&limit=${limit}`),
  revokeSecuritySession: (id, reason) =>
    req(
      `/api/web-admin/system/security/sessions/${encodeURIComponent(id)}/revoke`,
      { method: "POST", body: { reason } },
    ),
  settings: () => req("/api/web-admin/system/backup-settings"),
  patchSettings: (body) =>
    req("/api/web-admin/system/backup-settings", { method: "PATCH", body }),
  backup: (section) =>
    req("/api/web-admin/system/backup", {
      method: "POST",
      body: { section: section || "all" },
    }),
  restoreValidate: (file) => {
    const form = new FormData();
    form.append("file", file);
    return req("/api/web-admin/system/restore/validate", {
      method: "POST",
      form,
    });
  },
  restoreConfirm: (file, digest, confirmation) => {
    const form = new FormData();
    form.append("file", file);
    form.append("digest", digest);
    form.append("confirmation", confirmation);
    return req("/api/web-admin/system/restore/confirm", {
      method: "POST",
      form,
    });
  },
  exportExcel: () =>
    req("/api/web-admin/system/export/excel", { method: "POST" }),
  intakes: () => req("/api/admin/intakes"),
  // 🌊 موج Intakes-CA — مدیریت ورودی‌ها + ادمین‌های محتوا (سطح مالک؛ endpointهای موجود)
  intakeAdd: (code, label) =>
    req("/api/admin/intakes", { method: "POST", body: { code, label } }),
  intakeToggle: (code) =>
    req(`/api/admin/intakes/${encodeURIComponent(code)}/toggle`, {
      method: "POST",
    }),
  intakeDel: (code) =>
    req(`/api/admin/intakes/${encodeURIComponent(code)}`, { method: "DELETE" }),
  contentAdmins: () => req("/api/admin/content-admins"),
  contentAdminAdd: (uid) =>
    req(`/api/admin/content-admins/${uid}`, { method: "POST" }),
  contentAdminDel: (uid) =>
    req(`/api/admin/content-admins/${uid}`, { method: "DELETE" }),
  pendingUsers: () => req("/api/admin/users/pending"),
  // ── rbAC ──
  roles: () => req("/api/admin/rbac/roles"),
  perms: () => req("/api/admin/rbac/permissions"),
  createRole: (body) => req("/api/admin/rbac/roles", { method: "POST", body }),
  patchRole: (k, body) =>
    req(`/api/admin/rbac/roles/${k}`, { method: "PATCH", body }),
  deleteRole: (k) => req(`/api/admin/rbac/roles/${k}`, { method: "DELETE" }),
  roleOf: (uid) => req(`/api/admin/rbac/users/${uid}`),
  assignRoles: (uid, body) =>
    req(`/api/admin/rbac/users/${uid}/roles`, { method: "POST", body }),
  rbacIntakes: () => req("/api/web-admin/rbac/intakes"),
  // ── subscription admin ──
  subOverview: () => req("/api/web-admin/subscription/overview"),
  subPayments: (p) =>
    req("/api/web-admin/subscription/payments?" + new URLSearchParams(p || {})),
  subPaymentDecision: (pid, approved, note = "") =>
    req(`/api/web-admin/subscription/payments/${pid}/decision`, {
      method: "POST",
      body: { approved, note },
    }),
  subReceiptSrc: (pid) => `/api/web-admin/subscription/payments/${pid}/receipt`,
  discounts: () => req("/api/web-admin/subscription/discounts"),
  subSettingsUpdate: (body) =>
    req("/api/web-admin/subscription/settings", { method: "PATCH", body }),
  subPlanAdd: (body) =>
    req("/api/web-admin/subscription/plans", { method: "POST", body }),
  subPlanUpdate: (id, body) =>
    req(`/api/web-admin/subscription/plans/${id}`, { method: "PUT", body }),
  subPlanToggle: (id) =>
    req(`/api/web-admin/subscription/plans/${id}/toggle`, { method: "POST" }),
  subPlanDelete: (id) =>
    req(`/api/web-admin/subscription/plans/${id}`, { method: "DELETE" }),
  subSendReceipt: (id) =>
    req(`/api/web-admin/subscription/payments/${id}/send-receipt`, {
      method: "POST",
    }),
  // 🌊 W5 — بازگشت وجه + مغایرت‌گیری مالی
  subRefund: (pid, body) =>
    req(
      `/api/web-admin/subscription/payments/${encodeURIComponent(pid)}/refund`,
      { method: "POST", body },
    ),
  subReconcile: () => req("/api/web-admin/subscription/reconcile"),
  // 🌊 W5 — اقدام مغایرت + مرکز مالی
  subReconcileActivate: (pid) =>
    req(
      `/api/web-admin/subscription/reconcile/${encodeURIComponent(pid)}/activate`,
      { method: "POST", body: { confirm: true } },
    ),
  subReconFinalizeTopup: (pid) =>
    req(
      `/api/web-admin/subscription/reconcile/${encodeURIComponent(pid)}/finalize-topup`,
      { method: "POST", body: { confirm: true } },
    ),
  subFinance: () => req("/api/web-admin/subscription/finance"),
  // 🌊 W5 — ردیابی کامل رسید + خروجی CSV کرانه‌دار
  subPaymentTrace: (pid) =>
    req(
      `/api/web-admin/subscription/payments/${encodeURIComponent(pid)}/trace`,
    ),
  exportPaymentsCsv: (p = {}) =>
    downloadFile(
      "/api/web-admin/exports/payments.csv?" +
        new URLSearchParams(
          Object.entries(p).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
      `humsyar-payments-${fileDateStamp()}.csv`,
    ),
  exportWalletCsv: (p = {}) =>
    downloadFile(
      "/api/web-admin/exports/wallet.csv?" +
        new URLSearchParams(
          Object.entries(p).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
      `humsyar-wallet-${fileDateStamp()}.csv`,
    ),
  // 💰 W6 — کیف پول داخلی
  subWallets: (p = {}) =>
    req(
      "/api/web-admin/wallets?" +
        new URLSearchParams(
          Object.entries(p).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
    ),
  subWalletDetail: (uid, p = {}) =>
    req(
      `/api/web-admin/wallets/${uid}?` +
        new URLSearchParams(
          Object.entries(p).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
    ),
  subWalletAdjust: (uid, body) =>
    req(`/api/web-admin/wallets/${uid}/adjust`, { method: "POST", body }),
  subWalletRecredit: (pid) =>
    req("/api/web-admin/subscription/reconcile/wallet-recredit", {
      method: "POST",
      body: { payment_id: pid, confirm: true },
    }),
  subWalletResync: (uid) =>
    req(`/api/web-admin/wallets/${uid}/resync`, {
      method: "POST",
      body: { confirm: true },
    }),
  subWalletTxResolve: (txId, action) =>
    req(`/api/web-admin/wallet-tx/${encodeURIComponent(txId)}/resolve`, {
      method: "POST",
      body: { action, confirm: true },
    }),
  subSubscribers: (p) =>
    req(
      "/api/web-admin/subscription/subscribers?" + new URLSearchParams(p || {}),
    ),
  subSubscriber: (uid) => req(`/api/web-admin/subscription/subscribers/${uid}`),
  subUserSearch: (q) =>
    req("/api/web-admin/subscription/users/search?q=" + encodeURIComponent(q)),
  subGrant: (body) =>
    req("/api/web-admin/subscription/subscribers/grant", {
      method: "POST",
      body,
    }),
  subGrantBulk: (body) =>
    req("/api/web-admin/subscription/subscribers/grant-bulk", {
      method: "POST",
      body,
    }),
  subRevoke: (uid, reason) =>
    req(`/api/web-admin/subscription/subscribers/${uid}/revoke`, {
      method: "POST",
      body: { reason },
    }),
  // 🌊 W8/MISS-03 — خانواده
  subFamily: (ownerId) =>
    req(`/api/web-admin/subscription/family?owner_id=${ownerId}`),
  subFamilyAdd: (ownerId, userId) =>
    req("/api/web-admin/subscription/family/members", {
      method: "POST",
      body: { owner_id: ownerId, user_id: userId },
    }),
  subFamilyRemove: (ownerId, userId) =>
    req(`/api/web-admin/subscription/family/members/${userId}?owner_id=${ownerId}`, {
      method: "DELETE",
    }),
  discountAdd: (body) =>
    req("/api/web-admin/subscription/discounts", { method: "POST", body }),
  discountToggle: (code) =>
    req(
      `/api/web-admin/subscription/discounts/${encodeURIComponent(code)}/toggle`,
      { method: "POST" },
    ),
  discountDelete: (code) =>
    req(`/api/web-admin/subscription/discounts/${encodeURIComponent(code)}`, {
      method: "DELETE",
    }),
  discountPreview: (code) =>
    req(
      `/api/web-admin/subscription/discounts/${encodeURIComponent(code)}/preview`,
      { method: "POST" },
    ),
  discountBroadcast: (code, body) =>
    req(
      `/api/web-admin/subscription/discounts/${encodeURIComponent(code)}/broadcast`,
      { method: "POST", body },
    ),
  discountBroadcastStatus: (code, bid) =>
    req(
      `/api/web-admin/subscription/discounts/${encodeURIComponent(code)}/broadcast/${bid}`,
    ),
  discountBroadcastCancel: (code, bid) =>
    req(
      `/api/web-admin/subscription/discounts/${encodeURIComponent(code)}/broadcast/${bid}/cancel`,
      { method: "POST" },
    ),
  discountBroadcasts: (code) =>
    req(
      `/api/web-admin/subscription/discounts/${encodeURIComponent(code)}/broadcasts`,
    ),
  discountStats: (code) =>
    req(
      `/api/web-admin/subscription/discounts/${encodeURIComponent(code)}/stats`,
    ),
  subCardUpdate: (body) =>
    req("/api/web-admin/subscription/card", { method: "PUT", body }),
  // ── content (scope-aware) ──
  caIntakes: () => req("/api/content/intakes"),
  caOverview: (intake) =>
    req("/api/content/overview" + (intake ? `?intake=${intake}` : "")),
  questionIntakes: () => req("/api/web-admin/questions/intakes"),
  caQuestionsPending: (intake) =>
    req(
      "/api/web-admin/questions/pending" +
        (intake ? `?intake=${encodeURIComponent(intake)}` : ""),
    ),
  caQuestionApprove: (qid) =>
    req(`/api/web-admin/questions/${qid}/approve`, {
      method: "POST",
      body: { reason: "" },
    }),
  caQuestionReject: (qid, reason) =>
    req(`/api/web-admin/questions/${qid}/reject`, {
      method: "POST",
      body: { reason },
    }),
  caQuestionNeedsChanges: (qid, reason) =>
    req(`/api/web-admin/questions/${qid}/needs-changes`, {
      method: "POST",
      body: { reason },
    }),
  // 🛡 §۸۴ — حذف سخت سؤال (مجوز questions.delete). دلیل در query می‌رود
  // چون DELETE بدنه ندارد؛ همان قرارداد سرور.
  caQuestionDelete: (qid, reason = "") =>
    req(
      `/api/web-admin/questions/${qid}?reason=${encodeURIComponent(reason)}`,
      { method: "DELETE" },
    ),
  // 🌊 موج Q-Editor — ویرایش سؤال پیش از تأیید (scope-aware + audit)
  caQuestionPatch: (qid, body) =>
    req(`/api/web-admin/questions/${qid}`, { method: "PATCH", body }),
  // §W9 — گزارش‌های سؤال. هر دو به content_admin delegate می‌شوند.
  reportedQuestions: (p = {}) =>
    req(
      "/api/web-admin/questions/reported?" +
        new URLSearchParams(
          Object.entries(p).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
    ),
  questionReports: (qid, limit = 50) =>
    req(`/api/web-admin/questions/${qid}/reports?limit=${limit}`),
  // ── 🌊 WA3 — مدیریت کامل کاربر (permission-based، آینه‌ی دقیق ربات) ──
  waUserMessage: (uid, text) =>
    req(`/api/web-admin/users/${uid}/message`, {
      method: "POST",
      body: { text },
    }),
  waUserAction: (uid, action, reason = "") =>
    req(`/api/web-admin/users/${uid}/action`, {
      method: "POST",
      body: { action, reason },
    }),
  waUserPatch: (uid, body) =>
    req(`/api/web-admin/users/${uid}`, { method: "PATCH", body }),
  blacklist: () => req("/api/web-admin/blacklist"),
  // ── 🌊 WA3 — reorder محتوا ──
  waReorderLesson: (lid, direction) =>
    req(`/api/web-admin/content/lessons/${lid}/reorder`, {
      method: "POST",
      body: { direction },
    }),
  waReorderSession: (sid, direction) =>
    req(`/api/web-admin/content/sessions/${sid}/reorder`, {
      method: "POST",
      body: { direction },
    }),
  waReorderItem: (cid, direction) =>
    req(`/api/web-admin/content/items/${cid}/reorder`, {
      method: "POST",
      body: { direction },
    }),
  // ── 🌊 WA3 — تب‌های پریتی محتوا (همان API موجود content_admin) ──
  caSchedule: (stype) =>
    req("/api/web-admin/schedule" + (stype ? `?stype=${stype}` : "")),
  caScheduleCreate: (body) =>
    req("/api/web-admin/schedule", { method: "POST", body }),
  caScheduleEdit: (sid, body) =>
    req(`/api/web-admin/schedule/${sid}`, { method: "PATCH", body }),
  caScheduleDel: (sid) =>
    req(`/api/web-admin/schedule/${sid}`, { method: "DELETE" }),
  caScheduleBulkClear: (group, stype) => {
    const qs = new URLSearchParams();
    if (group) qs.set("group", group);
    if (stype) qs.set("stype", stype);
    const q = qs.toString() ? `?${qs.toString()}` : "";
    return req(`/api/web-admin/schedule${q}`, { method: "DELETE" });
  },
  caScheduleBulkDelete: (body) =>
    req("/api/web-admin/schedule/bulk-delete", { method: "POST", body }),
  caFlexChange: (sid, body) =>
    req(`/api/web-admin/schedule/${sid}/flex-change`, { method: "POST", body }),
  // ── 🧠 الگوی هفتگی (شنبه-جمعه) + اسکن هوشیار ──
  caScheduleTemplates: (group) =>
    req(
      "/api/web-admin/schedule/templates" +
        (group ? `?group=${encodeURIComponent(group)}` : ""),
    ),
  caScheduleTemplatesBulk: (body) =>
    req("/api/web-admin/schedule/templates/bulk", { method: "POST", body }),
  caScheduleTemplatesClear: (group) =>
    req(
      "/api/web-admin/schedule/templates" +
        (group ? `?group=${encodeURIComponent(group)}` : ""),
      { method: "DELETE" },
    ),
  caScheduleTemplatesGenerate: (body) =>
    req("/api/web-admin/schedule/templates/generate", { method: "POST", body }),
  caScheduleTemplatesScan: (file, group) => {
    const fd = new FormData();
    fd.append("file", file);
    return req(
      "/api/web-admin/schedule/templates/scan" +
        (group ? `?group=${encodeURIComponent(group)}` : ""),
      { method: "POST", form: fd },
    );
  },
  caScheduleTemplatesScanConfirm: (body) =>
    req("/api/web-admin/schedule/templates/scan/confirm", {
      method: "POST",
      body,
    }),
  caScheduleExamsScan: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return req("/api/web-admin/schedule/exams/scan", {
      method: "POST",
      form: fd,
    });
  },
  caScheduleExamsScanConfirm: (body) =>
    req("/api/web-admin/schedule/exams/scan/confirm", { method: "POST", body }),
  caFaq: () => req("/api/content/faq"),
  caFaqAdd: (body) => req("/api/content/faq", { method: "POST", body }),
  caFaqDel: (fid) => req(`/api/content/faq/${fid}`, { method: "DELETE" }),
  caFaqEdit: (fid, body) =>
    req(`/api/content/faq/${fid}`, { method: "PATCH", body }),
  refSubjects: (intake) =>
    req(
      "/api/content/references/subjects" +
        (intake ? `?intake=${encodeURIComponent(intake)}` : ""),
    ),
  refSubjectAdd: (body) =>
    req("/api/content/references/subjects", { method: "POST", body }),
  refSubjectEdit: (sid, name) =>
    req(`/api/content/references/subjects/${sid}`, {
      method: "PATCH",
      body: { name },
    }),
  refSubjectReorder: (sid, direction) =>
    req(`/api/content/references/subjects/${sid}/reorder`, {
      method: "POST",
      body: { direction },
    }),
  refSubjectDel: (sid) =>
    req(`/api/content/references/subjects/${sid}`, { method: "DELETE" }),
  refSubjectMoveRoot: (sid, intake) =>
    req(`/api/content/references/subjects/${sid}/move`, {
      method: "POST",
      body: { intake },
    }),
  refBooks: (sid) => req(`/api/content/references/subjects/${sid}/books`),
  refBookAdd: (sid, name) =>
    req(`/api/content/references/subjects/${sid}/books`, {
      method: "POST",
      body: { name },
    }),
  refBookEdit: (bid, name) =>
    req(`/api/content/references/books/${bid}`, {
      method: "PATCH",
      body: { name },
    }),
  refBookReorder: (bid, direction) =>
    req(`/api/content/references/books/${bid}/reorder`, {
      method: "POST",
      body: { direction },
    }),
  refBookDel: (bid) =>
    req(`/api/content/references/books/${bid}`, { method: "DELETE" }),
  refBookFork: (bid, intake) =>
    req(
      `/api/content/references/books/${bid}/fork?intake=${encodeURIComponent(intake)}`,
      { method: "POST" },
    ),
  refBookUnfork: (bid) =>
    req(`/api/content/references/books/${bid}/fork`, { method: "DELETE" }),
  refFiles: (bid, p = {}) =>
    req(
      `/api/content/references/books/${bid}/files?` +
        new URLSearchParams(
          Object.entries(p).filter(([, v]) => v !== undefined && v !== null),
        ),
    ),
  refFileAdd: (bid, form) =>
    req(`/api/content/references/books/${bid}/files`, { method: "POST", form }),
  refFileDel: (fid) =>
    req(`/api/content/references/files/${fid}`, { method: "DELETE" }),
  // ── 🌊 WA3 — نمرات (grades/recent + find-student + bulk) — همان ادمین ربات ──
  gradeIntakes: () => req("/api/web-admin/grades/intakes"),
  gradesRecent: (skip = 0, limit = 30, filters = {}) =>
    req(
      "/api/web-admin/grades/recent?" +
        new URLSearchParams({
          skip,
          limit,
          ...Object.fromEntries(
            Object.entries(filters).filter(
              ([, v]) => v !== "" && v !== null && v !== undefined,
            ),
          ),
        }),
    ),
  gradesFind: (name) =>
    req(`/api/web-admin/grades/find-student?q=${encodeURIComponent(name)}`),
  gradeTermOptions: () => req("/api/web-admin/grades/term-options"),
  gradeLessonTerm: (lesson) =>
    req(
      `/api/web-admin/grades/lesson-term?lesson=${encodeURIComponent(lesson)}`,
    ),
  gradesBulk: (body) =>
    req("/api/web-admin/grades/bulk", {
      method: "POST",
      body: {
        ...body,
        entries: (body.entries || []).map((e) => ({
          user_id: e.user_id ?? e.student_id,
          score: e.score,
        })),
        // 🛡 §۸۲-ج — ترم الزامی است؛ اگر خالی باشد سرور ۴۲۲ می‌دهد تا ادمین صریح انتخاب کند.
        term: (body.term || "").trim(),
      },
    }),
  gradeUpdate: (gid, score) =>
    req(`/api/web-admin/grades/${gid}`, { method: "PATCH", body: { score } }),
  gradeDelete: (gid) =>
    req(`/api/web-admin/grades/${gid}`, { method: "DELETE" }),
  // ── ai admin ──
  aiStats: () => req("/api/web-admin/ai/stats"),
  aiConfig: () => req("/api/web-admin/ai/config"),
  aiModels: () => req("/api/web-admin/ai/models"),
  aiConfigUpdate: (body) =>
    req("/api/web-admin/ai/config", { method: "PUT", body }),
  aiKeyRotate: (apiKey) =>
    req("/api/web-admin/ai/api-key/rotate", {
      method: "POST",
      body: { api_key: apiKey },
    }),
  aiTest: () => req("/api/web-admin/ai/test", { method: "POST" }),
  aiProfile: (uid) => req(`/api/web-admin/ai/users/${uid}/profile`),
  aiProfileClear: (uid) =>
    req(`/api/web-admin/ai/users/${uid}/profile`, { method: "DELETE" }),
  aiPersonas: () => req("/api/web-admin/ai/personas"),
  aiPersonaCreate: (body) =>
    req("/api/web-admin/ai/personas", { method: "POST", body }),
  aiPersonaActivate: (name) =>
    req(`/api/web-admin/ai/personas/${encodeURIComponent(name)}/activate`, {
      method: "POST",
    }),
  aiPersonaDelete: (name) =>
    req(`/api/web-admin/ai/personas/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
  aiBroadcastDraft: (notes) =>
    req("/api/web-admin/ai/broadcast-draft", {
      method: "POST",
      body: { notes },
    }),
  aiReports: (p = {}) =>
    req(
      "/api/web-admin/ai/reports?" +
        new URLSearchParams(
          Object.entries(p).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
    ),
  exportAiReports: (p = {}) =>
    downloadFile(
      "/api/web-admin/exports/ai-reports.csv?" +
        new URLSearchParams(
          Object.entries({ ...p, human: true }).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
      `humsyar-ai-reports-${fileDateStamp()}.csv`,
    ),
  aiBanned: (p = {}) =>
    req(
      "/api/web-admin/ai/banned?" +
        new URLSearchParams(
          Object.entries(p).filter(
            ([, v]) => v !== "" && v !== null && v !== undefined,
          ),
        ),
    ),
  aiUsers: (q) => req("/api/web-admin/ai/users?q=" + encodeURIComponent(q)),
  aiBan: (uid) =>
    req("/api/web-admin/ai/users/ban", {
      method: "POST",
      body: { user_id: uid },
    }),
  aiResetQuota: (uid) =>
    req("/api/web-admin/ai/users/reset-quota", {
      method: "POST",
      body: { user_id: uid },
    }),
  // ── 💍 Ring Street (admin) ──
  ringOverview: () => req("/api/ring/overview"),
  ringQueue: (p = {}) => req(`/api/ring/queue?${_ringQ(p)}`),
  ringSessions: (p = {}) => req(`/api/ring/sessions?${_ringQ(p)}`),
  ringSession: (sid) => req(`/api/ring/sessions/${encodeURIComponent(sid)}`),
  ringEndSession: (sid, reason = "admin") =>
    req(`/api/ring/sessions/${encodeURIComponent(sid)}/end`, {
      method: "POST",
      body: { reason },
    }),
  ringReports: (p = {}) => req(`/api/ring/reports?${_ringQ(p)}`),
  ringReport: (rid) => req(`/api/ring/reports/${rid}`),
  ringReview: (rid, action, note = "") =>
    req(`/api/ring/reports/${rid}/review`, {
      method: "POST",
      body: { action, note },
    }),
  ringProfiles: (p = {}) => req(`/api/ring/profiles?${_ringQ(p)}`),
  ringProfile: (uid) => req(`/api/ring/profiles/${uid}`),
  ringPause: (uid) =>
    req(`/api/ring/profiles/${uid}/pause`, { method: "POST" }),
  ringResume: (uid) =>
    req(`/api/ring/profiles/${uid}/resume`, { method: "POST" }),
  ringQueueRemove: (uid) =>
    req(`/api/ring/profiles/${uid}/queue/remove`, { method: "POST" }),
  ringBlocks: (p = {}) => req(`/api/ring/blocks?${_ringQ(p)}`),
  ringBans: () => req("/api/ring/bans"),
  ringBan: (body) => req("/api/ring/bans", { method: "POST", body }),
  ringUnban: (uid) => req(`/api/ring/bans/${uid}`, { method: "DELETE" }),
  // §۴۶/§۴۷/§۴۹ (V6) — سلامتِ چرخهٔ مچ، سلامتِ یک جلسه، و ترمیمِ محافظه‌کارانه
  ringMetrics: (days = 7) =>
    req(`/api/ring/metrics?days=${encodeURIComponent(days)}`),
  ringSessionHealth: (sid) =>
    req(`/api/ring/sessions/${encodeURIComponent(sid)}/health`),
  ringSessionRepair: (sid) =>
    req(`/api/ring/sessions/${encodeURIComponent(sid)}/repair`, {
      method: "POST",
    }),
  ringForceMatch: (user_a, user_b) =>
    req("/api/ring/force-match", { method: "POST", body: { user_a, user_b } }),
  // §۳۷/§۳۸ (V4) — «چرا این دو مچ نشدند؟» با همان الگوریتمِ زنده
  ringDebugMatch: (a, b) => req(`/api/ring/debug-match?${_ringQ({ a, b })}`),
  ringSettings: () => req("/api/ring/settings"),
  ringSaveSettings: (updates) =>
    req("/api/ring/settings", { method: "POST", body: { updates } }),
  ringFlag: (enabled, disable_mode = "soft") =>
    req("/api/ring/flag", { method: "POST", body: { enabled, disable_mode } }),
  ringState: () => req("/api/ring/state"),
  ringSetState: (state, disable_mode = "soft") =>
    req("/api/ring/state", { method: "POST", body: { state, disable_mode } }),
  ringRules: () => req("/api/ring/rules"),
  ringSaveRules: (text, bump_version = true) =>
    req("/api/ring/rules", { method: "POST", body: { text, bump_version } }),
  ringAnalytics: (days = 7) => req(`/api/ring/analytics?days=${days}`),
  ringAuditList: (limit = 60) => req(`/api/ring/audit?limit=${limit}`),
  ringReconcile: () =>
    req("/api/ring/maintenance/reconcile", { method: "POST" }),
  // 🌊 W7 — نیازمند اقدام قابل‌بستن + مدیریت اسپم کیف پول
  attentionDismiss: (key, reason, dismiss_hours=24) => req("/api/web-admin/attention/dismiss", { method: "POST", body: { key, reason, dismiss_hours } }),
  attentionRestore: (key) => req("/api/web-admin/attention/restore", { method: "POST", body: { key } }),
  attentionDismissals: () => req("/api/web-admin/attention/dismissals"),
  walletAlerts: () => req("/api/web-admin/system/wallet-alerts"),
  walletAlertsPatch: (body) => req("/api/web-admin/system/wallet-alerts", { method: "PATCH", body }),
  // 💳 W6 — Zarinpal Gateway (DB-backed, no restart)
  gatewayZarinpal: () => req("/api/admin/gateway/zarinpal"),
  gatewayZarinpalUpdate: (body) => req("/api/admin/gateway/zarinpal", { method: "PUT", body }),
  gatewayZarinpalTest: () => req("/api/admin/gateway/zarinpal/test", { method: "POST" }),

  ringPurge: () =>
    req("/api/ring/maintenance/purge-evidence", { method: "POST" }),
};

export function errText(e) {
  if (!e) return "خطای ناشناخته";
  const raw = e.message || String(e);
  const map = {
    forbidden: "مجوز لازم برای این بخش را ندارید.",
    admin_only: "این بخش فقط برای مالک سامانه است.",
    not_registered: "حساب موردنظر پیدا نشد.",
    missing_init_data: "نشست منقضی شده است؛ دوباره وارد شوید.",
    intake_out_of_scope: "این مورد خارج از محدوده ورودی شماست.",
    intake_not_configured:
      "برای نقش شما هنوز ورودی‌ای تنظیم نشده؛ از ادمین ارشد بخواهید ورودی‌تان را تعیین کند.",
    content_admin_only: "این بخش فقط برای مدیر محتواست.",
    request_timeout: "پاسخ سرویس بیش از حد طول کشید؛ دوباره تلاش کنید.",
  };
  // 🌊 range fix — برای 422 جزئیات اعتبارسنجی را نشان بده تا «بعضی ورودی‌ها...» مبهم نماند
  if (e.status === 422 && e.technical) {
    let detail = e.technical;
    try {
      const parsed = JSON.parse(e.technical);
      if (Array.isArray(parsed?.detail)) {
        detail = parsed.detail
          .map((x) => `${(x.loc || []).join(".")}: ${x.msg}`)
          .join(" | ");
      } else if (typeof parsed?.detail === "string") detail = parsed.detail;
    } catch {}
    // truncate
    if (detail.length > 500) detail = detail.slice(0, 500) + "…";
    const base = e.friendly || map[raw] || friendlyStatus(422);
    // اگر فقط HTTP 422 بود، همان friendly کافیست، ولی اگر detail واقعی دارد نمایش بده
    if (detail && detail !== "HTTP 422" && !detail.includes("HTTP 422")) {
      const combined = `${base} — ${detail}`;
      return e.errorId ? `${combined} · شناسه پیگیری: ${e.errorId}` : combined;
    }
  }
  const message =
    e.friendly ||
    map[raw] ||
    (e.status >= 500 || /^خطا\s*\(5\d\d\)/.test(raw)
      ? friendlyStatus(e.status || 500)
      : raw || friendlyStatus(e.status || 0));
  return e.errorId ? `${message} · شناسه پیگیری: ${e.errorId}` : message;
}

// 📥 خروجی CSV سمت کلاینت (بدون رفت‌وبرگشت سرور)
export function exportCSV(filename, columns, rows) {
  const esc = (v) => '"' + String(v ?? "").replaceAll('"', '""') + '"';
  const lines = [columns.map((c) => esc(c.label)).join(",")];
  for (const r of rows)
    lines.push(
      columns
        .map((c) => esc(typeof c.v === "function" ? c.v(r) : r[c.v]))
        .join(","),
    );
  const blob = new Blob(["﻿" + lines.join("\n")], {
    type: "text/csv;charset=utf-8",
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
