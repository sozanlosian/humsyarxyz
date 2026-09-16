import {
  useEffect,
  useState,
} from 'react';

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import api from '../../lib/api';
import { faDateTime } from '../../lib/format';
import Header from '../../components/layout/Header';
import PageError from '../../components/shared/PageError';
import Switch from '../../components/shared/Switch';

import {
  Spinner,
} from '../../components/shared/Loading';

import {
  SettingsSkeleton,
} from '../../components/shared/skeletons';

import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';
import { confirmAction } from '../../lib/confirm';

import {
  useUIStore,
} from '../../stores/uiStore';


/* ═══════════ ردیف تنظیم ═══════════ */

function SettingRow({
  icon,
  title,
  desc,
  danger,
  checked,
  busy,
  onToggle,
}) {
  return (
    <div
      className="menu-row"
      style={{
        borderColor: danger &&
          checked
          ? 'var(--bd-err)'
          : undefined,
      }}
    >
      <span
        style={{
          display: 'grid',
          flex: '0 0 40px',
          height: 40,
          placeItems: 'center',
          borderRadius: 'var(--r-md)',
          background: danger
            ? 'var(--soft-err)'
            : 'var(--soft-acc)',
          fontSize: 'var(--fs-xl)',
        }}
      >
        {icon}
      </span>

      <span
        style={{
          flex: 1,
          minWidth: 0,
          textAlign: 'right',
        }}
      >
        <b
          style={{
            display: 'block',
            fontSize: 'var(--fs-sm)',
          }}
        >
          {title}
        </b>

        <span
          style={{
            display: 'block',
            color: 'var(--txm)',
            fontSize: 'var(--fs-cap)',
            marginTop: 2,
            lineHeight: 1.8,
          }}
        >
          {desc}
        </span>
      </span>

      {/* قبلاً هنگام ذخیره، خودِ سوییچ با یک Spinner جایگزین می‌شد:
          عرضِ ردیف می‌پرید و کاربر لحظه‌ای وضعیت را گم می‌کرد. حالا
          همان سوییچ در حالت loading می‌ماند (قفل + نبضِ ظریف) ⇒ بدون
          layout shift و بدون امکانِ دابل‌کلیک. */}
      <Switch
        on={checked}
        danger={danger}
        loading={busy}
        onToggle={onToggle}
      />
    </div>
  );
}


/* ═══════════ کارت گروه لاگ ═══════════ */

function LogGroupCard({
  icon,
  title,
  savedId,
  value,
  dirty,
  saving,
  testing,
  onChange,
  onSave,
  onTest,
}) {
  const trimmed = value.trim();
  const invalid =
    trimmed !== '' &&
    !/^-\d+$/.test(trimmed);

  return (
    <div
      className="card"
      style={{ marginBottom: 12 }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--sp-3)',
          marginBottom: 'var(--sp-3)',
        }}
      >
        <span
          style={{
            display: 'grid',
            flex: '0 0 40px',
            height: 40,
            placeItems: 'center',
            borderRadius: 'var(--r-md)',
            background:
              'var(--soft-acc)',
            fontSize: 'var(--fs-xl)',
          }}
        >
          {icon}
        </span>

        <span
          style={{
            flex: 1,
            minWidth: 0,
          }}
        >
          <b
            style={{
              display: 'block',
              fontSize: 'var(--fs-sm)',
            }}
          >
            {title}
          </b>

          <span
            style={{
              display: 'block',
              color: savedId
                ? 'var(--t-ok)'
                : 'var(--txm)',
              fontSize: 'var(--fs-cap)',
              marginTop: 2,
            }}
          >
            {savedId ? (
              <>
                تنظیم شده ✅{' '}
                <code
                  dir="ltr"
                  style={{
                    fontSize: 'var(--fs-cap)',
                  }}
                >
                  {savedId}
                </code>
              </>
            ) : (
              'تنظیم نشده — لاگ فقط در دیتابیس ذخیره می‌شود'
            )}
          </span>
        </span>
      </div>

      <input
        className="inp"
        inputMode="numeric"
        dir="ltr"
        placeholder="-1001234567890"
        value={value}
        onChange={(event) =>
          onChange(event.target.value)
        }
        style={{
          width: '100%',
          textAlign: 'left',
        }}
      />

      {invalid && (
        <span
          style={{
            display: 'block',
            color: 'var(--err)',
            fontSize: 'var(--fs-cap)',
            marginTop: 6,
          }}
        >
          آیدی گروه باید عدد منفی
          باشد (مثل -1001234567890)
        </span>
      )}

      <div
        style={{
          display: 'flex',
          gap: 8,
          marginTop: 'var(--sp-3)',
        }}
      >
        <button
          className="btn btn-p"
          style={{
            flex: 1,
            minHeight: 34,
            fontSize: 'var(--fs-cap)',
          }}
          disabled={
            !dirty || invalid || saving
          }
          onClick={onSave}
        >
          {saving ? (
            <Spinner size={14} />
          ) : (
            '💾 ذخیره'
          )}
        </button>

        <button
          className="btn btn-dark"
          style={{
            minHeight: 34,
            fontSize: 'var(--fs-cap)',
          }}
          disabled={!savedId || testing}
          onClick={onTest}
        >
          {testing ? (
            <Spinner size={14} />
          ) : (
            '🧪 تست'
          )}
        </button>
      </div>

      <span
        style={{
          display: 'block',
          color: 'var(--txm)',
          fontSize: 'var(--fs-cap)',
          marginTop: 8,
          lineHeight: 1.8,
        }}
      >
        برای حذف تنظیم، فیلد را خالی
        کن و ذخیره بزن. ربات باید عضو
        گروه باشد.
      </span>
    </div>
  );
}


/* ═══════════ کارت لینک حمایت مالی ═══════════ */

function DonationLinkCard({
  savedLink,
  enabled,
  value,
  dirty,
  saving,
  onChange,
  onSave,
}) {
  const trimmed = value.trim();
  const invalid =
    trimmed !== '' &&
    !/^https?:\/\/.+/.test(trimmed);

  return (
    <div
      className="card"
      style={{ marginBottom: 15 }}
    >
      <b
        style={{
          display: 'block',
          fontSize: 'var(--fs-sm)',
          marginBottom: 8,
        }}
      >
        🔗 لینک صفحه حمایت مالی
      </b>

      {enabled && !savedLink && (
        <div
          style={{
            marginBottom: 'var(--sp-3)',
            padding: '9px 11px',
            borderRadius: 'var(--r-sm)',
            fontSize: 'var(--fs-cap)',
            lineHeight: 1.8,
            color: 'var(--t-warn)',
            background:
              'var(--soft-warn)',
            border:
              '1px solid var(--bd-warn)',
          }}
        >
          ⚠️ بخش فعال است اما لینکی
          تنظیم نشده — تا لینک ثبت
          نشود، دکمه‌ی حمایت در
          داشبورد کاربران نمایش داده
          نمی‌شود.
        </div>
      )}

      <input
        className="inp"
        dir="ltr"
        placeholder="https://reymit.org/humsyar"
        maxLength={300}
        value={value}
        onChange={(event) =>
          onChange(event.target.value)
        }
        style={{
          width: '100%',
          textAlign: 'left',
        }}
      />

      {invalid && (
        <span
          style={{
            display: 'block',
            color: 'var(--err)',
            fontSize: 'var(--fs-cap)',
            marginTop: 6,
          }}
        >
          لینک باید با http:// یا
          https:// شروع شود
        </span>
      )}

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent:
            'space-between',
          gap: 'var(--sp-3)',
          marginTop: 'var(--sp-3)',
        }}
      >
        <span
          style={{
            color: 'var(--txm)',
            fontSize: 'var(--fs-cap)',
            lineHeight: 1.8,
            flex: 1,
          }}
        >
          {savedLink
            ? '✅ لینک فعلی ذخیره شده است'
            : 'هنوز لینکی ثبت نشده'}
          {' — '}
          خالی = حذف لینک
        </span>

        <button
          className="btn btn-p"
          style={{
            minHeight: 34,
            padding: '6px 14px',
            fontSize: 'var(--fs-cap)',
          }}
          disabled={
            !dirty || invalid || saving
          }
          onClick={onSave}
        >
          {saving ? (
            <Spinner size={14} />
          ) : (
            '💾 ذخیره'
          )}
        </button>
      </div>
    </div>
  );
}


/* ═══════════ دکمه‌های دریافت بکاپ ═══════════ */

const BACKUP_BUTTONS = [
  {
    section: 'all',
    label: '💾 پشتیبان کامل (همه بخش‌ها)',
    wide: true,
  },
  { section: 'users', label: '👥 کاربران' },
  { section: 'content', label: '📚 علوم پایه' },
  { section: 'refs', label: '📖 رفرنس‌ها' },
  { section: 'qbank', label: '🧪 بانک سوال' },
  { section: 'subscription', label: '💳 اشتراک' },
  { section: 'grades', label: '📊 نمرات' },
  { section: 'access', label: '🔐 دسترسی‌ها' },
];


/* ═══════════ صفحه اصلی ═══════════ */

export default function SystemSettings() {
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
    queryKey: ['admin-bot-settings'],

    queryFn: () =>
      api
        .get('/api/admin/settings')
        .then(
          (response) =>
            response.data
        ),

    staleTime: 15_000,
  });


  const [maintenanceText, setMaintenanceText] =
    useState('');

  const [textDirty, setTextDirty] =
    useState(false);


  /* گروه‌های لاگ — آیدی خام به‌صورت رشته
     نگه داشته می‌شود تا ورودی کنترل‌شده
     بماند و هنگام ذخیره به عدد تبدیل شود */
  const [logAdmin, setLogAdmin] =
    useState('');

  const [logContent, setLogContent] =
    useState('');

  const [logAdminDirty, setLogAdminDirty] =
    useState(false);

  const [logContentDirty, setLogContentDirty] =
    useState(false);


  /* 💙 لینک حمایت مالی */
  const [donationLink, setDonationLink] =
    useState('');

  const [donationDirty, setDonationDirty] =
    useState(false);


  /* 💾 ساعت بکاپ خودکار */
  const [backupHour, setBackupHour] =
    useState('3');

  const [backupHourDirty, setBackupHourDirty] =
    useState(false);


  /* وقتی تنظیمات لود شد، متن را هم‌گام کن
     (فقط اگر کاربر دست نزده باشد) */
  useEffect(() => {
    if (!textDirty) {
      setMaintenanceText(
        data?.maintenance_text || ''
      );
    }
  }, [
    data?.maintenance_text,
    textDirty,
  ]);


  /* هم‌گام‌سازی فیلدهای گروه لاگ با سرور —
     مثل الگوی متن تعمیر، فقط تا وقتی کاربر
     فیلد را دست نزده باشد */
  useEffect(() => {
    if (!logAdminDirty) {
      setLogAdmin(
        data?.log_group_admin
          ? String(data.log_group_admin)
          : ''
      );
    }
  }, [
    data?.log_group_admin,
    logAdminDirty,
  ]);

  useEffect(() => {
    if (!logContentDirty) {
      setLogContent(
        data?.log_group_content
          ? String(data.log_group_content)
          : ''
      );
    }
  }, [
    data?.log_group_content,
    logContentDirty,
  ]);


  /* 💙 هم‌گام‌سازی لینک حمایت مالی */
  useEffect(() => {
    if (!donationDirty) {
      setDonationLink(
        data?.donation_link || ''
      );
    }
  }, [
    data?.donation_link,
    donationDirty,
  ]);


  /* 💾 هم‌گام‌سازی ساعت بکاپ خودکار */
  useEffect(() => {
    if (!backupHourDirty) {
      setBackupHour(
        String(
          data?.auto_backup_hour ?? 3
        )
      );
    }
  }, [
    data?.auto_backup_hour,
    backupHourDirty,
  ]);


  const patchMutation = useMutation({
    mutationFn: (payload) =>
      api.patch(
        '/api/admin/settings',
        payload
      ),

    onSuccess: (_response, payload) => {
      hapticNotif('success');

      queryClient.invalidateQueries({
        queryKey: [
          'admin-bot-settings',
        ],
      });

      if (
        payload.maintenance_mode ===
        true
      ) {
        toast(
          '🔧 حالت تعمیر فعال شد — کاربران پیام تعمیر را می‌بینند',
          'warning',
          3500
        );
      } else if (
        payload.maintenance_mode ===
        false
      ) {
        toast(
          '✅ حالت تعمیر غیرفعال شد',
          'success'
        );
      } else if (
        payload.donation_enabled ===
        true
      ) {
        toast(
          '💙 بخش حمایت مالی فعال شد',
          'success'
        );
      } else if (
        payload.donation_enabled ===
        false
      ) {
        toast(
          'بخش حمایت مالی غیرفعال شد',
          'success'
        );
      } else if (
        'donation_link' in payload
      ) {
        toast(
          payload.donation_link
            ? '✅ لینک حمایت مالی ذخیره شد'
            : '🗑 لینک حمایت مالی حذف شد',
          'success'
        );
      } else if (
        payload.auto_backup_enabled ===
        true
      ) {
        toast(
          '⏰ بکاپ خودکار روزانه فعال شد',
          'success'
        );
      } else if (
        payload.auto_backup_enabled ===
        false
      ) {
        toast(
          'بکاپ خودکار غیرفعال شد',
          'success'
        );
      } else if (
        'auto_backup_hour' in payload
      ) {
        toast(
          '✅ ساعت بکاپ خودکار ذخیره شد',
          'success'
        );
      } else if (
        'log_group_admin' in payload ||
        'log_group_content' in payload
      ) {
        const removed =
          payload.log_group_admin ===
            null ||
          payload.log_group_content ===
            null;
        toast(
          removed
            ? '🗑 تنظیم گروه لاگ حذف شد'
            : '✅ گروه لاگ به‌روزرسانی شد',
          'success'
        );
      } else {
        toast(
          'تنظیمات ذخیره شد',
          'success'
        );
      }
    },

    onError: (error) => {
      toast(
        error?.response?.data
          ?.detail ||
          'ذخیره تنظیمات انجام نشد',
        'error'
      );
    },
  });


  /* تست گروه لاگ — پیام واقعی از مسیر
     کامل وب ← ربات ← گروه می‌رود */
  const testMutation = useMutation({
    mutationFn: (kind) =>
      api.post(
        '/api/admin/settings/test-log-group',
        { kind }
      ),

    onSuccess: (response) => {
      hapticNotif('success');
      toast(
        response.data?.message ||
          '🧪 پیام تست در راه است',
        'success',
        4000
      );
    },

    onError: (error) => {
      hapticNotif('error');
      toast(
        error?.response?.data
          ?.detail ||
          'ارسال پیام تست انجام نشد',
        'error'
      );
    },
  });


  /* 💾 درخواست فایل پشتیبان — فایل JSON
     با الگوی خروجی اکسل از طریق ربات به
     چت ادمین ارسال می‌شود */
  const backupMutation = useMutation({
    mutationFn: (section) =>
      api.post('/api/admin/backup', {
        section,
      }),

    onSuccess: (response) => {
      hapticNotif('success');
      toast(
        response.data?.message ||
          '💾 فایل پشتیبان در راه است',
        'success',
        4500
      );
    },

    onError: (error) => {
      hapticNotif('error');
      toast(
        error?.response?.data
          ?.detail ||
          'درخواست بکاپ انجام نشد',
        'error'
      );
    },
  });


  const busyKey =
    patchMutation.isPending
      ? patchMutation.variables
      : null;


  const toggle = (key, value) => {
    patchMutation.mutate({
      [key]: value,
    });
  };


  const saveText = () => {
    haptic('light');
    setTextDirty(false);
    patchMutation.mutate({
      maintenance_text:
        maintenanceText.trim(),
    });
  };


  /* ذخیره گروه لاگ — فیلد خالی یعنی حذف
     تنظیم (null صریح برای بک‌اند) */
  const saveLogGroup = (kind) => {
    haptic('light');

    const raw = (
      kind === 'admin'
        ? logAdmin
        : logContent
    ).trim();

    if (
      raw !== '' &&
      !/^-\d+$/.test(raw)
    ) {
      toast(
        'آیدی گروه باید عدد منفی باشد (مثل -1001234567890)',
        'error'
      );
      return;
    }

    if (kind === 'admin') {
      setLogAdminDirty(false);
    } else {
      setLogContentDirty(false);
    }

    patchMutation.mutate({
      [kind === 'admin'
        ? 'log_group_admin'
        : 'log_group_content']:
        raw === ''
          ? null
          : parseInt(raw, 10),
    });
  };


  /* 💙 ذخیره لینک حمایت — فیلد خالی یعنی
     حذف لینک (مثل کلمه «حذف» در ربات) */
  const saveDonationLink = () => {
    haptic('light');

    const trimmed = donationLink.trim();

    if (
      trimmed &&
      !/^https?:\/\//.test(trimmed)
    ) {
      toast(
        'لینک باید با http:// یا https:// شروع شود',
        'error'
      );
      return;
    }

    setDonationDirty(false);
    patchMutation.mutate({
      donation_link: trimmed,
    });
  };


  /* 💾 ذخیره ساعت بکاپ خودکار */
  const saveBackupHour = () => {
    haptic('light');

    const hour = parseInt(
      backupHour,
      10
    );

    if (
      Number.isNaN(hour) ||
      hour < 0 ||
      hour > 23
    ) {
      toast(
        'ساعت باید بین ۰ تا ۲۳ باشد',
        'error'
      );
      return;
    }

    setBackupHourDirty(false);
    patchMutation.mutate({
      auto_backup_hour: hour,
    });
  };


  const maintenanceOn = Boolean(
    data?.maintenance_mode
  );

  const donationOn = Boolean(
    data?.donation_enabled
  );


  const autoBackupLastRun = data?.auto_backup_last_run
    ? faDateTime(data.auto_backup_last_run)
    : null;


  return (
    <>
      <Header
        title="تنظیمات ربات"
        subtitle={
          'سینک کامل با پنل ربات — هر تغییر در هر دو اعمال می‌شود'
        }
      />

      <main className="page fade-up">
        {isLoading ? (
          <SettingsSkeleton />
        ) : isError ? (
          <PageError
            text="دریافت تنظیمات انجام نشد."
            onRetry={() => refetch()}
          />
        ) : (
          <>
            {maintenanceOn && (
              <div
                className="card fade-up"
                style={{
                  marginBottom: 13,
                  padding:
                    '12px 14px',
                  borderColor:
                    'var(--bd-err)',
                  background:
                    'linear-gradient(145deg,var(--soft-err),var(--surf-card))',
                }}
              >
                <b
                  style={{
                    color: 'var(--err)',
                    fontSize: 'var(--fs-sm)',
                  }}
                >
                  🔧 حالت تعمیر فعال است
                </b>

                <span
                  style={{
                    display: 'block',
                    color: 'var(--txm)',
                    fontSize: 'var(--fs-cap)',
                    marginTop: 'var(--sp-1)',
                    lineHeight: 1.8,
                  }}
                >
                  تا غیرفعال شدن، کاربران
                  فقط پیام تعمیر را در ربات
                  می‌بینند.
                </span>
              </div>
            )}

            <div className="sec-title">
              🛠 وضعیت سرویس
            </div>

            <section
              className="card card-glow"
              style={{
                padding: '0 14px',
                marginBottom: 15,
              }}
            >
              <SettingRow
                icon="🔧"
                title="حالت تعمیر"
                desc="موقتاً ربات را برای کاربران غیرفعال و متن تعمیر نمایش می‌دهد"
                danger
                checked={maintenanceOn}
                busy={
                  patchMutation.isPending &&
                  busyKey?.maintenance_mode !==
                    undefined
                }
                onToggle={(value) =>
                  toggle(
                    'maintenance_mode',
                    value
                  )
                }
              />
            </section>

            <div className="sec-title">
              📝 متن حالت تعمیر
            </div>

            <section
              className="card"
              style={{
                marginBottom: 15,
              }}
            >
              <textarea
                className="inp"
                rows={3}
                value={maintenanceText}
                maxLength={400}
                placeholder="پیام پیش‌فرض: در حال به‌روزرسانی هستیم…"
                style={{
                  width: '100%',
                  resize: 'vertical',
                  lineHeight: 1.8,
                }}
                onChange={(event) => {
                  setMaintenanceText(
                    event.target.value
                  );
                  setTextDirty(true);
                }}
              />

              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent:
                    'space-between',
                  marginTop: 'var(--sp-3)',
                }}
              >
                <span
                  style={{
                    color: 'var(--txm)',
                    fontSize: 'var(--fs-cap)',
                  }}
                >
                  خالی = متن پیش‌فرض ربات •{' '}
                  {
                    maintenanceText.length
                  }
                  /۴۰۰
                </span>

                <button
                  className="btn btn-p"
                  style={{
                    minHeight: 34,
                    padding: '6px 14px',
                    fontSize: 'var(--fs-cap)',
                  }}
                  disabled={
                    !textDirty ||
                    patchMutation.isPending
                  }
                  onClick={saveText}
                >
                  {patchMutation.isPending &&
                  busyKey?.maintenance_text !==
                    undefined ? (
                    <Spinner size={14} />
                  ) : (
                    '💾 ذخیره متن'
                  )}
                </button>
              </div>
            </section>

            <div className="sec-title">
              🎓 ثبت‌نام
            </div>

            <section
              className="card"
              style={{
                padding: '0 14px',
                marginBottom: 15,
              }}
            >
              <SettingRow
                icon="🎓"
                title="الزام شماره دانشجویی"
                desc="کاربران جدید (و قدیمی بدون شماره) باید شماره دانشجویی وارد کنند — هم‌راستا با بات"
                checked={Boolean(
                  data?.require_student_id
                )}
                busy={
                  patchMutation.isPending &&
                  busyKey?.require_student_id !==
                    undefined
                }
                onToggle={(value) =>
                  toggle(
                    'require_student_id',
                    value
                  )
                }
              />
            </section>

            <div className="sec-title">
              💙 حمایت مالی
            </div>

            <section
              className="card"
              style={{
                padding: '0 14px',
                marginBottom: 12,
              }}
            >
              <SettingRow
                icon="💙"
                title="بخش حمایت مالی"
                desc="نمایش دکمه‌ی «💙 حمایت مالی» در داشبورد و صفحه‌ی «من» — همان تاگل پنل ربات"
                checked={donationOn}
                busy={
                  patchMutation.isPending &&
                  busyKey?.donation_enabled !==
                    undefined
                }
                onToggle={(value) =>
                  toggle(
                    'donation_enabled',
                    value
                  )
                }
              />
            </section>

            <DonationLinkCard
              savedLink={
                data?.donation_link ||
                null
              }
              enabled={donationOn}
              value={donationLink}
              dirty={donationDirty}
              saving={
                patchMutation.isPending &&
                busyKey?.donation_link !==
                  undefined
              }
              onChange={(value) => {
                setDonationLink(value);
                setDonationDirty(true);
              }}
              onSave={saveDonationLink}
            />

            <div className="sec-title">
              💾 پشتیبان‌گیری
            </div>

            <section
              className="card"
              style={{
                padding: '0 14px',
                marginBottom: 12,
              }}
            >
              <SettingRow
                icon="⏰"
                title="بکاپ خودکار روزانه"
                desc={
                  <>
                    هر روز فایل کامل JSON
                    می‌سازد و در چت ربات
                    می‌فرستد
                    {autoBackupLastRun
                      ? ` • آخرین اجرا: ${autoBackupLastRun}`
                      : ' • هنوز اجرا نشده'}
                  </>
                }
                checked={Boolean(
                  data?.auto_backup_enabled
                )}
                busy={
                  patchMutation.isPending &&
                  busyKey?.auto_backup_enabled !==
                    undefined
                }
                onToggle={(value) =>
                  toggle(
                    'auto_backup_enabled',
                    value
                  )
                }
              />
            </section>

            <section
              className="card"
              style={{ marginBottom: 12 }}
            >
              <b
                style={{
                  display: 'block',
                  fontSize: 'var(--fs-sm)',
                  marginBottom: 'var(--sp-1)',
                }}
              >
                🕐 ساعت اجرای بکاپ خودکار
              </b>

              <span
                style={{
                  display: 'block',
                  color: 'var(--txm)',
                  fontSize: 'var(--fs-cap)',
                  marginBottom: 'var(--sp-3)',
                  lineHeight: 1.8,
                }}
              >
                به‌وقت تهران — مثل
                تنظیمات «⏰ بکاپ خودکار»
                در پنل ربات
              </span>

              <div
                style={{
                  display: 'flex',
                  gap: 8,
                }}
              >
                <select
                  className="inp"
                  dir="ltr"
                  value={backupHour}
                  onChange={(event) => {
                    setBackupHour(
                      event.target.value
                    );
                    setBackupHourDirty(
                      true
                    );
                  }}
                  style={{
                    flex: 1,
                    textAlign: 'left',
                  }}
                >
                  {Array.from(
                    { length: 24 },
                    (_unused, hour) => (
                      <option
                        key={hour}
                        value={String(hour)}
                      >
                        {String(
                          hour
                        ).padStart(
                          2,
                          '0'
                        )}
                        :00
                      </option>
                    )
                  )}
                </select>

                <button
                  className="btn btn-p"
                  style={{
                    minHeight: 34,
                    padding:
                      '6px 16px',
                    fontSize: 'var(--fs-cap)',
                  }}
                  disabled={
                    !backupHourDirty ||
                    patchMutation.isPending
                  }
                  onClick={saveBackupHour}
                >
                  {patchMutation.isPending &&
                  busyKey?.auto_backup_hour !==
                    undefined ? (
                    <Spinner size={14} />
                  ) : (
                    '💾 ذخیره'
                  )}
                </button>
              </div>
            </section>

            <section
              className="card"
              style={{ marginBottom: 15 }}
            >
              <b
                style={{
                  display: 'block',
                  fontSize: 'var(--fs-sm)',
                  marginBottom: 'var(--sp-1)',
                }}
              >
                📦 دریافت فایل پشتیبان
                (JSON)
              </b>

              <span
                style={{
                  display: 'block',
                  color: 'var(--txm)',
                  fontSize: 'var(--fs-cap)',
                  marginBottom: 12,
                  lineHeight: 1.8,
                }}
              >
                فایل مثل خروجی اکسل، توسط
                ربات به چت شخصی تو ارسال
                می‌شود — با همان سازنده‌ی
                مشترک منوی «💾 پشتیبان» در
                ربات.
              </span>

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns:
                    '1fr 1fr',
                  gap: 8,
                }}
              >
                {BACKUP_BUTTONS.map(
                  (button) => {
                    const pending =
                      backupMutation.isPending &&
                      backupMutation.variables ===
                        button.section;

                    return (
                      <button
                        key={button.section}
                        className="btn btn-dark"
                        style={{
                          minHeight: 36,
                          fontSize: 'var(--fs-cap)',
                          gridColumn:
                            button.wide
                              ? '1 / -1'
                              : undefined,
                        }}
                        disabled={
                          backupMutation.isPending
                        }
                        onClick={() => {
                          haptic('light');
                          backupMutation.mutate(
                            button.section
                          );
                        }}
                      >
                        {pending ? (
                          <Spinner
                            size={14}
                          />
                        ) : (
                          button.label
                        )}
                      </button>
                    );
                  }
                )}
              </div>
            </section>

            <div className="sec-title">
              🛡 گروه‌های لاگ تلگرام
            </div>

            <LogGroupCard
              icon="🛡"
              title="گروه لاگ مدیریت"
              savedId={
                data?.log_group_admin ||
                null
              }
              value={logAdmin}
              dirty={logAdminDirty}
              saving={
                patchMutation.isPending &&
                busyKey?.log_group_admin !==
                  undefined
              }
              testing={
                testMutation.isPending &&
                testMutation.variables ===
                  'admin'
              }
              onChange={(value) => {
                setLogAdmin(value);
                setLogAdminDirty(true);
              }}
              onSave={() =>
                saveLogGroup('admin')
              }
              onTest={() =>
                testMutation.mutate(
                  'admin'
                )
              }
            />

            <LogGroupCard
              icon="🎓"
              title="گروه لاگ محتوا"
              savedId={
                data?.log_group_content ||
                null
              }
              value={logContent}
              dirty={logContentDirty}
              saving={
                patchMutation.isPending &&
                busyKey?.log_group_content !==
                  undefined
              }
              testing={
                testMutation.isPending &&
                testMutation.variables ===
                  'content'
              }
              onChange={(value) => {
                setLogContent(value);
                setLogContentDirty(
                  true
                );
              }}
              onSave={() =>
                saveLogGroup('content')
              }
              onTest={() =>
                testMutation.mutate(
                  'content'
                )
              }
            />

            <div
              className="page-hint"
              style={{ marginTop: 2 }}
            >
              <span>💡</span>

              <span>
                آیدی گروه همیشه{' '}
                <b>عدد منفی</b> است. برای
                پیدا کردنش، یک پیام از
                گروه را به{' '}
                <b>@RawDataBot</b>{' '}
                فوروارد کن و مقدار{' '}
                <b>chat.id</b> را اینجا
                وارد کن. همه‌ی لاگ‌های ربات
                و پنل وب با یک قالب یکسان به
                همین گروه‌ها می‌رسند.
              </span>
            </div>

            {/* 👑 P3 — بخش تعادل زنده‌ی پرستیژ */}
            <PrestigeConfigSection />

            <div
              className="page-hint"
              style={{ marginTop: 'var(--sp-4)' }}
            >
              <span>🛡</span>

              <span>
                هر تغییر در این صفحه به‌صورت
                خودکار در{' '}
                <b>لاگ فعالیت مدیران</b> با
                سطح حساسیت مناسب (حالت تعمیر =
                بحرانی) ثبت می‌شود — قابل
                پیگیری در «لاگ فعالیت مدیران ←
                پنل مدیریت».
              </span>
            </div>
          </>
        )}
      </main>
    </>
  );
}


/* 👑 موج P3 Prestige — بخش «تعادل زنده»
   خودکفا: کوئری/استیت/موتاسیون مستقل.
   آستانه‌ی رنک‌ها عمداً اینجا نیست
   (Design Lock — فقط XP/سقف/کول‌داون/سپر). */
function PrestigeConfigSection() {
  const queryClient = useQueryClient();

  const toast = useUIStore(
    (state) => state.toast
  );

  const { data } = useQuery({
    queryKey: ['admin-prestige-config'],
    queryFn: () =>
      api
        .get('/api/admin/prestige-config')
        .then(
          (response) => response.data
        ),
    staleTime: 30_000,
  });

  const [draft, setDraft] =
    useState(null);

  const [dirty, setDirty] =
    useState(false);

  if (!data) {
    return null;
  }

  const meta = data.meta || {};

  const effective = data.effective || {};

  const overrides = data.overrides || {};

  const current =
    draft ||
    Object.fromEntries(
      Object.keys(meta).map((key) => [
        key,
        String(
          effective[key] ?? ''
        ),
      ])
    );

  const setVal = (key, value) => {
    setDirty(true);

    setDraft({
      ...current,
      [key]: value,
    });
  };

  const saveMutation = useMutation({
    mutationFn: (values) =>
      api.put(
        '/api/admin/prestige-config',
        { values }
      ),

    onSuccess: (response) => {
      const applied =
        response.data?.applied || {};

      const rejected =
        response.data?.rejected || [];

      hapticNotif('success');

      queryClient.invalidateQueries({
        queryKey: [
          'admin-prestige-config',
        ],
      });

      setDraft(null);
      setDirty(false);

      toast(
        rejected.length
          ? `ذخیره شد (${Object.keys(applied).length} مقدار) — ${rejected.length} مورد نامعتبر رد شد`
          : 'تنظیمات تعادل به‌روز شد — بدون ری‌استارت اعمال می‌شود',
        rejected.length
          ? 'warning'
          : 'success'
      );
    },

    onError: (error) =>
      toast(
        error?.response?.data?.detail ||
          'ذخیره انجام نشد',
        'error'
      ),
  });

  const submit = () => {
    const values = {};

    Object.keys(meta).forEach((key) => {
      const raw =
        current[key];

      if (
        raw === '' ||
        raw == null
      ) {
        return;
      }

      const num = Number(raw);

      if (Number.isFinite(num)) {
        values[key] = num;
      }
    });

    saveMutation.mutate(values);
  };

  const stats =
    data.challenge_stats || {};

  const groups = [
    [
      '🎯 XP پاسخ',
      [
        'xp_easy',
        'xp_medium',
        'xp_hard',
        'xp_unknown',
        'xp_wrong_first',
        'xp_streak_day',
      ],
    ],
    [
      '📝 XP آزمون و اکوسیستم',
      [
        'xp_exam_complete',
        'xp_exam_acc80',
        'xp_exam_perfect',
        'xp_file_download',
        'xp_ai_daily',
        'xp_question_approved',
        'xp_report_useful',
      ],
    ],
    [
      '🏆 جوایز رقابتی',
      [
        'xp_challenge_win',
        'xp_apex_win',
        'xp_weekly_champion',
      ],
    ],
    [
      '⚖️ قواعد تعادل',
      [
        'daily_cap',
        'diminish_after',
        'shield_answers',
        'shield_days',
        'decay_idle_days',
        'challenge_cooldown_h',
        'challenge_cooldown_apex_h',
      ],
    ],
  ];

  return (
    <>
      <div className="sec-title">
        👑 تعادل زنده‌ی پرستیژ (بدون ری‌استارت)
      </div>

      <section
        className="card"
        style={{
          display: 'grid',
          gap: 'var(--sp-3)',
        }}
      >
        <div
          style={{
            color: 'var(--txm)',
            fontSize: 'var(--fs-cap)',
            lineHeight: 1.8,
          }}
        >
          ⚔️ چالش‌های امروز:{' '}
          <b>{stats.started_today ?? 0}</b>{' '}
          شروع ·{' '}
          <b>{stats.wins_today ?? 0}</b> برد ·{' '}
          <b>{stats.fails_today ?? 0}</b>{' '}
          شکست ·{' '}
          <b>{stats.pending_now ?? 0}</b> در
          جریان
        </div>

        {groups.map(
          ([title, keys]) => (
            <div key={title}>
              <div
                style={{
                  fontSize: 'var(--fs-cap)',
                  fontWeight: 700,
                  margin:
                    '6px 0 7px',
                }}
              >
                {title}
              </div>

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns:
                    '1fr 1fr',
                  gap: 8,
                }}
              >
                {keys.map((key) => (
                  <label
                    key={key}
                    style={{
                      display: 'grid',
                      gap: 3,
                    }}
                  >
                    <span
                      style={{
                        color:
                          'var(--txm)',
                        fontSize: 'var(--fs-cap)',
                      }}
                    >
                      {meta[key]?.label ||
                        key}
                      {Object.prototype
                        .hasOwnProperty.call(
                          overrides,
                          key
                        ) && (
                        <b
                          style={{
                            color:
                              'var(--warn)',
                          }}
                        >
                          {' '}
                          (اورراید)
                        </b>
                      )}
                    </span>

                    <input
                      type="number"
                      className="input"
                      value={
                        current[key] ??
                        ''
                      }
                      min={meta[key]?.min}
                      max={meta[key]?.max}
                      onChange={(e) =>
                        setVal(
                          key,
                          e.target.value
                        )
                      }
                      style={{
                        fontSize: 'var(--fs-sm)',
                        padding:
                          '6px 9px',
                      }}
                    />
                  </label>
                ))}
              </div>
            </div>
          )
        )}

        <div
          style={{
            display: 'flex',
            gap: 8,
          }}
        >
          <button
            type="button"
            className="btn btn-p"
            style={{ flex: 1 }}
            disabled={
              !dirty ||
              saveMutation.isPending
            }
            onClick={submit}
          >
            {saveMutation.isPending
              ? 'در حال ذخیره…'
              : '💾 ذخیره‌ی تنظیمات تعادل'}
          </button>

          <button
            type="button"
            className="btn btn-g"
            disabled={
              saveMutation.isPending
            }
            onClick={async () => {
              const ok = await confirmAction(
                'همه‌ی اوررایدها پاک و مقادیر پیش‌فرض برگردد؟',
              );
              if (ok) saveMutation.mutate({});
            }}
          >
            ↺ پیش‌فرض
          </button>
        </div>

        <div
          style={{
            color: 'var(--txm)',
            fontSize: 'var(--fs-cap)',
          }}
        >
          آستانه‌ی رنک‌ها (۳۰۰/۷۵۰/…) مطابق
          سند طراحی قفل‌است و از پنل قابل
          تغییر نیست.
        </div>
      </section>
    </>
  );
}
