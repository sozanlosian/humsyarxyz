import PageError from "../../components/shared/PageError";
import EmptyState from "../../components/shared/EmptyState";

import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import api from "../../lib/api";
import Header from "../../components/layout/Header";
import { Spinner } from "../../components/shared/Loading";

import { ScheduleSkeleton } from "../../components/shared/skeletons";
import { haptic } from "../../lib/telegram";
import { useUIStore } from "../../stores/uiStore";
import { faNum, faDate } from "../../lib/format";

function mergeScheduleBlocks(list) {
  const _p = (v) => {
    const m = String(v || "").match(/(\d{1,2}):(\d{2})/);
    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
  };
  const _f = (min) => `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
  const sorted = [...(list || [])].sort((a, b) => (a.date || "").localeCompare(b.date || "") || String(a.time || "").localeCompare(String(b.time || "")));
  const out = [];
  for (const cur of sorted) {
    const prev = out[out.length - 1];
    if (prev && prev.date === cur.date && prev.lesson === cur.lesson && (prev.group || "") === (cur.group || "") && (prev.type || "class") === (cur.type || "class") && (prev.location || "") === (cur.location || "") && (prev.teacher || "") === (cur.teacher || "")) {
      const prevEnd = _p(prev.end_time || prev.time_end || "") ?? (_p(prev.time) !== null ? _p(prev.time) + 60 : null);
      const prevStart = _p(prev.time);
      const prevDur = prevEnd !== null && prevStart !== null ? prevEnd - prevStart : null;
      const curStart = _p(cur.time);
      const curEnd = _p(cur.end_time || cur.time_end || "") ?? (curStart !== null ? curStart + 60 : null);
      const curDur = curEnd !== null && curStart !== null ? curEnd - curStart : null;
      if (prevEnd !== null && curStart !== null && prevEnd === curStart && curEnd !== null && prevDur === 60 && curDur === 60) {
        prev.end_time = _f(curEnd);
        prev._merged = (prev._merged || 1) + 1;
        continue;
      }
    }
    out.push({ ...cur });
  }
  return out;
}

import { useAuthStore } from "../../stores/authStore";

const TYPES = {
  class: {
    icon: "🏫",
    label: "کلاس‌ها",
    color: "var(--t-acc)",
    soft: "var(--soft-acc)",
  },

  exam: {
    icon: "📝",
    label: "امتحانات",
    color: "var(--t-err)",
    soft: "var(--soft-err)",
  },

  makeup: {
    icon: "🔄",
    label: "جبرانی",
    color: "var(--t-warn)",
    soft: "var(--soft-warn)",
  },
};

const days = (value) => {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const parsed = Number(value);

  return Number.isFinite(parsed) ? Math.max(0, Math.floor(parsed)) : null;
};

const groupName = (value) => {
  if (!value || value === "0") {
    return "";
  }

  if (value === "هر دو") {
    return "هر دو گروه";
  }

  return `گروه ${value}`;
};

export default function Schedule() {
  const [tab, setTab] = useState("class");
  const toast = useUIStore((s) => s.toast);
  const [calBusy, setCalBusy] = useState(false);

  /* 🌊 W8/UX-05 — دانلود iCal (blob با احراز initData) */
  const downloadCal = async () => {
    if (calBusy) return;
    setCalBusy(true);
    try {
      const r = await api.get("/api/schedule/ical", { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([r.data], { type: "text/calendar" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "humsyar-schedule.ics";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      toast("📅 فایل تقویم دانلود شد");
    } catch {
      toast("دانلود تقویم ناموفق بود", "err");
    }
    setCalBusy(false);
  };

  const userGroup = useAuthStore((state) => state.user?.group || "");

  const { data, isLoading, isError, refetch, isRefetching } = useQuery({
    queryKey: ["schedule", userGroup],

    queryFn: () => api.get("/api/schedule").then((response) => response.data),

    staleTime: 5 * 60 * 1000,

    refetchOnMount: "always",
  });

  const schedule = Array.isArray(data?.schedule) ? data.schedule : [];

  const items = schedule.filter((item) => item?.type === tab);

  /* 🧠 موج N3 — Deep Link: /schedule?hl=<درس>
     اولین کارت هم‌نام درس، اسکرول + فلش می‌خورد */
  const [flashIdx, setFlashIdx] = useState(-1);
  const [searchParams] = useSearchParams();
  const hlDone = useRef(false);

  useEffect(() => {
    if (hlDone.current || !items.length) return;

    const hl = searchParams.get("hl");
    if (!hl) return;

    const match = items.findIndex(
      (it) =>
        it.id === hl ||
        (it.lesson || "") === hl ||
        (it.lesson || "").includes(hl),
    );

    if (match < 0) return;

    hlDone.current = true;
    setFlashIdx(match);

    const el = document.querySelector(`[data-lidx="${match}"]`);

    if (el) {
      setTimeout(() => {
        el.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      }, 60);

      setTimeout(() => setFlashIdx(-1), 3200);
    }
  }, [items, searchParams]);

  const config = TYPES[tab];

  const counts = Object.fromEntries(
    Object.keys(TYPES).map((type) => [
      type,

      schedule.filter((item) => item?.type === type).length,
    ]),
  );

  const nearestExam = schedule.find((item) => item?.type === "exam");

  const nearestDays = days(nearestExam?.days_left);

  return (
    <>
      <Header
        title="برنامه درسی"
        subtitle={`برنامه شخصی ${groupName(data?.group || userGroup) || "شما"}`}
        back={false}
        onRefresh={refetch}
        refreshing={isRefetching}
      />

      <main className="page fade-up">
        <section
          className={"card card-glow hero-card"}
          style={{
            marginBottom: "var(--sp-4)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 13,
            }}
          >
            <div
              style={{
                width: 52,
                height: 52,

                display: "grid",
                placeItems: "center",

                borderRadius: "var(--r-lg)",

                background: "var(--grad-brand)",

                boxShadow: "var(--shd-glow)",

                fontSize: 24,
              }}
            >
              📅
            </div>

            <div
              style={{
                flex: 1,
              }}
            >
              <div
                style={{
                  color: "var(--txm)",

                  fontSize: "var(--fs-cap)",
                }}
              >
                برنامه ترم جاری
              </div>

              <div
                style={{
                  fontSize: "var(--fs-xl)",

                  fontWeight: 900,

                  marginTop: 2,
                }}
              >
                {groupName(data?.group || userGroup) || "گروه نامشخص"}
              </div>

              <div
                style={{
                  display: "flex",

                  gap: 5,

                  marginTop: "var(--sp-2)",
                }}
              >
                <span className="badge b-acc">{counts.class || 0} کلاس</span>

                <span className="badge b-red">{counts.exam || 0} امتحان</span>
              </div>
            </div>

            {nearestExam && nearestDays !== null && (
              <div
                style={{
                  minWidth: 58,

                  textAlign: "center",

                  padding: "8px 7px",

                  borderRadius: "var(--r-md)",

                  background:
                    nearestDays <= 3 ? "var(--soft-err)" : "var(--acc-soft)",

                  border: `1px solid ${
                    nearestDays <= 3 ? "var(--bd-err)" : "var(--bdg)"
                  }`,
                }}
              >
                <div
                  style={{
                    color: nearestDays <= 3 ? "var(--err)" : "var(--acc2)",

                    fontSize: "var(--fs-xl)",

                    fontWeight: 900,
                  }}
                >
                  {nearestDays}
                </div>

                <div
                  style={{
                    color: "var(--txm)",

                    fontSize: "var(--fs-cap)",
                  }}
                >
                  {nearestDays === 0 ? "امروز" : "روز تا امتحان"}
                </div>
              </div>
            )}
          </div>
        </section>

        <div className="row" style={{ marginBottom: 8 }}>
          <button type="button" className="btn sm" disabled={calBusy} onClick={downloadCal}>
            {calBusy ? "⏳ …" : "📅 افزودن به تقویم (.ics)"}
          </button>
        </div>

        <div className="tab-bar" role="tablist">
          {Object.entries(TYPES).map(([key, item]) => (
            <button
              type="button"
              role="tab"
              aria-selected={tab === key}
              key={key}
              className={`tab-btn ${tab === key ? "tab-btn--on" : ""}`}
              onClick={() => {
                haptic();
                setTab(key);
              }}
            >
              {item.icon} {item.label} {counts[key] ? `(${counts[key]})` : ""}
            </button>
          ))}
        </div>

        {isLoading ? (
          <ScheduleSkeleton />
        ) : isError ? (
          <PageError
            text={"دریافت برنامه انجام نشد."}
            onRetry={() => refetch()}
            pending={isRefetching}
          />
        ) : items.length === 0 ? (
          <EmptyState icon={TYPES[tab].icon}>
            موردی در بخش {TYPES[tab].label} ثبت نشده است.
          </EmptyState>
        ) : (
          (() => {
            const _merged = mergeScheduleBlocks(items);
            const _grouped2 = {};
            for (const it of _merged) {
              const k = it.date || "بدون تاریخ";
              (_grouped2[k] ||= []).push(it);
            }
            const _dates = Object.keys(_grouped2).sort((a, b) =>
              a.localeCompare(b),
            );
            return (
              <section style={{ display: "grid", gap: 14 }}>
                {_dates.map((day) => {
                  const dayItems = _grouped2[day].sort((a, b) =>
                    String(a.time || "").localeCompare(String(b.time || "")),
                  );
                  return (
                    <div key={day} style={{ display: "grid", gap: 9 }}>
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                          padding: "6px 2px",
                        }}
                      >
                        <span
                          style={{
                            display: "grid",
                            width: 36,
                            height: 36,
                            placeItems: "center",
                            borderRadius: 10,
                            background: "var(--acc-soft)",
                            fontSize: 16,
                          }}
                        >
                          📅
                        </span>
                        <div>
                          <b style={{ fontSize: "var(--fs-sm)" }}>
                            {faDate(day, "—")}
                          </b>
                          <div
                            className="muted"
                            style={{ fontSize: "var(--fs-cap)" }}
                          >
                            {faNum(dayItems.length)} جلسه · {faDate(day)}
                          </div>
                        </div>
                        <span className="spacer" />
                        <span className="badge b-acc">
                          {faNum(dayItems.length)}
                        </span>
                      </div>
                      {dayItems.map((item, index) => {
                        const remaining = days(item.days_left);

                        const urgent =
                          item.type === "exam" &&
                          remaining !== null &&
                          remaining <= 3;

                        const note = item.note || item.flex_note || "";

                        return (
                          <article
                            key={item.id || `${item.lesson}-${index}-${day}`}
                            data-lidx={index}
                            className={
                              flashIdx === index ? "card hl-flash" : "card"
                            }
                            style={{
                              padding: 13,

                              borderColor: urgent
                                ? "var(--bd-err)"
                                : "var(--bd)",
                              borderInlineStart: urgent
                                ? "3px solid var(--err)"
                                : item.type === "makeup"
                                  ? "3px solid var(--warn)"
                                  : "3px solid var(--acc)",
                            }}
                          >
                            <div
                              style={{
                                display: "flex",

                                alignItems: "flex-start",

                                gap: 11,
                              }}
                            >
                              <div
                                style={{
                                  display: "grid",

                                  flex: "0 0 46px",

                                  height: 46,

                                  placeItems: "center",

                                  borderRadius: "var(--r-md)",

                                  background: urgent
                                    ? "var(--soft-err)"
                                    : config.soft,

                                  fontSize: 21,
                                }}
                              >
                                {config.icon}
                              </div>

                              <div
                                style={{
                                  flex: 1,
                                  minWidth: 0,
                                }}
                              >
                                <div
                                  style={{
                                    display: "flex",

                                    alignItems: "center",

                                    gap: 6,
                                  }}
                                >
                                  <h3
                                    style={{
                                      overflow: "hidden",

                                      fontSize: "var(--fs-md)",

                                      fontWeight: 850,

                                      textOverflow: "ellipsis",

                                      whiteSpace: "nowrap",
                                    }}
                                  >
                                    {item.lesson || "بدون عنوان"}
                                  </h3>

                                  {item.flex_type === "flexible" && (
                                    <span className="badge b-yel">منعطف</span>
                                  )}
                                  {item._merged && (
                                    <span
                                      className="badge b-acc"
                                      style={{ fontSize: 10 }}
                                    >
                                      🔗 {faNum(item._merged)} ادغام
                                    </span>
                                  )}
                                </div>

                                {item.teacher && (
                                  <div
                                    style={{
                                      color: "var(--tx2)",

                                      fontSize: "var(--fs-cap)",

                                      marginTop: 3,
                                    }}
                                  >
                                    👨‍🏫 {item.teacher}
                                  </div>
                                )}

                                <div
                                  style={{
                                    display: "flex",

                                    flexWrap: "wrap",

                                    gap: 5,

                                    marginTop: "var(--sp-2)",
                                  }}
                                >
                                  <span className="badge b-acc">
                                    📆 {faDate(item.date, "تاریخ نامشخص")}
                                  </span>

                                  {item.time && (
                                    <span className="badge b-gray">
                                      ⏰ {faNum(item.time)}
                                      {item.end_time || item.time_end
                                        ? ` تا ${faNum(item.end_time || item.time_end)}`
                                        : ""}
                                    </span>
                                  )}

                                  {item.location && (
                                    <span className="badge b-gray">
                                      📍 {item.location}
                                    </span>
                                  )}

                                  {groupName(item.group) && (
                                    <span className="badge b-gray">
                                      {groupName(item.group)}
                                    </span>
                                  )}
                                </div>
                              </div>

                              {item.type === "exam" && remaining !== null && (
                                <span
                                  className={`badge ${
                                    urgent ? "b-red" : "b-grn"
                                  }`}
                                >
                                  {remaining === 0
                                    ? "امروز"
                                    : remaining === 1
                                      ? "فردا"
                                      : `${remaining} روز`}
                                </span>
                              )}
                            </div>

                            {note && (
                              <div
                                style={{
                                  marginTop: "var(--sp-3)",

                                  padding: "8px 10px",

                                  color: "var(--tx2)",

                                  background: "var(--soft-mut)",

                                  borderRadius: "var(--r-md)",

                                  fontSize: "var(--fs-cap)",

                                  lineHeight: 1.7,
                                }}
                              >
                                📝 {note}
                              </div>
                            )}
                          </article>
                        );
                      })}
                    </div>
                  );
                })}
              </section>
            );
          })()
        )}
      </main>
    </>
  );
}
