import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

/* ─────────────────────────────────────────────────────────────
   🚂 مهاجرت Railway — مینی‌اپ به‌عنوان زیرمسیر /app/ سرو می‌شود

   چرا /app/ و نه ریشه؟
   همان دامنه‌ی Railway سه namespace مستقل دارد:
     /app/*   → Telegram Mini App (این بیلد)
     /admin/* → Web Admin (webadmin/dist، base خودش /admin/)
     /api/*   → FastAPI

   مینی‌اپ خودش routeهایی مثل /admin و /me دارد؛ اگر روی ریشه
   سرو می‌شد با Web Admin تداخل (shadow) پیدا می‌کرد.

   base از VITE_BASE خوانده می‌شود؛ پیش‌فرض /app/ است.
   برای `npm run dev` محلی می‌توان VITE_BASE=/ داد.
   ───────────────────────────────────────────────────────────── */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const rawBase = (env.VITE_BASE || '/app/').trim();
  // Vite به base با اسلش پایانی نیاز دارد؛ /app → /app/
  const base = rawBase === '/' ? '/' : rawBase.replace(/\/+$/, '') + '/';

  return {
    base,
    plugins: [react()],
    server: {
      host: true,
      port: 5173,
      // در dev، API روی همان origin شبیه‌سازی می‌شود تا رفتار
      // production (same-origin) در dev هم دیده شود.
      proxy: {
        '/api': {
          target: env.VITE_DEV_API_PROXY || 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      sourcemap: false,
    },
  };
});
