import Switch from '../../components/shared/Switch';

import { faNum, faDate } from '../../lib/format';

import {
  useMemo,
  useState,
} from 'react';

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import Header from '../../components/layout/Header';
import PageError from '../../components/shared/PageError';
import {
  Spinner,
} from '../../components/shared/Loading';
import api from '../../lib/api';
import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';
import { confirmAction } from '../../lib/confirm';
import {
  useUIStore,
} from '../../stores/uiStore';


/* ─────────────────────────────────────────────
   🛡 مدیریت نقش‌ها — موج RBAC-W2 (قرارداد §۶)
   همه‌چیز داینامیک از /api/admin/rbac می‌آید:
   لیست نقش‌ها، رجیستری مجوزها، ساخت/ویرایش/حذف،
   ماتریس سوییچ‌های تکی دسته‌بندی‌شده. هیچ نقش/
   برچسب/رنگ/آیکونی اینجا هاردکد نیست — سرور
   تنها منبع حقیقت است (§۴).
───────────────────────────────────────────── */


const ROLES_KEY = ['rbac-roles'];
const PERMS_KEY = ['rbac-perms'];


/* 🎛 سوییچ کوچک — بدون وابستگی به کلاس‌های خاص
   تا روی هر دیتایی قابل استفاده باشد */
export function AdminRoles() {
  const toast = useUIStore((state) => state.toast);
  const queryClient = useQueryClient();

  const [mode, setMode] = useState('list');
  const [draft, setDraft] = useState(null);
  const [search, setSearch] = useState('');
  const [openCats, setOpenCats] = useState(
    () => new Set(),
  );


  const rolesQuery = useQuery({
    queryKey: ROLES_KEY,
    queryFn: () =>
      api
        .get('/api/admin/rbac/roles')
        .then((response) => response.data),
    staleTime: 30_000,
  });

  const permsQuery = useQuery({
    queryKey: PERMS_KEY,
    queryFn: () =>
      api
        .get('/api/admin/rbac/permissions')
        .then((response) => response.data),
    staleTime: 300_000,
  });

  const roles = rolesQuery.data?.roles || [];
  const categories = permsQuery.data?.categories || [];
  const allPerms = permsQuery.data?.permissions || [];


  const refresh = () =>
    queryClient.invalidateQueries({
      queryKey: ROLES_KEY,
    });


  const saveMutation = useMutation({
    mutationFn: (payload) =>
      payload.key
        ? api.patch(
          `/api/admin/rbac/roles/${payload.key}`,
          payload.body,
        )
        : api.post('/api/admin/rbac/roles', payload.body),

    onSuccess: () => {
      hapticNotif('success');
      toast('✅ نقش ذخیره شد', 'success');
      setMode('list');
      setDraft(null);
      refresh();
    },

    onError: (error) => {
      hapticNotif('error');
      const detail = error?.response?.data?.detail;
      toast(
        typeof detail === 'string' && detail
          ? detail
          : 'ذخیره نقش انجام نشد',
        'error',
      );
    },
  });


  const deleteMutation = useMutation({
    mutationFn: (key) =>
      api.delete(`/api/admin/rbac/roles/${key}`),

    onSuccess: () => {
      hapticNotif('success');
      toast('🗑 نقش حذف شد', 'success');
      refresh();
    },

    onError: (error) => {
      hapticNotif('error');
      const detail = error?.response?.data?.detail;
      toast(
        typeof detail === 'string' && detail
          ? detail
          : 'حذف نقش انجام نشد',
        'error',
      );
    },
  });


  /* ✏️ آغاز ویرایش/ساخت — draft با Set از مجوزها */
  const startEdit = (role = null) => {
    haptic('light');
    setSearch('');
    setOpenCats(new Set(categories.map((c) => c.key)));
    setDraft(
      role
        ? {
          key: role.key,
          label: role.label,
          desc: role.desc,
          icon: role.icon,
          color: role.color,
          priority: role.priority,
          perms: new Set(role.perms),
          system: role.system,
        }
        : {
          key: null,
          label: '',
          desc: '',
          icon: '🛡',
          color: 'var(--t-acc)',
          priority: 90,
          perms: new Set(),
          system: false,
        },
    );
    setMode('edit');
  };


  const togglePerm = (key) => {
    haptic('light');
    setDraft((prev) => {
      const perms = new Set(prev.perms);
      if (perms.has(key)) perms.delete(key);
      else perms.add(key);
      return { ...prev, perms };
    });
  };


  const setCatPerms = (catKey, on) => {
    const keys = allPerms
      .filter((p) => p.category === catKey)
      .map((p) => p.key);
    setDraft((prev) => {
      const perms = new Set(prev.perms);
      keys.forEach((key) =>
        on ? perms.add(key) : perms.delete(key),
      );
      return { ...prev, perms };
    });
  };


  const setAllPerms = (on) =>
    setDraft((prev) => ({
      ...prev,
      perms: on
        ? new Set(allPerms.map((p) => p.key))
        : new Set(),
    }));


  /* 🔍 فیلتر جست‌وجو روی ماتریس */
  const visiblePerms = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return allPerms;
    return allPerms.filter((perm) =>
      perm.label.toLowerCase().includes(needle) ||
      perm.key.toLowerCase().includes(needle),
    );
  }, [allPerms, search]);

  const grouped = useMemo(
    () =>
      categories.map((cat) => ({
        ...cat,
        perms: visiblePerms.filter(
          (perm) => perm.category === cat.key,
        ),
      })),
    [categories, visiblePerms],
  );


  const submit = () => {
    if (!draft.label.trim()) {
      toast('نام نقش را بنویس', 'error');
      return;
    }
    const body = {
      label: draft.label.trim(),
      desc: draft.desc.trim(),
      ...(draft.icon.trim()
        ? { icon: draft.icon.trim() }
        : {}),
      color: draft.color.trim() || 'var(--t-acc)',
      priority: Number(draft.priority) || 90,
      perms: [...draft.perms],
    };
    saveMutation.mutate(
      draft.key
        ? { key: draft.key, body }
        : { body },
    );
  };


  /* ════ حالت ویرایشگر (ساخت/ویرایش) ════ */
  if (mode === 'edit' && draft) {
    return (
      <>
        <Header
          title={
            draft.key ? `ویرایش ${draft.label}` : 'نقش جدید'
          }
          subtitle={
            draft.system
              ? 'نقش سیستمی — قابل ویرایش، حذف‌ناپذیر'
              : `${faNum(draft.perms.size)} مجوز انتخاب شده`
          }
          backTo="/admin/roles"
        />

        <main
          className="page fade-up"
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 'var(--sp-3)',
            paddingInline: 12,
          }}
        >
          {/* 🪪 مشخصات نقش */}
          <section
            className="card fade-up"
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 9,
              padding: '12px 14px',
            }}
          >
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                className="input"
                style={{ flex: 1, minHeight: 36, fontSize: 'var(--fs-sm)' }}
                placeholder="نام نقش (مثل ناظم شب)"
                value={draft.label}
                maxLength={60}
                onChange={(event) =>
                  setDraft({ ...draft, label: event.target.value })
                }
                aria-label="نام نقش"
              />
              <input
                className="input"
                style={{ width: 52, minHeight: 36, fontSize: 'var(--fs-lg)', textAlign: 'center' }}
                value={draft.icon}
                maxLength={2}
                onChange={(event) =>
                  setDraft({ ...draft, icon: event.target.value })
                }
                aria-label="آیکون"
              />
            </div>

            <input
              className="input"
              style={{ minHeight: 34, fontSize: 'var(--fs-meta)' }}
              placeholder="توضیح کوتاه (اختیاری)"
              value={draft.desc}
              maxLength={200}
              onChange={(event) =>
                setDraft({ ...draft, desc: event.target.value })
              }
              aria-label="توضیح نقش"
            />

            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--sp-3)',
                flexWrap: 'wrap',
              }}
            >
              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  fontSize: 'var(--fs-cap)',
                  color: 'var(--tx2)',
                }}
              >
                رنگ
                <input
                  type="color"
                  value={draft.color}
                  onChange={(event) =>
                    setDraft({ ...draft, color: event.target.value })
                  }
                  style={{
                    width: 28,
                    height: 24,
                    border: 'none',
                    background: 'none',
                    padding: 0,
                  }}
                  aria-label="رنگ نقش"
                />
              </label>

              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  fontSize: 'var(--fs-cap)',
                  color: 'var(--tx2)',
                }}
              >
                اولویت
                <input
                  type="number"
                  className="input"
                  style={{ width: 64, minHeight: 30, fontSize: 'var(--fs-meta)' }}
                  min={1}
                  max={999}
                  value={draft.priority}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      priority: event.target.value,
                    })
                  }
                  aria-label="اولویت نقش"
                />
              </label>
            </div>
          </section>

          {/* 🎚 نوار ابزار ماتریس مجوزها */}
          <section
            className="card fade-up"
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
              padding: '10px 12px',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                flexWrap: 'wrap',
              }}
            >
              <input
                type="search"
                className="input"
                style={{
                  flex: 1,
                  minWidth: 120,
                  minHeight: 32,
                  fontSize: 'var(--fs-meta)',
                }}
                placeholder="جست‌وجو در مجوزها…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                aria-label="جست‌وجو در مجوزها"
              />
              <button
                type="button"
                className="tab-btn"
                style={{ fontSize: 'var(--fs-cap)', minHeight: 28 }}
                onClick={() => setAllPerms(true)}
              >
                همه روشن
              </button>
              <button
                type="button"
                className="tab-btn"
                style={{ fontSize: 'var(--fs-cap)', minHeight: 28 }}
                onClick={() => setAllPerms(false)}
              >
                همه خاموش
              </button>
              <button
                type="button"
                className="tab-btn"
                style={{ fontSize: 'var(--fs-cap)', minHeight: 28 }}
                onClick={() =>
                  setOpenCats(
                    new Set(categories.map((c) => c.key)),
                  )
                }
              >
                باز کردن همه
              </button>
              <button
                type="button"
                className="tab-btn"
                style={{ fontSize: 'var(--fs-cap)', minHeight: 28 }}
                onClick={() => setOpenCats(new Set())}
              >
                جمع کردن همه
              </button>
            </div>
          </section>

          {/* 🧩 ماتریس دسته‌بندی‌شده — از رجیستری سرور */}
          {grouped.map((cat) =>
            cat.perms.length > 0 && (
              <section
                key={cat.key}
                className="card fade-up"
                style={{ padding: '0 12px 8px' }}
              >
                <button
                  type="button"
                  onClick={() => {
                    haptic('light');
                    setOpenCats((prev) => {
                      const next = new Set(prev);
                      if (next.has(cat.key)) next.delete(cat.key);
                      else next.add(cat.key);
                      return next;
                    });
                  }}
                  style={{
                    all: 'unset',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--sp-2)',
                    width: '100%',
                    padding: '10px 2px 6px',
                    cursor: 'pointer',
                    fontSize: 'var(--fs-meta)',
                    fontWeight: 700,
                  }}
                  aria-expanded={openCats.has(cat.key)}
                >
                  <span>
                    {cat.label}
                  </span>
                  <span
                    className="badge b-gray"
                    style={{ fontSize: 'var(--fs-cap)' }}
                  >
                    {faNum(
                      allPerms.filter(
                        (p) =>
                          p.category === cat.key &&
                          draft.perms.has(p.key),
                      ).length,
                    )}
                    {'/'}
                    {faNum(
                      allPerms.filter(
                        (p) => p.category === cat.key,
                      ).length,
                    )}
                  </span>
                  <span style={{ marginInlineStart: 'auto', fontSize: 'var(--fs-cap)', color: 'var(--txm)' }}>
                    {openCats.has(cat.key) ? '▲' : '▼'}
                  </span>
                </button>

                {openCats.has(cat.key) && (
                  <div
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        gap: 6,
                        paddingBottom: 6,
                      }}
                    >
                      <button
                        type="button"
                        className="tab-btn"
                        style={{ fontSize: 'var(--fs-cap)', minHeight: 24, padding: '2px 7px' }}
                        onClick={() => setCatPerms(cat.key, true)}
                      >
                        همهٔ این دسته روشن
                      </button>
                      <button
                        type="button"
                        className="tab-btn"
                        style={{ fontSize: 'var(--fs-cap)', minHeight: 24, padding: '2px 7px' }}
                        onClick={() => setCatPerms(cat.key, false)}
                      >
                        همه خاموش
                      </button>
                    </div>

                    {cat.perms.map((perm) => (
                      <div
                        key={perm.key}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 9,
                          padding: '7px 2px',
                          borderTop: '1px solid var(--line)',
                        }}
                      >
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 'var(--fs-cap)' }}>
                            {perm.label}
                          </div>
                          <div
                            style={{
                              fontSize: 'var(--fs-cap)',
                              color: 'var(--txm)',
                              direction: 'ltr',
                              textAlign: 'left',
                            }}
                          >
                            {perm.key}
                          </div>
                        </div>
                        <Switch
                          on={draft.perms.has(perm.key)}
                          onToggle={() => togglePerm(perm.key)}
                          color={`${draft.color}55`}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </section>
            ),
          )}

          {/* 💾 اکشن‌ها */}
          <div
            style={{
              display: 'flex',
              gap: 8,
              position: 'sticky',
              bottom: 10,
            }}
          >
            <button
              type="button"
              className="btn btn-p"
              style={{ flex: 1 }}
              disabled={saveMutation.isPending}
              onClick={submit}
            >
              {saveMutation.isPending
                ? <Spinner size={14} />
                : '💾'}{' '}
              ذخیره نقش
            </button>
            <button
              type="button"
              className="btn btn-d"
              onClick={() => {
                haptic('light');
                setMode('list');
                setDraft(null);
              }}
            >
              انصراف
            </button>
          </div>
        </main>
      </>
    );
  }


  /* ════ حالت لیست ════ */
  return (
    <>
      <Header
        title="مدیریت نقش‌ها"
        subtitle={`${faNum(roles.length)} نقش — RBAC دیتابیس‌محور`}
        backTo="/admin"
        right={
          <button
            type="button"
            className="btn btn-d"
            style={{ minHeight: 32, padding: '5px 10px', fontSize: 'var(--fs-cap)' }}
            onClick={() => startEdit()}
          >
            + نقش جدید
          </button>
        }
      />

      <main
        className="page fade-up"
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 'var(--sp-3)',
          paddingInline: 12,
        }}
      >
        {rolesQuery.isPending &&
          [0, 1, 2].map((key) => (
            <div
              key={key}
              className="skeleton"
              style={{ height: 86, borderRadius: 'var(--r-md)' }}
            />
          ))}

        {rolesQuery.isError && (
          <PageError
            text="نقش‌ها بارگذاری نشد"
            onRetry={() => rolesQuery.refetch()}
          />
        )}

        {roles.map((role, index) => (
          <section
            key={role.key}
            className="card pop-in"
            style={{
              padding: '11px 14px',
              animationDelay: `${Math.min(index * 30, 240)}ms`,
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--sp-3)',
              }}
            >
              <div
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: 'var(--r-md)',
                  background: `${role.color}22`,
                  color: role.color,
                  display: 'grid',
                  placeItems: 'center',
                  fontSize: 'var(--fs-xl)',
                  flexShrink: 0,
                }}
              >
                {role.icon}
              </div>

              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    flexWrap: 'wrap',
                  }}
                >
                  <b style={{ fontSize: 'var(--fs-sm)' }}>{role.label}</b>
                  {role.system ? (
                    <span className="badge b-pur" style={{ fontSize: 'var(--fs-cap)' }}>
                      🔒 سیستمی
                    </span>
                  ) : (
                    <span className="badge b-grn" style={{ fontSize: 'var(--fs-cap)' }}>
                      ✨ دلخواه
                    </span>
                  )}
                  {!role.active && (
                    <span className="badge b-red" style={{ fontSize: 'var(--fs-cap)' }}>
                      خاموش
                    </span>
                  )}
                  {!role.visible && (
                    <span className="badge b-gray" style={{ fontSize: 'var(--fs-cap)' }}>
                      مخفی
                    </span>
                  )}
                </div>

                {role.desc ? (
                  <div
                    style={{
                      color: 'var(--tx2)',
                      fontSize: 'var(--fs-cap)',
                      marginTop: 2,
                    }}
                  >
                    {role.desc}
                  </div>
                ) : null}

                <div
                  style={{
                    color: 'var(--txm)',
                    fontSize: 'var(--fs-cap)',
                    marginTop: 'var(--sp-1)',
                    display: 'flex',
                    gap: 8,
                    flexWrap: 'wrap',
                  }}
                >
                  <span>🎚 {faNum(role.perm_count)} مجوز</span>
                  <span>👥 {faNum(role.users_count)} کاربر</span>
                  <span>⏫ اولویت {faNum(role.priority)}</span>
                  <span>🗓 {faDate(role.updated_at)}</span>
                </div>
              </div>

              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 5,
                  flexShrink: 0,
                }}
              >
                <button
                  type="button"
                  className="btn btn-dark"
                  style={{ minHeight: 30, fontSize: 'var(--fs-meta)', padding: '4px 9px' }}
                  onClick={() => startEdit(role)}
                >
                  ✏️
                </button>
                <button
                  type="button"
                  className="btn btn-dark"
                  style={{
                    minHeight: 30,
                    fontSize: 'var(--fs-meta)',
                    padding: '4px 9px',
                    opacity:
                      role.system || role.users_count > 0 ? 0.35 : 1,
                  }}
                  disabled={role.system || role.users_count > 0}
                  title={
                    role.system
                      ? 'نقش سیستمی حذف‌ناپذیر است'
                      : role.users_count > 0
                        ? 'ابتدا نقش را از کاربران بگیر'
                        : 'حذف نقش'
                  }
                  onClick={async () => {
                    haptic('light');
                    const ok = await confirmAction(
                      `حذف نقش «${role.label}»؟ این کار برگشت‌ناپذیر است.`,
                    );
                    if (ok) deleteMutation.mutate(role.key);
                  }}
                >
                  🗑
                </button>
              </div>
            </div>
          </section>
        ))}
      </main>
    </>
  );
}


export default AdminRoles;
