"""W13 — ریفرال (زیرساخت خفته): قوانین خالص + نگهبان‌های سیم‌کشی استاتیک.

pure: growth_rules بدون هیچ وابستگی (CI بدون Mongo امن است).
static: متن‌خوانی فایل‌ها — بدون import ماژول‌های سنگین (bson/motor لازم نیست).
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import growth_rules as gr


def _read(rel):
    return (REPO / rel).read_text(encoding="utf-8")


# ═══════════ قوانین خالص ═══════════

def test_parse_ref_start_arg():
    # کد معتبر: دقیقاً ۸ نویسه از الفبای بدون ابهام (بدون 0/O/1/I/L)
    assert gr.parse_ref_start_arg("ref_AB23CD45") == "AB23CD45"
    # ورودی بات فقط args[0] است («ref_XXXX» خالص)؛ پیشوند کامل /start معتبر نیست
    assert gr.parse_ref_start_arg("/start ref_ab23cd45") is None
    assert gr.parse_ref_start_arg("  ref_AB23CD45\n") == "AB23CD45"
    assert gr.parse_ref_start_arg("hello") is None
    assert gr.parse_ref_start_arg("ref_") is None
    assert gr.parse_ref_start_arg("") is None
    assert gr.parse_ref_start_arg(None) is None
    assert gr.parse_ref_start_arg("  ref_X1  ") is None  # طول ≠ ۸
    # «1» در الفبا نیست → None (ضدتقلب/تایپی)
    assert gr.parse_ref_start_arg("ref_AB12CD34") is None
    assert gr.parse_ref_start_arg("ref_AB!23CD4") is None


def test_make_ref_code():
    seen = set()
    for _ in range(200):
        c = gr.make_ref_code()
        assert len(c) == gr.REF_CODE_LEN == 8
        assert all(ch in gr.REF_CODE_ALPHABET for ch in c)
        assert not set(c) & set("0O1IL")  # بدون نویسه‌ی اشتباه‌شونده
        seen.add(c)
    assert len(seen) == 200  # یکتایی عملی


def test_ref_link():
    assert gr.ref_link("MyBot", "AB12CD34") == \
        "https://t.me/MyBot?start=ref_AB12CD34"
    assert "ref_" in gr.ref_link("", "X")


def test_split_amounts():
    assert gr.split_amounts(7) == (4, 3)   # نصف اول رو به بالا
    assert gr.split_amounts(8) == (4, 4)
    assert gr.split_amounts(1) == (1, 0)
    assert gr.split_amounts(0) == (0, 0)
    assert gr.split_amounts(-5) == (0, 0)
    a, b = gr.split_amounts(999)
    assert a + b == 999  # پایستگی جمع


def test_merge_ref_config_defaults_off():
    cfg = gr.merge_ref_config(None)
    assert cfg["enabled"] is False      # خفته به‌صورت پیش‌فرض
    assert cfg["timing"] == "split"
    assert cfg["cap_daily"] == 5
    assert all(v["on"] is False for v in cfg["rewards"].values())
    assert set(cfg["rewards"]) == {"sub_days", "wallet", "discount", "xp"}
    # پیش‌فرض مقدارها از جدول انواع
    assert cfg["rewards"]["sub_days"]["amount"] == 7
    assert cfg["rewards"]["discount"]["amount"] == 20


def test_merge_ref_config_invalid_timing_and_caps():
    cfg = gr.merge_ref_config({"timing": "whenever", "cap_daily": -3,
                               "burst_n": "xx"})
    assert cfg["timing"] == "split"
    assert cfg["cap_daily"] == 0
    assert cfg["burst_n"] == 5  # نامعتبر → پیش‌فرض


def test_merge_ref_config_rewards_clamp():
    cfg = gr.merge_ref_config({"rewards": {
        "sub_days": {"on": True, "amount": 99999},
        "wallet": {"on": 1, "amount": -50},
        "discount": {"on": True, "amount": 0},
        "xp": {"amount": "abc"},
        "bogus": {"on": True, "amount": 5},
    }})
    assert cfg["rewards"]["sub_days"] == {"on": True, "amount": 365}
    assert cfg["rewards"]["wallet"] == {"on": True, "amount": 0}
    assert cfg["rewards"]["discount"] == {"on": True, "amount": 0}
    assert cfg["rewards"]["xp"] == {"on": False, "amount": 100}
    assert "bogus" not in cfg["rewards"]


def test_burst_flagged():
    now = 1_000_000.0
    assert gr.burst_flagged([now - 10, now - 60, now - 120], now,
                            3, 300) is True
    assert gr.burst_flagged([now - 10, now - 60, now - 900], now,
                            3, 300) is False
    assert gr.burst_flagged([now - 10], now, 3, 300) is False  # کمتر از آستانه
    assert gr.burst_flagged([], now, 3, 300) is False
    assert gr.burst_flagged([now - 1] * 5, now, 1, 60) is False  # n<=1 خاموش


def test_describe_granted():
    assert gr.describe_granted(None) == ""
    assert gr.describe_granted({}) == ""
    txt = gr.describe_granted({
        "sub_days": {"days": 3},
        "wallet": {"amount": 25000},
        "discount": {"code": "G-AB12", "percent": 20},
        "xp": {"xp": 100},
    })
    assert "3 روز اشتراک" in txt
    assert "25,000 تومان" in txt
    assert "G-AB12" in txt and "20٪" in txt
    assert "100 امتیاز پرستیژ" in txt


# ═══════════ نگهبان‌های سیم‌کشی (static) ═══════════

def test_wiring_start_attribution():
    t = _read("start.py")
    assert "context.user_data['pending_ref']" in t          # stash
    assert t.count("context.user_data.pop('pending_ref', None)") == 2  # consume ×۲
    assert "'pending_ref'" in t and "reg_group', 'pending_ref'" in t   # cleanup
    assert t.count("_ref_attribute(uid, _pr, 'bot')") == 2


def test_wiring_registration_ref():
    t = _read("api/routers/registration.py")
    assert 'ref: Optional[str] = ""' in t
    assert "_ref_attribute(uid, body.ref, 'miniapp')" in t


def test_wiring_finalize_hook():
    t = _read("db/finance.py")
    assert "def _referral_first_buy_trigger(fn):" in t
    assert "    @_referral_first_buy_trigger" in t
    assert "async def finalize_approved_payment" in t
    assert "from referral import on_first_payment" in t
    assert "logger.exception('referral first-buy hook failed')" in t


def test_wiring_profile_button():
    t = _read("profile.py")
    assert "async def _profile_keyboard" in t
    assert t.count("await _profile_keyboard(user)") == 7
    assert "callback_data='ref:menu'" in t
    assert "from referral import is_enabled as _ref_on" in t


def test_wiring_bot():
    t = _read("bot.py")
    assert "from referral import referral_callback" in t
    assert "from dunning import dunning_job, dunning_click" in t
    assert "r'^ref:'" in t and "r'^dun:'" in t
    assert "name='dunning_tick'" in t


def test_wiring_api_mine():
    t = _read("api/routers/referral.py")
    assert '"/mine"' in t and '"referral_mine"' in t
    assert '{"enabled": False}' in t or '{"enabled": False}' in t.replace(" ", "")
    main = _read("api/main.py")
    assert "    referral," in main
    assert 'prefix="/api/referral"' in main


def test_wiring_webadmin_backend():
    t = _read("api/routers/web_admin.py")
    assert '"/growth/config"' in t
    assert '"/growth/referrals"' in t
    assert '"/growth/stats"' in t
    assert '"/growth/referrals/{rid}/review"' in t
    assert t.count('_perm("subscription.manage")') >= 5
    assert "تغییر کانفیگ رشد" in t  # audit اجباری


def test_wiring_webadmin_frontend():
    api = _read("webadmin/src/api.js")
    for m in ("growthConfig", "growthUpdateConfig", "growthReferrals",
              "growthReview", "growthStats"):
        assert m in api
    app = _read("webadmin/src/app.jsx")
    assert "import('./pages/Growth.jsx')" in app
    assert "'/growth': Growth" in app
    assert "{ path: '/growth'" in app
    assert (REPO / "webadmin/src/pages/Growth.jsx").exists()
    g = _read("webadmin/src/pages/Growth.jsx")
    assert "subscription.manage" in g and "dunning" in g.lower()


def test_wiring_miniapp():
    reg = _read("miniapp/src/components/shared/Register.jsx")
    assert "getStartParam" in reg
    assert "getStartParam() || ''" in reg
    prof = _read("miniapp/src/pages/Me/Profile.jsx")
    assert "function ReferralCard({ data })" in prof
    assert "referral?.enabled" in prof
    assert prof.count("'referral-mine'") == 2  # کوئری + invalidation


def test_wiring_db():
    core = _read("db/core.py")
    assert "self.referrals     = _db['referrals']" in core
    assert core.count("self._index(self.referrals,") == 4
    assert "[('invitee_id', 1)], unique=True" in core
    assert "[('ref_code', 1)], unique=True" in core
    init = _read("db/__init__.py")
    assert "DBReferral" in init
    database = _read("database.py")
    assert "DBReferral" in database
    wallet = _read("db/wallet.py")
    assert "TX_REFERRAL_CREDIT = 'referral_credit'" in wallet
    assert "TX_REFERRAL_CREDIT: 'جایزه دعوت دوستان'" in wallet
    prestige = _read("db/prestige.py")
    assert "kind == 'referral'" in prestige


def test_modules_have_entrypoints():
    ref = _read("referral.py")
    for fn in ("async def attribute", "async def on_first_payment",
               "async def invite_link_for", "async def referral_callback",
               "async def notify_inviter", "async def is_enabled"):
        assert fn in ref
    dun = _read("dunning.py")
    for fn in ("async def dunning_job", "async def dunning_click",
               "def build_message"):
        assert fn in dun
