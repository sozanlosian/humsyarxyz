import {
  useState,
} from 'react';

import {
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import api from '../../lib/api';

import {
  useUIStore,
} from '../../stores/uiStore';


/* ─────────────────────────────────────────────
   🌊 W8/MISS-03 — بخش خانواده در صفحه‌ی اشتراک

   سه حالت: مالک پلن خانوادگی (اعضا + صندلی +
   ساخت کد)، عضو (نمایش مالک)، بی‌اشتراک
   (فرم ثبت کد دعوت). امنیت سمت سرور است؛
   اینجا فقط UX.
───────────────────────────────────────────── */


function useFamily(enabled) {
  return useQuery({
    queryKey: [
      'family-overview',
    ],

    queryFn: () =>
      api
        .get(
          '/api/subscription/family'
        )
        .then(
          (response) =>
            response.data
        ),

    enabled,
    staleTime: 60 * 1000,
    retry: false,
  });
}


export default function FamilySection({
  hasActive,
}) {
  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();

  const {
    data,
    refetch,
  } = useFamily(true);

  const [
    code,
    setCode,
  ] = useState('');

  const [
    newCode,
    setNewCode,
  ] = useState('');

  const [
    busy,
    setBusy,
  ] = useState(false);

  const refresh = () => {
    refetch();

    queryClient.invalidateQueries({
      queryKey: [
        'sub-status',
      ],
    });
  };

  const redeem = async () => {
    const c = code.trim();

    if (c.length < 8 || busy) {
      return;
    }

    setBusy(true);

    try {
      await api.post(
        '/api/subscription/family/redeem',

        { code: c },
      );

      toast(
        '🎉 به خانواده پیوستی!'
      );

      setCode('');
      refresh();
    } catch (e) {
      toast(
        e?.response?.data?.detail
        || 'ثبت کد ناموفق بود',

        'err',
      );
    } finally {
      setBusy(false);
    }
  };

  const makeCode = async () => {
    if (busy) {
      return;
    }

    setBusy(true);

    try {
      const r =
        await api.post(
          '/api/subscription/family/code'
        );

      setNewCode(
        r.data?.code || ''
      );

      refresh();
    } catch (e) {
      toast(
        e?.response?.data?.detail
        || 'ساخت کد ناموفق بود',

        'err',
      );
    } finally {
      setBusy(false);
    }
  };

  const removeMember = async (
    memberId
  ) => {
    if (busy) {
      return;
    }

    setBusy(true);

    try {
      await api.delete(
        `/api/subscription/family/members/${memberId}`
      );

      toast('عضو حذف شد');
      refresh();
    } catch (e) {
      toast(
        e?.response?.data?.detail
        || 'حذف ناموفق بود',

        'err',
      );
    } finally {
      setBusy(false);
    }
  };


  /* بی‌اشتراک: فقط فرم ثبت کد */
  if (!hasActive) {
    return (
      <section
        className="card"
        style={{ marginTop: 12 }}
      >
        <b>
          🎟 کد دعوت خانواده داری؟
        </b>

        <div
          className="row"
          style={{
            marginTop: 10,
            gap: 8,
          }}
        >
          <input
            className="inp"
            dir="ltr"
            placeholder="ABCDEFGH"
            value={code}
            maxLength={12}
            onChange={(e) =>
              setCode(e.target.value)
            }
            style={{
              flex: 1,
              textAlign: 'center',
              letterSpacing: 2,
            }}
          />

          <button
            type="button"
            className="btn btn-p"
            disabled={
              busy || code.trim().length < 8
            }
            onClick={redeem}
          >
            {busy ? '⏳' : 'ثبت'}
          </button>
        </div>
      </section>
    );
  }

  if (!data) {
    return null;
  }

  /* عضو خانواده */
  if (data.role === 'member') {
    return (
      <section
        className="card"
        style={{ marginTop: 12 }}
      >
        <b>
          👨‍👩‍👧 عضو خانواده‌ی{' '}

          {data.owner_name || '—'}
        </b>

        <div
          className="muted"
          style={{ marginTop: 6 }}
        >
          اشتراکت به مالک وصله؛ با پایان
          اشتراک مالک قطع می‌شود.
        </div>
      </section>
    );
  }

  /* مالک پلن شخصی: چیزی برای مدیریت نیست */
  if (
    Number(data.seats_total) <= 1
  ) {
    return null;
  }

  const members =
    (data.members || []).filter(
      (m) => m.status === 'active'
    );

  return (
    <section
      className="card"
      style={{ marginTop: 12 }}
    >
      <b>
        👨‍👩‍👧 خانواده‌ی من
      </b>

      <span className="muted">
        {' '}({members.length} از{' '}

        {Number(data.seats_total) - 1}{' '}
        صندلی)
      </span>

      {members.map((m) => (
        <div
          key={m.user_id}
          className="row"
          style={{
            marginTop: 8,
            gap: 8,
          }}
        >
          <span style={{ flex: 1 }}>
            👤 {m.name || m.user_id}
          </span>

          <button
            type="button"
            className="btn sm"
            disabled={busy}
            onClick={() =>
              removeMember(m.user_id)
            }
          >
            حذف
          </button>
        </div>
      ))}

      {newCode && (
        <div
          className="card"
          style={{
            marginTop: 10,
            textAlign: 'center',
            letterSpacing: 3,
            fontSize: 20,
          }}
          dir="ltr"
        >
          <b>{newCode}</b>

          <div
            className="muted"
            style={{
              fontSize: 12,
              letterSpacing: 0,
            }}
          >
            این کد را برای عضو جدید بفرست
            (یک‌بارمصرف)
          </div>
        </div>
      )}

      {Number(data.seats_left) > 0 ? (
        <button
          type="button"
          className="btn btn-full"
          disabled={busy}
          onClick={makeCode}
          style={{ marginTop: 10 }}
        >
          ➕ ساخت کد دعوت جدید
        </button>
      ) : (
        <div
          className="muted"
          style={{ marginTop: 10 }}
        >
          ⚠️ ظرفیت پر شده است.
        </div>
      )}
    </section>
  );
}
