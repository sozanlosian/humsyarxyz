import { confirmAction } from '../../lib/confirm';
import { faDate, faTime } from '../../lib/format';
import { useState } from 'react';
import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import api from '../../lib/api';
import Header from '../../components/layout/Header';
import PageError from '../../components/shared/PageError';
import EmptyState from '../../components/shared/EmptyState';
import {
  Spinner,
} from '../../components/shared/Loading';

import {
  ScheduleAdminSkeleton,
} from '../../components/shared/skeletons';
import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';
import { useUIStore } from '../../stores/uiStore';

const TYPES = [
  ['class', '🏫 کلاس'],
  ['exam', '📝 امتحان'],
  ['makeup', '🔄 جبرانی'],
];

const EMPTY_FORM = {
  type: 'class',
  lesson: '',
  teacher: '',
  date: '',
  time: '',
  end_time: '',
  group: 'هر دو',
  location: '',
  note: '',
  flex_type: 'fixed',
};

const apiError = (
  error,
  fallback
) => {
  const detail =
    error?.response?.data?.detail;

  return typeof detail === 'string'
    ? detail
    : fallback;
};

export default function AcademicScheduleAdmin() {
  const [tab, setTab] =
    useState('class');

  const [formOpen, setFormOpen] =
    useState(false);

  const [editingId, setEditingId] =
    useState(null);

  const [form, setForm] =
    useState(EMPTY_FORM);

  const [
    flexTarget,
    setFlexTarget,
  ] = useState(null);

  const [
    flexForm,
    setFlexForm,
  ] = useState({
    date: '',
    time: '',
    end_time: '',
    note: '',
  });

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();

  const {
    data,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: [
      'academic-schedule',
      tab,
    ],

    queryFn: () =>
      api
        .get(
          '/api/academic-admin/schedule',
          {
            params: {
              stype: tab,
            },
          }
        )
        .then(
          (response) => response.data
        ),
  });

  const refresh = () =>
    queryClient.invalidateQueries({
      queryKey: [
        'academic-schedule',
      ],
    });

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = {
        ...form,
        type: form.type || tab,
      };

      if (editingId) {
        const {
          type,
          ...updatePayload
        } = payload;

        return api.patch(
          `/api/academic-admin/schedule/${editingId}`,
          updatePayload
        );
      }

      return api.post(
        '/api/academic-admin/schedule',
        payload
      );
    },

    onSuccess: async () => {
      hapticNotif('success');

      toast(
        editingId
          ? 'برنامه ویرایش شد ✅'
          : 'برنامه ثبت شد ✅',
        'success'
      );

      setFormOpen(false);
      setEditingId(null);
      setForm(EMPTY_FORM);

      await refresh();
    },

    onError: (error) => {
      hapticNotif('error');

      toast(
        apiError(
          error,
          'ذخیره برنامه انجام نشد'
        ),
        'error'
      );
    },
  });

  const deleteMutation =
    useMutation({
      mutationFn: (id) =>
        api.delete(
          `/api/academic-admin/schedule/${id}`
        ),

      onSuccess: async () => {
        toast(
          'برنامه حذف شد',
          'info'
        );

        await refresh();
      },

      onError: (error) =>
        toast(
          apiError(
            error,
            'حذف انجام نشد'
          ),
          'error'
        ),
    });

  const flexMutation = useMutation({
    mutationFn: () =>
      api.post(
        `/api/academic-admin/schedule/${flexTarget.id}/flex-change`,
        flexForm
      ),

    onSuccess: async (
      response
    ) => {
      hapticNotif('success');

      toast(
        `زمان تغییر کرد؛ ${
          response.data?.notified || 0
        } اعلان ثبت شد ✅`,
        'success'
      );

      setFlexTarget(null);

      setFlexForm({
        date: '',
        time: '',
        end_time: '',
        note: '',
      });

      await refresh();
    },

    onError: (error) =>
      toast(
        apiError(
          error,
          'تغییر زمان انجام نشد'
        ),
        'error'
      ),
  });

  const items = Array.isArray(
    data?.schedule
  )
    ? data.schedule
    : [];

  const startCreate = () => {
    haptic();

    setEditingId(null);

    setForm({
      ...EMPTY_FORM,
      type: tab,
    });

    setFormOpen(true);
  };

  const startEdit = (item) => {
    haptic();

    setEditingId(item.id);

    setForm({
      type: item.type || tab,
      lesson: item.lesson || '',
      teacher: item.teacher || '',
      date: item.date || '',
      time: item.time || '',
      end_time: item.end_time || item.time_end || '',

      group: [
        '1',
        '2',
        'هر دو',
      ].includes(item.group)
        ? item.group
        : 'هر دو',

      location: item.location || '',
      note: item.note || '',

      flex_type:
        item.flex_type === 'flexible'
          ? 'flexible'
          : 'fixed',
    });

    setFormOpen(true);
  };

  const validForm =
    form.lesson.trim().length >= 2 &&
    /^\d{4}-\d{2}-\d{2}$/.test(
      form.date
    );

  if (formOpen) {
    return (
      <>
        <Header
          title={
            editingId
              ? '✏️ ویرایش برنامه'
              : '➕ برنامه جدید'
          }
          onBack={() =>
            setFormOpen(false)
          }
        />

        <div className="page fade-up">
          <div
            className="card card-glow"
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 'var(--sp-3)',
            }}
          >
            <label className="fld-label">
              نوع برنامه
            </label>

            <select
              className="inp"
              value={form.type}
              disabled={
                Boolean(editingId)
              }
              onChange={(event) =>
                setForm({
                  ...form,
                  type:
                    event.target.value,
                })
              }
            >
              {TYPES.map(
                ([value, label]) => (
                  <option
                    key={value}
                    value={value}
                  >
                    {label}
                  </option>
                )
              )}
            </select>

            <label className="fld-label">
              نام درس *
            </label>

            <input
              className="inp"
              value={form.lesson}
              maxLength={100}
              onChange={(event) =>
                setForm({
                  ...form,
                  lesson:
                    event.target.value,
                })
              }
              placeholder="مثلاً فیزیولوژی"
            />

            <label className="fld-label">
              نام استاد
            </label>

            <input
              className="inp"
              value={form.teacher}
              maxLength={100}
              onChange={(event) =>
                setForm({
                  ...form,
                  teacher:
                    event.target.value,
                })
              }
              placeholder="نام استاد"
            />

            <div className="grid2" style={{ gridTemplateColumns: '1fr auto auto' }}>
              <input
                className="inp"
                type="date"
                value={form.date}
                onChange={(event) =>
                  setForm({
                    ...form,
                    date:
                      event.target.value,
                  })
                }
              />

              <input
                className="inp"
                type="time"
                value={form.time}
                onChange={(event) => {
                  const v = event.target.value;
                  const synth = {"08:00":"10:00","10:00":"12:00","13:00":"15:00","15:00":"17:00","17:00":"19:00"};
                  setForm({
                    ...form,
                    time: v,
                    end_time: form.end_time || synth[v] || form.end_time,
                  });
                }}
                title="شروع"
              />
              <input
                className="inp"
                type="time"
                value={form.end_time}
                onChange={(event) =>
                  setForm({
                    ...form,
                    end_time:
                      event.target.value,
                  })
                }
                title="پایان"
              />
            </div>
            {form.time && form.end_time && (
              <div className="muted" style={{ fontSize: 'var(--fs-cap)' }}>
                ⏰ {faTime(form.time)} تا {faTime(form.end_time)}
              </div>
            )}

            <div className="grid2">
              <select
                className="inp"
                value={form.group}
                onChange={(event) =>
                  setForm({
                    ...form,
                    group:
                      event.target.value,
                  })
                }
              >
                <option value="هر دو">
                  هر دو گروه
                </option>

                <option value="1">
                  گروه ۱
                </option>

                <option value="2">
                  گروه ۲
                </option>
              </select>

              <select
                className="inp"
                value={form.flex_type}
                onChange={(event) =>
                  setForm({
                    ...form,
                    flex_type:
                      event.target.value,
                  })
                }
              >
                <option value="fixed">
                  ثابت
                </option>

                <option value="flexible">
                  منعطف
                </option>
              </select>
            </div>

            <input
              className="inp"
              value={form.location}
              maxLength={100}
              onChange={(event) =>
                setForm({
                  ...form,
                  location:
                    event.target.value,
                })
              }
              placeholder="محل برگزاری"
            />

            <textarea
              className="inp"
              rows={3}
              maxLength={500}
              value={form.note}
              onChange={(event) =>
                setForm({
                  ...form,
                  note:
                    event.target.value,
                })
              }
              placeholder="توضیحات اختیاری"
            />
          </div>

          <button
            className="btn btn-p btn-full"
            style={{
              marginTop: 'var(--sp-4)',
            }}
            disabled={
              !validForm ||
              saveMutation.isPending
            }
            onClick={() =>
              saveMutation.mutate()
            }
          >
            {saveMutation.isPending
              ? <Spinner size={16} />
              : '💾 ذخیره برنامه'}
          </button>
        </div>
      </>
    );
  }

  return (
    <>
      <Header
        title="📅 مدیریت برنامه"
        subtitle={`${items.length} مورد`}
      />

      <div className="page fade-up">
        <div
          className="tab-bar"
          style={{
            marginBottom: 12,
          }}
        >
          {TYPES.map(
            ([value, label]) => (
              <button
                key={value}
                className="tab-btn"
                onClick={() => {
                  haptic();
                  setTab(value);
                }}
                style={{
                  background:
                    tab === value
                      ? 'var(--acc)'
                      : 'transparent',

                  color:
                    tab === value
                      ? 'var(--t-white)'
                      : 'var(--tx2)',
                }}
              >
                {label}
              </button>
            )
          )}
        </div>

        <button
          className="btn btn-p btn-full"
          style={{
            marginBottom: 'var(--sp-4)',
          }}
          onClick={startCreate}
        >
          + افزودن برنامه
        </button>

        {isLoading ? (
          <ScheduleAdminSkeleton />
        ) : isError ? (
          <PageError
            text="دریافت برنامه‌ها انجام نشد."
            onRetry={() => refetch()}
          />
        ) : items.length === 0 ? (
          <EmptyState icon="📭">
            موردی ثبت نشده است.
          </EmptyState>
        ) : (
          items.map((item) => (
            <div
              key={item.id}
              className="card"
              style={{
                marginBottom: 9,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent:
                    'space-between',
                  gap: 'var(--sp-3)',
                }}
              >
                <div style={{ flex: 1 }}>
                  <div
                    style={{
                      fontWeight: 700,
                    }}
                  >
                    {item.lesson ||
                      'بدون عنوان'}
                  </div>

                  <div
                    style={{
                      fontSize: 'var(--fs-meta)',
                      color: 'var(--txm)',
                      marginTop: 3,
                    }}
                  >
                    {item.date ? faDate(item.date) : '—'}

                    {item.time
                      ? ` • ${faTime(item.time)}${(item.end_time||item.time_end)?` تا ${faTime(item.end_time||item.time_end)}`:''}`
                      : ''}

                    {' • '}

                    {item.group === 'هر دو'
                      ? 'هر دو گروه'
                      : `گروه ${item.group}`}
                  </div>

                  {item.teacher && (
                    <div>
                      استاد: {item.teacher}
                    </div>
                  )}

                  {item.location && (
                    <div>
                      📍 {item.location}
                    </div>
                  )}

                  {item.note && (
                    <div>
                      📝 {item.note}
                    </div>
                  )}
                </div>

                <span
                  className={`badge ${
                    item.flex_type ===
                    'flexible'
                      ? 'b-yel'
                      : 'b-gray'
                  }`}
                >
                  {item.flex_type ===
                  'flexible'
                    ? 'منعطف'
                    : 'ثابت'}
                </span>
              </div>

              <div
                style={{
                  display: 'flex',
                  gap: 'var(--sp-2)',
                  marginTop: 11,
                }}
              >
                <button
                  className="btn btn-dark"
                  style={{ flex: 1 }}
                  onClick={() =>
                    startEdit(item)
                  }
                >
                  ✏️ ویرایش
                </button>

                {item.flex_type ===
                  'flexible' && (
                  <button
                    className="btn btn-p"
                    style={{ flex: 1 }}
                    onClick={() => {
                      setFlexTarget(item);

                      setFlexForm({
                        date:
                          item.date || '',
                        time:
                          item.time || '',
                        end_time:
                          item.end_time || item.time_end || '',
                        note:
                          item.flex_note ||
                          '',
                      });
                    }}
                  >
                    🔄 تغییر زمان
                  </button>
                )}

                <button
                  className="btn btn-d"
                  style={{ flex: 1 }}
                  onClick={async () => {
                    if (
                      await confirmAction(
                        'این برنامه حذف شود؟'
                      )
                    ) {
                      deleteMutation.mutate(
                        item.id
                      );
                    }
                  }}
                >
                  🗑 حذف
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {flexTarget && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 300,
            background:
              'var(--scrim-strong)',
            display: 'flex',
            alignItems: 'flex-end',
          }}
          onClick={() =>
            setFlexTarget(null)
          }
        >
          <div
            className="card fade-up"
            style={{
              width: '100%',
              margin: 0,
              borderRadius:
                '20px 20px 0 0',
            }}
            onClick={(event) =>
              event.stopPropagation()
            }
          >
            <div className="sec-title">
              تغییر زمان
            </div>

            <input
              className="inp"
              type="date"
              value={flexForm.date}
              onChange={(event) =>
                setFlexForm({
                  ...flexForm,
                  date:
                    event.target.value,
                })
              }
            />

            <div style={{ display:'flex', gap: 8 }}>
            <input
              className="inp"
              type="time"
              value={flexForm.time}
              onChange={(event) =>
                setFlexForm({
                  ...flexForm,
                  time:
                    event.target.value,
                })
              }
              title="شروع"
            />
            <input
              className="inp"
              type="time"
              value={flexForm.end_time}
              onChange={(event) =>
                setFlexForm({
                  ...flexForm,
                  end_time:
                    event.target.value,
                })
              }
              title="پایان"
            />
            </div>

            <textarea
              className="inp"
              value={flexForm.note}
              onChange={(event) =>
                setFlexForm({
                  ...flexForm,
                  note:
                    event.target.value,
                })
              }
              placeholder="توضیح تغییر"
            />

            <button
              className="btn btn-p btn-full"
              disabled={
                !flexForm.date ||
                !flexForm.time ||
                flexMutation.isPending
              }
              onClick={() =>
                flexMutation.mutate()
              }
            >
              ثبت و ارسال اعلان
            </button>
          </div>
        </div>
      )}
    </>
  );
}
