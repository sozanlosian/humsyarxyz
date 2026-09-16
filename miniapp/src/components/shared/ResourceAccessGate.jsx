import {
  useNavigate,
} from 'react-router-dom';

import {
  useQuery,
} from '@tanstack/react-query';

import api from '../../lib/api';
import Header from '../layout/Header';
import SubscriptionLock from './SubscriptionLock';
import { Spinner } from './Loading';


/* ─────────────────────────────────────────────
   🛡 دروازه‌ی دسترسی منابع — Gate «قبل از Mount»

   ریشه‌ی رفتارِ غلطِ قبلی: خودِ صفحه‌ی منابع
   Mount می‌شد، کوئری‌های محتوا شلیک می‌شدند و
   فقط بعد از ۴۰۳ِ سرور قفل ظاهر می‌شد — یعنی
   کاربرِ بدون اشتراک هم اسکلت می‌دید، هم
   ریکوئست محتوا می‌رفت، هم State صفحه ساخته
   می‌شد.

   معماریِ این فایل دقیقاً برعکس است: وضعیت
   دسترسی «اول» ارزیابی می‌شود و کامپوننتِ
   صفحه فقط وقتی Mount می‌شود که دسترسی قطعی
   باشد. در غیر این صورت — بدون حتی یک فریم
   از صفحه و بدون هیچ ریکوئستِ محتوا — همان
   لحظه صفحه‌ی قفل رندر می‌شود.

   منبع وضعیت = همان کوئریِ مشترکِ
   ['sub-status'] با دقیقاً همان کلید و آدرسِ
   صفحه‌ی «من». نتیجه: اگر کاربر اخیراً «من»
   را دیده باشد، جواب در کشِ React Query تازه
   است (staleTime پنج دقیقه) و دروازه بدون
   هیچ ریکوئستِ جدیدی، در همان رندرِ اول
   تصمیم می‌گیرد — حتی برای تشخیص قفل هم
   صفر فریم انتظار. پس از خرید پلن،
   Me/Subscription همین کلید را invalidate
   می‌کند؛ پس کش هرگز کهنه نمی‌ماند.

   مرجع نهاییِ امنیت همچنان بک‌اند است: گیتِ
   ۴۰۳ روی API و قفلِ داخلیِ صفحه‌ها (نمایشِ
   قفل در صورت ۴۰۳ واقعیِ محتوا) دست‌نخورده
   باقی می‌مانند — این دروازه لایه‌ی UX است،
   نه جایگزینِ امنیت.

   سیاست خطا — fail-open: اگر خودِ «وضعیتِ
   اشتراک» خوانده نشود (قطعیِ لحظه‌ای شبکه)،
   صفحه Mount می‌شود تا مشترکِ واقعی قفلِ
   کاذب نبیند؛ سرور در نبودِ دسترسی ۴۰۳
   می‌دهد و قفلِ داخلی همان را نشان می‌دهد.
───────────────────────────────────────────── */


/* هوکِ مشترکِ وضعیتِ دسترسی منابع.
   resource_access را سرور از همان تابعِ واحدِ
   has_access ربات می‌سازد؛ اینجا هیچ منطقِ
   جداگانه‌ای بازنویسی نشده است */
export function useResourceAccess() {
  return useQuery({
    queryKey: [
      'sub-status',
    ],

    queryFn: () =>
      api
        .get(
          '/api/subscription/status'
        )
        .then(
          (response) =>
            response.data
        ),

    /* دقیقاً برابر صفحه‌ی «من» تا هر دو از
       یک پنجره‌ی تازگیِ مشترک استفاده کنند */
    staleTime: 5 * 60 * 1000,
  });
}


export default function ResourceAccessGate({
  feature,
  featureKey = '',
  children,
}) {
  const navigate =
    useNavigate();

  const {
    data,
    isPending,
    isError,
  } = useResourceAccess();

  const goLearnHome = () =>
    navigate('/learn');

  /* با کشِ تازه، isPending از همان رندرِ
     اول false است و این شاخه اصلاً دیده
     نمی‌شود؛ فقط برای «کشِ خالی» — یک نمایشِ
     خنثای کوتاه، نه اسکلتِ صفحه‌ی محتوا */
  if (isPending) {
    return (
      <>
        <Header
          title={feature}
          back
          onBack={goLearnHome}
        />

        <main
          className="page"
          style={{
            display: 'grid',
            minHeight: '40vh',
            placeItems: 'center',
          }}
        >
          <Spinner size={26} />
        </main>
      </>
    );
  }

  /* 🌊 W7 — تصمیم فیچرمحور از نقشه‌ی features (در همان sub-status)؛
     بدون featureKey همان رفتار legacy. fail-open: بک‌اند مرجع نهایی است. */
  let hasAccess = isError
    ? true
    : data?.resource_access !==
      false;

  let lockMode = 'sub';

  if (featureKey && !isError) {
    const fmap = data?.features?.[featureKey];

    if (!fmap) {
      hasAccess = true;
    } else if (!fmap.enabled) {
      hasAccess = false; lockMode = 'disabled';
    } else if (fmap.access === 'subscription' && !data?.active) {
      hasAccess = false; lockMode = 'sub';
    } else {
      hasAccess = true;
    }
  }

  if (!hasAccess) {
    return (
      <>
        <Header
          title={feature}
          back
          onBack={goLearnHome}
        />

        <main
          className="page"
        >
          <SubscriptionLock
            feature={feature}
            featureKey={featureKey}
            mode={lockMode}
          />
        </main>
      </>
    );
  }

  return children;
}
