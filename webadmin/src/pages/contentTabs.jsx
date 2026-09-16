import React, { useEffect, useState } from "react";
import { api, errText } from "../api.js";
import {
  DataTable,
  Loading,
  ErrorState,
  Empty,
  B,
  FaDateTime,
  toast,
  Confirm,
  Modal,
  NoPerm,
} from "../ui.jsx";
import SavedViews from "../SavedViews.jsx";
import { PersianDatePicker } from "../PersianDatePicker.jsx";
import {
  faDigits,
  formatFaDate,
  formatFaTime,
  jalaliDateParts,
  jalaliMonthLengthFor,
} from "../time.js";
import {
  ContentActionGroup,
  ContentBreadcrumb,
  ContentDensityToggle,
  ContentEmptyState,
  ContentErrorState,
  ContentIconButton,
  ContentItem,
  ContentKV,
  ContentMetric,
  ContentMoreActions,
  ContentPane,
  ContentReorderControls,
  ContentShell,
  ContentSkeleton,
  ContentStats,
  ContentToolbar,
  ContentWorkspace,
  FileTypeBadge,
  ScopeBadge,
  useContentDensity,
} from "../ContentPrimitives.jsx";

// ── 🔗 Harmonized schedule merge helper (single source of truth for 1h→2h) ──
function mergeScheduleBlocks(list) {
  const _p = (v) => {
    const m = String(v || "").match(/(\d{1,2}):(\d{2})/);
    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
  };
  const _f = (min) => `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
  const sorted = [...(list || [])].sort(
    (a, b) => (a.date || "").localeCompare(b.date || "") || String(a.time || "").localeCompare(String(b.time || "")),
  );
  const out = [];
  for (const cur of sorted) {
    const prev = out[out.length - 1];
    if (
      prev &&
      prev.date === cur.date &&
      prev.lesson === cur.lesson &&
      (prev.group || "") === (cur.group || "") &&
      (prev.type || "class") === (cur.type || "class") &&
      (prev.location || "") === (cur.location || "") &&
      (prev.teacher || "") === (cur.teacher || "")
    ) {
      const prevEnd = _p(prev.end_time || prev.time_end || "") ?? (_p(prev.time) !== null ? _p(prev.time) + 60 : null);
      const prevStart = _p(prev.time);
      const prevDur = prevEnd !== null && prevStart !== null ? prevEnd - prevStart : null;
      const curStart = _p(cur.time);
      const curEnd = _p(cur.end_time || cur.time_end || "") ?? (curStart !== null ? curStart + 60 : null);
      const curDur = curEnd !== null && curStart !== null ? curEnd - curStart : null;
      if (prevEnd !== null && curStart !== null && prevEnd === curStart && curEnd !== null && prevDur === 60 && curDur === 60) {
        prev.end_time = _f(curEnd);
        prev._merged = (prev._merged || 1) + 1;
        prev._mergedIds = [...(prev._mergedIds || [prev.id]), cur.id];
        continue;
      }
    }
    out.push({ ...cur, _mergedIds: [cur.id] });
  }
  return out;
}


// ════════════════════════════════════════════════════════════════════
// 🌊 WA3 — تب‌های پریتی «مرکز فرماندهی محتوا» (همه روی API موجود، scope-aware)
// ════════════════════════════════════════════════════════════════════

export function useIntakes() {
  const [meta, setMeta] = useState({
    intakes: [],
    scope_kind: "global",
    scope_intake: "",
  });
  useEffect(() => {
    api
      .caIntakes()
      .then((r) =>
        setMeta({
          intakes: r.intakes || [],
          scope_kind: r.scope_kind || "global",
          scope_intake: r.scope_intake || "",
        }),
      )
      .catch(() => {});
  }, []);
  return meta;
}

function IntakeSelect({ intakes, value, onChange, scopeKind = "global" }) {
  return (
    <select
      className="inp"
      value={value}
      disabled={scopeKind === "scoped"}
      onChange={(e) => onChange(e.target.value)}
    >
      {scopeKind === "global" && <option value="">🌐 سراسری (پایه)</option>}
      {intakes.map((i) => (
        <option key={i.code || i} value={i.code || i}>
          🏷 {i.label || i.code || i}
        </option>
      ))}
    </select>
  );
}

// ── 📖 رفرنس‌ها: موضوع → کتاب → فایل (سه‌ستونه‌ی فرماندهی) ──────────
export function RefsTab() {
  const intakeMeta = useIntakes();
  const intakes = intakeMeta.intakes;
  const [intake, setIntake] = useState("");
  const [subjects, setSubjects] = useState(null);
  const [err, setErr] = useState("");
  const [permErr, setPermErr] = useState(false);
  const [sub, setSub] = useState(null);
  const [books, setBooks] = useState(null);
  const [booksReadonly, setBooksReadonly] = useState(false);
  const [booksCanCreate, setBooksCanCreate] = useState(false); // 🌊 C3
  const [book, setBook] = useState(null);
  const [files, setFiles] = useState(null);
  const [filesPage, setFilesPage] = useState({ total: 0, hasMore: false });
  const [filesReadonly, setFilesReadonly] = useState(false);
  const [addModal, setAddModal] = useState(null); // {kind:'subject'|'book'|'file'}
  const [editModal, setEditModal] = useState(null); // {kind,item}
  const [confirm, setConfirm] = useState(null); // {text, run}
  const [rootMove, setRootMove] = useState(null);
  const [booksErr, setBooksErr] = useState("");
  const [filesErr, setFilesErr] = useState("");
  const [density, setDensity] = useContentDensity();
  useEffect(() => {
    if (intakeMeta.scope_kind === "scoped" && intakeMeta.scope_intake)
      setIntake(intakeMeta.scope_intake);
  }, [intakeMeta.scope_kind, intakeMeta.scope_intake]);

  const loadSubjects = async () => {
    setErr("");
    try {
      const r = await api.refSubjects(intake || undefined);
      setSubjects(r.subjects || []);
      if (!intake && r.intake) setIntake(r.intake);
    } catch (e) {
      if (e.status === 403) setPermErr(true);
      else setErr(errText(e));
    }
  };
  useEffect(() => {
    setSub(null);
    setBook(null);
    loadSubjects();
  }, [intake]);
  const loadBooks = async (selectedSubject) => {
    setSub(selectedSubject);
    setBook(null);
    setBooks(null);
    setBooksErr("");
    setFilesErr("");
    try {
      const r = await api.refBooks(selectedSubject.id);
      setBooks(r.books || []);
      setBooksReadonly(!!r.readonly);
      setBooksCanCreate(!!r.can_create_own);
    } catch (e) {
      setBooksErr(errText(e));
    }
  };
  const loadFiles = async (selectedBook, append = false) => {
    const currentCount = append ? (files || []).length : 0;
    setBook(selectedBook);
    if (!append) setFiles(null);
    setFilesErr("");
    try {
      const r = await api.refFiles(selectedBook.id, {
        skip: currentCount,
        limit: 50,
      });
      const batch = r.files || [];
      setFiles((previous) =>
        append ? [...(previous || []), ...batch] : batch,
      );
      setFilesPage({
        total: Number(r.total ?? batch.length),
        hasMore: Boolean(r.has_more),
      });
      setFilesReadonly(!!r.readonly);
    } catch (e) {
      setFilesErr(errText(e));
    }
  };
  const reorderRef = async (fn, reload) => {
    try {
      const r = await fn();
      if (r?.ok === false)
        return toast("به ابتدا/انتهای فهرست رسیده‌اید", "err");
      toast("ترتیب ذخیره شد ✅");
      await reload();
    } catch (e) {
      toast(errText(e), "err");
    }
  };

  if (permErr) return <NoPerm text="مدیریت رفرنس‌ها فقط برای مدیر محتواست" />;

  const selectedIntakeLabel = intake
    ? intakes.find((item) => (item.code || item) === intake)?.label || intake
    : "سراسری";
  return (
    <ContentShell density={density}>
      <ContentBreadcrumb
        items={[
          { label: "محتوا" },
          { label: "رفرنس‌ها" },
          { label: selectedIntakeLabel },
          ...(sub ? [{ label: sub.name }] : []),
          ...(book ? [{ label: book.name }] : []),
        ]}
      />
      <SavedViews
        scope="content-references"
        density={density}
        filters={{ intake }}
        onApply={(filters) => setIntake(filters.intake || "")}
        label="نماهای رفرنس"
      />
      <ContentToolbar>
        <IntakeSelect
          intakes={intakes}
          value={intake}
          onChange={setIntake}
          scopeKind={intakeMeta.scope_kind}
        />
        <span className="spacer" />
        <ContentDensityToggle value={density} onChange={setDensity} />
        <button
          className="btn sm primary"
          onClick={() => setAddModal({ kind: "subject" })}
        >
          ➕ موضوع
        </button>
      </ContentToolbar>
      {err ? (
        <ContentErrorState
          title="موضوع‌های رفرنس بارگذاری نشد"
          error={err}
          onRetry={loadSubjects}
        />
      ) : (
        <ContentWorkspace columns={3}>
          <ContentPane
            icon="📖"
            title="موضوع‌ها"
            count={subjects ? subjects.length.toLocaleString("fa") : null}
          >
            {!subjects ? (
              <ContentSkeleton panes={1} rows={5} />
            ) : subjects.length === 0 ? (
              <ContentEmptyState
                icon="📖"
                title="هنوز موضوعی ثبت نشده"
                description="برای ساخت ساختار رفرنس، نخستین موضوع را ایجاد کنید."
                action={
                  <button
                    className="btn sm primary"
                    onClick={() => setAddModal({ kind: "subject" })}
                  >
                    افزودن موضوع
                  </button>
                }
              />
            ) : (
              subjects.map((subject, index) => (
                <ContentItem
                  key={subject.id}
                  icon="📖"
                  title={subject.name}
                  active={sub?.id === subject.id}
                  readonly={subject.readonly}
                  scope={subject.intake ? "intake" : "global"}
                  scopeLabel={subject.intake || "سراسری"}
                  onClick={() => loadBooks(subject)}
                  actions={
                    !subject.readonly ? (
                      <>
                        <ContentReorderControls
                          noun="موضوع"
                          canUp={index > 0}
                          canDown={index < subjects.length - 1}
                          onUp={() =>
                            reorderRef(
                              () => api.refSubjectReorder(subject.id, "up"),
                              loadSubjects,
                            )
                          }
                          onDown={() =>
                            reorderRef(
                              () => api.refSubjectReorder(subject.id, "down"),
                              loadSubjects,
                            )
                          }
                        />
                        <ContentIconButton
                          icon="✎"
                          label="ویرایش نام موضوع"
                          kind="primary"
                          onClick={() =>
                            setEditModal({ kind: "subject", item: subject })
                          }
                        />
                        <ContentMoreActions>
                          {intakeMeta.scope_kind === "global" && (
                            <ContentIconButton
                              icon="📦"
                              label="انتقال موضوع به دامنه دیگر"
                              onClick={() =>
                                setRootMove({
                                  kind: "subject",
                                  id: subject.id,
                                  label: subject.name,
                                  from: subject.intake || "",
                                })
                              }
                            />
                          )}
                          <ContentIconButton
                            icon="🗑"
                            label={`حذف موضوع ${subject.name}`}
                            kind="danger"
                            onClick={() =>
                              setConfirm({
                                text: `حذف موضوع «${subject.name}» با همه‌ی کتاب‌ها و فایل‌هایش؟`,
                                run: async () => {
                                  await api.refSubjectDel(subject.id);
                                  toast("حذف شد");
                                  setSub(null);
                                  loadSubjects();
                                },
                              })
                            }
                          />
                        </ContentMoreActions>
                      </>
                    ) : null
                  }
                />
              ))
            )}
          </ContentPane>

          <ContentPane
            icon="📚"
            title="کتاب‌ها"
            subtitle={sub?.name}
            count={books ? books.length.toLocaleString("fa") : null}
            actions={
              sub && (!sub.readonly || booksCanCreate) ? (
                <button
                  className="btn sm primary"
                  onClick={() => setAddModal({ kind: "book" })}
                  aria-label={`افزودن کتاب به ${sub.name}`}
                >
                  {sub.readonly ? "➕ کتاب (ورودی من)" : "➕ کتاب"}
                </button>
              ) : null
            }
          >
            {!sub ? (
              <ContentEmptyState
                icon="📚"
                title="موضوعی انتخاب نشده"
                description="یک موضوع را برای مشاهده کتاب‌های آن انتخاب کنید."
              />
            ) : booksErr ? (
              <ContentErrorState
                title="کتاب‌ها بارگذاری نشد"
                error={booksErr}
                compact
                onRetry={() => loadBooks(sub)}
              />
            ) : !books ? (
              <ContentSkeleton panes={1} rows={5} />
            ) : books.length === 0 ? (
              <ContentEmptyState
                icon="📕"
                title="هنوز کتابی ثبت نشده"
                description="نخستین کتاب این موضوع را ایجاد کنید."
                action={
                  !sub.readonly || booksCanCreate ? (
                    <button
                      className="btn sm primary"
                      onClick={() => setAddModal({ kind: "book" })}
                    >
                      {sub.readonly
                        ? "افزودن کتاب برای ورودی من"
                        : "افزودن کتاب"}
                    </button>
                  ) : null
                }
              />
            ) : (
              books.map((entry, index) => {
                const editable =
                  !booksReadonly || entry.is_fork || entry.intake === intake;
                const scope = entry.is_fork
                  ? "override"
                  : entry.intake
                    ? "intake"
                    : "global";
                return (
                  <ContentItem
                    key={entry.id}
                    icon={entry.is_fork ? "⭐" : "📕"}
                    title={entry.name}
                    active={book?.id === entry.id}
                    readonly={!editable}
                    scope={scope}
                    scopeLabel={
                      entry.is_fork ? "نسخه اختصاصی" : entry.intake || "سراسری"
                    }
                    onClick={() => loadFiles(entry)}
                    actions={
                      <>
                        {!entry.is_fork && !entry.intake && intake && (
                          <ContentIconButton
                            icon="🍴"
                            label="ساخت نسخه اختصاصی برای این ورودی"
                            kind="primary"
                            onClick={async () => {
                              try {
                                await api.refBookFork(entry.id, intake);
                                toast("نسخه اختصاصی ساخته شد ⭐");
                                loadBooks(sub);
                              } catch (error) {
                                toast(errText(error), "err");
                              }
                            }}
                          />
                        )}
                        {editable && (
                          <>
                            <ContentReorderControls
                              noun="کتاب"
                              canUp={index > 0}
                              canDown={index < books.length - 1}
                              onUp={() =>
                                reorderRef(
                                  () => api.refBookReorder(entry.id, "up"),
                                  () => loadBooks(sub),
                                )
                              }
                              onDown={() =>
                                reorderRef(
                                  () => api.refBookReorder(entry.id, "down"),
                                  () => loadBooks(sub),
                                )
                              }
                            />
                            <ContentIconButton
                              icon="✎"
                              label="ویرایش نام کتاب"
                              kind="primary"
                              onClick={() =>
                                setEditModal({ kind: "book", item: entry })
                              }
                            />
                            <ContentMoreActions>
                              {entry.is_fork && (
                                <ContentIconButton
                                  icon="↩"
                                  label="بازگشت به نسخه سراسری"
                                  onClick={async () => {
                                    try {
                                      await api.refBookUnfork(entry.id);
                                      toast("↩️ بازگشت به نسخه‌ی سراسری");
                                      loadBooks(sub);
                                    } catch (error) {
                                      toast(errText(error), "err");
                                    }
                                  }}
                                />
                              )}
                              <ContentIconButton
                                icon="🗑"
                                label={`حذف کتاب ${entry.name}`}
                                kind="danger"
                                onClick={() =>
                                  setConfirm({
                                    text: `حذف کتاب «${entry.name}» و فایل‌هایش؟`,
                                    run: async () => {
                                      await api.refBookDel(entry.id);
                                      toast("حذف شد");
                                      setBook(null);
                                      loadBooks(sub);
                                    },
                                  })
                                }
                              />
                            </ContentMoreActions>
                          </>
                        )}
                      </>
                    }
                  />
                );
              })
            )}
          </ContentPane>

          <ContentPane
            icon="📁"
            title="فایل‌ها"
            subtitle={book?.name}
            count={
              files
                ? Number(filesPage.total || files.length).toLocaleString("fa")
                : null
            }
            actions={
              book ? (
                filesReadonly ? (
                  <B>🔒 فقط‌خواندنی</B>
                ) : (
                  <button
                    className="btn sm primary"
                    onClick={() => setAddModal({ kind: "file" })}
                  >
                    ⬆️ آپلود فایل
                  </button>
                )
              ) : null
            }
          >
            {!book ? (
              <ContentEmptyState
                icon="📁"
                title="کتابی انتخاب نشده"
                description="یک کتاب را برای مشاهده فایل‌های آن انتخاب کنید."
              />
            ) : filesErr ? (
              <ContentErrorState
                title="فایل‌های کتاب بارگذاری نشد"
                error={filesErr}
                compact
                onRetry={() => loadFiles(book)}
              />
            ) : !files ? (
              <ContentSkeleton panes={1} rows={5} />
            ) : files.length === 0 ? (
              <ContentEmptyState
                icon="📭"
                title="هنوز فایلی ثبت نشده"
                description="نخستین فایل این کتاب را بارگذاری کنید."
                action={
                  !filesReadonly ? (
                    <button
                      className="btn sm primary"
                      onClick={() => setAddModal({ kind: "file" })}
                    >
                      آپلود فایل
                    </button>
                  ) : null
                }
              />
            ) : (
              <>
                {files.map((file) => (
                  <ContentItem
                    key={file.id}
                    icon={<FileTypeBadge type="document" compact />}
                    title={file.description || "(بدون توضیح)"}
                    meta={`${file.lang === "fa" ? "فارسی" : "English"} · جلد ${file.volume}`}
                    readonly={filesReadonly}
                    scope={
                      book.is_fork
                        ? "override"
                        : book.intake
                          ? "intake"
                          : "global"
                    }
                    scopeLabel={
                      book.is_fork ? "نسخه اختصاصی" : book.intake || "سراسری"
                    }
                    metrics={
                      <ContentMetric
                        icon="⬇"
                        value={Number(file.downloads || 0).toLocaleString("fa")}
                        label="دریافت"
                      />
                    }
                    actions={
                      !filesReadonly ? (
                        <ContentIconButton
                          icon="🗑"
                          label={`حذف فایل ${file.description || "بدون عنوان"}`}
                          kind="danger"
                          onClick={() =>
                            setConfirm({
                              text: `حذف فایل «${file.description || "بدون عنوان"}» از کتاب «${book.name}»؟`,
                              run: async () => {
                                await api.refFileDel(file.id);
                                toast("حذف شد");
                                loadFiles(book);
                              },
                            })
                          }
                        />
                      ) : null
                    }
                  />
                ))}
                {filesPage.hasMore && (
                  <button
                    className="btn content-load-more"
                    onClick={() => loadFiles(book, true)}
                  >
                    نمایش فایل‌های بیشتر
                  </button>
                )}
              </>
            )}
          </ContentPane>
        </ContentWorkspace>
      )}

      {addModal && (
        <RefAddModal
          kind={addModal.kind}
          sub={sub}
          book={book}
          intake={intake}
          ownOnly={!!(sub?.readonly && booksCanCreate)}
          onClose={(ok) => {
            const kind = addModal.kind;
            setAddModal(null);
            if (ok) {
              if (kind === "subject") loadSubjects();
              else if (kind === "book") loadBooks(sub);
              else loadFiles(book);
            }
          }}
        />
      )}
      {editModal && (
        <RefNameModal
          kind={editModal.kind}
          item={editModal.item}
          onClose={(ok) => {
            const kind = editModal.kind;
            setEditModal(null);
            if (ok) kind === "subject" ? loadSubjects() : loadBooks(sub);
          }}
        />
      )}
      {confirm && (
        <Confirm
          text={confirm.text}
          danger
          onYes={async () => {
            await confirm.run();
            setConfirm(null);
          }}
          onNo={() => setConfirm(null)}
        />
      )}
      {rootMove && (
        <RootMoveControl
          item={rootMove}
          intakes={intakes}
          onClose={(ok) => {
            setRootMove(null);
            if (ok) {
              setSub(null);
              loadSubjects();
            }
          }}
        />
      )}
    </ContentShell>
  );
}

function RootMoveControl({ item, intakes, onClose }) {
  const [to, setTo] = useState(item.from || "");
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      if (item.kind === "subject") await api.refSubjectMoveRoot(item.id, to);
      // 🛡 قبلاً به api.caMoveQbankRoot می‌خورد که وجود خارجی ندارد
      // (نه در api.js، نه endpointی در بک‌اند) ⇒ TypeError خام.
      // اینجا فقط kind='subject' ساخته می‌شود، پس شاخه غیرقابل‌دسترس
      // است؛ اما خطای صریح بهتر از کرش مبهم برای kind های آینده است.
      else
        throw new Error(
          `انتقال root برای نوع «${item.kind}» هنوز پشتیبانی نمی‌شود`,
        );
      toast("انتقال root انجام شد ✅");
      onClose(true);
    } catch (e) {
      let conflict = "";
      if (e.status === 409) {
        try {
          const d = JSON.parse(e.technical || "{}");
          conflict = `${d.reason || "تعارض مقصد"}${d.existing_id ? ` · Existing: ${d.existing_id}` : ""}`;
        } catch {}
      }
      toast(conflict || errText(e), "err");
      setBusy(false);
    }
  };
  return (
    <Modal title={`📦 انتقال «${item.label}»`} onClose={() => onClose(false)}>
      <div className="muted">
        مبدأ: {item.from || "سراسری"}؛ مقصد را انتخاب کنید. overwrite ضمنی انجام
        نمی‌شود.
      </div>
      <select
        className="inp content-input-full content-row-top-sm"
        value={to}
        onChange={(e) => setTo(e.target.value)}
      >
        <option value="">🌐 سراسری</option>
        {intakes.map((x) => (
          <option key={x.code || x} value={x.code || x}>
            {x.label || x.code || x}
          </option>
        ))}
      </select>
      <div className="row content-row-top">
        <button
          className="btn danger"
          disabled={busy || to === item.from}
          onClick={run}
        >
          تأیید انتقال
        </button>
        <button className="btn" onClick={() => onClose(false)}>
          انصراف
        </button>
      </div>
    </Modal>
  );
}

function RefNameModal({ kind, item, onClose }) {
  const [name, setName] = useState(item.name || "");
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      title={
        kind === "subject" ? "✏️ ویرایش موضوع رفرنس" : "✏️ ویرایش نام کتاب"
      }
      onClose={() => onClose(false)}
    >
      <div className="grid content-modal-grid">
        <input
          className="inp"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
        <div className="row">
          <button
            className="btn primary"
            disabled={busy || !name.trim()}
            onClick={async () => {
              setBusy(true);
              try {
                if (kind === "subject")
                  await api.refSubjectEdit(item.id, name.trim());
                else await api.refBookEdit(item.id, name.trim());
                toast("نام ذخیره شد ✅");
                onClose(true);
              } catch (e) {
                toast(errText(e), "err");
                setBusy(false);
              }
            }}
          >
            ذخیره
          </button>
          <button className="btn" onClick={() => onClose(false)}>
            انصراف
          </button>
        </div>
      </div>
    </Modal>
  );
}

function RefAddModal({ kind, sub, book, intake, ownOnly, onClose }) {
  const [name, setName] = useState("");
  const [lang, setLang] = useState("fa");
  const [volume, setVolume] = useState(1);
  const [desc, setDesc] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const titles = {
    subject: "➕ موضوع جدید",
    book: `➕ کتاب جدید — ${sub?.name}`,
    file: `⬆️ فایل — ${book?.name}`,
  };
  return (
    <Modal title={titles[kind]} onClose={() => onClose(false)}>
      <div className="grid content-modal-grid">
        {kind === "book" && ownOnly ? (
          <div className="muted">
            📅 این کتاب فقط برای ورودی «{intake || "—"}» ساخته می‌شود؛ کتاب‌های
            سراسری این موضوع دست‌نخورده می‌مانند.
          </div>
        ) : null}
        {kind !== "file" && (
          <input
            className="inp"
            placeholder={
              kind === "subject" ? "نام موضوع (مثلاً آناتومی)…" : "نام کتاب…"
            }
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        )}
        {kind === "file" && (
          <>
            <div className="row">
              <select
                className="inp"
                value={lang}
                onChange={(e) => setLang(e.target.value)}
              >
                <option value="fa">🇮🇷 فارسی</option>
                <option value="en">🇬🇧 انگلیسی</option>
              </select>
              <input
                className="inp content-volume-input"
                type="number"
                min="1"
                value={volume}
                onChange={(e) => setVolume(+e.target.value)}
                title="جلد"
              />
            </div>
            <input
              className="inp"
              placeholder="توضیح فایل…"
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
            />
            <input
              type="file"
              className="inp"
              onChange={(e) => setFile(e.target.files[0] || null)}
            />
          </>
        )}
        <div className="row">
          <button
            className="btn primary"
            disabled={busy || (kind === "file" ? !file : !name.trim())}
            onClick={async () => {
              setBusy(true);
              try {
                if (kind === "subject")
                  await api.refSubjectAdd({
                    name: name.trim(),
                    intake: intake || "",
                  });
                else if (kind === "book")
                  await api.refBookAdd(sub.id, name.trim());
                else {
                  const fd = new FormData();
                  fd.append("lang", lang);
                  fd.append("volume", volume);
                  fd.append("description", desc || (file && file.name) || "");
                  fd.append("file", file);
                  await api.refFileAdd(book.id, fd);
                }
                toast("ثبت شد ✅");
                onClose(true);
              } catch (e) {
                toast(errText(e), "err");
              }
              setBusy(false);
            }}
          >
            {busy ? "⏳…" : "ثبت"}
          </button>
          <button className="btn" onClick={() => onClose(false)}>
            انصراف
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ── 📅 کلاس‌ها و برنامه (schedule با flex + الگوی هفتگی + اسکن هوشیار) ─
const SCHED_TYPES = [
  ["", "همه"],
  ["class", "🏫 کلاس"],
  ["exam", "📝 امتحان"],
  ["makeup", "🔄 جبرانی"],
];
const WEEKDAY_FA = [
  "شنبه",
  "یکشنبه",
  "دوشنبه",
  "سه‌شنبه",
  "چهارشنبه",
  "پنج‌شنبه",
  "جمعه",
];
const WEEKDAY_SHORT = ["ش", "ی", "د", "س", "چ", "پ", "ج"];

function HushyarScanPanel({ onGenerated }) {
  const [mode, setMode] = useState("weekly"); // weekly | exam
  const [weeklyFile, setWeeklyFile] = useState(null);
  const [weeklyGroup, setWeeklyGroup] = useState("");
  const [weeklyLoading, setWeeklyLoading] = useState(false);
  const [weeklySlots, setWeeklySlots] = useState(null); // preview
  const [weeklyClear, setWeeklyClear] = useState(false);
  const [weeklyBusy, setWeeklyBusy] = useState(false);
  const [templates, setTemplates] = useState(null);
  const [tplGroup, setTplGroup] = useState("");
  const [genStart, setGenStart] = useState("");
  const [genEnd, setGenEnd] = useState("");
  const [genGroup, setGenGroup] = useState("");
  const [genDry, setGenDry] = useState(false);
  const [genBusy, setGenBusy] = useState(false);
  const [genRes, setGenRes] = useState(null);
  const [examFile, setExamFile] = useState(null);
  const [examLoading, setExamLoading] = useState(false);
  const [examPreview, setExamPreview] = useState(null);
  const [examBusy, setExamBusy] = useState(false);
  const [collapsed, setCollapsed] = useState(true);
  const [scanConfirm, setScanConfirm] = useState(null);

  const loadTpl = async (g) => {
    try {
      const r = await api.caScheduleTemplates(g || undefined);
      setTemplates(r.templates || []);
    } catch (e) {
      setTemplates([]);
    }
  };
  useEffect(() => {
    loadTpl(tplGroup);
  }, [tplGroup]);

  const doWeeklyScan = async () => {
    if (!weeklyFile)
      return toast("لطفاً عکس جدول برنامه را انتخاب کنید", "err");
    setWeeklyLoading(true);
    try {
      const r = await api.caScheduleTemplatesScan(
        weeklyFile,
        weeklyGroup || undefined,
      );
      const slots = (r.slots || []).map((s, i) => ({
        _k: i,
        weekday: Number(s.weekday ?? 0),
        time: String(s.time || "08:00"),
        end_time: String(s.end_time || s.time_end || ""),
        lesson: String(s.lesson || ""),
        teacher: String(s.teacher || ""),
        location: String(s.location || ""),
        group: s.group || weeklyGroup || "هر دو",
        flex_type: s.flex_type || "fixed",
        notes: String(s.notes || ""),
        type: s.type || "class",
      }));
      // synthesize missing end_time for preview (08->10 etc) if empty
      const synth = {
        "08:00": "10:00",
        "10:00": "12:00",
        "13:00": "15:00",
        "15:00": "17:00",
        "17:00": "19:00",
      };
      const fixed = slots.map((s) => ({
        ...s,
        end_time: s.end_time || synth[s.time] || "",
      }));
      setWeeklySlots(fixed);
      if (!fixed.length)
        toast("هوشیار چیزی استخراج نکرد — عکس واضح‌تری امتحان کنید", "err");
      else
        toast(
          `هوشیار ${fixed.length.toLocaleString("fa")} ردیف تشخیص داد — پیش‌نمایش را بررسی کنید ✅`,
        );
    } catch (e) {
      toast(errText(e), "err");
    }
    setWeeklyLoading(false);
  };
  const doWeeklyConfirm = async () => {
    if (!weeklySlots || !weeklySlots.length) return;
    const cleaned = weeklySlots.filter((s) => s.lesson.trim() && s.time.trim());
    if (!cleaned.length)
      return toast("حداقل یک ردیف با درس و ساعت لازم است", "err");
    // اعتبارسنجی محلی بازه
    for (const s of cleaned) {
      if (s.end_time && s.end_time.trim()) {
        const toMin = (v) => {
          const [h, m] = v.split(":").map(Number);
          return h * 60 + m;
        };
        try {
          if (toMin(s.end_time.trim()) <= toMin(s.time.trim()))
            return toast(
              `بازه‌ی «${s.lesson}» نامعتبر است — پایان باید بعد از شروع باشد (${formatFaTime(s.time)} تا ${formatFaTime(s.end_time)})`,
              "err",
            );
        } catch {}
      }
    }
    setWeeklyBusy(true);
    try {
      const body = {
        slots: cleaned.map((s) => ({
          weekday: Number(s.weekday),
          time: s.time.trim(),
          end_time: (s.end_time || "").trim(),
          lesson: s.lesson.trim(),
          teacher: (s.teacher || "").trim().slice(0, 80),
          location: (s.location || "").trim().slice(0, 80),
          group: s.group || "هر دو",
          flex_type: s.flex_type || "fixed",
          notes: (s.notes || "").trim().slice(0, 300),
          type: "class",
        })),
        clear_existing: !!weeklyClear,
        group: weeklyGroup || null,
      };
      const r = await api.caScheduleTemplatesScanConfirm(body);
      toast(
        `الگوی هفتگی ذخیره شد — ${Number(r.total || cleaned.length).toLocaleString("fa")} ردیف ✅`,
      );
      setWeeklySlots(null);
      setWeeklyFile(null);
      loadTpl(tplGroup);
      onGenerated && onGenerated();
    } catch (e) {
      toast(errText(e), "err");
    }
    setWeeklyBusy(false);
  };
  const doExamScan = async () => {
    if (!examFile) return toast("عکس برنامه امتحانات را انتخاب کنید", "err");
    setExamLoading(true);
    try {
      const r = await api.caScheduleExamsScan(examFile);
      const exs = (r.exams || []).map((e, i) => ({
        _k: i,
        lesson: String(e.lesson || ""),
        date: String(e.date || ""),
        time: String(e.time || "08:00"),
        location: String(e.location || ""),
        group: e.group || "هر دو",
      }));
      setExamPreview(exs);
      if (!exs.length) toast("هوشیار امتحانی تشخیص نداد", "err");
      else toast(`${exs.length.toLocaleString("fa")} امتحان تشخیص داده شد ✅`);
    } catch (e) {
      toast(errText(e), "err");
    }
    setExamLoading(false);
  };
  const doExamConfirm = async () => {
    if (!examPreview || !examPreview.length) return;
    const cleaned = examPreview.filter((e) => e.lesson.trim() && e.date.trim());
    if (!cleaned.length) return toast("درس و تاریخ الزامی است", "err");
    setExamBusy(true);
    try {
      const r = await api.caScheduleExamsScanConfirm({
        exams: cleaned.map((e) => ({
          lesson: e.lesson.trim(),
          date: e.date.trim(),
          time: e.time.trim() || "08:00",
          location: (e.location || "").trim(),
          group: e.group || "هر دو",
        })),
      });
      toast(
        `ثبت شد — ${Number(r.created || 0).toLocaleString("fa")} امتحان جدید، ${Number(r.skipped || 0).toLocaleString("fa")} تکراری نادیده گرفته شد ✅`,
      );
      setExamPreview(null);
      setExamFile(null);
      onGenerated && onGenerated();
    } catch (e) {
      toast(errText(e), "err");
    }
    setExamBusy(false);
  };
  const doGenerate = async () => {
    if (!genStart || !genEnd)
      return toast("بازه تاریخ شمسی را کامل کنید", "err");
    setGenBusy(true);
    setGenRes(null);
    try {
      const r = await api.caScheduleTemplatesGenerate({
        start_date: genStart,
        end_date: genEnd,
        group: genGroup || null,
        dry_run: !!genDry,
      });
      setGenRes(r);
      if (!genDry) {
        toast(
          `تولید شد — ${Number(r.created || 0).toLocaleString("fa")} برنامه جدید ✅`,
        );
        onGenerated && onGenerated();
        loadTpl(tplGroup);
      } else
        toast(
          `پیش‌نمایش: ${Number(r.created || 0).toLocaleString("fa")} مورد ایجاد می‌شود`,
        );
    } catch (e) {
      toast(errText(e), "err");
    }
    setGenBusy(false);
  };

  return (
    <div
      className="panel"
      style={{
        marginBottom: 12,
        border: collapsed ? undefined : "2px solid var(--c-accent)",
      }}
    >
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        className="row content-tab-toolbar"
        style={{
          width: "100%",
          cursor: "pointer",
          background: "transparent",
          border: 0,
          padding: "10px 12px",
          justifyContent: "space-between",
        }}
      >
        <span
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          <b>🧠 اسکن برنامه کلاسی با هوشیار</b>
          <B kind="acc">SAT-FRI هفتگی</B>
          <span className="muted small">
            عکس جدول → الگوی هفتگی → تولید خودکار برنامه
          </span>
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {templates && (
            <B>{Number(templates.length).toLocaleString("fa")} ردیف الگو</B>
          )}
          <span className="muted">{collapsed ? "▸ بازکردن" : "▾ بستن"}</span>
        </span>
      </button>
      {!collapsed && (
        <div style={{ padding: "0 12px 12px", display: "grid", gap: 12 }}>
          <div className="tabs content-inline-tabs" role="tablist">
            {[
              ["weekly", "🗓 الگوی هفتگی (شنبه-جمعه)"],
              ["exam", "📝 امتحانات"],
            ].map(([k, lbl]) => (
              <button
                key={k}
                type="button"
                role="tab"
                aria-selected={mode === k}
                className={`tab ${mode === k ? "on" : ""}`}
                onClick={() => setMode(k)}
              >
                {lbl}
              </button>
            ))}
          </div>

          {mode === "weekly" && (
            <div style={{ display: "grid", gap: 10 }}>
              <div
                className="panel panel-pad"
                style={{
                  background: "var(--bg)",
                  border: "1px dashed var(--border)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    gap: 8,
                    flexWrap: "wrap",
                    alignItems: "center",
                  }}
                >
                  <b>📸 اسکن جدول هفتگی</b>
                  <span className="muted small">
                    JPG/PNG/WEBP تا 12MB — هوشیار ردیف‌های جدول را می‌خواند و
                    پیش‌نمایش می‌دهد (بدون ذخیره خودکار)
                  </span>
                  <span className="spacer" />
                  <select
                    className="inp"
                    value={weeklyGroup}
                    onChange={(e) => setWeeklyGroup(e.target.value)}
                    title="گروه پیش‌فرض اگر در جدول مشخص نیست"
                  >
                    <option value="">گروه از جدول</option>
                    <option value="هر دو">👥 هر دو گروه</option>
                    <option value="1">1️⃣ گروه ۱</option>
                    <option value="2">2️⃣ گروه ۲</option>
                  </select>
                  <label className="btn sm" style={{ cursor: "pointer" }}>
                    <input
                      type="file"
                      accept="image/*"
                      style={{ display: "none" }}
                      onChange={(e) =>
                        setWeeklyFile(e.target.files?.[0] || null)
                      }
                    />
                    {weeklyFile ? "📎 " + weeklyFile.name : "انتخاب عکس"}
                  </label>
                  <button
                    className="btn primary"
                    disabled={weeklyLoading || !weeklyFile}
                    onClick={doWeeklyScan}
                  >
                    {weeklyLoading ? "⏳ اسکن…" : "🧠 اسکن با هوشیار"}
                  </button>
                </div>
                {weeklyFile && (
                  <div className="muted small" style={{ marginTop: 6 }}>
                    📎 {weeklyFile.name} · {(weeklyFile.size / 1024).toFixed(0)}{" "}
                    KB
                  </div>
                )}
              </div>

              {weeklySlots && (
                <div
                  className="panel panel-pad"
                  style={{ background: "var(--bg)" }}
                >
                  <div
                    className="row"
                    style={{ flexWrap: "wrap", gap: 8, marginBottom: 8 }}
                  >
                    <b>
                      🔍 پیش‌نمایش {weeklySlots.length.toLocaleString("fa")}{" "}
                      ردیف — ویرایش کنید سپس تأیید
                    </b>
                    <span className="spacer" />
                    <label
                      className="row"
                      style={{ gap: 6, cursor: "pointer" }}
                    >
                      <input
                        type="checkbox"
                        checked={weeklyClear}
                        onChange={(e) => setWeeklyClear(e.target.checked)}
                      />{" "}
                      پاک‌سازی الگوی قبلی این گروه قبل از ذخیره
                    </label>
                    <button
                      className="btn sm"
                      onClick={() => setWeeklySlots(null)}
                    >
                      انصراف
                    </button>
                    <button
                      className="btn primary"
                      disabled={weeklyBusy}
                      onClick={doWeeklyConfirm}
                    >
                      {weeklyBusy
                        ? "⏳…"
                        : `✅ تأیید و ذخیره الگو (${weeklySlots.length.toLocaleString("fa")})`}
                    </button>
                  </div>
                  <div style={{ overflowX: "auto" }}>
                    <table
                      className="tbl"
                      style={{ minWidth: 980, fontSize: 13 }}
                    >
                      <thead>
                        <tr>
                          <th>روز</th>
                          <th>از</th>
                          <th>تا</th>
                          <th>بازه</th>
                          <th>درس *</th>
                          <th>استاد</th>
                          <th>مکان</th>
                          <th>گروه</th>
                          <th>نوع</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {weeklySlots.map((s, idx) => (
                          <tr key={s._k}>
                            <td>
                              <select
                                className="inp sm"
                                value={s.weekday}
                                onChange={(e) =>
                                  setWeeklySlots((a) =>
                                    a.map((x, i) =>
                                      i === idx
                                        ? {
                                            ...x,
                                            weekday: Number(e.target.value),
                                          }
                                        : x,
                                    ),
                                  )
                                }
                              >
                                {WEEKDAY_FA.map((lbl, i) => (
                                  <option key={i} value={i}>
                                    {lbl}
                                  </option>
                                ))}
                              </select>
                            </td>
                            <td>
                              <input
                                className="inp sm"
                                type="time"
                                value={s.time}
                                onChange={(e) =>
                                  setWeeklySlots((a) =>
                                    a.map((x, i) =>
                                      i === idx
                                        ? { ...x, time: e.target.value }
                                        : x,
                                    ),
                                  )
                                }
                                style={{ width: 92 }}
                              />
                            </td>
                            <td>
                              <input
                                className="inp sm"
                                type="time"
                                value={s.end_time || ""}
                                onChange={(e) =>
                                  setWeeklySlots((a) =>
                                    a.map((x, i) =>
                                      i === idx
                                        ? { ...x, end_time: e.target.value }
                                        : x,
                                    ),
                                  )
                                }
                                style={{ width: 92 }}
                              />
                            </td>
                            <td
                              className="muted small"
                              style={{ whiteSpace: "nowrap" }}
                            >
                              {s.time && s.end_time
                                ? `${formatFaTime(s.time)} تا ${formatFaTime(s.end_time)}`
                                : "—"}
                            </td>
                            <td>
                              <input
                                className="inp sm"
                                value={s.lesson}
                                onChange={(e) =>
                                  setWeeklySlots((a) =>
                                    a.map((x, i) =>
                                      i === idx
                                        ? { ...x, lesson: e.target.value }
                                        : x,
                                    ),
                                  )
                                }
                                placeholder="درس"
                                style={{ minWidth: 130 }}
                              />
                            </td>
                            <td>
                              <input
                                className="inp sm"
                                value={s.teacher}
                                onChange={(e) =>
                                  setWeeklySlots((a) =>
                                    a.map((x, i) =>
                                      i === idx
                                        ? { ...x, teacher: e.target.value }
                                        : x,
                                    ),
                                  )
                                }
                                placeholder="استاد"
                                style={{ width: 100 }}
                              />
                            </td>
                            <td>
                              <input
                                className="inp sm"
                                value={s.location}
                                onChange={(e) =>
                                  setWeeklySlots((a) =>
                                    a.map((x, i) =>
                                      i === idx
                                        ? { ...x, location: e.target.value }
                                        : x,
                                    ),
                                  )
                                }
                                placeholder="مکان"
                                style={{ width: 100 }}
                              />
                            </td>
                            <td>
                              <select
                                className="inp sm"
                                value={s.group}
                                onChange={(e) =>
                                  setWeeklySlots((a) =>
                                    a.map((x, i) =>
                                      i === idx
                                        ? { ...x, group: e.target.value }
                                        : x,
                                    ),
                                  )
                                }
                              >
                                <option value="هر دو">هر دو</option>
                                <option value="1">۱</option>
                                <option value="2">۲</option>
                              </select>
                            </td>
                            <td>
                              <select
                                className="inp sm"
                                value={s.flex_type}
                                onChange={(e) =>
                                  setWeeklySlots((a) =>
                                    a.map((x, i) =>
                                      i === idx
                                        ? { ...x, flex_type: e.target.value }
                                        : x,
                                    ),
                                  )
                                }
                              >
                                <option value="fixed">ثابت</option>
                                <option value="flexible">منعطف</option>
                              </select>
                            </td>
                            <td>
                              <button
                                className="btn sm danger"
                                onClick={() =>
                                  setWeeklySlots((a) =>
                                    a.filter((_, i) => i !== idx),
                                  )
                                }
                              >
                                ✕
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <button
                    className="btn sm"
                    style={{ marginTop: 8 }}
                    onClick={() =>
                      setWeeklySlots((a) => [
                        ...a,
                        {
                          _k: Date.now() + Math.random(),
                          weekday: 0,
                          time: "08:00",
                          end_time: "10:00",
                          lesson: "",
                          teacher: "",
                          location: "",
                          group: weeklyGroup || "هر دو",
                          flex_type: "fixed",
                          notes: "",
                          type: "class",
                        },
                      ])
                    }
                  >
                    ➕ افزودن ردیف
                  </button>
                </div>
              )}

              <div
                className="panel panel-pad"
                style={{ background: "var(--bg)" }}
              >
                <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
                  <b>📋 الگوی فعلی</b>
                  <select
                    className="inp sm"
                    value={tplGroup}
                    onChange={(e) => setTplGroup(e.target.value)}
                  >
                    <option value="">همه گروه‌ها</option>
                    <option value="هر دو">👥 هر دو</option>
                    <option value="1">گروه ۱</option>
                    <option value="2">گروه ۲</option>
                  </select>
                  <span className="spacer" />
                  <button className="btn sm" onClick={() => loadTpl(tplGroup)}>
                    ↻ تازه‌سازی
                  </button>
                  <button
                    className="btn sm danger"
                    onClick={() =>
                      setScanConfirm({
                        text: "پاک‌سازی الگوی این گروه؟ الگوهای هفتگی این گروه حذف می‌شود. برای حذف برنامه‌های تولیدشده هم از فهرست زیر اقدام کنید.",
                        danger: true,
                        run: async () => {
                          try {
                            const r = await api.caScheduleTemplatesClear(
                              tplGroup || undefined,
                            );
                            toast(
                              `پاک شد — ${Number(r.deleted ?? 0).toLocaleString("fa-IR")} ردیف الگو حذف شد ✅`,
                            );
                            loadTpl(tplGroup);
                          } catch (e) {
                            if (e.status === 404) {
                              toast(
                                "الگویی برای این گروه وجود نداشت — چیزی برای پاک‌سازی نیست",
                                "info",
                              );
                              loadTpl(tplGroup);
                            } else toast(errText(e), "err");
                          }
                        },
                      })
                    }
                  >
                    🗑 پاک‌سازی این گروه
                  </button>
                </div>
                {!templates ? (
                  <Loading rows={2} />
                ) : templates.length === 0 ? (
                  <div className="muted" style={{ padding: 8 }}>
                    الگویی وجود ندارد
                  </div>
                ) : (
                  <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
                    {WEEKDAY_FA.map((lbl, wd) => {
                      const rows = templates.filter(
                        (t) => Number(t.weekday) === wd,
                      );
                      if (!rows.length) return null;
                      return (
                        <div
                          key={wd}
                          className="row"
                          style={{
                            gap: 6,
                            flexWrap: "wrap",
                            alignItems: "flex-start",
                            borderBottom: "1px solid var(--border)",
                            paddingBottom: 6,
                          }}
                        >
                          <B>{lbl}</B>
                          {rows
                            .sort(
                              (a, b) =>
                                String(a.time).localeCompare(String(b.time)) ||
                                String(a.end_time || "").localeCompare(
                                  String(b.end_time || ""),
                                ),
                            )
                            .map((r, i) => (
                              <span
                                key={i}
                                style={{
                                  padding: "5px 8px",
                                  fontSize: 12,
                                  borderRadius: "var(--r-sm)",
                                  background: "rgba(77,184,255,0.08)",
                                  border: "1px solid rgba(77,184,255,0.18)",
                                  color: "var(--c-txt2)",
                                }}
                              >
                                {formatFaTime(r.time)}
                                {r.end_time ? ` تا ${formatFaTime(r.end_time)}` : ""}{" "}
                                {r.lesson}{" "}
                                <span style={{ color: "var(--c-txt3)" }}>
                                  ({r.group})
                                </span>
                              </span>
                            ))}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <div
                className="panel panel-pad"
                style={{
                  background: "var(--bg)",
                  border: "1px solid var(--border)",
                }}
              >
                <b>⚙️ تولید برنامه از روی الگو</b>
                <div className="muted small">
                  بازه شمسی را انتخاب کنید؛ برنامه برای هر روز مطابق الگو ساخته
                  می‌شود (تکراری‌ها نادیده)
                </div>
                <div
                  className="grid"
                  style={{
                    gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))",
                    gap: 8,
                    marginTop: 8,
                  }}
                >
                  <PersianDatePicker
                    value={genStart}
                    onChange={setGenStart}
                    placeholder="شروع (شمسی)"
                  />
                  <PersianDatePicker
                    value={genEnd}
                    onChange={setGenEnd}
                    placeholder="پایان (شمسی)"
                  />
                  <select
                    className="inp"
                    value={genGroup}
                    onChange={(e) => setGenGroup(e.target.value)}
                  >
                    <option value="">همه گروه‌های الگو</option>
                    <option value="هر دو">👥 هر دو</option>
                    <option value="1">گروه ۱</option>
                    <option value="2">گروه ۲</option>
                  </select>
                  <label
                    className="row"
                    style={{ gap: 6, alignItems: "center" }}
                  >
                    <input
                      type="checkbox"
                      checked={genDry}
                      onChange={(e) => setGenDry(e.target.checked)}
                    />{" "}
                    پیش‌نمایش (dry-run)
                  </label>
                </div>
                <div className="row" style={{ gap: 8, marginTop: 8 }}>
                  <button
                    className="btn primary"
                    disabled={genBusy || !genStart || !genEnd}
                    onClick={doGenerate}
                  >
                    {genBusy
                      ? "⏳…"
                      : genDry
                        ? "👁 پیش‌نمایش تولید"
                        : "🚀 تولید برنامه + اطلاع‌رسانی"}
                  </button>
                  {genRes && (
                    <span className="muted small">
                      نتیجه: {Number(genRes.created || 0).toLocaleString("fa")}{" "}
                      ایجاد · {Number(genRes.skipped || 0).toLocaleString("fa")}{" "}
                      تکراری
                    </span>
                  )}
                </div>
              </div>
            </div>
          )}

          {mode === "exam" && (
            <div style={{ display: "grid", gap: 10 }}>
              <div
                className="panel panel-pad"
                style={{
                  background: "var(--bg)",
                  border: "1px dashed var(--border)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    gap: 8,
                    flexWrap: "wrap",
                    alignItems: "center",
                  }}
                >
                  <b>📸 اسکن برنامه امتحانات</b>
                  <span className="muted small">
                    JPG/PNG/WEBP تا 12MB — تاریخ‌ها به‌صورت شمسی خوانده و به
                    میلادی تبدیل می‌شوند
                  </span>
                  <span className="spacer" />
                  <label className="btn sm" style={{ cursor: "pointer" }}>
                    <input
                      type="file"
                      accept="image/*"
                      style={{ display: "none" }}
                      onChange={(e) => setExamFile(e.target.files?.[0] || null)}
                    />
                    {examFile ? "📎 " + examFile.name : "انتخاب عکس"}
                  </label>
                  <button
                    className="btn primary"
                    disabled={examLoading || !examFile}
                    onClick={doExamScan}
                  >
                    {examLoading ? "⏳ اسکن…" : "🧠 اسکن امتحانات"}
                  </button>
                </div>
              </div>
              {examPreview && (
                <div
                  className="panel panel-pad"
                  style={{ background: "var(--bg)" }}
                >
                  <div
                    className="row"
                    style={{ flexWrap: "wrap", gap: 8, marginBottom: 8 }}
                  >
                    <b>
                      🔍 پیش‌نمایش {examPreview.length.toLocaleString("fa")}{" "}
                      امتحان
                    </b>
                    <span className="spacer" />
                    <button
                      className="btn sm"
                      onClick={() => setExamPreview(null)}
                    >
                      انصراف
                    </button>
                    <button
                      className="btn primary"
                      disabled={examBusy}
                      onClick={doExamConfirm}
                    >
                      {examBusy
                        ? "⏳…"
                        : `✅ تأیید و ثبت (${examPreview.length.toLocaleString("fa")})`}
                    </button>
                  </div>
                  <div style={{ overflowX: "auto" }}>
                    <table
                      className="tbl"
                      style={{ minWidth: 720, fontSize: 13 }}
                    >
                      <thead>
                        <tr>
                          <th>درس *</th>
                          <th>تاریخ *</th>
                          <th>ساعت</th>
                          <th>مکان</th>
                          <th>گروه</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {examPreview.map((e, idx) => (
                          <tr key={e._k}>
                            <td>
                              <input
                                className="inp sm"
                                value={e.lesson}
                                onChange={(ev) =>
                                  setExamPreview((a) =>
                                    a.map((x, i) =>
                                      i === idx
                                        ? { ...x, lesson: ev.target.value }
                                        : x,
                                    ),
                                  )
                                }
                                placeholder="درس"
                                style={{ minWidth: 140 }}
                              />
                            </td>
                            <td>
                              <input
                                className="inp sm"
                                dir="ltr"
                                value={e.date}
                                onChange={(ev) =>
                                  setExamPreview((a) =>
                                    a.map((x, i) =>
                                      i === idx
                                        ? { ...x, date: ev.target.value }
                                        : x,
                                    ),
                                  )
                                }
                                placeholder="YYYY/MM/DD یا 1405/01/20"
                                style={{ width: 150 }}
                              />
                            </td>
                            <td>
                              <input
                                className="inp sm"
                                type="time"
                                value={e.time}
                                onChange={(ev) =>
                                  setExamPreview((a) =>
                                    a.map((x, i) =>
                                      i === idx
                                        ? { ...x, time: ev.target.value }
                                        : x,
                                    ),
                                  )
                                }
                                style={{ width: 90 }}
                              />
                            </td>
                            <td>
                              <input
                                className="inp sm"
                                value={e.location}
                                onChange={(ev) =>
                                  setExamPreview((a) =>
                                    a.map((x, i) =>
                                      i === idx
                                        ? { ...x, location: ev.target.value }
                                        : x,
                                    ),
                                  )
                                }
                                style={{ width: 110 }}
                              />
                            </td>
                            <td>
                              <select
                                className="inp sm"
                                value={e.group}
                                onChange={(ev) =>
                                  setExamPreview((a) =>
                                    a.map((x, i) =>
                                      i === idx
                                        ? { ...x, group: ev.target.value }
                                        : x,
                                    ),
                                  )
                                }
                              >
                                <option value="هر دو">هر دو</option>
                                <option value="1">۱</option>
                                <option value="2">۲</option>
                              </select>
                            </td>
                            <td>
                              <button
                                className="btn sm danger"
                                onClick={() =>
                                  setExamPreview((a) =>
                                    a.filter((_, i) => i !== idx),
                                  )
                                }
                              >
                                ✕
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <button
                    className="btn sm"
                    style={{ marginTop: 8 }}
                    onClick={() =>
                      setExamPreview((a) => [
                        ...a,
                        {
                          _k: Date.now() + Math.random(),
                          lesson: "",
                          date: "",
                          time: "08:00",
                          location: "",
                          group: "هر دو",
                        },
                      ])
                    }
                  >
                    ➕ افزودن امتحان
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {scanConfirm && (
        <Confirm
          text={scanConfirm.text}
          danger={scanConfirm.danger}
          onYes={async () => {
            await scanConfirm.run();
            setScanConfirm(null);
          }}
          onNo={() => setScanConfirm(null)}
        />
      )}
    </div>
  );
}

export function ScheduleTab() {
  const [stype, setStype] = useState("");
  const [view, setView] = useState("list");
  const [items, setItems] = useState(null);
  const [err, setErr] = useState("");
  const [permErr, setPermErr] = useState(false);
  const [edit, setEdit] = useState(null);
  const [flex, setFlex] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [bulkMode, setBulkMode] = useState(false);
  const [selected, setSelected] = useState(() => new Set());
  const [showRangeModal, setShowRangeModal] = useState(false);
  const [rangeFrom, setRangeFrom] = useState("");
  const [rangeTo, setRangeTo] = useState("");

  const load = async () => {
    setErr("");
    try {
      setItems((await api.caSchedule(stype || undefined)).schedule || []);
    } catch (e) {
      if (e.status === 403) setPermErr(true);
      else setErr(errText(e));
    }
  };
  useEffect(() => {
    setItems(null);
    load();
  }, [stype]);

  if (permErr)
    return <NoPerm text="مدیریت برنامه فقط برای ادمین ارشد محتواست" />;
  if (err) return <ErrorState error={err} onRetry={load} />;

  const TYPE_FA = { class: "کلاس", exam: "امتحان", makeup: "جبرانی" };
  const byDate = (items || []).reduce((acc, item) => {
    (acc[item.date || "بدون تاریخ"] ||= []).push(item);
    return acc;
  }, {});
  const datedItems = (items || [])
    .map((item) => ({ item, parts: jalaliDateParts(item.date) }))
    .filter((x) => x.parts);
  const monthKey = datedItems[0]?.parts.monthKey || "";
  const monthItems = monthKey
    ? datedItems.filter((x) => x.parts.monthKey === monthKey)
    : [];
  const monthLength = monthItems.length
    ? jalaliMonthLengthFor(monthItems[0].item.date)
    : 0;

  // ── Bulk helpers ──
  const _allListIds = (() => {
    if (!items) return [];
    // flattened ids for current filter (stype)
    const ids = [];
    for (const it of items) {
      if (it?.id) ids.push(String(it.id));
      if (Array.isArray(it?._mergedIds)) {
        for (const mid of it._mergedIds)
          if (!ids.includes(String(mid))) ids.push(String(mid));
      }
    }
    // dedup
    return [...new Set(ids)];
  })();
  const _mergedForBulk = (() => {
    try {
      return mergeScheduleBlocks(items || []);
    } catch {
      return (items || []).map((c) => ({ ...c, _mergedIds: [c.id] }));
    }
  })();
  const _bulkAllIds = (() => {
    const ids = [];
    for (const it of _mergedForBulk)
      for (const mid of it._mergedIds || [it.id]) ids.push(String(mid));
    return [...new Set(ids)];
  })();
  const isSelected = (id) => selected.has(String(id));
  const toggleOne = (idOrIds) => {
    const ids = Array.isArray(idOrIds)
      ? idOrIds.map(String)
      : [String(idOrIds)];
    setSelected((prev) => {
      const nxt = new Set(prev);
      const allSel = ids.every((x) => nxt.has(x));
      if (allSel) ids.forEach((x) => nxt.delete(x));
      else ids.forEach((x) => nxt.add(x));
      return nxt;
    });
  };
  const selectAllVisible = () => setSelected(new Set(_bulkAllIds.map(String)));
  const clearSelection = () => setSelected(new Set());
  const selectedCount = selected.size;
  const _faInterval = (s) => {
    const _ie = (st) => {
      const m = String(st || "").match(/(\d{1,2}):(\d{2})/);
      if (!m) return "";
      return `${String(Number(m[1]) + 2).padStart(2, "0")}:${String(Number(m[2])).padStart(2, "0")}`;
    };
    const _er = s.end_time || s.time_end || _ie(s.time);
    return s.time ? `${formatFaTime(s.time)} تا ${formatFaTime(_er)}` : "—";
  };
  const _faIntervalShort = (s) => {
    const _ie = (st) => {
      const m = String(st || "").match(/(\d{1,2}):(\d{2})/);
      if (!m) return "";
      return `${String(Number(m[1]) + 2).padStart(2, "0")}:${String(Number(m[2])).padStart(2, "0")}`;
    };
    const _er = s.end_time || s.time_end || _ie(s.time);
    return s.time ? `${formatFaTime(s.time)}–${formatFaTime(_er)}` : "•";
  };
  const doBulkDeleteSelected = async () => {
    if (selectedCount === 0) return toast("چیزی انتخاب نشده", "err");
    setConfirm({
      text: `حذف ${selectedCount.toLocaleString("fa")} مورد انتخاب‌شده؟ این عمل برگشت‌ناپذیر است.`,
      danger: true,
      run: async () => {
        const r = await api.caScheduleBulkDelete({ ids: [...selected] });
        toast(
          `حذف شد — ${Number(r.deleted || 0).toLocaleString("fa")} مورد ✅`,
        );
        clearSelection();
        setBulkMode(false);
        load();
      },
    });
  };
  const doBulkDeleteAllFiltered = async () => {
    const n = _bulkAllIds.length;
    if (n === 0) return toast("موردی برای حذف وجود ندارد", "err");
    const label = stype
      ? stype === "class"
        ? "کلاس"
        : stype === "exam"
          ? "امتحان"
          : "جبرانی"
      : "همه در این تب";
    setConfirm({
      text: `حذف همه‌ی ${n.toLocaleString("fa")} مورد «${label}» در فیلتر فعلی؟ از ۲۸ شهریور تا ۲۵ دی و هر تاریخ دیگری که در این فیلتر است، همه پاک می‌شود.`,
      danger: true,
      run: async () => {
        const r = await api.caScheduleBulkDelete({
          stype: stype || undefined,
          group: undefined,
          delete_all: !stype ? true : false,
          ...(stype ? { stype } : {}),
        });
        let deleted = r.deleted;
        if (n > 0 && deleted === 0) {
          const r2 = await api.caScheduleBulkClear(
            undefined,
            stype || undefined,
          );
          deleted = r2.deleted;
        }
        toast(`حذف شد — ${Number(deleted || 0).toLocaleString("fa")} مورد ✅`);
        clearSelection();
        setBulkMode(false);
        load();
      },
    });
  };
  const doBulkDeleteRange = async () => {
    if (!rangeFrom || !rangeTo)
      return toast("بازه‌ی تاریخ را کامل انتخاب کنید", "err");
    if (rangeFrom > rangeTo)
      return toast("بازه‌ی تاریخ نامعتبر است: تاریخ شروع باید قبل از پایان باشد", "err");
    setConfirm({
      text: `حذف بازه‌ای از ${rangeFrom} تا ${rangeTo} ؟`,
      danger: true,
      run: async () => {
        const r = await api.caScheduleBulkDelete({
          date_from: rangeFrom,
          date_to: rangeTo,
          stype: stype || undefined,
        });
        toast(
          `حذف شد — ${Number(r.deleted || 0).toLocaleString("fa")} مورد در بازه ✅`,
        );
        setShowRangeModal(false);
        clearSelection();
        setBulkMode(false);
        load();
      },
    });
  };

  return (
    <>
      <HushyarScanPanel onGenerated={load} />
      <div className="row content-tab-toolbar">
        <div
          className="tabs content-inline-tabs"
          role="tablist"
          aria-label="نوع برنامه"
        >
          {SCHED_TYPES.map(([k, v]) => (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={stype === k}
              className={`tab ${stype === k ? "on" : ""}`}
              onClick={() => setStype(k)}
            >
              {v}
            </button>
          ))}
        </div>
        <div className="segmented" role="group" aria-label="نمای برنامه">
          {[
            ["list", "فهرست"],
            ["week", "هفته/Agenda"],
            ["month", "ماه"],
          ].map(([k, label]) => (
            <button
              key={k}
              className={view === k ? "on" : ""}
              aria-pressed={view === k}
              onClick={() => setView(k)}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          className={`btn ${bulkMode ? "primary" : ""}`}
          onClick={() => {
            setBulkMode((v) => {
              const nxt = !v;
              if (v) setSelected(new Set());
              return nxt;
            });
          }}
          title="انتخاب چندتایی برای حذف گروهی"
        >
          ☑️ انتخاب گروهی
        </button>
        <button
          className="btn primary"
          onClick={() =>
            setEdit({ type: "class", group: "هر دو", flex_type: "fixed" })
          }
        >
          ➕ مورد جدید
        </button>
      </div>
      {bulkMode && (
        <div
          className="panel"
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 8,
            padding: "10px 12px",
            marginBottom: 10,
            background: "var(--c-surface2)",
            border: "1px solid var(--c-line)",
            borderRadius: "var(--r-lg)",
            position: "sticky",
            top: 8,
            zIndex: 2,
          }}
        >
          <span className="badge acc" style={{ fontSize: 12 }}>
            {selectedCount.toLocaleString("fa")} انتخاب‌شده
          </span>
          <span className="muted" style={{ fontSize: 11 }}>
            از {_bulkAllIds.length.toLocaleString("fa")} مورد در این تب
          </span>
          <span style={{ flex: 1 }} />
          <button
            className="btn sm"
            onClick={selectAllVisible}
            disabled={_bulkAllIds.length === 0}
          >
            ✅ انتخاب همه
          </button>
          <button
            className="btn sm"
            onClick={clearSelection}
            disabled={selectedCount === 0}
          >
            ↩️ لغو انتخاب
          </button>
          <button
            className="btn sm danger"
            onClick={doBulkDeleteSelected}
            disabled={selectedCount === 0}
          >
            🗑 حذف انتخاب‌شده
          </button>
          <button
            className="btn sm danger"
            onClick={doBulkDeleteAllFiltered}
            disabled={_bulkAllIds.length === 0}
            title="حذف همه‌ی موارد فیلترشده (مثلا از ۲۸ شهریور تا ۲۵ دی)"
          >
            🧹 حذف همه در این تب
          </button>
          <button
            className="btn sm warn"
            onClick={() => setShowRangeModal(true)}
          >
            📅 حذف بازه‌ای
          </button>
        </div>
      )}
      {showRangeModal && (
        <div
          className="modal-backdrop"
          onClick={() => setShowRangeModal(false)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(8,15,31,0.55)",
            display: "grid",
            placeItems: "center",
            zIndex: 60,
          }}
        >
          <div
            className="panel panel-pad"
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "min(420px,92vw)",
              background: "var(--c-bg2)",
              border: "1px solid var(--c-line2)",
              borderRadius: "var(--r-xl)",
            }}
          >
            <b>📅 حذف بازه‌ای — انتخاب بازه‌ی شمسی</b>
            <div className="muted small" style={{ marginTop: 6 }}>
              مثلا ۱۴۰۴/۰۶/۲۸ تا ۱۴۰۴/۱۰/۲۵ — همه‌ی برنامه‌ها در این بازه پاک
              می‌شوند (فیلتر نوع هم اعمال می‌شود اگر تب کلاس/امتحان انتخاب
              باشد).
            </div>
            <div className="grid" style={{ gap: 8, marginTop: 12 }}>
              <div className="row" style={{ gap: 8 }}>
                <div style={{ flex: 1 }}>
                  <div
                    className="muted"
                    style={{ fontSize: 11, marginBottom: 4 }}
                  >
                    از تاریخ
                  </div>
                  <PersianDatePicker
                    value={rangeFrom}
                    onChange={setRangeFrom}
                    placeholder="۱۴۰۴/۰۶/۲۸"
                  />
                </div>
                <div style={{ flex: 1 }}>
                  <div
                    className="muted"
                    style={{ fontSize: 11, marginBottom: 4 }}
                  >
                    تا تاریخ
                  </div>
                  <PersianDatePicker
                    value={rangeTo}
                    onChange={setRangeTo}
                    placeholder="۱۴۰۴/۱۰/۲۵"
                  />
                </div>
              </div>
              <div
                className="row"
                style={{ gap: 8, justifyContent: "flex-end" }}
              >
                <button
                  className="btn sm"
                  onClick={() => setShowRangeModal(false)}
                >
                  انصراف
                </button>
                <button
                  className="btn sm danger"
                  onClick={doBulkDeleteRange}
                  disabled={!rangeFrom || !rangeTo}
                >
                  🗑 حذف بازه
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      {!items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty icon="📅" text="موردی نیست" />
      ) : (
        <>
          {(() => {
            // —— consolidated view: shared merged data for all three views (theme-integrated)
            // NOTE: merged/grouped are also recomputed below for week/month scope — kept inside for isolation;
            // second computation is cheap (O(n log n)) for <200 items.
            const merged = mergeScheduleBlocks(items);
            const grouped = merged.reduce((acc, it) => {
              const k = it.date || "بدون تاریخ";
              (acc[k] ||= []).push(it);
              return acc;
            }, {});
            const sortedDates = Object.keys(grouped).sort((a, b) =>
              a.localeCompare(b),
            );
            const TYPE_STYLE = {
              class: {
                col: "var(--c-acc)",
                bg: "rgba(77,184,255,0.09)",
                bd: "rgba(77,184,255,0.22)",
              },
              exam: {
                col: "var(--c-bad)",
                bg: "rgba(248,113,113,0.09)",
                bd: "rgba(248,113,113,0.22)",
              },
              makeup: {
                col: "var(--c-ok)",
                bg: "rgba(58,210,155,0.09)",
                bd: "rgba(58,210,155,0.22)",
              },
            };
            if (view !== "list") return null;
            return (
              <div style={{ display: "grid", gap: 14 }}>
                {sortedDates.map((day) => {
                  const rows = grouped[day].sort((a, b) =>
                    String(a.time || "").localeCompare(String(b.time || "")),
                  );
                  return (
                    <section
                      key={day}
                      className="panel"
                      style={{
                        padding: 0,
                        overflow: "hidden",
                        borderRadius: "var(--r-lg)",
                        border: "1px solid var(--c-line)",
                        background: "var(--c-surface)",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 10,
                          padding: "11px 14px",
                          background: "var(--c-surface2)",
                          borderBottom: "1px solid var(--c-line)",
                        }}
                      >
                        {bulkMode && (
                          <input
                            type="checkbox"
                            checked={
                              rows.length > 0 &&
                              rows.every((r) =>
                                (r._mergedIds || [r.id]).every((id) =>
                                  selected.has(String(id)),
                                ),
                              )
                            }
                            onChange={() => {
                              const ids = rows
                                .flatMap((r) => r._mergedIds || [r.id])
                                .map(String);
                              const all = ids.every((id) => selected.has(id));
                              setSelected((prev) => {
                                const nxt = new Set(prev);
                                if (all) ids.forEach((id) => nxt.delete(id));
                                else ids.forEach((id) => nxt.add(id));
                                return nxt;
                              });
                            }}
                            style={{
                              width: 18,
                              height: 18,
                              accentColor: "var(--c-acc)",
                            }}
                          />
                        )}
                        <span
                          style={{
                            display: "grid",
                            width: 38,
                            height: 38,
                            placeItems: "center",
                            borderRadius: 10,
                            background: "var(--c-acc-soft)",
                            fontSize: 18,
                          }}
                        >
                          📅
                        </span>
                        <div style={{ flex: 1 }}>
                          <b style={{ fontSize: "var(--fs-md)" }}>
                            {formatFaDate(day, { long: true })}
                          </b>
                          <div
                            className="muted"
                            style={{ fontSize: "var(--fs-cap)", marginTop: 2 }}
                          >
                            {faDigits(rows.length)} جلسه · {formatFaDate(day)}
                          </div>
                        </div>
                        <button
                          className="btn sm"
                          onClick={() =>
                            setEdit({
                              type: stype || "class",
                              date: day,
                              group: "هر دو",
                              flex_type: "fixed",
                              time: "08:00",
                              end_time: "10:00",
                            })
                          }
                          title="افزودن برنامه برای این روز (کلاس/امتحان/جبرانی)"
                          style={{ padding: "4px 8px", fontSize: 11 }}
                        >
                          ＋ افزودن
                        </button>
                        <B kind="acc">{faDigits(rows.length)}</B>
                      </div>
                      <div style={{ display: "grid", gap: 8, padding: 10 }}>
                        {rows.map((s) => {
                          const sty = TYPE_STYLE[s.type] || TYPE_STYLE.class;
                          const interval = _faInterval(s);
                          return (
                            <div
                              key={s.id}
                              className="card"
                              style={{
                                display: "flex",
                                alignItems: "stretch",
                                gap: 0,
                                padding: 0,
                                overflow: "hidden",
                                borderRadius: 12,
                                border:
                                  bulkMode &&
                                  (s._mergedIds || [s.id]).every((id) =>
                                    selected.has(String(id)),
                                  )
                                    ? "1px solid var(--c-acc)"
                                    : "1px solid var(--c-line)",
                                background:
                                  bulkMode &&
                                  (s._mergedIds || [s.id]).every((id) =>
                                    selected.has(String(id)),
                                  )
                                    ? "color-mix(in srgb, var(--c-acc) 9%, var(--c-bg2))"
                                    : "var(--c-bg2)",
                                borderInlineStart: `3px solid ${sty.col}`,
                                boxShadow: "var(--sh-1)",
                              }}
                            >
                              <div
                                style={{
                                  flex: 1,
                                  display: "flex",
                                  alignItems: "center",
                                  gap: 12,
                                  padding: "10px 12px",
                                }}
                              >
                                {bulkMode && (
                                  <input
                                    type="checkbox"
                                    checked={(s._mergedIds || [s.id]).every(
                                      (id) => selected.has(String(id)),
                                    )}
                                    onChange={() =>
                                      toggleOne(s._mergedIds || [s.id])
                                    }
                                    style={{
                                      width: 16,
                                      height: 16,
                                      accentColor: "var(--c-acc)",
                                      flexShrink: 0,
                                    }}
                                  />
                                )}
                                <div
                                  style={{
                                    display: "grid",
                                    placeItems: "center",
                                    minWidth: 86,
                                    padding: "7px 8px",
                                    borderRadius: 10,
                                    background: sty.bg,
                                    border: `1px solid ${sty.bd}`,
                                    textAlign: "center",
                                  }}
                                >
                                  <span
                                    style={{
                                      fontSize: 11,
                                      fontWeight: 800,
                                      color: sty.col,
                                      lineHeight: 1.2,
                                    }}
                                  >
                                    {interval}
                                  </span>
                                  {s._merged && s._merged > 1 && (
                                    <span
                                      style={{
                                        fontSize: 10,
                                        color: sty.col,
                                        opacity: 0.85,
                                        marginTop: 3,
                                      }}
                                    >
                                      🔗 {faDigits(s._merged)} بازه ادغام
                                    </span>
                                  )}
                                </div>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                  <div
                                    style={{
                                      display: "flex",
                                      alignItems: "center",
                                      gap: 6,
                                      flexWrap: "wrap",
                                    }}
                                  >
                                    <b
                                      style={{
                                        fontSize: "var(--fs-sm)",
                                        whiteSpace: "nowrap",
                                        overflow: "hidden",
                                        textOverflow: "ellipsis",
                                      }}
                                    >
                                      {s.lesson}
                                    </b>
                                    <span
                                      className="badge"
                                      style={{
                                        background: sty.bg,
                                        color: sty.col,
                                        border: `1px solid ${sty.bd}`,
                                        fontSize: 11,
                                      }}
                                    >
                                      {TYPE_FA[s.type] || s.type}
                                    </span>
                                    {s.flex_type === "flexible" && (
                                      <span
                                        className="badge b-yel"
                                        style={{ fontSize: 11 }}
                                      >
                                        منعطف
                                      </span>
                                    )}
                                    <span
                                      className="badge b-gray"
                                      style={{ fontSize: 11 }}
                                    >
                                      {s.group === "هر دو"
                                        ? "👥 هر دو"
                                        : `گروه ${faDigits(s.group)}`}
                                    </span>
                                  </div>
                                  <div
                                    className="muted"
                                    style={{
                                      fontSize: "var(--fs-cap)",
                                      marginTop: 4,
                                      display: "flex",
                                      gap: 8,
                                      flexWrap: "wrap",
                                      alignItems: "center",
                                    }}
                                  >
                                    {s.teacher && <span>👨‍🏫 {s.teacher}</span>}
                                    {s.location && <span>📍 {s.location}</span>}
                                    {s.flex_note && (
                                      <span style={{ color: "var(--warn)" }}>
                                        🔄 {s.flex_note}
                                      </span>
                                    )}
                                  </div>
                                </div>
                              </div>
                              <div
                                style={{
                                  display: "flex",
                                  alignItems: "center",
                                  gap: 4,
                                  padding: "8px 8px",
                                  borderInlineStart: "1px solid var(--c-line)",
                                  background: "var(--c-surface2)",
                                  flexWrap: "wrap",
                                }}
                              >
                                {s.flex_type === "flexible" && (
                                  <button
                                    className="btn sm"
                                    title="اعلام زمان جدید کلاس منعطف"
                                    onClick={() => setFlex(s)}
                                    style={{ fontSize: 11 }}
                                  >
                                    🔄 زمان
                                  </button>
                                )}
                                <button
                                  className="btn sm"
                                  onClick={() =>
                                    setEdit({ ...s, note: s.note || "" })
                                  }
                                  aria-label={`ویرایش ${s.lesson}`}
                                  style={{ padding: "6px 8px" }}
                                >
                                  ✏️
                                </button>
                                <button
                                  className="btn sm"
                                  onClick={() =>
                                    setEdit({
                                      ...s,
                                      id: null,
                                      lesson: `${s.lesson} — کپی`,
                                      note: s.note || "",
                                    })
                                  }
                                  aria-label={`کپی ${s.lesson}`}
                                  style={{ padding: "6px 8px" }}
                                >
                                  📄
                                </button>
                                <button
                                  className="btn sm danger"
                                  aria-label={`حذف ${s.lesson}`}
                                  onClick={() =>
                                    setConfirm({
                                      text:
                                        s._merged > 1
                                          ? `حذف «${s.lesson}» (${formatFaDate(s.date)}) — ${faDigits(s._merged)} جلسه ادغام‌شده با هم حذف می‌شود؟`
                                          : `حذف «${s.lesson}» (${formatFaDate(s.date)})؟`,
                                      run: async () => {
                                        if (
                                          s._mergedIds &&
                                          s._mergedIds.length > 1
                                        ) {
                                          for (const mid of s._mergedIds) {
                                            try {
                                              await api.caScheduleDel(mid);
                                            } catch {}
                                          }
                                          toast(
                                            `${faDigits(s._mergedIds.length)} جلسه حذف شد`,
                                          );
                                        } else {
                                          const r = await api.caScheduleDel(
                                            s.id,
                                          );
                                          toast(
                                            `برنامه لغو و به ${Number(r.notified || 0).toLocaleString("fa")} نفر اطلاع داده شد`,
                                          );
                                        }
                                        load();
                                      },
                                    })
                                  }
                                  style={{ padding: "6px 8px" }}
                                >
                                  🗑
                                </button>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </section>
                  );
                })}
              </div>
            );
          })()}

          {view === "week" &&
            (() => {
              // هفته: همان داده‌ی ادغام‌شده‌ی فهرست اما به‌صورت Agenda فشرده — recompute for isolation
              const _wMerged = mergeScheduleBlocks(items);
              const _wGrouped = _wMerged.reduce((acc, it) => {
                (acc[it.date || "بدون تاریخ"] ||= []).push(it);
                return acc;
              }, {});
              const weekEntries = Object.entries(_wGrouped)
                .sort(([a], [b]) => a.localeCompare(b))
                .slice(0, 7);
              return (
                <div className="schedule-agenda">
                  {weekEntries.map(([day, rows]) => (
                    <section key={day} className="panel panel-pad">
                      <div className="section-title">
                        <span>{formatFaDate(day)}</span>
                        <B>{rows.length.toLocaleString("fa")} مورد</B>
                      </div>
                      <div className="grid content-grid-tight">
                        {rows.map((s) => (
                          <button
                            key={s.id}
                            className="schedule-agenda-item"
                            onClick={() =>
                              setEdit({ ...s, note: s.note || "" })
                            }
                          >
                            <span>{_faInterval(s)}</span>
                            <b>{s.lesson}</b>
                            <span className="muted">
                              {TYPE_FA[s.type] || s.type} · {s.group}
                            </span>
                          </button>
                        ))}
                      </div>
                    </section>
                  ))}
                </div>
              );
            })()}
          {view === "month" &&
            (() => {
              const _mMerged = mergeScheduleBlocks(items);
              const _mDated = _mMerged
                .map((item) => ({ item, parts: jalaliDateParts(item.date) }))
                .filter((x) => x.parts);
              const _mMonthKey = _mDated[0]?.parts.monthKey || monthKey;
              const _mMonthItems = _mMonthKey
                ? _mDated.filter((x) => x.parts.monthKey === _mMonthKey)
                : [];
              const _mMonthLength = _mMonthItems.length
                ? jalaliMonthLengthFor(_mMonthItems[0].item.date)
                : monthLength;
              const _mMonthItemsFlat = _mMonthItems;
              return (
                <div className="schedule-month">
                  <div className="schedule-month-head">
                    <b>
                      {_mMonthKey ? faDigits(_mMonthKey) : "ماه داده‌های موجود"}
                    </b>
                    <span className="muted">
                      نمای ماه شمسی بر اساس تاریخ‌های واقعی ثبت‌شده
                    </span>
                  </div>
                  <div className="schedule-month-grid">
                    {Array.from({ length: _mMonthLength }, (_, i) => i + 1).map(
                      (day) => {
                        const rows = _mMonthItemsFlat
                          .filter((x) => x.parts.day === day)
                          .map((x) => x.item);
                        return (
                          <div
                            key={day}
                            className={`schedule-day ${rows.length ? "has" : ""}`}
                          >
                            <span className="muted">
                              {day.toLocaleString("fa")}
                            </span>
                            {rows.slice(0, 3).map((s) => (
                              <button
                                key={s.id}
                                onClick={() =>
                                  setEdit({ ...s, note: s.note || "" })
                                }
                                title={`${s.lesson} · ${_faInterval(s)}`}
                              >
                                {_faIntervalShort(s)} {s.lesson}
                              </button>
                            ))}
                            {rows.length > 3 && (
                              <B>+{(rows.length - 3).toLocaleString("fa")}</B>
                            )}
                          </div>
                        );
                      },
                    )}
                  </div>
                </div>
              );
            })()}
        </>
      )}
      {edit && (
        <ScheduleModal
          row={edit.id ? edit : null}
          preset={edit}
          onClose={(ok) => {
            setEdit(null);
            if (ok) load();
          }}
        />
      )}
      {flex && (
        <FlexModal
          row={flex}
          onClose={(ok) => {
            setFlex(null);
            if (ok) load();
          }}
        />
      )}
      {confirm && (
        <Confirm
          text={confirm.text}
          danger
          onYes={async () => {
            await confirm.run();
            setConfirm(null);
          }}
          onNo={() => setConfirm(null)}
        />
      )}
    </>
  );
}

function ScheduleModal({ row, preset, onClose }) {
  const [f, setF] = useState({
    type: preset.type || "class",
    lesson: preset.lesson || "",
    teacher: preset.teacher || "",
    date: preset.date || "",
    time: preset.time || "",
    end_time: preset.end_time || preset.time_end || "",
    group: preset.group || "هر دو",
    location: preset.location || "",
    note: preset.note || preset.notes || "",
    flex_type: preset.flex_type || "fixed",
  });
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  // synthesize preview for common slots
  const synthEnd = {
    "08:00": "10:00",
    "10:00": "12:00",
    "13:00": "15:00",
    "15:00": "17:00",
    "17:00": "19:00",
  };
  return (
    <Modal
      title={row ? "✏️ ویرایش مورد برنامه" : "➕ مورد جدید برنامه"}
      onClose={() => onClose(false)}
    >
      <div className="grid content-modal-grid">
        <div className="row">
          <select
            className="inp"
            value={f.type}
            onChange={(e) => set("type", e.target.value)}
          >
            {[
              ["class", "🏫 کلاس"],
              ["exam", "📝 امتحان"],
              ["makeup", "🔄 جبرانی"],
            ].map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          <select
            className="inp"
            value={f.flex_type}
            onChange={(e) => set("flex_type", e.target.value)}
          >
            <option value="fixed">زمان ثابت</option>
            <option value="flexible">منعطف (اعلام بعدی)</option>
          </select>
          <select
            className="inp"
            value={f.group}
            onChange={(e) => set("group", e.target.value)}
          >
            <option value="هر دو">👥 هر دو گروه</option>
            <option value="1">1️⃣ گروه ۱</option>
            <option value="2">2️⃣ گروه ۲</option>
          </select>
        </div>
        <input
          className="inp"
          placeholder="درس / عنوان *"
          value={f.lesson}
          onChange={(e) => set("lesson", e.target.value)}
        />
        <div className="row">
          <PersianDatePicker
            value={f.date}
            onChange={(value) => set("date", value)}
            placeholder="تاریخ شمسی"
          />
          <input
            className="inp"
            type="time"
            value={f.time}
            onChange={(e) => {
              const v = e.target.value;
              set("time", v);
              if (!f.end_time && synthEnd[v]) set("end_time", synthEnd[v]);
            }}
            title="شروع"
          />
          <input
            className="inp"
            type="time"
            value={f.end_time}
            onChange={(e) => set("end_time", e.target.value)}
            title="پایان"
          />
        </div>
        {f.time && f.end_time && (
          <div className="muted small">
            ⏰ بازه: {formatFaTime(f.time)} تا {formatFaTime(f.end_time)}{" "}
            {(() => {
              try {
                const [ah, am] = f.time.split(":").map(Number);
                const [bh, bm] = f.end_time.split(":").map(Number);
                if (bh * 60 + bm <= ah * 60 + am)
                  return "⚠️ پایان باید بعد از شروع باشد";
              } catch {}
              return "";
            })()}
          </div>
        )}
        <input
          className="inp"
          placeholder="استاد…"
          value={f.teacher}
          onChange={(e) => set("teacher", e.target.value)}
        />
        <input
          className="inp"
          placeholder="مکان…"
          value={f.location}
          onChange={(e) => set("location", e.target.value)}
        />
        <textarea
          className="inp"
          rows={2}
          placeholder="یادداشت…"
          value={f.note}
          onChange={(e) => set("note", e.target.value)}
        />
        <div className="row">
          <button
            className="btn primary"
            disabled={busy || !f.lesson.trim() || !f.date}
            onClick={async () => {
              setBusy(true);
              try {
                const body = { ...f };
                let r;
                if (row) {
                  delete body.type;
                  r = await api.caScheduleEdit(row.id, body);
                } else r = await api.caScheduleCreate(body);
                toast(
                  `ثبت شد و به ${Number(r.notified || 0).toLocaleString("fa")} نفر اطلاع داده شد ✅`,
                );
                onClose(true);
              } catch (e) {
                toast(errText(e), "err");
              }
              setBusy(false);
            }}
          >
            {row ? "ذخیره" : "ایجاد + اطلاع‌رسانی"}
          </button>
          <button className="btn" onClick={() => onClose(false)}>
            انصراف
          </button>
        </div>
      </div>
    </Modal>
  );
}

function FlexModal({ row, onClose }) {
  const [f, setF] = useState({
    date: row.date || "",
    time: row.time || "",
    end_time: row.end_time || row.time_end || "",
    note: "",
  });
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      title={`🔄 اعلام زمان جدید — ${row.lesson}`}
      onClose={() => onClose(false)}
    >
      <div className="grid content-modal-grid">
        <p className="muted">
          این اکشن زمان جدید (بازه) را ثبت و برای دانشجویان این گروه اطلاع‌رسانی
          می‌کند.
        </p>
        <div className="row">
          <PersianDatePicker
            value={f.date}
            onChange={(value) => setF((x) => ({ ...x, date: value }))}
            placeholder="تاریخ شمسی"
          />
          <input
            className="inp"
            type="time"
            value={f.time}
            onChange={(e) => setF((x) => ({ ...x, time: e.target.value }))}
            title="شروع"
          />
          <input
            className="inp"
            type="time"
            value={f.end_time}
            onChange={(e) => setF((x) => ({ ...x, end_time: e.target.value }))}
            title="پایان"
          />
        </div>
        {f.time && f.end_time && (
          <div className="muted small">
            ⏰ {formatFaTime(f.time)} تا {formatFaTime(f.end_time)}
          </div>
        )}
        <input
          className="inp"
          placeholder="یادداشت (اختیاری)…"
          value={f.note}
          onChange={(e) => setF((x) => ({ ...x, note: e.target.value }))}
        />
        <div className="row">
          <button
            className="btn primary"
            disabled={busy || !f.date}
            onClick={async () => {
              setBusy(true);
              try {
                const r = await api.caFlexChange(row.id, f);
                toast(
                  `زمان جدید ثبت و به ${Number(r.notified || 0).toLocaleString("fa")} نفر اطلاع داده شد ✅`,
                );
                onClose(true);
              } catch (e) {
                toast(errText(e), "err");
              }
              setBusy(false);
            }}
          >
            اعلام
          </button>
          <button className="btn" onClick={() => onClose(false)}>
            انصراف
          </button>
        </div>
      </div>
    </Modal>
  );
}
export function FaqTab() {
  const [items, setItems] = useState(null);
  const [err, setErr] = useState("");
  const [permErr, setPermErr] = useState(false);
  const [addModal, setAddModal] = useState(false);
  const [editItem, setEditItem] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [open, setOpen] = useState({});

  const load = async () => {
    setErr("");
    try {
      setItems((await api.caFaq()).items || []);
    } catch (e) {
      if (e.status === 403) setPermErr(true);
      else setErr(errText(e));
    }
  };
  useEffect(() => {
    load();
  }, []);

  if (permErr) return <NoPerm text="مدیریت FAQ فقط برای مدیر محتواست" />;
  if (err) return <ErrorState error={err} onRetry={load} />;

  const cats = {};
  (items || []).forEach((i) => {
    (cats[i.category] = cats[i.category] || []).push(i);
  });
  return (
    <>
      <div className="row content-tab-toolbar">
        <span className="muted">{(items || []).length} پرسش</span>
        <span className="spacer" />
        <button className="btn primary" onClick={() => setAddModal(true)}>
          ➕ پرسش جدید
        </button>
      </div>
      {!items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty icon="❓" text="پرسشی نیست" />
      ) : (
        Object.entries(cats).map(([cat, rows]) => (
          <div key={cat} className="panel content-faq-section">
            <div className="panel-pad row content-section-row">
              <b>🗂 {cat}</b>
              <B>{rows.length}</B>
            </div>
            {rows.map((f) => (
              <div key={f.id} className="row content-faq-row">
                <div
                  className="content-faq-copy"
                  onClick={() => setOpen((x) => ({ ...x, [f.id]: !x[f.id] }))}
                >
                  <div className="content-faq-question">
                    {open[f.id] ? "▾" : "▸"} {f.question}
                  </div>
                  {open[f.id] && (
                    <div
                      className="muted content-faq-answer"
                      style={{ whiteSpace: "pre-wrap" }}
                    >
                      {f.answer}
                    </div>
                  )}
                </div>
                <button
                  className="btn sm"
                  aria-label={`ویرایش پرسش ${f.question.slice(0, 40)}`}
                  onClick={() => setEditItem(f)}
                >
                  ✏️
                </button>
                <button
                  className="btn sm danger"
                  aria-label={`حذف پرسش ${f.question.slice(0, 40)}`}
                  onClick={() =>
                    setConfirm({
                      text: `حذف پرسش «${f.question.slice(0, 40)}…»؟`,
                      run: async () => {
                        await api.caFaqDel(f.id);
                        toast("حذف شد");
                        load();
                      },
                    })
                  }
                >
                  🗑
                </button>
              </div>
            ))}
          </div>
        ))
      )}
      {addModal && (
        <FaqAddModal
          onClose={(ok) => {
            setAddModal(false);
            if (ok) load();
          }}
        />
      )}
      {editItem && (
        <FaqEditModal
          item={editItem}
          onClose={(ok) => {
            setEditItem(null);
            if (ok) load();
          }}
        />
      )}
      {confirm && (
        <Confirm
          text={confirm.text}
          danger
          onYes={async () => {
            await confirm.run();
            setConfirm(null);
          }}
          onNo={() => setConfirm(null)}
        />
      )}
    </>
  );
}

function FaqAddModal({ onClose }) {
  const [f, setF] = useState({ category: "عمومی", question: "", answer: "" });
  const [busy, setBusy] = useState(false);
  return (
    <Modal title="➕ پرسش متداول جدید" onClose={() => onClose(false)}>
      <div className="grid content-modal-grid">
        <input
          className="inp"
          placeholder="دسته…"
          value={f.category}
          onChange={(e) => setF((x) => ({ ...x, category: e.target.value }))}
        />
        <input
          className="inp"
          placeholder="پرسش (حداقل ۵ حرف) *"
          value={f.question}
          onChange={(e) => setF((x) => ({ ...x, question: e.target.value }))}
        />
        <textarea
          className="inp"
          rows={4}
          placeholder="پاسخ (حداقل ۵ حرف) *"
          value={f.answer}
          onChange={(e) => setF((x) => ({ ...x, answer: e.target.value }))}
        />
        <div className="row">
          <button
            className="btn primary"
            disabled={
              busy || f.question.trim().length < 5 || f.answer.trim().length < 5
            }
            onClick={async () => {
              setBusy(true);
              try {
                await api.caFaqAdd({
                  category: f.category.trim() || "عمومی",
                  question: f.question.trim(),
                  answer: f.answer.trim(),
                });
                toast("ثبت شد ✅");
                onClose(true);
              } catch (e) {
                toast(errText(e), "err");
              }
              setBusy(false);
            }}
          >
            ثبت
          </button>
          <button className="btn" onClick={() => onClose(false)}>
            انصراف
          </button>
        </div>
      </div>
    </Modal>
  );
}

function FaqEditModal({ item, onClose }) {
  const [f, setF] = useState({
    category: item.category || "عمومی",
    question: item.question || "",
    answer: item.answer || "",
  });
  const [busy, setBusy] = useState(false);
  return (
    <Modal title="✏️ ویرایش پرسش متداول" onClose={() => onClose(false)}>
      <div className="grid content-modal-grid">
        <input
          className="inp"
          placeholder="دسته…"
          value={f.category}
          onChange={(e) => setF((x) => ({ ...x, category: e.target.value }))}
        />
        <input
          className="inp"
          placeholder="پرسش (حداقل ۵ حرف) *"
          value={f.question}
          onChange={(e) => setF((x) => ({ ...x, question: e.target.value }))}
        />
        <textarea
          className="inp"
          rows={5}
          placeholder="پاسخ (حداقل ۵ حرف) *"
          value={f.answer}
          onChange={(e) => setF((x) => ({ ...x, answer: e.target.value }))}
        />
        <div className="row">
          <button
            className="btn primary"
            disabled={
              busy || f.question.trim().length < 5 || f.answer.trim().length < 5
            }
            onClick={async () => {
              setBusy(true);
              try {
                const payload = {};
                if (f.category.trim() !== (item.category || ""))
                  payload.category = f.category.trim();
                if (f.question.trim() !== (item.question || ""))
                  payload.question = f.question.trim();
                if (f.answer.trim() !== (item.answer || ""))
                  payload.answer = f.answer.trim();
                if (!Object.keys(payload).length) {
                  toast("تغییری ایجاد نشد", "err");
                  setBusy(false);
                  return;
                }
                await api.caFaqEdit(item.id, payload);
                toast("ویرایش ذخیره شد ✅");
                onClose(true);
              } catch (e) {
                toast(errText(e), "err");
              }
              setBusy(false);
            }}
          >
            ذخیره
          </button>
          <button className="btn" onClick={() => onClose(false)}>
            انصراف
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ── 🚩 صف و تاریخچه گزارش‌های محتوا/سؤال ────────────────────────
export function ReportsTab() {
  const [status, setStatus] = useState("new");
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [stats, setStats] = useState(null);
  const [err, setErr] = useState("");
  const [permErr, setPermErr] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const LIMIT = 30;
  const load = async () => {
    setErr("");
    setData(null);
    try {
      const [rows, counts] = await Promise.all([
        api.caReports({
          status: status || undefined,
          skip: (page - 1) * LIMIT,
          limit: LIMIT,
        }),
        api.caReportStats(),
      ]);
      setData(rows);
      setStats(counts);
    } catch (e) {
      if (e.status === 403) setPermErr(true);
      else setErr(errText(e));
    }
  };
  useEffect(() => {
    load();
  }, [status, page]);
  const change = async () => {
    const c = confirm;
    setConfirm(null);
    try {
      await api.caReportStatus(c.row.id, c.status);
      toast("وضعیت گزارش ذخیره شد ✅");
      load();
    } catch (e) {
      toast(errText(e), "err");
    }
  };
  if (permErr)
    return (
      <NoPerm text="بررسی گزارش‌های محتوا نیازمند مجوز reports.review است" />
    );
  if (err) return <ErrorState error={err} onRetry={load} />;
  const total = data?.total || 0;
  const cols = [
    {
      k: "reason",
      label: "دلیل",
      render: (r) => <B kind="warn">{r.reason || "—"}</B>,
    },
    {
      k: "target_type",
      label: "هدف",
      render: (r) => (
        <div>
          <b>{r.target_type === "question" ? "سؤال" : "محتوا"}</b>
          <div className="muted code">{r.target_id || "—"}</div>
        </div>
      ),
    },
    {
      k: "note",
      label: "توضیح",
      render: (r) => <span className="content-pre-wrap">{r.note || "—"}</span>,
    },
    { k: "reporter_name", label: "گزارش‌دهنده" },
    {
      k: "created_at",
      label: "ثبت",
      render: (r) => <FaDateTime value={r.created_at} />,
    },
    {
      k: "status",
      label: "وضعیت",
      render: (r) => (
        <B
          kind={
            r.status === "resolved"
              ? "ok"
              : r.status === "rejected"
                ? "bad"
                : r.status === "reviewing"
                  ? "acc"
                  : "warn"
          }
        >
          {r.status}
        </B>
      ),
    },
    {
      k: "ops",
      label: "",
      stop: true,
      render: (r) => (
        <div className="row content-actions-tight">
          {r.status !== "reviewing" && (
            <button
              className="btn sm"
              onClick={() => setConfirm({ row: r, status: "reviewing" })}
            >
              👁 بررسی
            </button>
          )}
          {r.status !== "resolved" && (
            <button
              className="btn sm ok"
              onClick={() => setConfirm({ row: r, status: "resolved" })}
            >
              ✅ حل
            </button>
          )}
          {r.status !== "rejected" && (
            <button
              className="btn sm danger"
              onClick={() => setConfirm({ row: r, status: "rejected" })}
            >
              ✖ رد
            </button>
          )}
        </div>
      ),
    },
  ];
  return (
    <>
      <div className="row content-tab-toolbar content-wrap">
        <div>
          <div className="h1">گزارش‌های محتوا و سؤال</div>
          <div className="sub">
            صف بررسی، وضعیت جاری و تاریخچه کامل گزارش‌های دانشجویان
          </div>
        </div>
        <span className="spacer" />
        {stats && (
          <>
            <B kind="warn">
              جدید: {Number(stats.new || 0).toLocaleString("fa")}
            </B>
            <B kind="acc">
              در بررسی: {Number(stats.reviewing || 0).toLocaleString("fa")}
            </B>
            <B kind="ok">
              حل: {Number(stats.resolved || 0).toLocaleString("fa")}
            </B>
          </>
        )}
      </div>
      <div
        className="tabs content-tabs-sm"
        role="tablist"
        aria-label="وضعیت گزارش‌ها"
      >
        {[
          ["new", "جدید"],
          ["reviewing", "در بررسی"],
          ["resolved", "حل‌شده"],
          ["rejected", "ردشده"],
          ["", "همه تاریخچه"],
        ].map(([k, l]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={status === k}
            className={`tab ${status === k ? "on" : ""}`}
            onClick={() => {
              setStatus(k);
              setPage(1);
            }}
          >
            {l}
          </button>
        ))}
      </div>
      <SavedViews
        scope="reports"
        filters={{ status }}
        onApply={(f) => {
          setStatus(f.status ?? "new");
          setPage(1);
        }}
        label="صف‌های ذخیره‌شده"
      />
      {!data ? (
        <Loading rows={6} />
      ) : (
        <DataTable
          columns={cols}
          rows={data.reports || []}
          rowKey="id"
          colToggle
          pager={{
            page,
            pages: Math.max(1, Math.ceil(total / LIMIT)),
            total,
            onPage: setPage,
          }}
          empty={<Empty icon="🚩" text="گزارشی در این وضعیت نیست" />}
        />
      )}
      {confirm && (
        <Confirm
          danger={confirm.status === "rejected"}
          text={`تغییر وضعیت گزارش #${confirm.row.id} به «${confirm.status}»؟`}
          onYes={change}
          onNo={() => setConfirm(null)}
        />
      )}
    </>
  );
}
