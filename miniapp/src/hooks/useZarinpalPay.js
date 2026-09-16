/* 🌊 W2 — هوک مشترک پرداخت آنلاین زرین‌پال (خرید پلن + شارژ کیف پول).
   request → openLink در مرورگر خارجی → verify با احراز هویت داخل مینی‌اپ.
   پرداختِ در انتظار در localStorage نگه داشته می‌شود تا با بستن/بازکردن
   مینی‌اپ گم نشود؛ درگاه بعد از ۱ ساعت pending را خودش لغو می‌کند. */
import {
  useCallback,
  useState,
} from 'react';

import {
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import api from '../lib/api';

import {
  openExternalLink,
} from '../lib/telegram';

import {
  useUIStore,
} from '../stores/uiStore';


const PENDING_KEY =
  'humsyar_zp_pending';


export const readPendingPay = () => {
  try {
    return JSON.parse(
      localStorage.getItem(PENDING_KEY) || 'null'
    );
  } catch {
    return null;
  }
};


export const writePendingPay = (value) => {
  try {
    if (value) {
      localStorage.setItem(
        PENDING_KEY,
        JSON.stringify(value)
      );
    } else {
      localStorage.removeItem(PENDING_KEY);
    }
  } catch {
    /* حافظه در دسترس نیست — پرداخت در حافظه‌ی موقت می‌ماند */
  }
};


/* وضعیت عمومی درگاه (فقط boolean؛ بدون secret) */
export function useGatewayStatus() {
  return useQuery({
    queryKey: [
      'gateway-status',
    ],

    queryFn: () =>
      api
        .get(
          '/api/subscription/gateway-status'
        )
        .then(
          (response) =>
            response.data
        ),

    staleTime:
      5 * 60 * 1000,

    retry: 1,
  });
}


export function useZarinpalPay({
  kind = 'plan',
  onDone,
} = {}) {
  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();

  const [
    pending,
    setPendingState,
  ] = useState(() =>
    readPendingPay()
  );

  const [
    busy,
    setBusy,
  ] = useState(false);

  const setPending = useCallback(
    (value) => {
      writePendingPay(value);
      setPendingState(value);
    },
    []
  );

  const refresh = useCallback(
    async () => {
      await queryClient.invalidateQueries({
        queryKey: ['sub-status'],
      });

      await queryClient.invalidateQueries({
        queryKey: ['wallet'],
      });
    },
    [queryClient]
  );

  /* ساخت پرداخت و بازکردن درگاه.
     payload خرید: { plan_id, discount_code?, gift_to?, gift_message? }
     payload شارژ: { amount } */
  const request = useCallback(
    async (payload) => {
      setBusy(true);

      try {
        const endpoint =
          payload.plan_id
            ? '/api/subscription/zarinpal/request'
            : '/api/subscription/zarinpal/topup';

        const response = await api.post(
          endpoint,

          {
            ...payload,

            idem:
              `zpm-${Date.now()}-` +
              `${Math.random()
                .toString(36)
                .slice(2, 10)}`,
          },

          {
            timeout:
              30_000,
          }
        );

        const data =
          response.data || {};

        const record = {
          authority: data.authority,
          url: data.url,
          payment_id: data.payment_id,
          final_price: data.final_price,
          kind,
          at: Date.now(),
        };

        setPending(record);
        openExternalLink(data.url);

        return record;
      } catch (error) {
        toast(
          error?.response
            ?.data
            ?.detail ||
            'اتصال به درگاه ناموفق بود',

          'error'
        );

        throw error;
      } finally {
        setBusy(false);
      }
    },
    [kind, setPending, toast]
  );

  /* استعلام نتیجه — فقط با احراز هویت داخل مینی‌اپ/ربات */
  const verify = useCallback(
    async (authority) => {
      setBusy(true);

      try {
        const response =
          await api.post(
            '/api/subscription/zarinpal/verify',

            { authority },

            {
              timeout:
                30_000,
            }
          );

        setPending(null);
        await refresh();

        toast(
          kind === 'topup'
            ? 'کیف پول شارژ شد ✅'
            : 'اشتراک فعال شد ✅',

          'success'
        );

        onDone?.(
          response.data
        );

        return response.data;
      } catch (error) {
        const status =
          error?.response
            ?.status;

        /* 404/409 یعنی پرداخت دیگر قابل تأیید نیست
           (منقضی، لغو یا قبلاً بسته‌شده) — pending محلی پاک شود */
        if (
          status === 404 ||
          status === 409
        ) {
          setPending(null);
          await refresh();
        }

        toast(
          error?.response
            ?.data
            ?.detail ||
            'تأیید پرداخت ناموفق بود',

          'error'
        );

        throw error;
      } finally {
        setBusy(false);
      }
    },
    [kind, setPending, refresh, toast, onDone]
  );

  const cancelLocal = useCallback(
    () => {
      setPending(null);
    },
    [setPending]
  );

  return {
    pending,
    busy,
    request,
    verify,
    cancelLocal,
    setPending,
  };
}
