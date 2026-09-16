import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './app.jsx';
import ErrorBoundary from './ErrorBoundary.jsx';
import './styles.css';

// مرز بیرونی: اگر خودِ App هنگام bootstrap بترکد (نه فقط یک صفحه)،
// باز هم به‌جای صفحه‌ی سفید یک پیام قابل‌اقدام دیده می‌شود.
createRoot(document.getElementById('root')).render(
  <ErrorBoundary><App /></ErrorBoundary>,
);
