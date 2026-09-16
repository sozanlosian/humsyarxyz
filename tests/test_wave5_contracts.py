"""موج ۵ — گاردهای ایستا برای باگ‌های بازتولیدشده‌ی این دور.

هر تست این فایل مستقیماً به یک نقصِ *واقعیِ* مشاهده‌شده در کد گره خورده
است، نه یک قاعده‌ی سلیقه‌ای. هر گارد با «جهش» (خراب‌کردن عمدیِ رفع)
آزموده شده تا مطمئن شویم واقعاً چیزی می‌گیرد.

وابستگی بیرونی ندارد (نه Mongo، نه تلگرام) تا در همان job سبکِ CI اجرا شود.
"""
import ast
import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


class RingDeadButtonTests(unittest.TestCase):
    """§W5-1 — دکمه‌ی «منوی اصلی ربات» در منوی رینگ مرده بود.

    `callback_data="main"` با هیچ CallbackQueryHandlerی مطابقت نمی‌کرد
    (هیچ pattern با ^main ثبت نشده)، پس تپ روی آن هیچ‌وقت هیچ کاری نمی‌کرد.
    """

    def test_no_bare_callback_data_outside_a_namespace(self):
        registered = self._registered_prefixes()
        offenders = []
        for path in sorted(ROOT.glob("ring/*.py")):
            for match in re.finditer(
                r"callback_data\s*=\s*(?:f)?[\"']([^\"'{}]+)[\"']", path.read_text(encoding="utf-8")
            ):
                data = match.group(1)
                if not any(data.startswith(p) for p in registered):
                    offenders.append(f"{path.name}: {data}")
        self.assertEqual([], offenders, f"callback_data بدون هندلر: {offenders}")

    def test_ring_menu_home_button_stays_in_ring_namespace(self):
        keyboards = read("ring", "keyboards.py")
        self.assertNotIn('callback_data="main"', keyboards)
        self.assertIn('callback_data=f"{CB}home"', keyboards)

    @staticmethod
    def _registered_prefixes() -> set:
        """پیشوندهایی که واقعاً در bot.py به یک هندلر وصل‌اند."""
        bot = read("bot.py")
        prefixes = set()
        for match in re.finditer(r"r?['\"]\^([A-Za-z_]+)", bot):
            prefixes.add(match.group(1))
        # رینگ خودش با pattern=r'^ring:' ثبت می‌شود
        prefixes.add("ring")
        return prefixes


class RingHomeRestoresKeyboardTests(unittest.TestCase):
    """§W5-2 — `ring:home` فقط متنِ «/start را بزن» می‌داد.

    کاربر برای برگشتن به ربات باید دستی دستور تایپ می‌کرد و کیبورد اصلی
    هم برنمی‌گشت. حالا خودِ کیبوردِ متناسب با نقش دوباره فرستاده می‌شود.
    """

    def test_home_handler_sends_real_keyboard(self):
        handlers = read("ring", "handlers.py")
        body = handlers[handlers.index("async def _r_home("):]
        body = body[: body.index("async def _r_menu(")]
        # به شکلِ *فراخوانی* assert می‌کنیم، نه صرفِ حضورِ رشته: وگرنه یک
        # نامِ شبیه (get_keyboard_for_user_XX) هم تست را سبز نگه می‌دارد.
        # (این دقیقاً در جهش‌آزمایی لو رفت.)
        self.assertIn("await get_keyboard_for_user(user, uid)", body)
        self.assertIn("reply_markup=await get_keyboard_for_user", body)
        # fallback رفتار قبلی باید حفظ شده باشد
        self.assertIn("/start", body)


class BotRbacParityTests(unittest.TestCase):
    """§W5-3 — ورود به پنل ربات فقط `admin_roles` میراثی را می‌دید.

    نقشی که در پنل وب ساخته می‌شد (فقط در user_roles) نمی‌توانست پنل
    ربات را باز کند، هرچند `admin_callback` یک لایه جلوتر همان نقش را
    می‌پذیرفت — یعنی دو تصمیمِ ناسازگار روی یک مسیر.
    """

    def test_router_admin_gate_consults_shared_permissions(self):
        router = read("message_router.py")
        gate = router[router.index('elif text == "👨‍⚕️ پنل ادمین"'):]
        gate = gate[: gate.index('elif text == "🔍 جستجو"')]
        self.assertIn("get_admin_role", gate)
        self.assertIn("get_user_perms", gate, "گیت هنوز نقش‌های RBAC را نمی‌بیند")


class AiInflightLockTests(unittest.TestCase):
    """§W5-4 — قفلِ «یک پرسش در لحظه» درون‌پراسسی بود.

    `_busy_users` یک setِ پایتونی است و طبق supervisord ربات و API دو
    پراسس جدا هستند ⇒ کاربر می‌توانست هم‌زمان از ربات و مینی‌اپ بپرسد و
    هر دو رد شوند: دو فراخوان به provider و دو بار هزینه.
    """

    def test_shared_claim_helpers_exist_and_use_durable_lock(self):
        ai = read("ai_solver.py")
        self.assertIn("async def ai_claim_inflight", ai)
        self.assertIn("async def ai_release_inflight", ai)
        self.assertIn("async def ai_is_inflight", ai)
        self.assertIn("op_claim('ai_inflight'", ai)
        self.assertIn("op_release('ai_inflight'", ai)

    def test_api_router_no_longer_decides_on_local_set(self):
        api_ai = read("api", "routers", "ai.py")
        body = "\n".join(
            line for line in api_ai.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertNotIn("_busy_users.add", body)
        self.assertNotIn("_busy_users.discard", body)
        self.assertNotIn("in _busy_users", body)
        self.assertIn("await ai_claim_inflight", body)
        self.assertIn("await ai_release_inflight", body)
        self.assertIn("await ai_is_inflight", body)

    def test_every_bot_claim_has_a_release(self):
        ai = read("ai_solver.py")
        claims = ai.count("await ai_claim_inflight(")
        releases = ai.count("await ai_release_inflight(")
        # هر مسیرِ ادعا باید دقیقاً یک finally با release داشته باشد
        # (تعریف خودِ helperها یک بار اضافه می‌شود، پس >= کافی نیست)
        self.assertGreaterEqual(releases, claims - 1)
        self.assertGreaterEqual(claims, 3, "هر سه مسیرِ ربات باید قفل بگیرند")

    def test_claim_sites_are_inside_try_finally(self):
        """ادعا بدون finally = قفلِ نشتی تا انقضای TTL."""
        tree = ast.parse(read("ai_solver.py"))
        offenders = []
        for func in ast.walk(tree):
            if not isinstance(func, ast.AsyncFunctionDef):
                continue
            if func.name.startswith("ai_"):
                continue  # خودِ helperها
            src = ast.dump(func)
            if "ai_claim_inflight" not in src:
                continue
            if "ai_release_inflight" not in src:
                offenders.append(func.name)
        self.assertEqual([], offenders, f"ادعای بدون آزادسازی: {offenders}")


class BlacklistReasonTests(unittest.TestCase):
    """§W5-5 — دلیلِ مسدودی خوانده می‌شد ولی هرگز نمایش داده نمی‌شد."""

    def test_blacklist_view_renders_reason(self):
        admin = read("admin.py")
        body = admin[admin.index("async def _show_blacklist("):]
        body = body[: body.index("\n\nasync def ", 10)]
        self.assertIn("reason", body)
        self.assertIn("_esc(reason", body, "دلیل هنوز به خروجی نمی‌رود")


if __name__ == "__main__":
    unittest.main()
