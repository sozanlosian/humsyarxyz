# -*- coding: utf-8 -*-
"""💰 W6 — کیف پول داخلی: ledger/idempotency/هم‌زمانی + refund→wallet +
خرید با کیف پول روی همان سیستم اشتراک + مغایرت‌گیری + امنیت.

قراردادها:
- هر اثر اقتصادی دقیقاً یک بار (کلید یکتای ref) حتی زیر دابل‌کلیک/ری‌تری؛
- debit اتمیک شرطی → موجودی منفی ناممکن؛ دو خرید هم‌زمان روی موجودی
  یکسان → فقط یکی برنده؛
- refund = گذار اتمیک + اعتبار کیف پول با reference متقابل؛
- خرید با کیف پول مسیر موازی نیست (همان sub_payments + finalize)؛
- خطای فعال‌سازی → compensating reversal؛
- مغایرت «بازگشت وجه بدون اعتبار» پرچم+اقدام امن idempotent دارد؛
- دانشجو فقط کیف پول خودش؛ ادمین با permission.
بدون Mongo → Skip (CI)."""
import asyncio
import hashlib
import hmac
import json
import os
import socket
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode

from bson import ObjectId as OID

ROOT = Path(__file__).resolve().parents[1]

ADMIN_UID = 889701
STUDENT_A = 889702
STUDENT_B = 889703
TEST_TOKEN = "123456:W6-WALLET-TOKEN"

PLAN_W6 = OID(f"{401:024x}")       # ۱۲۰٬۰۰۰ تومان — ۳۰ روز
PLAN_BAD_W6 = OID(f"{402:024x}")   # days=0 → جبران reversal
PAY_W6_REFUND = OID(f"{403:024x}") # رسید approved برای refund→wallet
PAY_W6_ORPHAN = OID(f"{404:024x}") # refunded بدون اعتبار → مغایرت


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _mongo_available() -> bool:
    uri = os.getenv("MONGODB_URI", "")
    if not (uri.startswith("mongodb://127.0.0.1")
            or uri.startswith("mongodb://localhost")):
        return False
    host, _, port = uri[len("mongodb://"):].partition(":")
    try:
        with socket.create_connection((host, int(port or 27017)), timeout=1):
            return True
    except OSError:
        return False


def _signed_init_data(uid: int) -> str:
    token = os.environ.setdefault("TELEGRAM_TOKEN", TEST_TOKEN)
    user = {"id": uid, "first_name": "W6", "username": "w6_test"}
    pairs = {"user": json.dumps(user, separators=(",", ":")),
             "auth_date": str(int(time.time()))}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**pairs, "hash": digest})


class WalletStaticTests(unittest.TestCase):
    """گارد ساختاری: گیت مجوزها، ایندکس یکتا، debit شرطی، سیم‌کشی UI."""

    def setUp(self):
        self.wa = read("api", "routers", "web_admin.py")
        self.wallet_db = read("db", "wallet.py")
        self.sub_router = read("api", "routers", "subscription.py")
        self.finance_db = read("db", "finance.py")

    def test_admin_wallet_routes_perm_gated(self):
        for route in ('"/wallets"', '"/wallets/{uid}"',
                      '"/wallets/{uid}/adjust"',
                      '"/subscription/reconcile/wallet-recredit"'):
            idx = self.wa.index(f"@router.get({route})" if "adjust" not in route
                                and "recredit" not in route
                                else f"@router.post({route})")
            self.assertIn('_perm("subscription.manage")',
                          self.wa[idx:idx + 900], route)

    def test_ledger_invariants_in_db_layer(self):
        # کلید یکتای تراکنش = idempotency؛ debit شرطی = بدون موجودی منفی
        self.assertIn("reference_type", self.wallet_db)
        self.assertIn("DuplicateKeyError", self.wallet_db)
        self.assertIn("'balance': {'$gte': -delta}", self.wallet_db)
        # ledger اصلاح‌پذیر silent نیست — فقط compensating transaction
        self.assertIn("TX_REVERSAL", self.wallet_db)

    def test_student_api_self_scoped(self):
        sub = read("api", "routers", "subscription.py")
        self.assertIn('"/wallet"', sub)
        self.assertIn('"/buy-wallet"', sub)
        # منطق خرید در db است، نه endpoint (جلوگیری از منطق موازی)؛
        # تخفیف هم به همان سرویس واحد سپرده می‌شود
        self.assertIn("db.wallet_purchase(user_id, body.plan_id, body.idem",
                      sub)
        self.assertIn("discount_code=body.discount_code", sub)
        self.assertIn("async def wallet_purchase", self.wallet_db)
        self.assertIn("discount_validate", self.wallet_db)
        self.assertIn("discount_consume", self.wallet_db)

    def test_topup_wired_end_to_end(self):
        """🌊 W6.2 — شارژ کیف پول: یک مسیر مالی، سه کلاینت، صفر منطق موازی."""
        # API دانشجو: اندپوینت شارژ روی همان زیرساخت رسید
        self.assertIn('"/topup"', self.sub_router)
        self.assertIn('plan_id="wallet_topup"', self.sub_router)
        # تنها نقطه‌ی اعتبار: finalize (مشترک بات/وب)
        self.assertIn("wallet_topup", self.finance_db)
        self.assertIn("sub_payment_topup", self.finance_db)
        self.assertIn("TX_TOPUP = 'topup_credit'", self.wallet_db)
        # بات: پروفایل → کیف پول، جریان رسید شارژ، شعبه‌ی تأیید
        prof = read("profile.py")
        self.assertIn("sub:wallet", prof)
        bot = read("subscription.py")
        self.assertIn("topup_screenshot_handler", bot)
        self.assertIn("is_topup", bot)
        # مینی‌اپ: فرم شارژ با رسید
        self.assertIn("/api/subscription/topup", read(
            "miniapp", "src", "pages", "Me", "Subscription.jsx"))
        # وب‌ادمین: اقدام مغایرت + گارد refund
        self.assertIn("finalize-topup", self.wa)
        self.assertIn("topup_without_wallet_credit", self.wallet_db)
        api_js = read("webadmin", "src", "api.js")
        self.assertIn("subReconFinalizeTopup:", api_js)

    def test_refund_credits_wallet(self):
        idx = self.wa.index("async def wa_subscription_refund")
        body = self.wa[idx:idx + 3000]
        self.assertIn("wallet_credit", body)
        self.assertIn('"sub_payment_refund"', body)

    def test_resolve_endpoint_perm_gated(self):
        idx = self.wa.index('@router.post("/wallet-tx/{tx_id}/resolve")')
        self.assertIn('_perm("subscription.manage")',
                      self.wa[idx:idx + 600])
        # تشخیص کرش در لایه‌ی db است و evidence-based
        self.assertIn("async def wallet_resolve_pending", self.wallet_db)
        self.assertIn("_wallet_ok_ledger_sum", self.wallet_db)

    def test_ui_wired(self):
        api_js = read("webadmin", "src", "api.js")
        for fn in ("subWallets:", "subWalletDetail:", "subWalletAdjust:",
                   "subWalletRecredit:", "subWalletResync:",
                   "subWalletTxResolve:"):
            self.assertIn(fn, api_js, fn)
        sub_jsx = read("webadmin", "src", "pages", "Subscriptions.jsx")
        self.assertIn("کیف پول", sub_jsx)
        self.assertIn("تعیین تکلیف", sub_jsx)


@unittest.skipUnless(_mongo_available(), "MongoDB در دسترس نیست (CI)")
class WalletRuntimeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("TELEGRAM_TOKEN", TEST_TOKEN)
        os.environ["ADMIN_ID"] = str(ADMIN_UID)
        os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
        import httpx
        cls.httpx = httpx
        import api.main as main_mod
        cls.app = main_mod.app
        from database import db
        cls.db = db
        cls.admin_h = {"X-Init-Data": _signed_init_data(ADMIN_UID)}
        cls.a_h = {"X-Init-Data": _signed_init_data(STUDENT_A)}
        cls.b_h = {"X-Init-Data": _signed_init_data(STUDENT_B)}
        from _rtloop import adopt
        adopt()
        cls._run(cls._prepare())

    @classmethod
    def tearDownClass(cls):
        cls._run(cls._clean())

    @classmethod
    def _run(cls, coro):
        from _rtloop import run
        return run(coro)

    @classmethod
    async def _prepare(cls):
        db = cls.db
        # تولید در shared bootstrap ایندکس‌ها را می‌سازد؛ تست هم همان را
        # انجام می‌دهد — idempotency مالی به unique index واقعی تکیه دارد
        await db.ensure_indexes()
        for uid, name, role in ((ADMIN_UID, "W6 Admin", "admin"),
                                (STUDENT_A, "علی رضایی", "student"),
                                (STUDENT_B, "سارا محمدی", "student")):
            await db.users.update_one({"user_id": uid}, {"$set": {
                "user_id": uid, "name": name, "student_id": f"98{uid % 1000}",
                "role": role, "approved": True, "suspended": False}},
                upsert=True)
        await cls._clean()
        await db.sub_plans.update_one({"_id": PLAN_W6}, {"$set": {
            "name": "ماهانه", "days": 30, "price": 120000,
            "active": True}}, upsert=True)
        await db.sub_plans.update_one({"_id": PLAN_BAD_W6}, {"$set": {
            "name": "پلن خراب", "days": 0, "price": 10000,
            "active": True}}, upsert=True)
        await db.sub_payments.update_one({"_id": PAY_W6_REFUND}, {"$set": {
            "user_id": STUDENT_A, "plan_id": str(PLAN_W6), "plan_name": "ماهانه",
            "price": 120000, "final_price": 120000, "status": "approved",
            "reviewed_at": "2026-01-02T00:00:00+00:00",
            "submitted_at": "2026-01-01T00:00:00+00:00"}}, upsert=True)
        await db.sub_payments.update_one({"_id": PAY_W6_ORPHAN}, {"$set": {
            "user_id": STUDENT_B, "plan_id": str(PLAN_W6), "plan_name": "ماهانه",
            "price": 120000, "final_price": 120000, "status": "refunded",
            "refunded_at": "2026-01-03T00:00:00+00:00",
            "submitted_at": "2026-01-01T00:00:00+00:00"}}, upsert=True)

    @classmethod
    async def _clean(cls):
        db = cls.db
        uids = [ADMIN_UID, STUDENT_A, STUDENT_B]
        await db.wallets.delete_many({"user_id": {"$in": uids}})
        await db.wallet_transactions.delete_many({"user_id": {"$in": uids}})
        await db.sub_payments.delete_many(
            {"$or": [{"_id": {"$in": [PAY_W6_REFUND, PAY_W6_ORPHAN]}},
                     {"user_id": {"$in": uids}, "method": "wallet"},
                     {"plan_id": "wallet_topup",
                      "user_id": {"$in": uids}}]})
        await db.subscriptions.delete_many({"_id": {"$in": uids}})
        await db.sub_plans.delete_many(
            {"_id": {"$in": [PLAN_W6, PLAN_BAD_W6]}})
        await db.audit_logs.delete_many(
            {"target.id": {"$in": [str(PAY_W6_REFUND), str(PAY_W6_ORPHAN),
                                   str(STUDENT_A), str(STUDENT_B)]}})
        await db.discount_codes.delete_many({"code": "W6TEST20"})
        await db.discount_uses.delete_many({"code": "W6TEST20"})

    @classmethod
    def _reset_wallets(cls, uids):
        """ایزولاسیون تست: هر تست با کیف پول صفرِ خودش شروع می‌شود."""
        async def run():
            await cls.db.wallets.delete_many({"user_id": {"$in": uids}})
            await cls.db.wallet_transactions.delete_many(
                {"user_id": {"$in": uids}})
        cls._run(run())

    def _client_ctx(self):
        return self.httpx.AsyncClient(
            transport=self.httpx.ASGITransport(app=self.app),
            base_url="http://test")

    # ── هسته‌ی ledger ──────────────────────────────────────────
    def test_provision_idempotent_concurrent(self):
        async def run():
            w1 = await self.db.wallet_get_or_create(STUDENT_A)
            w2 = await self.db.wallet_get_or_create(STUDENT_A)
            assert w1["_id"] == w2["_id"]
            ws = await asyncio.gather(
                *[self.db.wallet_get_or_create(STUDENT_A) for _ in range(8)])
            assert len({str(w["_id"]) for w in ws}) == 1
            assert await self.db.wallets.count_documents(
                {"user_id": STUDENT_A}) == 1
        self._run(run())

    def test_credit_debit_and_idempotency(self):
        self._reset_wallets([STUDENT_B])
        async def run():
            db = self.db
            t1 = await db.wallet_credit(STUDENT_B, 50000, "refund_credit",
                                        "unit", "k1", ADMIN_UID, "تست")
            assert t1["balance_after"] == 50000
            t1b = await db.wallet_credit(STUDENT_B, 50000, "refund_credit",
                                         "unit", "k1", ADMIN_UID, "تست")
            assert str(t1b["_id"]) == str(t1["_id"])  # بدون اعتبار دوم
            w = await db.wallet_get_for_user_id(STUDENT_B)
            assert int(w["balance"]) == 50000
            t2 = await db.wallet_debit(STUDENT_B, 20000, "subscription_purchase",
                                       "unit", "k2", STUDENT_B, "تست")
            assert t2["balance_before"] == 50000 and t2["balance_after"] == 30000
            # موجودی ناکافی → خطا با کد + موجودی دست‌نخورده
            from db.wallet import WalletError
            try:
                await db.wallet_debit(STUDENT_B, 999999, "subscription_purchase",
                                      "unit", "k3", STUDENT_B, "تست")
                assert False, "باید insufficient_balance می‌گرفت"
            except WalletError as e:
                assert e.code == "insufficient_balance"
            w = await db.wallet_get_for_user_id(STUDENT_B)
            assert int(w["balance"]) == 30000
        self._run(run())

    # ── refund → wallet (E2E) ─────────────────────────────────
    def test_refund_credits_wallet_once(self):
        self._reset_wallets([STUDENT_A])
        async def run():
            await self.db.sub_payments.update_one(
                {"_id": PAY_W6_REFUND},
                {"$set": {"status": "approved"}})
            await self.db.wallet_transactions.delete_many(
                {"reference_type": "sub_payment_refund",
                 "reference_id": str(PAY_W6_REFUND)})
            async with self._client_ctx() as c:
                r = await c.post(
                    f"/api/web-admin/subscription/payments/{PAY_W6_REFUND}/refund",
                    headers=self.admin_h,
                    json={"confirm": True, "reason": "انصراف دانشجو",
                          "revoke_subscription": False})
                assert r.status_code == 200, r.text
                d = r.json()
                assert d["wallet_credited"] is True
                assert d["wallet_balance_after"] == 120000
                # دابل‌کلیک ادمین → ۴۰۹ و بدون اعتبار دوم
                r2 = await c.post(
                    f"/api/web-admin/subscription/payments/{PAY_W6_REFUND}/refund",
                    headers=self.admin_h,
                    json={"confirm": True, "reason": "انصراف دانشجو"})
                assert r2.status_code == 409
                n = await self.db.wallet_transactions.count_documents(
                    {"reference_type": "sub_payment_refund",
                     "reference_id": str(PAY_W6_REFUND), "status": "ok"})
                assert n == 1, f"اعتبار تکراری: {n}"
                w = await self.db.wallet_get_for_user_id(STUDENT_A)
                assert int(w["balance"]) == 120000
                # trace: زنجیره مالی رسید شامل تراکنش کیف پول است
                r3 = await c.get(
                    f"/api/web-admin/subscription/payments/{PAY_W6_REFUND}/trace",
                    headers=self.admin_h)
                assert any(t["type"] == "refund_credit"
                           for t in r3.json()["wallet_txs"])
        self._run(run())

    # ── خرید با کیف پول (E2E + reuse + دابل‌کلیک) ─────────────
    def test_wallet_purchase_e2e_and_replay(self):
        """reuse: اعتبار بازگشت‌وجه → خرید همان مبلغ → موجودی صفر."""
        self._reset_wallets([STUDENT_A])
        async def run():
            await self.db.wallet_credit(
                STUDENT_A, 120000, "refund_credit", "unit", "e2e-seed",
                ADMIN_UID, "شبیه‌سازی بازگشت وجه")
            async with self._client_ctx() as c:
                r = await c.get("/api/subscription/wallet",
                                headers=self.a_h)
                assert r.status_code == 200
                assert r.json()["balance"] == 120000
                r = await c.post("/api/subscription/buy-wallet",
                                 headers=self.a_h,
                                 json={"plan_id": str(PLAN_W6),
                                       "idem": "w6-e2e-1"})
                assert r.status_code == 200, r.text
                d = r.json()
                assert d["ok"] and d["balance"] == 0
                sub = await self.db.sub_get(STUDENT_A)
                assert sub and sub["status"] == "active"
                pay = await self.db.sub_payment_get(d["payment_id"])
                assert pay["method"] == "wallet" and pay["status"] == "approved"
                # دابل‌کلیک با idem یکسان → همان نتیجه، بدون اثر دوم
                r2 = await c.post("/api/subscription/buy-wallet",
                                  headers=self.a_h,
                                  json={"plan_id": str(PLAN_W6),
                                        "idem": "w6-e2e-1"})
                assert r2.status_code == 200
                assert r2.json()["replay"] is True
                n = await self.db.wallet_transactions.count_documents(
                    {"reference_type": "sub_payment_wallet",
                     "reference_id": d["payment_id"], "status": "ok"})
                assert n == 1
        self._run(run())

    def test_insufficient_balance_error_human(self):
        self._reset_wallets([STUDENT_B])
        async def run():
            async with self._client_ctx() as c:
                r = await c.post("/api/subscription/buy-wallet",
                                 headers=self.b_h,
                                 json={"plan_id": str(PLAN_W6),
                                       "idem": "w6-e2e-poor"})
                assert r.status_code == 400
                detail = r.json()["detail"]
                assert "کافی نیست" in detail and "کسری" in detail
        self._run(run())

    def test_concurrent_purchases_only_one_wins(self):
        self._reset_wallets([STUDENT_B])
        async def run():
            db = self.db
            # موجودی دقیقاً یک پلن؛ دو خرید هم‌زمان با idem متفاوت
            await db.wallet_credit(STUDENT_B, 120000, "admin_credit",
                                   "unit", "conc-credit", ADMIN_UID, "تست")
            results = await asyncio.gather(
                db.wallet_purchase(STUDENT_B, str(PLAN_W6), "w6-conc-a"),
                db.wallet_purchase(STUDENT_B, str(PLAN_W6), "w6-conc-b"),
                return_exceptions=True)
            oks = [r for r in results if isinstance(r, dict)]
            errs = [r for r in results if not isinstance(r, dict)]
            assert len(oks) == 1, f"باید دقیقاً یک خرید موفق باشد: {results}"
            assert getattr(errs[0], "code", "") == "insufficient_balance"
            w = await db.wallet_get_for_user_id(STUDENT_B)
            assert int(w["balance"]) == 0, w["balance"]
            # دقیقاً یک رسید approved برای این دو تلاش
            n = await db.sub_payments.count_documents(
                {"user_id": STUDENT_B, "method": "wallet",
                 "status": "approved"})
            assert n == 1, n
        self._run(run())

    def test_bad_plan_compensates_with_reversal(self):
        self._reset_wallets([STUDENT_B])
        async def run():
            db = self.db
            await db.wallet_credit(STUDENT_B, 10000, "admin_credit",
                                   "unit", "bad-credit", ADMIN_UID, "تست")
            before = int((await db.wallet_get_for_user_id(STUDENT_B))["balance"])
            from db.wallet import WalletError
            try:
                await db.wallet_purchase(STUDENT_B, str(PLAN_BAD_W6),
                                         "w6-bad-plan")
                assert False
            except WalletError as e:
                assert e.code == "plan_days_invalid"
            after = int((await db.wallet_get_for_user_id(STUDENT_B))["balance"])
            assert after == before, "مبلغ باید با reversal برگردد"
            n = await db.wallet_transactions.count_documents(
                {"user_id": STUDENT_B, "type": "reversal", "status": "ok"})
            assert n >= 1
        self._run(run())

    # ── مغایرت‌گیری + اقدام امن ────────────────────────────────
    def test_orphan_refund_flagged_and_repairable(self):
        async def run():
            async with self._client_ctx() as c:
                r = await c.get("/api/web-admin/subscription/reconcile",
                                headers=self.admin_h)
                assert r.status_code == 200
                items = r.json()["items"]
                hit = next((i for i in items
                            if i["type"] == "refund_without_wallet_credit"
                            and i["payment_id"] == str(PAY_W6_ORPHAN)), None)
                assert hit, "بازگشت وجه بدون اعتبار باید پرچم بخورد"
                assert "اعتبار کیف پول ایجاد نشده" in hit["summary"]
                # اقدام امن: تأیید صریح لازم است
                r2 = await c.post(
                    "/api/web-admin/subscription/reconcile/wallet-recredit",
                    headers=self.admin_h,
                    json={"payment_id": str(PAY_W6_ORPHAN), "confirm": False})
                assert r2.status_code == 400
                r3 = await c.post(
                    "/api/web-admin/subscription/reconcile/wallet-recredit",
                    headers=self.admin_h,
                    json={"payment_id": str(PAY_W6_ORPHAN), "confirm": True})
                assert r3.status_code == 200, r3.text
                # اجرای دوباره = idempotent (یک اثر اقتصادی)
                r4 = await c.post(
                    "/api/web-admin/subscription/reconcile/wallet-recredit",
                    headers=self.admin_h,
                    json={"payment_id": str(PAY_W6_ORPHAN), "confirm": True})
                assert r4.status_code == 200
                n = await self.db.wallet_transactions.count_documents(
                    {"reference_type": "sub_payment_refund",
                     "reference_id": str(PAY_W6_ORPHAN), "status": "ok"})
                assert n == 1
                r5 = await c.get("/api/web-admin/subscription/reconcile",
                                 headers=self.admin_h)
                assert not any(i["type"] == "refund_without_wallet_credit"
                               and i["payment_id"] == str(PAY_W6_ORPHAN)
                               for i in r5.json()["items"])
        self._run(run())

    def test_balance_mismatch_detected(self):
        async def run():
            await self.db.wallet_get_or_create(STUDENT_B)
            # خرابکاری عمدی موجودی کش‌شده → مغایرت حسابداری
            await self.db.wallets.update_one({"user_id": STUDENT_B},
                                             {"$inc": {"balance": 7000}})
            async with self._client_ctx() as c:
                r = await c.get("/api/web-admin/subscription/reconcile",
                                headers=self.admin_h)
                hit = next((i for i in r.json()["items"]
                            if i["type"] == "wallet_balance_mismatch"
                            and i["user_id"] == STUDENT_B), None)
                assert hit and hit["amount"] == 7000
            await self.db.wallets.update_one({"user_id": STUDENT_B},
                                             {"$inc": {"balance": -7000}})
        self._run(run())

    # ── امنیت/دامنه ────────────────────────────────────────────
    def test_privacy_and_rbac(self):
        async def run():
            async with self._client_ctx() as c:
                # دانشجو فقط کیف پول خودش را می‌بیند (مسیر user-scoped است)
                r = await c.get("/api/subscription/wallet/transactions",
                                headers=self.b_h)
                assert r.status_code == 200
                assert all(t["direction"] in ("credit", "debit")
                           for t in r.json()["items"])
                # اندپوینت‌های ادمین برای دانشجو ۴۰۳
                for path in ("/api/web-admin/wallets",
                             f"/api/web-admin/wallets/{STUDENT_A}",
                             f"/api/web-admin/wallets/{STUDENT_A}/adjust"):
                    method = "post" if "adjust" in path else "get"
                    r = await getattr(c, method)(path, headers=self.b_h)
                    assert r.status_code == 403, (path, r.status_code)
        self._run(run())

    def test_admin_adjust_requires_confirm_and_audits(self):
        async def run():
            async with self._client_ctx() as c:
                r = await c.post(f"/api/web-admin/wallets/{STUDENT_B}/adjust",
                                 headers=self.admin_h,
                                 json={"amount": 50000, "reason": "x",
                                       "confirm": False})
                assert r.status_code in (400, 422)  # دلیل <۳ نویسه رد است
                r = await c.post(f"/api/web-admin/wallets/{STUDENT_B}/adjust",
                                 headers=self.admin_h,
                                 json={"amount": 50000,
                                       "reason": "بدون تأیید",
                                       "confirm": False})
                assert r.status_code == 400  # تأیید صریح لازم است
                r = await c.post(f"/api/web-admin/wallets/{STUDENT_B}/adjust",
                                 headers=self.admin_h,
                                 json={"amount": 50000, "reason": "اصلاح مالی تست",
                                       "confirm": True})
                assert r.status_code == 200, r.text
                assert r.json()["balance_after"] is not None
                n = await self.db.audit_logs.count_documents(
                    {"action": "تنظیم دستی کیف پول",
                     "target.id": str(STUDENT_B)})
                assert n == 1
        self._run(run())

    def test_discount_wallet_purchase(self):
        """🎟 کد تخفیف روی خرید کیف‌پولی: همان فرمول مسیر رسید + snapshot."""
        self._reset_wallets([STUDENT_A])
        async def run():
            db = self.db
            await db.discount_codes.delete_many({"code": "W6TEST20"})
            await db.discount_add("W6TEST20", 20, max_uses=5)
            await db.wallet_credit(STUDENT_A, 200000, "admin_credit",
                                   "unit", "disc-seed", ADMIN_UID, "تست")
            from db.wallet import WalletError
            # کد نامعتبر → خطای شفاف، بدون اثر مالی
            try:
                await db.wallet_purchase(STUDENT_A, str(PLAN_W6),
                                         "w6-disc-bad",
                                         discount_code="NOPE999")
                assert False
            except WalletError as e:
                assert e.code == "discount_invalid"
            # خرید با تخفیف ۲۰٪ → مبلغ نهایی ۹۶٬۰۰۰
            res = await db.wallet_purchase(STUDENT_A, str(PLAN_W6),
                                           "w6-disc-ok",
                                           discount_code="w6test20")
            assert res["amount"] == 96000, res
            w = await db.wallet_get_for_user_id(STUDENT_A)
            assert int(w["balance"]) == 104000
            pay = await db.sub_payment_get(res["payment_id"])
            assert pay["final_price"] == 96000
            assert pay["discount_code"] == "W6TEST20"
            assert pay["discount_percent"] == 20
            # کد دقیقاً یک بار مصرف شده
            d = await db.discount_codes.find_one({"code": "W6TEST20"})
            assert int(d.get("used_count") or 0) == 1
            await db.discount_codes.delete_many({"code": "W6TEST20"})
            await db.discount_uses.delete_many({"code": "W6TEST20"})
        self._run(run())

    def test_attention_includes_wallet_issues(self):
        """§۶۴ — مغایرت مالی کیف پول باید وارد «نیازمند اقدام» شود."""
        async def run():
            await self.db.wallet_get_or_create(STUDENT_B)
            await self.db.wallets.update_one({"user_id": STUDENT_B},
                                             {"$inc": {"balance": 5000}})
            async with self._client_ctx() as c:
                r = await c.get("/api/web-admin/attention",
                                headers=self.admin_h)
                assert r.status_code == 200
                hit = next((i for i in r.json()["items"]
                            if i["key"] == "wallet_issues"), None)
                assert hit and hit["count"] >= 1, r.json()["items"]
                assert hit["severity"] == "critical"
            await self.db.wallets.update_one({"user_id": STUDENT_B},
                                             {"$inc": {"balance": -5000}})
        self._run(run())

    def test_resync_repairs_mismatch(self):
        """§۹۰ — repair امن: هم‌ترازسازی موجودی کش با ledger + audit."""
        async def run():
            await self.db.wallet_get_or_create(STUDENT_B)
            w0 = await self.db.wallet_get_for_user_id(STUDENT_B)
            ledger = int(w0["balance"])
            await self.db.wallets.update_one({"user_id": STUDENT_B},
                                             {"$inc": {"balance": 7000}})
            async with self._client_ctx() as c:
                r = await c.post(f"/api/web-admin/wallets/{STUDENT_B}/resync",
                                 headers=self.admin_h, json={"confirm": False})
                assert r.status_code == 400
                r = await c.post(f"/api/web-admin/wallets/{STUDENT_B}/resync",
                                 headers=self.admin_h, json={"confirm": True})
                assert r.status_code == 200, r.text
                assert r.json()["balance"] == ledger
                w = await self.db.wallet_get_for_user_id(STUDENT_B)
                assert int(w["balance"]) == ledger
                n = await self.db.audit_logs.count_documents(
                    {"action": "هم‌ترازسازی موجودی کیف پول با ledger",
                     "target.id": str(STUDENT_B)})
                assert n >= 1
                # مغایرت از لیست خارج شد
                r = await c.get("/api/web-admin/subscription/reconcile",
                                headers=self.admin_h)
                assert not any(i["type"] == "wallet_balance_mismatch"
                               and i["user_id"] == STUDENT_B
                               for i in r.json()["items"])
        self._run(run())

    # ── 🌊 W6.1 — کرش‌ریکاوری عمیق: تراکنش معلق ───────────────
    async def _inject_pending(self, uid, amount, ref, direction="credit",
                              simulate_applied=False):
        """تراکنش pending دستی = شبیه‌سازی کرش بین مراحل؛ اگر
        simulate_applied=True اثر مالی هم (بدون نشان‌گذاری) روی موجودی است."""
        from time_utils import utc_now_iso
        r = await self.db.wallet_transactions.insert_one({
            "user_id": uid,
            "type": "refund_credit" if direction == "credit"
                    else "subscription_purchase",
            "direction": direction, "amount": amount,
            "currency": "تومان",
            "reference_type": "pending_test", "reference_id": ref,
            "balance_before": None, "balance_after": None,
            "label": "تست کرش", "actor_id": 0, "status": "pending",
            "created_at": "2026-01-01T00:00:00+00:00"})
        if simulate_applied:
            delta = amount if direction == "credit" else -amount
            await self.db.wallets.update_one({"user_id": uid},
                                             {"$inc": {"balance": delta}})
        return str(r.inserted_id)

    async def _assert_ledger_invariant(self, uid):
        w = await self.db.wallet_get_for_user_id(uid)
        ledger = await self.db._wallet_ok_ledger_sum(uid)
        assert int(w["balance"]) == ledger, \
            f"invariant شکست: balance={w['balance']} ledger={ledger}"

    def test_resolve_pending_not_applied(self):
        """کرش قبل از اعمال → complete اثر را اتمیک اعمال می‌کند."""
        async def run():
            await self.db.wallet_get_or_create(STUDENT_B)
            tx_id = await self._inject_pending(STUDENT_B, 25000, "nx1")
            b0 = int((await self.db.wallet_get_for_user_id(
                STUDENT_B))["balance"])
            async with self._client_ctx() as c:
                # در مغایرت‌گیری پرچم می‌خورد و اکشن تعیین تکلیف دارد
                r = await c.get("/api/web-admin/subscription/reconcile",
                                headers=self.admin_h)
                hit = next((i for i in r.json()["items"]
                            if i["type"] == "wallet_tx_stuck_pending"
                            and i["user_id"] == STUDENT_B), None)
                assert hit and any(a.get("tx_id") == tx_id
                                   for a in hit["actions"])
                # بدون تأیید → ۴۰۰
                r = await c.post(f"/api/web-admin/wallet-tx/{tx_id}/resolve",
                                 headers=self.admin_h,
                                 json={"action": "complete", "confirm": False})
                assert r.status_code == 400
                r = await c.post(f"/api/web-admin/wallet-tx/{tx_id}/resolve",
                                 headers=self.admin_h,
                                 json={"action": "complete", "confirm": True})
                assert r.status_code == 200, r.text
                assert r.json()["resolution"] == "applied_now"
                w = await self.db.wallet_get_for_user_id(STUDENT_B)
                assert int(w["balance"]) == b0 + 25000
                # تعیین تکلیف دوباره → ۴۰۹ (اثر دوم هرگز)
                r = await c.post(f"/api/web-admin/wallet-tx/{tx_id}/resolve",
                                 headers=self.admin_h,
                                 json={"action": "complete", "confirm": True})
                assert r.status_code == 409
            await self._assert_ledger_invariant(STUDENT_B)
        self._run(run())

    def test_resolve_pending_applied_detection(self):
        """کرش بعد از $inc → تشخیص evidence-based: فقط نشان‌گذاری، بدون اثر دوم."""
        async def run():
            await self.db.wallet_get_or_create(STUDENT_B)
            tx_id = await self._inject_pending(STUDENT_B, 10000, "nx2",
                                               simulate_applied=True)
            b0 = int((await self.db.wallet_get_for_user_id(
                STUDENT_B))["balance"])
            async with self._client_ctx() as c:
                r = await c.post(f"/api/web-admin/wallet-tx/{tx_id}/resolve",
                                 headers=self.admin_h,
                                 json={"action": "complete", "confirm": True})
                assert r.status_code == 200, r.text
                assert r.json()["resolution"] == "marked_applied"
                w = await self.db.wallet_get_for_user_id(STUDENT_B)
                assert int(w["balance"]) == b0, "اثر دوم اعمال شد!"
            await self._assert_ledger_invariant(STUDENT_B)
        self._run(run())

    def test_cancel_applied_credit_compensates(self):
        """لغوِ اعتبارِ اعمال‌شده = compensating debit، نه بازنویسی ledger."""
        async def run():
            await self.db.wallet_get_or_create(STUDENT_B)
            tx_id = await self._inject_pending(STUDENT_B, 8000, "nx3",
                                               simulate_applied=True)
            b0 = int((await self.db.wallet_get_for_user_id(
                STUDENT_B))["balance"])
            async with self._client_ctx() as c:
                r = await c.post(f"/api/web-admin/wallet-tx/{tx_id}/resolve",
                                 headers=self.admin_h,
                                 json={"action": "cancel", "confirm": True})
                assert r.status_code == 200, r.text
                assert r.json()["resolution"] == "cancelled"
                w = await self.db.wallet_get_for_user_id(STUDENT_B)
                assert int(w["balance"]) == b0 - 8000
                n = await self.db.wallet_transactions.count_documents(
                    {"reference_type": "pending_cancel",
                     "reference_id": tx_id, "status": "ok"})
                assert n == 1
            await self._assert_ledger_invariant(STUDENT_B)
        self._run(run())

    def test_resync_blocked_while_pending_exists(self):
        async def run():
            await self.db.wallet_get_or_create(STUDENT_B)
            tx_id = await self._inject_pending(STUDENT_B, 5000, "nx4")
            async with self._client_ctx() as c:
                r = await c.post(f"/api/web-admin/wallets/{STUDENT_B}/resync",
                                 headers=self.admin_h, json={"confirm": True})
                assert r.status_code == 409
                # بعد از تعیین تکلیف، resync آزاد است
                r = await c.post(f"/api/web-admin/wallet-tx/{tx_id}/resolve",
                                 headers=self.admin_h,
                                 json={"action": "cancel", "confirm": True})
                assert r.status_code == 200
                r = await c.post(f"/api/web-admin/wallets/{STUDENT_B}/resync",
                                 headers=self.admin_h, json={"confirm": True})
                assert r.status_code == 200
            await self._assert_ledger_invariant(STUDENT_B)
        self._run(run())

    def test_concurrent_same_ref_credit_once(self):
        """دو credit هم‌زمان با مرجع یکسان → دقیقاً یک اثر اقتصادی."""
        self._reset_wallets([STUDENT_B])
        async def run():
            await self.db.wallet_get_or_create(STUDENT_B)
            w0 = int((await self.db.wallet_get_for_user_id(
                STUDENT_B))["balance"])
            await asyncio.gather(
                self.db.wallet_credit(STUDENT_B, 30000, "refund_credit",
                                      "unit", "race-ref", ADMIN_UID, "تست"),
                self.db.wallet_credit(STUDENT_B, 30000, "refund_credit",
                                      "unit", "race-ref", ADMIN_UID, "تست"))
            n = await self.db.wallet_transactions.count_documents(
                {"reference_type": "unit", "reference_id": "race-ref"})
            assert n == 1, f"تراکنش تکراری: {n}"
            w = await self.db.wallet_get_for_user_id(STUDENT_B)
            assert int(w["balance"]) == w0 + 30000
            await self._assert_ledger_invariant(STUDENT_B)
        self._run(run())

    def test_ledger_invariant_after_mixed_ops(self):
        """پس از توالی مخلوط عملیات‌ها: balance == جمع جبری ledgerِ ok."""
        async def run():
            for uid in (STUDENT_A, STUDENT_B):
                await self._assert_ledger_invariant(uid)
        self._run(run())

    # ── 🌊 W6.2 — شارژ کیف پول با رسید بانکی ──────────────────
    async def _make_topup_payment(self, uid, amount):
        await self.db.sub_payments.delete_many(
            {"plan_id": "wallet_topup", "user_id": uid})
        return await self.db.sub_payment_create(
            user_id=uid, plan_id="wallet_topup", plan_name="شارژ کیف پول",
            price=amount, final_price=amount, screenshot_file_id="tgfile")

    def test_topup_finalize_credits_once(self):
        """تأیید رسید شارژ = اعتبار کیف پول؛ ری‌تری finalize اثر دوم ندارد."""
        self._reset_wallets([STUDENT_A])
        async def run():
            db = self.db
            await db.wallet_get_or_create(STUDENT_A)
            pid = await self._make_topup_payment(STUDENT_A, 40000)
            assert await db.sub_payment_decide(pid, approved=True,
                                               admin_id=ADMIN_UID)
            res = await db.finalize_approved_payment(
                await db.sub_payment_get(pid), ADMIN_UID)
            assert res["is_topup"] and res["amount"] == 40000
            w = await db.wallet_get_for_user_id(STUDENT_A)
            assert int(w["balance"]) == 40000
            # اجرای دوباره (کرش/ری‌تری) → already، بدون اعتبار دوم
            res2 = await db.finalize_approved_payment(
                await db.sub_payment_get(pid), ADMIN_UID)
            assert res2["already"]
            w = await db.wallet_get_for_user_id(STUDENT_A)
            assert int(w["balance"]) == 40000
            n = await db.wallet_transactions.count_documents(
                {"reference_type": "sub_payment_topup",
                 "reference_id": pid, "type": "topup_credit"})
            assert n == 1, f"تراکنش شارژ تکراری: {n}"
            await self._assert_ledger_invariant(STUDENT_A)
        self._run(run())

    def test_topup_refund_guarded(self):
        """رسید شارژ مسیر بازگشت وجه به کیف پول ندارد (پرداخت دوبرابر ممنوع)."""
        self._reset_wallets([STUDENT_A])
        async def run():
            db = self.db
            await db.wallet_get_or_create(STUDENT_A)
            pid = await self._make_topup_payment(STUDENT_A, 30000)
            await db.sub_payment_decide(pid, approved=True,
                                        admin_id=ADMIN_UID)
            await db.finalize_approved_payment(
                await db.sub_payment_get(pid), ADMIN_UID)
            async with self._client_ctx() as c:
                r = await c.post(
                    f"/api/web-admin/subscription/payments/{pid}/refund",
                    headers=self.admin_h,
                    json={"confirm": True, "reason": "تست شارژ"})
                assert r.status_code == 409, r.text
                w = await db.wallet_get_for_user_id(STUDENT_A)
                assert int(w["balance"]) == 30000
            await self._assert_ledger_invariant(STUDENT_A)
        self._run(run())

    def test_topup_reconcile_and_finalize_endpoint(self):
        """تأییدشده‌ی بدون اعتبار → مغایرت بحرانی؛ اقدام تعمیر = finalize."""
        self._reset_wallets([STUDENT_B])
        async def run():
            db = self.db
            await db.wallet_get_or_create(STUDENT_B)
            pid = await self._make_topup_payment(STUDENT_B, 25000)
            await db.sub_payment_decide(pid, approved=True,
                                        admin_id=ADMIN_UID)
            # بدون finalize — شبیه‌سازی کرش بین تأیید و اعتبار
            async with self._client_ctx() as c:
                r = await c.get("/api/web-admin/subscription/reconcile",
                                headers=self.admin_h)
                items = r.json()["items"]
                hit = next((i for i in items
                            if i["type"] == "topup_without_wallet_credit"
                            and i["payment_id"] == pid), None)
                assert hit, "رسید شارژِ بی‌اعتبار پرچم نخورد"
                assert any(a["key"] == "finalize_topup"
                           for a in hit["actions"])
                # false-positive ممنوع: رسید شارژ ≠ «تأییدشده بدون اشتراک»
                assert not any(
                    i["type"] == "approved_no_active_sub"
                    and i.get("technical") == pid for i in items)
                r = await c.post(
                    f"/api/web-admin/subscription/reconcile/{pid}"
                    "/finalize-topup",
                    headers=self.admin_h, json={"confirm": True})
                assert r.status_code == 200, r.text
                assert r.json()["amount"] == 25000
                w = await db.wallet_get_for_user_id(STUDENT_B)
                assert int(w["balance"]) == 25000
                r = await c.get("/api/web-admin/subscription/reconcile",
                                headers=self.admin_h)
                assert not any(
                    i["type"] == "topup_without_wallet_credit"
                    and i["payment_id"] == pid for i in r.json()["items"])
            await self._assert_ledger_invariant(STUDENT_B)
        self._run(run())

    def test_topup_api_guards(self):
        """مرز مبلغ + رسید الزامی + رسیدِ در انتظار — همه سرور-ساید."""
        self._reset_wallets([STUDENT_A])
        async def run():
            async with self._client_ctx() as c:
                # مبلغ زیر کرانه → ۴۲۲ (بدون هیچ اثر مالی)
                r = await c.post("/api/subscription/topup",
                                 headers=self.b_h,
                                 data={"amount": "500"})
                assert r.status_code == 422, r.text
                # مبلغ معتبر ولی بدون رسید → ۴۲۲
                r = await c.post("/api/subscription/topup",
                                 headers=self.b_h,
                                 data={"amount": "50000"})
                assert r.status_code == 422, r.text
            w = await self.db.wallet_get_for_user_id(STUDENT_A)
            assert int((w or {}).get("balance", 0)) == 0
        self._run(run())

    def test_wallet_admin_views(self):
        # خودبسنده: state لازم را خودش می‌سازد (نه side-effect تست‌های قبلی)
        self._reset_wallets([STUDENT_A])
        async def run():
            await self.db.wallet_credit(STUDENT_A, 120000, "refund_credit",
                                        "unit", "admin-views-seed",
                                        ADMIN_UID, "بازگشت وجه تست")
            async with self._client_ctx() as c:
                r = await c.get("/api/web-admin/wallets",
                                headers=self.admin_h)
                assert r.status_code == 200
                ids = [w["user_id"] for w in r.json()["items"]]
                assert STUDENT_A in ids
                r = await c.get(f"/api/web-admin/wallets/{STUDENT_A}",
                                headers=self.admin_h)
                d = r.json()
                assert d["summary"]["user_name"] == "علی رضایی"
                assert any(t["type"] == "refund_credit"
                           for t in d["transactions"])
                r = await c.get("/api/web-admin/subscription/finance",
                                headers=self.admin_h)
                w = r.json()["wallet"]
                assert w["wallets"] >= 2 and "by_type" in w
                r = await c.get(f"/api/web-admin/users/{STUDENT_A}/360",
                                headers=self.admin_h)
                assert r.json()["wallet"]["credits_total"] >= 120000
        self._run(run())


if __name__ == "__main__":
    unittest.main()
