import React, { useState } from 'react';
import { api, errText } from '../api.js';
import { toast } from '../ui.jsx';

export default function Login({ onDone }) {
  const [step, setStep] = useState(1);
  const [ident, setIdent] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);

  const send = async () => {
    if (!ident.trim()) return toast('شناسه را وارد کنید', 'err');
    setBusy(true);
    try {
      const r = await api.requestCode(ident.trim());
      toast(r.message || 'کد ارسال شد');
      setStep(2);
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  const verify = async () => {
    if (code.trim().length !== 6) return toast('کد ۶ رقمی را کامل وارد کنید', 'err');
    setBusy(true);
    try {
      await api.verify(ident.trim(), code.trim());
      toast('خوش آمدید 👋');
      onDone();
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };

  return (
    <div className="login-hero">
      <div className="panel login-card">
        <div className="logo">🏥</div>
        <h2 style={{ marginBottom: 4 }}>مرکز فرماندهی هامزیار</h2>
        <p className="sub" style={{ marginBottom: 20 }}>ورود امن مدیران با کد یک‌بارمصرف تلگرام</p>

        {step === 1 ? (
          <>
            <input className="inp" style={{ width: '100%', marginBottom: 10, textAlign: 'center' }}
                   placeholder="آیدی عددی تلگرام یا @username"
                   value={ident} onChange={e => setIdent(e.target.value)}
                   onKeyDown={e => e.key === 'Enter' && send()} />
            <button className="btn primary" style={{ width: '100%' }} disabled={busy} onClick={send}>
              {busy ? '…' : '📩 ارسال کد ورود'}
            </button>
          </>
        ) : (
          <>
            <p className="sub">کد ۶ رقمی به تلگرام شما ارسال شد (اعتبار ۵ دقیقه)</p>
            <input className="inp otp-inp" maxLength={6} dir="ltr"
                   placeholder="——————" value={code}
                   onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
                   onKeyDown={e => e.key === 'Enter' && verify()} />
            <button className="btn primary" style={{ width: '100%', marginTop: 10 }}
                    disabled={busy} onClick={verify}>
              {busy ? '…' : '🔐 ورود'}
            </button>
            <button className="btn sm" style={{ width: '100%', marginTop: 8 }}
                    onClick={() => { setStep(1); setCode(''); }}>
              ↩️ تغییر شناسه
            </button>
          </>
        )}
        <p className="muted" style={{ marginTop: 16 }}>نشست امن ۱۲ ساعته · کوکی HttpOnly · ثبت در لاگ حسابرسی</p>
      </div>
    </div>
  );
}
