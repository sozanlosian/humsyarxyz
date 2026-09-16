import React, { useState } from 'react';
import { api, errText } from '../api.js';
import { B, PageHeader, toast } from '../ui.jsx';

const CAPABILITIES = [
  { key: 'questions', icon: '🧪', title: 'درون‌ریزی سؤال', desc: 'Parse → Validate → Preview → Confirm با گزارش ردیف‌های نامعتبر', go: '/questions?create=1', perms: ['questions.review', 'questions.review_scoped'] },
  { key: 'grades', icon: '📊', title: 'درون‌ریزی و ثبت گروهی نمره', desc: 'CSV با Telegram ID/Score یا انتخاب دانشجو؛ validation سمت سرور و اعلان نتیجه', go: '/exams?tab=grades&new=grade', perms: ['grades.manage', 'grades.scoped'] },
  { key: 'users', icon: '👥', title: 'خروجی کاربران', desc: 'خروجی CSV انتخاب جاری از جدول کاربران یا فایل Excel کامل از مسیر امن ربات', go: '/users', perms: ['users.view', 'users.manage'] },
  { key: 'audit', icon: '🧭', title: 'خروجی/تحقیق حسابرسی', desc: 'ابتدا فیلترها و نمای ذخیره‌شده را در مرکز حسابرسی تعیین کنید', go: '/audit', perms: ['audit.view'] },
];

export default function TransferCenter({ me, go }) {
  const [busy, setBusy] = useState('');
  const has = (...keys) => !!me?.is_owner || keys.some(k => (me?.perms || []).includes(k));
  const excel = async () => {
    setBusy('excel');
    try { await api.exportExcel(); toast('خروجی Excel کامل از طریق ربات ارسال می‌شود'); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy('');
  };
  const backup = async () => {
    setBusy('backup');
    try { await api.backup(); toast('پشتیبان JSON کامل از طریق ربات ارسال می‌شود'); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy('');
  };
  return <>
    <PageHeader title="مرکز انتقال داده" description="نقطه ورود یکپارچه برای import/exportهای واقعی و scope-aware؛ بدون بارگیری کامل dataset در مرورگر"
      actions={<>{has('backup.manage') && <button className="btn" disabled={!!busy} onClick={backup}>{busy === 'backup' ? '⏳' : '💾 JSON کامل'}</button>}
        {has('backup.manage') && <button className="btn primary" disabled={!!busy} onClick={excel}>{busy === 'excel' ? '⏳' : '📑 Excel کامل'}</button>}</>} />
    <div className="grid g2">
      {CAPABILITIES.filter(c => has(...c.perms)).map(c => <button key={c.key} className="panel panel-pad transfer-card" onClick={() => go(c.go)}>
        <span className="transfer-icon">{c.icon}</span><span style={{ flex: 1, textAlign: 'right' }}><b>{c.title}</b><span className="muted">{c.desc}</span></span><B kind="acc">بازکردن ‹</B>
      </button>)}
    </div>
    <div className="panel panel-pad" style={{ marginTop: 14 }}>
      <b>قواعد ایمنی انتقال</b>
      <div className="grid g3" style={{ marginTop: 10 }}>
        <div><B kind="ok">Validate</B><p className="muted">مقادیر، scope و موجودیت‌ها پیش از mutation در backend کنترل می‌شوند.</p></div>
        <div><B kind="warn">Preview</B><p className="muted">سؤال و نمره قبل از commit قابل بازبینی‌اند؛ عملیات حساس Confirm دارد.</p></div>
        <div><B kind="acc">Audit</B><p className="muted">ثبت نمره، سؤال، خروجی و پشتیبان در همان audit مشترک ثبت می‌شوند.</p></div>
      </div>
    </div>
  </>;
}
