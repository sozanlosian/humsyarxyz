import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StaticContractTests(unittest.TestCase):
    def test_python_sources_parse(self):
        for path in [ROOT / "api" / "main.py", ROOT / "api" / "routers" / "academic_admin.py",
                     ROOT / "api" / "routers" / "content_admin.py", ROOT / "db" / "core.py",
                     ROOT / "schedule.py", ROOT / "ai_solver.py"]:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_quota_and_index_contracts_are_atomic_and_structured(self):
        core = (ROOT / "db" / "core.py").read_text(encoding="utf-8")
        ai = (ROOT / "ai_solver.py").read_text(encoding="utf-8")
        self.assertIn("async def ai_consume_quota", core)
        self.assertIn("find_one_and_update", core)
        self.assertIn("'ai_usage_count': {'$lt': limit}", core)
        self.assertNotIn("spec = repr(coros[idx])", core)
        self.assertIn("index_specs", core)
        self.assertIn("db.ai_consume_quota", ai)

    def test_scope_and_qbank_contracts(self):
        academic = (ROOT / "api" / "routers" / "academic_admin.py").read_text(encoding="utf-8")
        content = (ROOT / "api" / "routers" / "content_admin.py").read_text(encoding="utf-8")
        self.assertIn("async def _assert_student_scope", academic)
        self.assertIn("async def get_grade_admin_user", academic)
        self.assertIn('@router.get("/qbank/files")', content)
        self.assertIn('@router.post("/qbank/files")', content)
        self.assertIn('@router.delete("/qbank/files/{file_id}")', content)

    def test_frontends_have_direct_route_guards(self):
        mini = (ROOT / "miniapp" / "src" / "App.jsx").read_text(encoding="utf-8")
        web = (ROOT / "webadmin" / "src" / "app.jsx").read_text(encoding="utf-8")
        self.assertIn("function PermissionRoute", mini)
        self.assertIn("function canAccessRoute", web)
        self.assertIn("!canAccessRoute(route, me)", web)


if __name__ == "__main__":
    unittest.main()
