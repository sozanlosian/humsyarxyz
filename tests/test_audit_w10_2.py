"""W10.2 — MiniApp crash-hotfix regression guards (static, no browser needed).

C-01 (Schedule): صفحه‌ی برنامه faDate/faNum را بدون import صدا می‌زد —
      کرش لایو «faDate is not defined».
C-02 (Subscription): افکت resume پرداخت، payments را در deps آرایه
      قبل از تعریف const آن می‌خواند — کرش لایو
      «Cannot access 'R' before initialization» (نام مینیفای‌شده‌ی payments).
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCHEDULE = REPO / 'miniapp/src/pages/Schedule/index.jsx'
SUBSCRIPTION = REPO / 'miniapp/src/pages/Me/Subscription.jsx'


def _imported_names(text):
    """نام‌هایی که فایل از ماژول‌ها import کرده (شامل import چندخطی)."""
    names = set()
    for m in re.finditer(r'import\s*\{([^}]*)\}\s*from', text):
        for part in m.group(1).split(','):
            part = part.strip()
            if not part:
                continue
            alias = re.split(r'\s+as\s+', part)
            names.add(alias[-1].strip())
    for m in re.finditer(r'import\s+([A-Za-z_$][\w$]*)\s+from', text):
        names.add(m.group(1))
    return names


def _called_without_import(text, imported, helper):
    """فراخوانی helper( بدون import متناظر (خاصیت شیء حساب نیست)."""
    body = re.sub(r'import\s+.*?;', '', text, flags=re.S)
    for m in re.finditer(r'\b' + re.escape(helper) + r'\s*\(', body):
        pre = body[max(0, m.start() - 2):m.start()]
        if pre.endswith('.'):
            continue  # x.helper() — متد شیء، نه هلپر ماژول
        if helper not in imported:
            return True
    return False


def test_schedule_imports_format_helpers():
    """C-01: ریشه‌ی کرش برنامه — faDate/faNum باید import شده باشند."""
    text = SCHEDULE.read_text(encoding='utf-8')
    imported = _imported_names(text)
    assert 'faDate' in imported, 'Schedule uses faDate() but does not import it'
    assert 'faNum' in imported, 'Schedule uses faNum() but does not import it'


def test_subscription_effect_declared_after_payments():
    """C-02: ریشه‌ی کرش اشتراک — افکت resume باید بعد از const payments باشد.

    آرایه‌ی deps هنگام رندر (نه هنگام اجرای افکت) خوانده می‌شود؛ اگر قبل
    از تعریف payments باشد، TDZ می‌دهد.
    """
    lines = SUBSCRIPTION.read_text(encoding='utf-8').split('\n')
    decl = next(
        i for i, ln in enumerate(lines)
        if re.match(r'\s*const payments\s*=', ln)
    )
    use = next(
        i for i, ln in enumerate(lines)
        if '[payments, zp]' in ln
    )
    assert use > decl, (
        f'resume-effect deps (line {use + 1}) still read before '
        f'`payments` is declared (line {decl + 1}) → TDZ crash'
    )


def test_no_undef_format_helpers_miniapp():
    """C-03: هیچ ماژول مینی‌اپ هلپر فرمت/تلگرام را بدون import صدا نزند.

    زیرمجموعه‌ی بادوام از sweep کامل no-undef (W10.2) که روی هر دو
    فرانت‌اند صفر خطا داد؛ این تست همان کلاس کرش را برای آینده قفل می‌کند.
    """
    helpers = ['faDate', 'faNum', 'number', 'percent', 'errorText',
               'haptic', 'hapticNotif', 'confirmAction']
    bad = []
    for path in sorted((REPO / 'miniapp/src').rglob('*.jsx')) + \
            sorted((REPO / 'miniapp/src').rglob('*.js')):
        text = path.read_text(encoding='utf-8')
        imported = _imported_names(text)
        local = set(re.findall(
            r'(?:const|let|var|function)\s+([A-Za-z_$][\w$]*)', text))
        for h in helpers:
            if h in local:
                continue
            if _called_without_import(text, imported, h):
                bad.append(f'{path.relative_to(REPO)}: {h}() without import')
    assert not bad, 'missing imports (live-crash class):\n' + '\n'.join(bad)
