"""Offline safeguards for the read-only Instagram inspector."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "app/services/instagram_page_inspector.py"
HANDLER = ROOT / "app/handlers/instagram_inspect.py"
MAIN = ROOT / "app/main.py"


class InspectorTests(unittest.TestCase):
    def test_modules_compile(self):
        for path in (SERVICE, HANDLER, MAIN):
            with self.subTest(path=path.name):
                compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_no_account_lookup_or_form_submission(self):
        source = SERVICE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        self.assertFalse(
            names & {"fill", "click", "press", "type", "evaluate", "request"}
        )
        function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                        and node.name == "inspect_recovery_page")
        self.assertEqual(function.args.args, [])
        self.assertEqual(function.args.kwonlyargs, [])
        self.assertIsNone(function.args.vararg)
        self.assertIsNone(function.args.kwarg)

    def test_command_registered(self):
        self.assertIn(
            'CommandHandler("instagram", instagram_inspect_command, block=False)',
            MAIN.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
