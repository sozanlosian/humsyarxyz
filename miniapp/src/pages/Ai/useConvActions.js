import {
  useState,
} from 'react';

import {
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';

import api from '../../lib/api';
import {
  confirmAction,
} from '../../lib/confirm';
import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';
import {
  useUIStore,
} from '../../stores/uiStore';

import {
  exportConversation,
  fetchConvMessages,
  shareConversation,
} from '../../lib/convExport';


/* ─────────────────────────────────────────────
   اکشن‌های مشترک روی گفت‌وگو (پین/بایگانی/
   رونوشت/خروجی/اشتراک/حذف) — یک‌جا برای صفحه‌ی
   تاریخچه و شیتِ داخل چت تا رفتار کاملاً یکسان
   بماند.
───────────────────────────────────────────── */


function getErrorMessage(error, fallback) {
  const detail = error?.response?.data?.detail;

  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }

  return fallback;
}


export default function useConvActions({
  navigate,
  onDeleted,
}) {
  const toast = useUIStore(
    (state) => state.toast,
  );

  const queryClient = useQueryClient();

  // خروجی/اشتراک async دستی است؛ pending آن‌ها
  // را هم در busy لحاظ می‌کنیم
  const [ioBusy, setIoBusy] = useState(false);


  const invalidateList = () =>
    queryClient.invalidateQueries({
      queryKey: ['ai-conversations'],
    });


  const patchConvMutation = useMutation({
    mutationFn: ({ id, patch }) =>
      api.patch(
        `/api/ai/conversations/${id}`,
        patch,
      ),

    onSuccess: invalidateList,

    onError: (error) => {
      toast(
        getErrorMessage(
          error,
          'ذخیره‌ی تغییر گفت‌وگو انجام نشد',
        ),
        'error',
      );
    },
  });


  const duplicateConvMutation = useMutation({
    mutationFn: (item) =>
      api.post(
        `/api/ai/conversations/` +
        `${item.id}/duplicate`,
      ),

    onSuccess: (response) => {
      const id = String(
        response.data?.id || '',
      );

      hapticNotif('success');

      toast(
        'رونوشت ساخته شد',
        'success',
      );

      invalidateList();

      // گفت‌وگوهای خالیِ احتمالیِ قدیمی پاک
      // نشده‌اند — کش همان را هم بذر می‌کنیم تا
      // بدون لودینگ باز شود
      if (id) {
        navigate(`/ai/c/${id}`);
      }
    },

    onError: (error) => {
      toast(
        getErrorMessage(
          error,
          'ساخت رونوشت انجام نشد',
        ),
        'error',
      );
    },
  });


  const deleteConvMutation = useMutation({
    mutationFn: (item) =>
      api.delete(
        `/api/ai/conversations/${item.id}`,
      ),

    onSuccess: (_, item) => {
      hapticNotif('success');

      queryClient.removeQueries({
        queryKey: ['ai-conv-msgs', item.id],
      });

      if (item.legacy) {
        // سند مرجع هم پاک شده — وضعیت تازه شود
        queryClient.invalidateQueries({
          queryKey: ['ai-status'],
        });

        toast(
          'حافظه‌ی مشترک با ربات پاک شد',
          'info',
        );

      } else {
        toast(
          'گفت‌وگو حذف شد',
          'info',
        );
      }

      invalidateList();

      onDeleted?.(item);
    },

    onError: (error) => {
      toast(
        getErrorMessage(
          error,
          'حذف گفت‌وگو انجام نشد',
        ),
        'error',
      );
    },
  });


  const runExport = async (item) => {
    setIoBusy(true);

    try {
      const messages =
        await fetchConvMessages(item.id);

      if (!messages.length) {
        toast(
          'این گفت‌وگو هنوز پیامی ندارد',
          'warning',
        );

        return;
      }

      const result = await exportConversation(
        item,
        messages,
      );

      if (result === 'downloaded') {
        hapticNotif('success');

        toast(
          'فایل خروجی دانلود شد',
          'success',
        );

      } else if (result === 'copied') {
        toast(
          'متن کامل گفت‌وگو کپی شد',
          'success',
        );

      } else {
        toast(
          'خروجی‌گرفتن انجام نشد',
          'error',
        );
      }

    } catch (error) {
      toast(
        getErrorMessage(
          error,
          'خروجی‌گرفتن انجام نشد',
        ),
        'error',
      );

    } finally {
      setIoBusy(false);
    }
  };


  const runShare = async (item) => {
    setIoBusy(true);

    try {
      const messages =
        await fetchConvMessages(item.id);

      if (!messages.length) {
        toast(
          'این گفت‌وگو هنوز پیامی ندارد',
          'warning',
        );

        return;
      }

      const result = await shareConversation(
        item,
        messages,
      );

      if (result === 'shared') {
        hapticNotif('success');

      } else if (result === 'copied') {
        toast(
          'خلاصه برای اشتراک کپی شد',
          'success',
        );

      } else if (result === 'failed') {
        toast(
          'اشتراک‌گذاری انجام نشد',
          'error',
        );
      }

      // cancelled → سکوت؛ انتخاب خود کاربر بوده

    } catch (error) {
      toast(
        getErrorMessage(
          error,
          'اشتراک‌گذاری انجام نشد',
        ),
        'error',
      );

    } finally {
      setIoBusy(false);
    }
  };


  // نقطه‌ی ورود واحد — هر دو UI فقط این را صدا
  // می‌زنند؛ 'rename' عمداً اینجا نیست چون ورودی
  // این‌لاین می‌خواهد و خودِ لیست مدیریتش می‌کند
  const runAction = async (item, actionId) => {
    haptic('light');

    if (actionId === 'pin') {
      patchConvMutation.mutate({
        id: item.id,
        patch: { pinned: !item.pinned },
      });

    } else if (actionId === 'archive') {
      patchConvMutation.mutate({
        id: item.id,
        patch: { archived: !item.archived },
      });

    } else if (actionId === 'duplicate') {
      duplicateConvMutation.mutate(item);

    } else if (actionId === 'delete') {
      haptic('medium');

      const confirmed = item.legacy
        ? await confirmAction(
            'حافظه‌ی مشترک هوشیار در ربات و ' +
            'وب‌اپ کاملاً پاک شود؟ ' +
            'این کار برگشت‌ناپذیر است.',
          )
        : await confirmAction(
            `گفت‌وگوی «${item.title}» ` +
            'برای همیشه حذف شود؟',
          );

      if (confirmed) {
        deleteConvMutation.mutate(item);
      }

    } else if (actionId === 'export') {
      await runExport(item);

    } else if (actionId === 'share') {
      await runShare(item);
    }
  };


  return {
    runAction,

    // تغییرنام این‌لاین در لیست‌ها با همان
    // موتیشن پچ انجام می‌شود
    patchConvMutation,

    busy:
      patchConvMutation.isPending
      || duplicateConvMutation.isPending
      || deleteConvMutation.isPending
      || ioBusy,
  };
}
