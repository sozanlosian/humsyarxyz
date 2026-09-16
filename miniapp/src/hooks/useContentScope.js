import { useEffect } from 'react';

import { useQuery } from '@tanstack/react-query';

import api from '../lib/api';

import {
  useContentScopeStore,
} from '../stores/contentScopeStore';

/* 🌊 موج C1 — منبع واحد scope ورودی پنل محتوا در مینی‌اپ.
   هر صفحه‌ی مدیریت محتوا (علوم پایه/رفرنس/بانک سؤال/بررسی
   سؤال) از این هوک استفاده می‌کند تا:
     • ادمین ورودی خاص: حتی با deep-link هم scope خودش
       resolve و قفل شود (بدون picker)
     • ادمین ارشد بدون انتخاب: به picker هدایت شود
   enforce نهایی همیشه Backend است؛ این فقط UX است. */
export function useContentScope() {
  const intake = useContentScopeStore(
    (state) => state.intake
  );

  const label = useContentScopeStore(
    (state) => state.label
  );

  const mode = useContentScopeStore(
    (state) => state.mode
  );

  const setScope = useContentScopeStore(
    (state) => state.setScope
  );

  const {
    data,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['content-intakes'],

    queryFn: () =>
      api
        .get('/api/content/intakes')
        .then((response) => response.data),

    staleTime: 60_000,
  });


  /* قفل scope از پاسخ بک‌اند (منبع تصمیم: سرور) */
  useEffect(() => {
    if (!data) {
      return;
    }

    if (data.scope_kind === 'scoped') {
      setScope(
        data.scope_intake || '',
        data.scope_label || '',
        'scoped'
      );
    } else if (mode !== 'global') {
      setScope(intake, label, 'global');
    }
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, [data]);


  const ready = Boolean(data);

  const kind =
    data?.scope_kind || mode || null;

  const isScoped = kind === 'scoped';

  /* intake مؤثر که باید به API پاس شود */
  const effectiveIntake = !ready
    ? null
    : isScoped
      ? data.scope_intake || ''
      : intake;

  const effectiveLabel = isScoped
    ? data?.scope_label || label || effectiveIntake
    : label ||
      (effectiveIntake === ''
        ? '🌐 سراسری'
        : effectiveIntake);

  /* ادمین ارشد هنوز ورودی انتخاب نکرده */
  const needsPicker =
    ready &&
    kind === 'global' &&
    intake === null;


  return {
    ready,
    isLoading,
    isError,
    kind,
    isScoped,
    intake: effectiveIntake,
    label: effectiveLabel,
    needsPicker,
    intakes: data?.intakes || [],
  };
}
