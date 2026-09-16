import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/* 🌊 موج C1 — متن (scope) ورودی پنل محتوا.
   فقط UX است: enforce واقعی در Backend (API + Bot) انجام
   می‌شود و این استور هیچ دسترسی‌ای باز نمی‌کند.
   intake = کد ورودی؛ '' = 🌐 سراسری (محتوای مشترک/legacy).
   mode: 'global' (ادمین ارشد — picker دارد) |
         'scoped' (ادمین ورودی خاص — قفل، بدون picker) */
export const useContentScopeStore = create(
  persist(
    (set) => ({
      intake: null,
      /* null یعنی هنوز انتخاب نشده */
      label: '',
      mode: null,

      setScope: (intake, label, mode) =>
        set({
          intake,
          label,
          mode,
        }),

      setIntake: (intake, label) =>
        set({
          intake,
          label,
        }),

      clearScope: () =>
        set({
          intake: null,
          label: '',
          mode: null,
        }),
    }),
    {
      name: 'humsyar-content-scope',
    }
  )
);
