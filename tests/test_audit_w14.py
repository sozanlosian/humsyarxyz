"""W14 — پیگیری پرداخت نیمه‌تمام (dunning): قوانین خالص + سیم‌کشی استاتیک.

pure: growth_rules (بدون Mongo) + انتخاب سررسیدها.
static: claim اتمیک، سکوت شبانه، تفویض به وریفای زرین‌پال، اندپوینت‌ها و UI.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import growth_rules as gr


def _read(rel):
    return (REPO / rel).read_text(encoding="utf-8")


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ═══════════ زمان و سکوت ═══════════

def test_parse_iso_ts():
    assert gr.parse_iso_ts("2026-01-01T00:00:00Z") == 1767225600.0
    assert gr.parse_iso_ts("2026-01-01T00:00:00+00:00") == 1767225600.0
    assert gr.parse_iso_ts("2026-01-01T00:00:00") == 1767225600.0  # naive→UTC
    assert gr.parse_iso_ts("not-a-date") is None
    assert gr.parse_iso_ts("") is None
    assert gr.parse_iso_ts(None) is None
    assert gr.parse_iso_ts(12345) is None


def test_tehran_hour_known_values():
    # 2026-01-01T00:00:00Z → ‎۰۳:۳۰‎ تهران (بدون DST از ۲۰۲۲)
    assert gr.tehran_hour(1767225600.0) == 3
    # 2026-01-01T12:00:00Z → ‎۱۵:۳۰‎ تهران
    assert gr.tehran_hour(1767268800.0) == 15
    # مرز نیمه‌شب: 20:31Z → ‎۰۰:۰۱‎ تهران
    assert gr.tehran_hour(1767299460.0) == 0


def test_in_quiet_hours():
    assert gr.in_quiet_hours(3, 0, 7) is True
    assert gr.in_quiet_hours(7, 0, 7) is False   # پایان بازه بیرون است
    assert gr.in_quiet_hours(12, 0, 7) is False
    # بازه‌ی overnight
    assert gr.in_quiet_hours(23, 22, 7) is True
    assert gr.in_quiet_hours(6, 22, 7) is True
    assert gr.in_quiet_hours(12, 22, 7) is False
    # شروع=پایان → بدون سکوت
    assert gr.in_quiet_hours(3, 0, 0) is False


def test_merge_dun_config():
    cfg = gr.merge_dun_config(None)
    assert cfg == {"enabled": False, "step1_s": 3600, "step2_s": 86400,
                   "quiet_start": 0, "quiet_end": 7}
    cfg = gr.merge_dun_config({"enabled": True, "step1_s": 5,
                               "quiet_end": 99, "step2_s": "xx"})
    assert cfg["enabled"] is True
    assert cfg["step1_s"] == 60       # حداقل گام
    assert cfg["step2_s"] == 86400    # نامعتبر → پیش‌فرض
    assert cfg["quiet_end"] == 23     # clamp سقف
    assert gr.dun_steps(cfg) == [60, 86400]


def test_dunning_message():
    m1 = gr.dunning_message({"plan_name": "پرو", "final_price": 99000}, 0)
    assert "نیمه‌تمام" in m1 and "پرو" in m1 and "99,000 تومان" in m1
    m2 = gr.dunning_message({}, 1)
    assert "آخرین یادآوری" in m2 and "اشتراک" in m2


# ═══════════ انتخاب سررسیدها ═══════════

def _pay(**kw):
    d = {"_id": "p1", "status": "zarinpal_pending",
         "submitted_at": _iso(1_900_000.0), "final_price": 50000,
         "dunning_sent": []}
    d.update(kw)
    return d


def test_dunning_due_happy_path():
    now = 2_000_000.0
    due = gr.dunning_due([_pay()], now, [3600, 86400])
    assert len(due) == 1 and due[0][1] == 0  # گام اول


def test_dunning_due_step2_after_step1():
    now = 2_000_000.0
    p = _pay(submitted_at=_iso(now - 90_000), dunning_sent=[0])
    due = gr.dunning_due([p], now, [3600, 86400])
    assert len(due) == 1 and due[0][1] == 1


def test_dunning_due_skips():
    now = 2_000_000.0
    pays = [
        _pay(_id="young", submitted_at=_iso(now - 100)),   # خیلی تازه
        _pay(_id="done", submitted_at=_iso(now - 90_000),
             dunning_sent=[0, 1]),                          # هر دو گام رفته
        _pay(_id="paid", status="approved"),                # پرداخت‌شده
        _pay(_id="exp", status="zarinpal_expired"),          # منقضی
        _pay(_id="free", final_price=0),                     # رایگان
        _pay(_id="baddate", submitted_at="garbage"),         # تاریخ خراب
        _pay(_id="nodate", submitted_at=None),
        "not-a-dict",
        None,
    ]
    assert gr.dunning_due(pays, now, [3600, 86400]) == []


def test_dunning_due_one_step_per_doc():
    # هر دو گام از نظر سنی سررسیده ولی گام ۰ ارسال نشده → فقط گام ۰
    now = 2_000_000.0
    p = _pay(submitted_at=_iso(now - 200_000), dunning_sent=[])
    due = gr.dunning_due([p], now, [3600, 86400])
    assert [i for _, i in due] == [0]


# ═══════════ نگهبان‌های سیم‌کشی (static) ═══════════

def test_wiring_claim_is_atomic_and_status_guarded():
    t = _read("db/referral.py")
    # claim باید اتمیک باشد و فقط روی pending موفق شود (حذف خودکار paid/expired)
    assert "async def dun_mark_sent" in t
    assert "'_id': oid, 'status': 'zarinpal_pending'" in t
    assert "dunning_sent" in t and "$addToSet" in t


def test_wiring_job_guards():
    t = _read("dunning.py")
    assert "merge_dun_config" in t
    assert "if not cfg['enabled']:" in t or 'if not cfg["enabled"]:' in t
    assert "in_quiet_hours" in t and "tehran_hour" in t
    assert "dunning_due" in t and "dun_mark_sent" in t
    assert "dun:resume:" in t  # دکمه‌ی ادامه‌ی پرداخت


def test_wiring_resume_delegates_to_verify():
    t = _read("dunning.py")
    assert "dun_log_click" in t
    assert "from subscription import _zarinpal_check" in t
    # کنترل مالکیت قبل از تفویض
    assert "doc.get('user_id') or 0) != uid" in t


def test_wiring_backend_indexes_stats():
    core = _read("db/core.py")
    assert "W14 — پیگیری" in core
    assert "[('status', 1), ('created_at', -1)]" in core
    assert (REPO / "db/referral.py").exists()
    t = _read("db/referral.py")
    assert "async def dun_recent_pending" in t
    assert "async def dun_stats" in t


def test_wiring_admin_and_ui():
    wa = _read("api/routers/web_admin.py")
    assert "growth_stats" in wa or "/growth/stats" in wa
    assert "dun_stats" in wa
    g = _read("webadmin/src/pages/Growth.jsx")
    assert "DunningTab" in g
    assert "quiet_start" in g and "step1_s" in g
    assert "paid_after_reminder" in g
