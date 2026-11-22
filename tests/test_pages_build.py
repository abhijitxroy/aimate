import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "build_pages", Path(__file__).resolve().parents[1] / "tools/build_pages.py"
)
pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pages)


class PagesBuildTests(unittest.TestCase):
    def test_frontend_only_and_relative_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "site"
            pages.build(output)
            html = (output / "index.html").read_text(encoding="utf-8")
            self.assertNotIn('"/static/', html)
            self.assertIn('id="conversations"', html)
            self.assertIn('id="question"', html)
            self.assertLess(html.index("pages/preview.js"), html.index("app/static/app.js"))
            self.assertEqual(
                (output / "app/static/app.js").read_bytes(),
                (pages.ROOT / "app/static/app.js").read_bytes(),
            )
            files = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
            self.assertTrue(all(p in {"index.html", ".nojekyll"} or
                                p.startswith(("app/static/", "pages/")) for p in files))
            self.assertFalse(any(p.endswith((".db", ".sqlite", ".env", ".py")) for p in files))

    def test_refuse_existing_output_with_unrelated_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            sentinel = output / "private.db"
            sentinel.write_text("must not publish")
            with self.assertRaises(ValueError):
                pages.build(output)
            self.assertEqual(sentinel.read_text(), "must not publish")


if __name__ == "__main__":
    unittest.main()
