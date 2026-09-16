import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import { ROUTER_BASENAME, APP_BASE } from './lib/base';
import './styles/globals.css';

// 🌊 W4 — PWA offline cache (best-effort) — only in production
if (typeof window !== 'undefined' && 'serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    const swUrl = (APP_BASE || '/app/') === '/' ? '/sw.js' : (APP_BASE || '/app/').replace(/\/$/, '') + '/sw.js';
    navigator.serviceWorker.register(swUrl).catch(()=>{});
    // auto-reload on new SW
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      // debounced reload to avoid loop
      if (!window.__swReloaded) { window.__swReloaded = true; window.location.reload(); }
    });
  });
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

/* 🚂 Railway: باندل زیر /app/ سرو می‌شود، پس router هم باید همان
   base را بداند. مقدار از تک‌منبع حقیقت src/lib/base.js خوانده
   می‌شود و در حالت ریشه undefined است (رفتار قبلی دست‌نخورده). */
ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter basename={ROUTER_BASENAME}>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </BrowserRouter>
  </React.StrictMode>
);
