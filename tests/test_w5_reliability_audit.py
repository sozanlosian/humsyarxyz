# -*- coding: utf-8 -*-
"""🌊 W5 (ممیزی) — پایداری عملیاتی: پنجره‌ی آشتی، بکاپ، REL-03، DB-03، CODE-02.

۱) گارد ایستا: سیم‌کشی آیتم‌ها + نبود رفتار ناامن قدیمی.
۲) runtime خالص: شمارنده‌ها، رمزنگاری بایت، قرارداد sha، ۳ تست کرش DB-03.
۳) runtime با Mongo محلی (DB-gated): upsert هم‌زمان + ایندکس TTL.

داده با پیشوند w5؛ در پایان پاک می‌شود. loop مشترک (tests/_rtloop).
"""
import asyncio
import hashlib
import json
import os
import socket
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

W5_N = 50


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class W5StaticTests(unittest.TestCase):
    """گاردهای ایستای W5."""

    def test_recon_window(self):
        src = read("api", "routers", "web_admin.py")
        self.assertIn('"recon_window_days"', src)
        self.assertIn('"window_days":', src)
        self.assertIn('"skipped_stale":', src)

    def test_plan_delete_returns_bool_and_callers_handle(self):
        fin = read("db", "finance.py")
        self.assertIn("async def sub_plan_delete", fin)
        self.assertIn("-> bool:", fin)
        api = read("api", "routers", "subscription_management.py")
        self.assertIn("if not await db.sub_plan_delete(", api)
        self.assertIn("status_code=500", api)
        bot = read("subscription_admin.py")
        self.assertIn("if not await db.sub_plan_delete(parts[2]):", bot)

    def test_backup_size_gate_and_encryption(self):
        bot = read("bot.py")
        self.assertIn("48 * 1024 * 1024", bot)
        self.assertIn("40 * 1024 * 1024", bot)
        self.assertIn("encrypt_bytes", bot)
        self.assertIn(".enc", bot)
        cry = read("utils_crypto.py")
        self.assertIn("def encrypt_bytes", cry)
        self.assertIn("def decrypt_bytes", cry)

    def test_backup_sha_wired(self):
        bak = read("backup.py")
        self.assertIn("sha256_sections", bak)
        self.assertIn(".json.enc", bak)
        self.assertIn("decrypt_bytes", bak)
        # قدیمیِ ناامن: پذیرش .json بدون راستی‌آزماییِ در دسترس
        self.assertIn("ناسازگار است", bak)

    def test_rel03_wired(self):
        main = read("api", "main.py")
        self.assertIn("api_counters", main)
        self.assertIn("client_errors.router", main)
        core = read("db", "core.py")
        self.assertIn("self.client_errors", core)
        self.assertIn("self.client_errors, [(\'at\', 1)]", core)
        wa = read("api", "routers", "web_admin.py")
        self.assertIn('"/system/client-errors"', wa)
        self.assertIn('"api": _api', wa)

    def test_rel03_frontend_wired(self):
        eb = read("miniapp", "src", "components", "shared",
                  "ErrorBoundary.jsx")
        self.assertIn("/api/client-errors", eb)
        api = read("webadmin", "src", "api.js")
        self.assertIn("systemClientErrors", api)
        sys = read("webadmin", "src", "pages", "System.jsx")
        self.assertIn("systemClientErrors", sys)
        self.assertIn("recent_5xx", sys)

    def test_db03_doc_exists(self):
        doc = read("docs", "db-no-transactions.md")
        self.assertIn("تراکنش ممنوع", doc)
        self.assertIn("test_w5_reliability_audit", doc)


class W5PureRuntimeTests(unittest.TestCase):
    """runtime بدون Mongo: شمارنده، رمز، sha، کرش."""

    def test_counters_record_and_snapshot(self):
        from api.api_counters import record, snapshot
        route = "/w5probe/unique-route"
        record("GET", route, 200, "r1")
        record("GET", route, 200, "r2")
        record("POST", route, 500, "r3")
        snap = snapshot()
        row = next(r for r in snap["routes"] if r["route"] == route)
        self.assertEqual(row["requests"], 3)
        self.assertEqual(row["by_class"].get("2xx"), 2)
        self.assertEqual(row["by_class"].get("5xx"), 1)
        self.assertTrue(snap["ephemeral"])
        self.assertIn("r3", [e["request_id"] for e in snap["recent_5xx"]])

    def test_crypto_bytes_roundtrip(self):
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            self.skipTest("cryptography نصب نیست")
        import utils_crypto as uc
        prev, uc._fernet = uc._fernet, Fernet(Fernet.generate_key())
        try:
            blob = b'{"w5": "probe-\xc3\xa9"}' * 100
            enc = uc.encrypt_bytes(blob)
            self.assertIsNotNone(enc)
            self.assertNotEqual(enc, blob)
            self.assertEqual(uc.decrypt_bytes(enc), blob)
            self.assertIsNone(uc.decrypt_bytes(b"tampered-token"))
        finally:
            uc._fernet = prev

    def test_sha_canonical_contract(self):
        def canon(sections):
            body = json.dumps(sections, ensure_ascii=False,
                              sort_keys=True, default=str)
            return hashlib.sha256(body.encode("utf-8")).hexdigest()
        a = {"b": [1, 2], "a": {"x": 1}}
        b = {"a": {"x": 1}, "b": [1, 2]}  # ترتیب کلید متفاوت
        self.assertEqual(canon(a), canon(b))
        tampered = {"a": {"x": 2}, "b": [1, 2]}
        self.assertNotEqual(canon(a), canon(tampered))

    def test_crash_concurrent_upserts_stay_consistent(self):
        """DB-03/قرارداد۱: upsertهای هم‌زمان ⇒ کلیدهای کامل، بدون سند پاره."""
        async def go():
            doc, lock = {}, asyncio.Lock()

            async def set_setting(k, v):  # مدل update_one تک‌سندیِ اتمیک
                async with lock:
                    doc[k] = v

            await asyncio.gather(*[set_setting(f"k{i}", f"v{i}-x" * 10)
                                   for i in range(100)])
            self.assertEqual(len(doc), 100)
            for i in range(100):
                self.assertEqual(doc[f"k{i}"], f"v{i}-x" * 10)
        asyncio.run(go())

    def test_crash_mid_pipeline_retry_has_no_double_effect(self):
        """DB-03/قرارداد۲: کرش وسط پایپ‌لاین + retry ⇒ بدون اثر دوبل."""
        async def go():
            state = {"granted": [], "claimed": set()}

            async def pipeline(op_key, crash_after=9):
                steps = ["debit", "grant", "audit"]
                for i, s in enumerate(steps):
                    if (op_key, s) in state["claimed"]:
                        continue
                    if i == crash_after:
                        raise RuntimeError("crash!")
                    state["claimed"].add((op_key, s))
                    if s == "grant":
                        state["granted"].append(op_key)

            with self.assertRaises(RuntimeError):
                await pipeline("op1", crash_after=1)
            await pipeline("op1")  # اجرای مجدد پس از کرش
            self.assertEqual(state["granted"], ["op1"])
        asyncio.run(go())

    def test_crash_competing_claims_exactly_once(self):
        """DB-03/قرارداد۳: claim رقابتی ⇒ دقیقاً یک برنده."""
        async def go():
            store, lock = set(), asyncio.Lock()

            async def claim(k):  # مدل insert-if-absent اتمیک
                async with lock:
                    if k in store:
                        return False
                    store.add(k)
                    return True

            wins = await asyncio.gather(*[claim("opX") for _ in range(20)])
            self.assertEqual(sum(1 for w in wins if w), 1)
        asyncio.run(go())


def _mongo_available() -> bool:
    uri = os.getenv("MONGODB_URI", "")
    if not (uri.startswith("mongodb://127.0.0.1") or
            uri.startswith("mongodb://localhost")):
        return False
    host, _, port = uri[len("mongodb://"):].partition(":")
    try:
        with socket.create_connection((host, int(port or 27017)), timeout=1):
            return True
    except OSError:
        return False


@unittest.skipUnless(_mongo_available(), "MONGODB_URI محلی در دسترس نیست (CI)")
class W5DbGatedTests(unittest.TestCase):
    """upsert هم‌زمان واقعی + TTL روی Mongo محلی."""

    KEYS = [f"w5_probe_{i}" for i in range(W5_N)]

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
        from database import db
        cls.db = db
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
        await cls._clean()
        await cls.db.ensure_indexes()

    @classmethod
    async def _clean(cls):
        await cls.db.settings.update_one(
            {"_id": "global"},
            {"$unset": {k: "" for k in cls.KEYS}})

    def test_db03_concurrent_upserts_real(self):
        async def go():
            db = self.db
            await asyncio.gather(*[db.set_setting(k, f"v-{k}")
                                   for k in self.KEYS])
            doc = await db.settings.find_one({"_id": "global"}) or {}
            missing = [k for k in self.KEYS if doc.get(k) != f"v-{k}"]
            self.assertEqual(missing, [])
        self._run(go())

    def test_rel03_client_errors_ttl(self):
        async def go():
            info = await self.db.client_errors.index_information()
            self.assertIn("at_1", info)
            self.assertEqual(info["at_1"].get("expireAfterSeconds"), 2592000)
        self._run(go())
