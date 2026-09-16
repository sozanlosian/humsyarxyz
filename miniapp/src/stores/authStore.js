import { create } from 'zustand';
import api from '../lib/api';
import { getTgUser, isTelegram } from '../lib/telegram';

export const useAuthStore = create((set) => ({
  user: null,
  tgUser: null,
  loading: true,
  error: null,

  init: async () => {
    const tgUser = getTgUser();

    set({
      tgUser,
      loading: true,
      error: null,
    });

    // خارج از محیط تلگرام، initData معتبر وجود ندارد
    // و API نمی‌تواند کاربر را احراز هویت کند.
    if (!isTelegram) {
      set({
        loading: false,
        error: 'telegram_required',
      });

      return;
    }

    try {
      const response = await api.get('/api/profile');

      set({
        user: response.data?.user || null,
        loading: false,
        error: null,
      });
    } catch (error) {
      const detail = error.response?.data?.detail;

      /* 🧯 فقط رشتهً‌ رشته! detail در خطاهای
         422 لیست/آبجکت است و اگر به AuthError
         برسد، رندرش کرش می‌کند (صفحه‌ی تاریک) */
      set({
        loading: false,

        error:
          typeof detail === 'string'
            ? detail

          : error.response
            ? 'error'
            : 'network_error',
      });
    }
  },

  refresh: async () => {
    try {
      const response = await api.get('/api/profile');
      const user = response.data?.user || null;

      set({ user });

      return user;
    } catch (_) {
      return null;
    }
  },

  /* تغییر وضعیت احراز هویت وسط نشست
     (مثل تعلیق کاربر توسط مدیر در حین استفاده) —
     api.js این رویدادها را روی window دیسپچ می‌کند */
  forceError: (code) =>
    set({
      user: null,
      loading: false,
      error: code,
    }),
}));
