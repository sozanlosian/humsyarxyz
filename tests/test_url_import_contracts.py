# -*- coding: utf-8 -*-
"""📥 URL-Import — قرارداد درون‌ریزی محتوای راه‌دور.

۱) گارد ایستا: SSRF، سقف سخت streaming، cleanup، reuseهای اجباری
   (upload helper، db.*ها، RBAC، audit)، wiring سه سطح UI.
۲) runtime: سرور HTTP محلی (فقط با hook صریح URLIMPORT_TRUSTED_HOSTS
   مجاز می‌شود) + stub آپلود تلگرام؛ چرخه‌ی کامل موفق، idempotency،
   SSRF (loopback untrusted/private/metadata/redirect-به-private)،
   سقف حجم، نوع غیرمجاز، تکراری+force، لغو، RBAC دانشجو، recovery.

بدون Mongo → Skip. loop مشترک tests/_rtloop."""
import asyncio
import hashlib
import hmac
import http.server
import json
import os
import socket
import socketserver
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode

from bson import ObjectId as OID

ROOT = Path(__file__).resolve().parents[1]

ADMIN_UID = 889001
STUDENT_UID = 889002
TEST_TOKEN = "123456:W21-TEST-TOKEN"

PDF_BYTES = b"%PDF-1.4\n" + b"x" * 4096
PDF_A = b"%PDF-1.4\n" + b"A" * 3000   # مخصوص success
PDF_B = b"%PDF-1.4\n" + b"B" * 3000   # مخصوص idempotency
PDF_C = b"%PDF-1.4\n" + b"C" * 3000   # مخصوص duplicate
EXE_BYTES = b"MZ" + b"\x00" * 2048
FAKE_PDF = b"hello not a pdf" * 200
BIG_BYTES = b"b" * (1024 * 1024 + 512 * 1024)  # 1.5MB


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):  # سکوت
        pass

    def do_GET(self):
        if self.path in ("/file.pdf", "/fileA.pdf", "/fileB.pdf", "/fileC.pdf"):
            body = {"file.pdf": PDF_BYTES, "fileA.pdf": PDF_A,
                    "fileB.pdf": PDF_B, "fileC.pdf": PDF_C}[self.path[1:]]
            ctype = "application/pdf"
        elif self.path == "/file.exe":
            body, ctype = EXE_BYTES, "application/x-msdownload"
        elif self.path == "/fake.pdf":
            body, ctype = FAKE_PDF, "application/pdf"
        elif self.path == "/big.bin":
            body, ctype = BIG_BYTES, "application/octet-stream"
        elif self.path == "/redirect-priv":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest")
            self.end_headers()
            return
        elif self.path == "/slow":
            time.sleep(8)
            body, ctype = PDF_BYTES, "application/pdf"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if self.path.endswith(".pdf") and self.path != "/fake.pdf":
            self.send_header("Content-Disposition",
                             f'attachment; filename="physiology{self.path[-5] if self.path != "/file.pdf" else ""}.pdf"')
        self.end_headers()
        self.wfile.write(body)


class UrlImportStaticTests(unittest.TestCase):

    def test_ssrf_protection_present(self):
        src = read("url_import_service.py")
        for token in ("is_private", "is_loopback", "is_link_local",
                      "169.254.169.254", "SSRF_BLOCKED", "MAX_REDIRECTS"):
            self.assertIn(token, src, f"مولفه‌ی SSRF {token} fehlt")
        self.assertIn("await validate_url(url)  # هر هاپ دوباره", src,
                      "اعتبارسنجی مجدد هر redirect لازم است")

    def test_streaming_hard_limit(self):
        src = read("url_import_service.py")
        self.assertIn("aiter_bytes", src, "دانلود باید استریمی باشد")
        self.assertIn("written > max_bytes", src, "سقف سخت حین stream")
        self.assertNotIn("await response.read()", src)

    def test_reuse_not_parallel(self):
        src = read("url_import_service.py")
        self.assertIn("upload_and_get_file_id", src,
                      "آپلود تلگرام باید همان helper موجود باشد")
        for fn in ("qbank_file_add", "bs_add_content", "ref_add_file"):
            self.assertIn(fn, src, f"ثبت محتوا باید با {fn} موجود باشد")
        core = read("db", "core.py")
        self.assertIn("url_import_jobs", core)

    def test_router_rbac_and_endpoints(self):
        src = read("api", "routers", "url_import.py")
        self.assertIn("get_content_admin_user", src)
        for route in ("/url-import/jobs", "/cancel", "/retry"):
            self.assertIn(route, src)
        main = read("api", "main.py")
        self.assertIn("url_import.router", main)
        self.assertIn("recover_stale_jobs", main)

    def test_no_secret_in_logs(self):
        src = read("url_import_service.py")
        self.assertIn("def redact_url", src)
        self.assertIn("url_safe", src)

    def test_ui_wired_three_surfaces(self):
        apijs = read("webadmin", "src", "api.js")
        self.assertIn("urlImportCreate", apijs)
        self.assertIn("urlImportRetry", apijs)
        page = read("webadmin", "src", "pages", "Content.jsx")
        self.assertIn("درون‌ریزی URL", page)
        self.assertIn("UrlImportTab", page)
        mini = read("miniapp", "src", "pages", "Admin", "UrlImport.jsx")
        self.assertIn("url-import/jobs", mini)
        app = read("miniapp", "src", "App.jsx")
        self.assertIn("/admin/content/url-import", app)
        home = read("miniapp", "src", "pages", "Admin", "ContentHome.jsx")
        self.assertIn("درون‌ریزی از URL", home)
        bot = read("content_admin.py")
        self.assertIn("ca:urlimport", bot)
        self.assertIn("_ui_run_bot", bot)
        botpy = read("bot.py")
        self.assertIn("'ui_url'", botpy)

    def test_cleanup_and_recovery(self):
        src = read("url_import_service.py")
        self.assertIn("shutil.rmtree(tmp_root", src)
        self.assertIn("async def recover_stale_jobs", src)
        self.assertIn("WORKER_RESTART", src)


def _mongo_available() -> bool:
    uri = os.getenv("MONGODB_URI", "")
    if not (uri.startswith("mongodb://127.0.0.1") or uri.startswith("mongodb://localhost")):
        return False
    host, _, port = uri[len("mongodb://"):].partition(":")
    try:
        with socket.create_connection((host, int(port or 27017)), timeout=1):
            return True
    except OSError:
        return False


def _signed_init_data(uid: int) -> str:
    token = os.environ.setdefault("TELEGRAM_TOKEN", TEST_TOKEN)
    user = {"id": uid, "first_name": "UI", "username": "ui_test"}
    pairs = {"user": json.dumps(user, separators=(",", ":")),
             "auth_date": str(int(time.time()))}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**pairs, "hash": digest})


@unittest.skipUnless(_mongo_available(), "MONGODB_URI محلی در دسترس نیست (CI)")
class UrlImportRuntimeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("TELEGRAM_TOKEN", TEST_TOKEN)
        os.environ["ADMIN_ID"] = str(ADMIN_UID)
        os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")

        # سرور فایل محلی + hook صریح اعتماد (فقط همین host:port)
        cls.httpd = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        os.environ["URLIMPORT_TRUSTED_HOSTS"] = f"127.0.0.1:{cls.port}"

        import httpx
        cls.httpx = httpx
        import api.main as main_mod
        cls.app = main_mod.app
        from database import db
        cls.db = db
        import url_import_service as svc
        cls.svc = svc
        # stub آپلود تلگرام — همان نقطه‌ی پوشش سرویس
        cls._real_upload = svc._telegram_upload

        async def _fake_upload(admin_id, filename, raw, mime):
            return f"TGTEST-{hashlib.sha256(raw).hexdigest()[:10]}"
        svc._telegram_upload = _fake_upload

        cls.admin_h = {"X-Init-Data": _signed_init_data(ADMIN_UID)}
        cls.student_h = {"X-Init-Data": _signed_init_data(STUDENT_UID)}

        from _rtloop import adopt
        adopt()
        cls._run(cls._prepare())

    @classmethod
    def tearDownClass(cls):
        cls.svc._telegram_upload = cls._real_upload
        cls.httpd.shutdown()
        cls._run(cls._clean())

    @classmethod
    def _run(cls, coro):
        from _rtloop import run
        return run(coro)

    @classmethod
    async def _prepare(cls):
        db = cls.db
        for uid, role in ((ADMIN_UID, "admin"), (STUDENT_UID, "student")):
            await db.users.update_one({"user_id": uid}, {"$set": {
                "user_id": uid, "name": f"UI {uid}", "role": role,
                "approved": True, "suspended": False}}, upsert=True)
        await cls._clean()

    @classmethod
    async def _clean(cls):
        db = cls.db
        await db.url_import_jobs.delete_many({"admin_id": {"$in": [ADMIN_UID, STUDENT_UID]}})
        await db.qbank_files.delete_many({"uploaded_by": ADMIN_UID,
                                          "telegram_file_id": {"$regex": "^TGTEST-"}})
        await db.settings.update_one({"_id": "global"},
                                     {"$unset": {"url_import_max_mb": ""}})

    def _client_ctx(self):
        return self.httpx.AsyncClient(
            transport=self.httpx.ASGITransport(app=self.app), base_url="http://t")

    def _base(self):
        return f"http://127.0.0.1:{self.port}"

    async def _create(self, c, url, idem, **kw):
        return await c.post("/api/content/url-import/jobs",
                            headers=self.admin_h,
                            json={"url": url, "idem": idem, **kw})

    async def _wait(self, job_id, want=None, timeout=25):
        deadline = time.time() + timeout
        while time.time() < deadline:
            doc = await self.svc.get_import_job(job_id)
            if doc and (want is None or doc["status"] in want or
                        doc["status"] in self.svc.TERMINAL):
                return doc
            await asyncio.sleep(0.4)
        return await self.svc.get_import_job(job_id)

    def test_success_end_to_end(self):
        async def run():
            async with self._client_ctx() as c:
                r = await self._create(c, f"{self._base()}/fileA.pdf", "ui-e2e-1",
                                       kind="qbank", lesson="فیزیولوژی",
                                       topic="قلب")
                job = r.json()["job"]
                doc = await self._wait(job["id"], {"completed"})
                qf = await self.db.qbank_files.find_one({"_id": OID(doc["content_id"])})
                return r, doc, qf
        r, doc, qf = self._run(run())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(doc["status"], "completed", doc.get("error"))
        self.assertEqual(doc["progress"]["percent"], 100)
        self.assertTrue(doc["telegram_file_id"])
        self.assertEqual(doc["filename"], "physiologyA.pdf",
                         "filename باید از Content-Disposition بیاید")
        self.assertEqual(doc["size"], len(PDF_A))
        self.assertTrue(doc["sha256"])
        evs = [t["event"] for t in doc["timeline"]]
        for e in ("import_created", "download_started",
                  "telegram_upload_completed", "import_completed"):
            self.assertIn(e, evs)
        self.assertIsNotNone(qf, "رکورد qbank باید ساخته شود")
        self.assertEqual(qf["lesson"], "فیزیولوژی")

    def test_idempotent_create(self):
        async def run():
            async with self._client_ctx() as c:
                r1 = await self._create(c, f"{self._base()}/fileB.pdf", "ui-idem-1")
                r2 = await self._create(c, f"{self._base()}/fileB.pdf", "ui-idem-1")
                n = await self.db.url_import_jobs.count_documents(
                    {"idem_key": "ui-idem-1"})
                await self._wait(r1.json()["job"]["id"])
                return r1, r2, n
        r1, r2, n = self._run(run())
        self.assertEqual(r1.json()["job"]["id"], r2.json()["job"]["id"])
        self.assertEqual(n, 1)

    def test_ssrf_blocks_untrusted_and_private(self):
        async def run():
            async with self._client_ctx() as c:
                # پورت دیگرِ loopback خارج از allowlist
                r1 = await self._create(c, "http://127.0.0.1:9/none", "ui-ssrf-1")
                j1 = await self._wait(r1.json()["job"]["id"], {"failed"})
                r2 = await self._create(c, "http://169.254.169.254/latest",
                                        "ui-ssrf-2")
                j2 = await self._wait(r2.json()["job"]["id"], {"failed"})
                r3 = await self._create(c, "ftp://example.com/x", "ui-ssrf-3")
                return j1, j2, r3
        j1, j2, r3 = self._run(run())
        self.assertEqual(j1["error"]["code"], "SSRF_BLOCKED")
        self.assertEqual(j2["error"]["code"], "SSRF_BLOCKED")
        self.assertEqual(r3.status_code, 200)  # job ساخته شد؛ در فاز validate رد می‌شود

    def test_redirect_to_private_blocked(self):
        async def run():
            async with self._client_ctx() as c:
                r = await self._create(c, f"{self._base()}/redirect-priv",
                                       "ui-redir-1")
                return await self._wait(r.json()["job"]["id"], {"failed"})
        doc = self._run(run())
        self.assertEqual(doc["error"]["code"], "SSRF_BLOCKED")

    def test_size_limit_enforced_during_stream(self):
        async def run():
            await self.db.set_setting("url_import_max_mb", 1)
            async with self._client_ctx() as c:
                r = await self._create(c, f"{self._base()}/big.bin", "ui-big-1")
                doc = await self._wait(r.json()["job"]["id"], {"failed"})
                await self.db.settings.update_one(
                    {"_id": "global"}, {"$unset": {"url_import_max_mb": ""}})
                return doc
        doc = self._run(run())
        self.assertEqual(doc["error"]["code"], "DOWNLOAD_TOO_LARGE")

    def test_unsupported_and_fake_type(self):
        async def run():
            async with self._client_ctx() as c:
                r1 = await self._create(c, f"{self._base()}/file.exe", "ui-type-1")
                j1 = await self._wait(r1.json()["job"]["id"], {"failed"})
                r2 = await self._create(c, f"{self._base()}/fake.pdf", "ui-type-2")
                j2 = await self._wait(r2.json()["job"]["id"], {"failed"})
                return j1, j2
        j1, j2 = self._run(run())
        self.assertEqual(j1["error"]["code"], "UNSUPPORTED_TYPE")
        self.assertEqual(j2["error"]["code"], "UNSUPPORTED_TYPE",
                         "magic bytes باید پسوند دروغین را رد کند")

    def test_duplicate_then_force(self):
        async def run():
            async with self._client_ctx() as c:
                r1 = await self._create(c, f"{self._base()}/fileC.pdf", "ui-dup-a")
                await self._wait(r1.json()["job"]["id"], {"completed"})
                r2 = await self._create(c, f"{self._base()}/fileC.pdf", "ui-dup-b")
                j2 = await self._wait(r2.json()["job"]["id"], {"duplicate"})
                jid2 = str(j2["_id"])
                rr = await c.post(
                    f"/api/content/url-import/jobs/{jid2}/retry",
                    headers=self.admin_h, json={"force": True})
                j3 = await self._wait(jid2, {"completed"})
                return j2, rr, j3
        j2, rr, j3 = self._run(run())
        self.assertEqual(j2["status"], "duplicate")
        self.assertEqual(rr.status_code, 200, rr.text)
        self.assertEqual(j3["status"], "completed")

    def test_cancel_running_job(self):
        async def run():
            async with self._client_ctx() as c:
                r = await self._create(c, f"{self._base()}/slow", "ui-cancel-1")
                jid = r.json()["job"]["id"]
                await asyncio.sleep(1.2)
                rc = await c.post(f"/api/content/url-import/jobs/{jid}/cancel",
                                  headers=self.admin_h)
                doc = await self.svc.get_import_job(jid)
                return rc, doc
        rc, doc = self._run(run())
        self.assertEqual(rc.status_code, 200, rc.text)
        self.assertEqual(doc["status"], "cancelled")

    def test_student_denied(self):
        async def run():
            async with self._client_ctx() as c:
                return await c.post("/api/content/url-import/jobs",
                                    headers=self.student_h,
                                    json={"url": f"{self._base()}/file.pdf",
                                          "idem": "ui-stu-1"})
        r = self._run(run())
        self.assertEqual(r.status_code, 403)

    def test_crash_recovery(self):
        async def run():
            await self.db.url_import_jobs.insert_one({
                "admin_id": ADMIN_UID, "status": "downloading",
                "url_safe": "old", "created_at": "2026-01-01T00:00:00",
                "timeline": []})
            doc = await self.db.url_import_jobs.find_one(
                {"admin_id": ADMIN_UID, "status": "downloading"})
            n = await self.svc.recover_stale_jobs()
            after = await self.db.url_import_jobs.find_one({"_id": doc["_id"]})
            return n, after
        n, after = self._run(run())
        self.assertGreaterEqual(n, 1)
        self.assertEqual(after["status"], "failed")
        self.assertEqual(after["error"]["code"], "WORKER_RESTART")


if __name__ == "__main__":
    unittest.main(verbosity=2)
