/* 🌊 W2 — لندینگ بازگشت از درگاه زرین‌پال (/payment/verify).
   دو حالت:
   ۱) بازشدن داخل مینی‌اپ (initData هست) → استعلام خودکار با احراز هویت.
   ۲) بازشدن در مرورگر خارجی (initData نیست) → راهنمای بازگشت به ربات/مینی‌اپ.
   این صفحه هرگز بدون احراز هویت verify نمی‌کند. */
import {
  useEffect,
  useRef,
  useState,
} from 'react';

import {
  Link,
  useSearchParams,
} from 'react-router-dom';

import api from '../../lib/api';

import {
  getInitData,
  openExternalLink,
} from '../../lib/telegram';

import Header from '../../components/layout/Header';

import {
  Spinner,
} from '../../components/shared/Loading';

import {
  useGatewayStatus,
} from '../../hooks/useZarinpalPay';


export default function PaymentVerify() {
  const [searchParams] =
    useSearchParams();

  const authority =
    (
      searchParams.get('Authority') || ''
    ).trim();

  const zpStatus =
    (
      searchParams.get('Status') || ''
    ).trim();

  const gatewayQuery =
    useGatewayStatus();

  const botUsername =
    gatewayQuery.data
      ?.bot_username || '';

  const hasAuth =
    Boolean(getInitData());

  const [
    state,
    setState,
  ] = useState('idle');

  const [
    detail,
    setDetail,
  ] = useState(null);

  const onceRef = useRef(false);

  /* استعلام خودکار — فقط وقتی داخل مینی‌اپ هستیم */
  useEffect(() => {
    if (
      onceRef.current ||
      !hasAuth ||
      !authority ||
      zpStatus !== 'OK'
    ) {
      return;
    }

    onceRef.current = true;
    setState('verifying');

    api
      .post(
        '/api/subscription/zarinpal/verify',

        { authority },

        { timeout: 30_000 }
      )
      .then(
        (response) => {
          setDetail(
            response.data || {}
          );

          setState('success');
        }
      )
      .catch(
        (error) => {
          setDetail({
            message:
              error?.response
                ?.data
                ?.detail ||
              'تأیید پرداخت ناموفق بود',
          });

          setState('failed');
        }
      );
  }, [hasAuth, authority, zpStatus]);

  const renderBody = () => {
    /* کاربر در درگاه «انصراف» زده */
    if (
      zpStatus &&
      zpStatus !== 'OK'
    ) {
      return (
        <div className="card">
          <b>پرداخت لغو شد 🚫</b>

          <div
            className="muted"
            style={{ marginTop: 6 }}
          >
            در درگاه دکمه‌ی انصراف را زدی؛ هیچ مبلغی از حسابت
            کم نشده. اگر می‌خواهی دوباره تلاش کن.
          </div>

          <Link
            to="/me/subscription"
            className="btn btn-p btn-full"
            style={{ marginTop: 12 }}
          >
            بازگشت به اشتراک
          </Link>
        </div>
      );
    }

    if (!authority) {
      return (
        <div className="card">
          <b>لینک نامعتبر است ⚠️</b>

          <div
            className="muted"
            style={{ marginTop: 6 }}
          >
            شناسه‌ی پرداخت در لینک پیدا نشد.
          </div>

          <Link
            to="/me/subscription"
            className="btn btn-p btn-full"
            style={{ marginTop: 12 }}
          >
            بازگشت به اشتراک
          </Link>
        </div>
      );
    }

    /* مرورگر خارجی — بدون احراز هویت، فقط راهنما */
    if (!hasAuth) {
      return (
        <div className="card">
          <b>پرداخت انجام شد ✅</b>

          <div
            className="muted"
            style={{ marginTop: 6 }}
          >
            برای فعال‌سازی نهایی، به ربات برگرد و دکمه‌ی
            «بررسی پرداخت» را بزن — یا همین صفحه را داخل
            مینی‌اپ باز کن تا خودکار تأیید شود.
          </div>

          <div
            className="muted"
            style={{
              marginTop: 8,
              fontSize: 'var(--fs-cap)',
            }}
          >
            شناسه‌ی پیگیری درگاه:
            <br />
            <code>{authority}</code>
          </div>

          {botUsername && (
            <button
              type="button"
              className="btn btn-p btn-full"
              style={{ marginTop: 12 }}
              onClick={() =>
                openExternalLink(
                  `https://t.me/${botUsername}`
                )
              }
            >
              بازگشت به ربات 🤖
            </button>
          )}

          <Link
            to="/me/subscription"
            className="btn btn-full"
            style={{ marginTop: 8 }}
          >
            رفتن به صفحه‌ی اشتراک
          </Link>
        </div>
      );
    }

    if (
      state === 'verifying' ||
      state === 'idle'
    ) {
      return (
        <div
          className="card"
          style={{ textAlign: 'center' }}
        >
          <Spinner />

          <div
            className="muted"
            style={{ marginTop: 8 }}
          >
            در حال استعلام نتیجه‌ی پرداخت از درگاه…
          </div>
        </div>
      );
    }

    if (state === 'success') {
      return (
        <div className="card">
          <b>پرداخت تأیید شد 🎉</b>

          <div
            className="muted"
            style={{ marginTop: 6 }}
          >
            {detail?.end_date
              ? `اشتراک تا ${detail.end_date} فعال شد.`
              : 'مبلغ به حساب شما اضافه شد.'}
          </div>

          {detail?.ref_id && (
            <div
              className="muted"
              style={{
                marginTop: 8,
                fontSize: 'var(--fs-cap)',
              }}
            >
              شماره پیگیری: <code>{detail.ref_id}</code>
            </div>
          )}

          {detail?.mock && (
            <div
              className="muted"
              style={{
                marginTop: 8,
                fontSize: 'var(--fs-cap)',
              }}
            >
              حالت نمایشی درگاه — پرداخت واقعی انجام نشد.
            </div>
          )}

          <Link
            to="/me/subscription"
            className="btn btn-p btn-full"
            style={{ marginTop: 12 }}
          >
            مشاهده‌ی اشتراک
          </Link>
        </div>
      );
    }

    return (
      <div className="card">
        <b>تأیید نشد ⚠️</b>

        <div
          className="muted"
          style={{ marginTop: 6 }}
        >
          {detail?.message}
        </div>

        <div
          className="muted"
          style={{
            marginTop: 8,
            fontSize: 'var(--fs-cap)',
          }}
        >
          اگر مبلغ از حسابت کم شده، شناسه‌ی زیر را برای
          پشتیبانی بفرست:
          <br />
          <code>{authority}</code>
        </div>

        <Link
          to="/me/subscription"
          className="btn btn-p btn-full"
          style={{ marginTop: 12 }}
        >
          بازگشت به اشتراک
        </Link>
      </div>
    );
  };

  return (
    <>
      <Header title="نتیجه‌ی پرداخت" />

      <main className="page">
        {renderBody()}

        <div
          className="muted"
          style={{
            marginTop: 12,
            fontSize: 'var(--fs-cap)',
            textAlign: 'center',
          }}
        >
          پرداخت امن با زرین‌پال 💳
        </div>
      </main>
    </>
  );
}
