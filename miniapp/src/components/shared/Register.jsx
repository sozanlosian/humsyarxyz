import {
  useEffect,
  useMemo,
  useState,
} from 'react';

import {
  useMutation,
  useQuery,
} from '@tanstack/react-query';

import api from '../../lib/api';

import {
  tg,
  haptic,
  hapticNotif,
  getStartParam,
} from '../../lib/telegram';

import {
  hideBackButton,
} from '../../lib/backButton';

import {
  useAuthStore,
} from '../../stores/authStore';

import {
  Spinner,
} from './Loading';


/* ═══════════ قاب ثابت صفحه ═══════════ */

function Screen({
  glow,
  children,
}) {
  /* روی صفحات فول‌اسکرین احراز، دکمه
     بک نیتیو تلگرام نباید گیر کند */
  useEffect(() => {
    try {
      hideBackButton();
    } catch (_) {
      /* نسخه قدیمی */
    }
  }, []);

  return (
    <main
      dir="rtl"
      style={{
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: '100%',
        minHeight: '100dvh',
        padding: '24px 16px',
        overflow: 'hidden',
        color: 'var(--tx)',

        /* شفاف — لایه‌ی fixed مشترک body؛
           بدون پرش نور هنگام ورود/خروج ویزارد */
        background: 'transparent',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: '10%',
          width: 250,
          height: 250,
          borderRadius: '50%',
          background: glow,
          filter: 'blur(55px)',
        }}
      />

      <section
        className="card card-glow fade-up"
        style={{
          position: 'relative',
          width: '100%',
          maxWidth: 390,
          padding: 22,
        }}
      >
        {children}
      </section>
    </main>
  );
}


/* ═══════════ کارت انتخابی ═══════════ */

function ChoiceCard({
  icon,
  title,
  desc,
  selected,
  onClick,
}) {
  return (
    <button
      type="button"
      className="choice-card"
      aria-pressed={selected}
      onClick={() => {
        haptic('light');
        onClick();
      }}
    >
      <span className="choice-card__check">
        {selected ? '✓' : ''}
      </span>

      <span className="choice-card__icon">
        {icon}
      </span>

      <span className="choice-card__text">
        <b>{title}</b>

        {desc && (
          <span>{desc}</span>
        )}
      </span>
    </button>
  );
}


/* ═══════════ نوار پیشرفت مراحل ═══════════ */

function Steps({
  total,
  current,
}) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        gap: 6,
        marginBottom: 16,
      }}
    >
      {Array.from(
        { length: total },
        (_, index) => (
          <span
            key={index}
            className={`step-dot ${
              index < current
                ? 'step-dot--done'
                : index === current
                  ? 'step-dot--now'
                  : ''
            }`}
          />
        )
      )}
    </div>
  );
}


/* ═══════════ صفحه «در انتظار تأیید» ═══════════ */

function PendingScreen({
  name,
  onClose,
}) {
  return (
    <Screen glow="var(--soft-warn-2)">
      <div
        style={{ textAlign: 'center' }}
      >
        <div
          className="pulse-ring"
          style={{
            display: 'grid',
            width: 72,
            height: 72,
            placeItems: 'center',
            margin: '0 auto',
            background:
              'var(--soft-warn-2)',
            border:
              '1px solid var(--bd-warn)',
            borderRadius: 'var(--r-xl)',
            fontSize: 35,
          }}
        >
          ⏳
        </div>

        <h1
          style={{
            marginTop: 16,
            fontSize: 'var(--fs-xl)',
            fontWeight: 900,
          }}
        >
          ثبت‌نام ثبت شد! 🎉
        </h1>

        <p
          style={{
            marginTop: 8,
            color: 'var(--tx2)',
            fontSize: 'var(--fs-meta)',
            lineHeight: 1.9,
          }}
        >
          {name ? (
            <>
              <b>{name}</b> عزیز،
              درخواستت برای مدیریت
              ارسال شد.
              <br />
            </>
          ) : (
            'درخواستت برای مدیریت ارسال شد.'
          )}
          به محض تأیید،{' '}
          <b>همین صفحه خودکار</b>{' '}
          وارد حسابت می‌شود — لازم
          نیست چیزی ببندی! ✨
        </p>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 'var(--sp-2)',
            marginTop: 13,
            padding: '9px 11px',
            borderRadius: 'var(--r-md)',
            background:
              'var(--soft-mut)',
            color: 'var(--tx2)',
            fontSize: 'var(--fs-cap)',
          }}
        >
          <Spinner size={13} />
          در حال بررسی زنده وضعیت
          تأیید…
        </div>

        <button
          type="button"
          className="btn btn-dark btn-full"
          style={{ marginTop: 16 }}
          onClick={onClose}
        >
          بازگشت به تلگرام
        </button>
      </div>
    </Screen>
  );
}


/* ═══════════ صفحه مسدود ═══════════ */

function BlockedScreen({
  onClose,
}) {
  return (
    <Screen glow="var(--soft-err-2)">
      <div
        style={{ textAlign: 'center' }}
      >
        <div
          style={{
            display: 'grid',
            width: 72,
            height: 72,
            placeItems: 'center',
            margin: '0 auto',
            background:
              'var(--soft-err-2)',
            border:
              '1px solid var(--bd-err)',
            borderRadius: 'var(--r-xl)',
            fontSize: 35,
          }}
        >
          🚫
        </div>

        <h1
          style={{
            marginTop: 16,
            fontSize: 'var(--fs-xl)',
            fontWeight: 900,
          }}
        >
          دسترسی مسدود است
        </h1>

        <p
          style={{
            marginTop: 8,
            color: 'var(--tx2)',
            fontSize: 'var(--fs-meta)',
            lineHeight: 1.9,
          }}
        >
          حساب شما توسط مدیریت مسدود
          شده و امکان ثبت‌نام مجدد
          وجود ندارد. در صورت اعتراض،
          از طریق راه‌های ارتباطی با
          مدیریت در تماس باشید.
        </p>

        <button
          type="button"
          className="btn btn-dark btn-full"
          style={{ marginTop: 16 }}
          onClick={onClose}
        >
          بازگشت به تلگرام
        </button>
      </div>
    </Screen>
  );
}


/* ═══════════ ویزارد اصلی ═══════════ */

export default function Register() {
  const init = useAuthStore(
    (state) => state.init
  );

  const tgUser = useAuthStore(
    (state) => state.tgUser
  );


  /* وضعیت زنده ثبت‌نام — پولینگ هر ۱۰ ثانیه */
  const {
    data: status,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['reg-status'],

    queryFn: () =>
      api
        .get('/api/auth/status')
        .then(
          (response) =>
            response.data
        ),

    refetchInterval: 10_000,
    staleTime: 5_000,
  });


  /* اگر مدیر تأیید کرد → ورود خودکار */
  useEffect(() => {
    if (status?.state === 'approved') {
      hapticNotif('success');
      init();
    }
  }, [status?.state, init]);


  /* مراحل پویا — مثل بات: ورودی و
     شماره دانشجویی فقط وقتی لازم‌اند */
  const steps = useMemo(() => {
    const list = ['name', 'group'];

    if (status?.intakes?.length) {
      list.push('intake');
    }

    if (status?.require_student_id) {
      list.push('student_id');
    }

    return list;
  }, [status]);


  const [stepIndex, setStepIndex] =
    useState(0);

  const [name, setName] = useState('');

  const [group, setGroup] =
    useState('');

  const [intake, setIntake] =
    useState('');

  const [studentId, setStudentId] =
    useState('');

  const [fieldError, setFieldError] =
    useState('');

  const [done, setDone] =
    useState(false);


  /* پیش‌پرکردن نام از پروفایل تلگرام */
  useEffect(() => {
    if (name) return;

    const full = [
      tgUser?.first_name,
      tgUser?.last_name,
    ]
      .filter(Boolean)
      .join(' ')
      .trim();

    if (full.length >= 3) {
      setName(full);
    }
    // eslint-disable-next-line
  }, [tgUser]);


  const currentStep =
    steps[stepIndex] || 'name';


  const close = () => {
    haptic('light');

    try {
      tg?.close?.();
    } catch (_) {
      window.history.back();
    }
  };

  const goPrev = () => {
    haptic('light');
    setFieldError('');
    setStepIndex((index) =>
      Math.max(0, index - 1)
    );
  };

  const goNext = () => {
    haptic('light');
    setFieldError('');

    if (currentStep === 'name') {
      const trimmed = name.trim();

      if (trimmed.length < 3) {
        return setFieldError(
          'نام باید حداقل ۳ حرف باشد'
        );
      }

      if (trimmed.length > 50) {
        return setFieldError(
          'نام نباید بیشتر از ۵۰ حرف باشد'
        );
      }
    }

    setStepIndex((index) =>
      Math.min(
        steps.length - 1,
        index + 1
      )
    );

    return undefined;
  };


  const registerMutation =
    useMutation({
      mutationFn: () =>
        api.post(
          '/api/auth/register',
          {
            name: name.trim(),
            group,
            intake,
            student_id:
              studentId.trim(),
            // 🌱 W13 — کد دعوت از دیپ‌لینک (اختیاری)
            ref:
              getStartParam() || '',
          }
        ),

      onSuccess: (response) => {
        hapticNotif('success');

        if (
          response.data?.state ===
          'approved'
        ) {
          init();
        } else {
          setDone(true);
          refetch();
        }
      },

      onError: (error) => {
        hapticNotif('error');

        const detail =
          error.response?.data
            ?.detail;

        if (
          detail ===
            'already_pending' ||
          detail ===
            'already_registered'
        ) {
          setDone(
            detail ===
              'already_pending'
          );
          refetch();

          if (
            detail ===
            'already_registered'
          ) {
            init();
          }
          return;
        }

        setFieldError(
          typeof detail ===
            'string' &&
            detail.length < 90
            ? detail
            : 'ثبت‌نام انجام نشد — دوباره تلاش کنید'
        );
      },
    });


  const submit = () => {
    const trimmed = studentId.trim();

    if (
      status?.require_student_id &&
      !(
        trimmed.length >= 5 &&
        trimmed.length <= 30
      )
    ) {
      hapticNotif('error');

      return setFieldError(
        'شماره دانشجویی باید بین ۵ تا ۳۰ کاراکتر باشد'
      );
    }

    setFieldError('');
    registerMutation.mutate();

    return undefined;
  };


  /* ── رندر وضعیت‌ها ── */

  if (isLoading) {
    return (
      <Screen glow="var(--soft-acc-2)">
        <div
          style={{
            display: 'grid',
            placeItems: 'center',
            gap: 'var(--sp-3)',
            padding: '26px 0',
            textAlign: 'center',
          }}
        >
          <Spinner size={26} />

          <span
            style={{
              color: 'var(--txm)',
              fontSize: 'var(--fs-meta)',
            }}
          >
            در حال آماده‌سازی فرم
            ثبت‌نام…
          </span>
        </div>
      </Screen>
    );
  }


  if (isError) {
    return (
      <Screen glow="var(--soft-info)">
        <div
          style={{ textAlign: 'center' }}
        >
          <div
            style={{ fontSize: 40 }}
          >
            🌐
          </div>

          <h1
            style={{
              marginTop: 12,
              fontSize: 'var(--fs-xl)',
              fontWeight: 900,
            }}
          >
            ارتباط برقرار نشد
          </h1>

          <p
            style={{
              marginTop: 8,
              color: 'var(--tx2)',
              fontSize: 'var(--fs-meta)',
            }}
          >
            اینترنت خود را بررسی
            کنید و دوباره تلاش کنید.
          </p>

          <button
            type="button"
            className="btn btn-p btn-full"
            style={{ marginTop: 16 }}
            onClick={() => refetch()}
          >
            ↻ تلاش دوباره
          </button>
        </div>
      </Screen>
    );
  }


  if (
    status?.state === 'blacklisted'
  ) {
    return (
      <BlockedScreen
        onClose={close}
      />
    );
  }


  if (
    done ||
    status?.state === 'pending'
  ) {
    return (
      <PendingScreen
        name={
          name.trim() ||
          status?.user?.name ||
          ''
        }
        onClose={close}
      />
    );
  }


  if (status?.state === 'suspended') {
    return (
      <BlockedScreen
        onClose={close}
      />
    );
  }


  /* ── خود ویزارد ── */

  const stepConfig = {
    name: {
      title: 'نام و نام خانوادگی',
      hint: 'نام کامل خود را بنویسید — مثلاً: علی احمدی',
    },

    group: {
      title: 'گروه درسی',
      hint: 'گروه کلاسی خود را انتخاب کنید',
    },

    intake: {
      title: 'ورودی تحصیلی',
      hint: 'سال ورود خود به دانشکده را انتخاب کنید',
    },

    student_id: {
      title: 'شماره دانشجویی',
      hint: 'این فیلد برای تکمیل ثبت‌نام الزامی است',
    },
  }[currentStep];


  const isLast =
    stepIndex ===
    steps.length - 1;

  const canContinue =
    currentStep === 'name'
      ? name.trim().length >= 3
      : currentStep === 'group'
        ? Boolean(group)
        : currentStep === 'intake'
          ? Boolean(intake)
          : studentId.trim().length >= 5;


  return (
    <Screen glow="var(--soft-acc-2)">
      <Steps
        total={steps.length}
        current={stepIndex}
      />

      <div
        style={{ textAlign: 'center' }}
      >
        <span className="badge b-acc">
          {isLast
            ? 'مرحلهٔ نهایی'
            : `مرحلهٔ ${stepIndex + 1}`}{' '}
          از {steps.length}
        </span>

        <h1
          style={{
            marginTop: 9,
            fontSize: 'var(--fs-xl)',
            fontWeight: 900,
          }}
        >
          🩺 ثبت‌نام در هامزیار
        </h1>

        <div
          style={{
            marginTop: 'var(--sp-2)',
            color: 'var(--acc2)',
            fontSize: 'var(--fs-sm)',
            fontWeight: 800,
          }}
        >
          {stepConfig.title}
        </div>

        <p
          style={{
            marginTop: 'var(--sp-1)',
            color: 'var(--txm)',
            fontSize: 'var(--fs-cap)',
          }}
        >
          {stepConfig.hint}
        </p>
      </div>


      <div style={{ marginTop: 17 }}>
        {/* ── مرحله نام ── */}
        {currentStep === 'name' && (
          <input
            className="inp"
            value={name}
            autoFocus
            maxLength={50}
            placeholder="نام و نام خانوادگی…"
            style={{
              textAlign: 'center',
              fontSize: 'var(--fs-md)',
            }}
            onChange={(event) => {
              setName(
                event.target.value
              );
              setFieldError('');
            }}
            onKeyDown={(event) => {
              if (
                event.key ===
                  'Enter' &&
                canContinue
              ) {
                goNext();
              }
            }}
          />
        )}

        {/* ── مرحله گروه ── */}
        {currentStep === 'group' && (
          <div className="choice-grid">
            <ChoiceCard
              icon="1️⃣"
              title="گروه ۱"
              desc="کلاس‌های گروه یک"
              selected={group === '1'}
              onClick={() =>
                setGroup('1')
              }
            />

            <ChoiceCard
              icon="2️⃣"
              title="گروه ۲"
              desc="کلاس‌های گروه دو"
              selected={group === '2'}
              onClick={() =>
                setGroup('2')
              }
            />
          </div>
        )}

        {/* ── مرحله ورودی ── */}
        {currentStep ===
          'intake' && (
          <div
            className="choice-grid"
            style={{
              gridTemplateColumns:
                '1fr',
              maxHeight: 230,
              overflowY: 'auto',
            }}
          >
            {status?.intakes?.map(
              (item) => (
                <ChoiceCard
                  key={item.code}
                  icon="📅"
                  title={item.label}
                  selected={
                    intake ===
                    item.code
                  }
                  onClick={() =>
                    setIntake(
                      item.code
                    )
                  }
                />
              )
            )}
          </div>
        )}

        {/* ── مرحله شماره دانشجویی ── */}
        {currentStep ===
          'student_id' && (
          <input
            className="inp"
            value={studentId}
            autoFocus
            maxLength={30}
            inputMode="numeric"
            placeholder="مثلاً ۴۰۱۲۳۴۵۶۷"
            style={{
              textAlign: 'center',
              fontSize: 'var(--fs-md)',
              letterSpacing: 1,
            }}
            onChange={(event) => {
              setStudentId(
                event.target.value
              );
              setFieldError('');
            }}
            onKeyDown={(event) => {
              if (
                event.key ===
                  'Enter' &&
                canContinue &&
                !registerMutation.isPending
              ) {
                submit();
              }
            }}
          />
        )}


        {/* خطای فیلد */}
        {fieldError && (
          <div
            className="fade-up"
            style={{
              marginTop: 9,
              padding: '7px 10px',
              borderRadius: 'var(--r-sm)',
              background:
                'var(--soft-err)',
              color: 'var(--err)',
              fontSize: 'var(--fs-cap)',
              textAlign: 'center',
            }}
          >
            ⚠️ {fieldError}
          </div>
        )}


        {/* خلاصه انتخاب‌ها در مرحله آخر */}
        {isLast &&
          steps.length > 2 && (
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                justifyContent:
                  'center',
                gap: 5,
                marginTop: 11,
              }}
            >
              <span className="badge b-gray">
                👤 {name.trim()}
              </span>

              <span className="badge b-gray">
                👥 گروه {group}
              </span>

              {intake && (
                <span className="badge b-gray">
                  📅{' '}
                  {status?.intakes?.find(
                    (item) =>
                      item.code ===
                      intake
                  )?.label || intake}
                </span>
              )}
            </div>
          )}
      </div>


      {/* دکمه‌ها */}
      <div
        style={{
          display: 'flex',
          gap: 8,
          marginTop: 18,
        }}
      >
        {stepIndex > 0 ? (
          <button
            type="button"
            className="btn btn-dark"
            style={{ flex: '0 0 92px' }}
            onClick={goPrev}
          >
            → قبلی
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-dark"
            style={{ flex: '0 0 92px' }}
            onClick={close}
          >
            انصراف
          </button>
        )}

        <button
          type="button"
          className="btn btn-p"
          style={{ flex: 1 }}
          disabled={
            !canContinue ||
            registerMutation.isPending
          }
          onClick={
            isLast ? submit : goNext
          }
        >
          {registerMutation.isPending ? (
            <Spinner size={15} />
          ) : isLast ? (
            '✅ تکمیل ثبت‌نام'
          ) : (
            'مرحله بعد ←'
          )}
        </button>
      </div>


      <div
        style={{
          marginTop: 'var(--sp-4)',
          color: 'var(--txm)',
          fontSize: 'var(--fs-cap)',
          textAlign: 'center',
          lineHeight: 1.8,
        }}
      >
        ثبت‌نام از مینی‌اپ و ربات
        کاملاً هم‌گام است — بعد از
        تأیید مدیریت به هر دو دسترسی
        خواهی داشت.
      </div>
    </Screen>
  );
}
