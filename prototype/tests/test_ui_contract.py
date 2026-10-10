"""Read-only two-shell static UI contract, synthetic data only."""
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "ui"
PUBLIC = ROOT / "index.html"
ADMIN = ROOT / "admin.html"
CSS = ROOT / "styles.css"


class Doc(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)

    def elements(self, tag):
        return [attrs for t, attrs in self.nodes if t == tag]


def read(path):
    doc = Doc()
    doc.feed(path.read_text(encoding="utf-8"))
    doc.close()
    return doc


class TwoShellUXTests(unittest.TestCase):
    def test_two_and_only_two_html_pages(self):
        self.assertEqual({f.name for f in ROOT.glob("*.html")},
                         {"index.html", "admin.html"})

    def test_html_is_fa_rtl_and_responsive(self):
        for path in (PUBLIC, ADMIN):
            with self.subTest(page=path):
                doc = read(path)
                self.assertEqual(doc.elements("html")[0]["lang"], "fa")
                self.assertEqual(doc.elements("html")[0]["dir"], "rtl")
                self.assertTrue(any(m.get("name") == "viewport"
                                    for m in doc.elements("meta")))
                self.assertEqual(len(doc.elements("main")), 1)

    def test_purely_synthetic_and_clearly_disclaimed(self):
        for path in (PUBLIC, ADMIN):
            with self.subTest(page=path):
                text = " ".join(read(path).text)
                for phrase in ("نمایشی", "ساختگی", "بدون"):
                    self.assertIn(phrase, text)

    def test_five_external_role_views_exactly(self):
        ids = [a["data-role"] for a in read(PUBLIC).elements("a")
               if "data-role" in a]
        self.assertEqual(ids, ["1", "2", "3", "4", "7"])

    def test_one_admin_and_exactly_four_areas(self):
        doc = read(ADMIN)
        ids = [a["data-area"] for a in doc.elements("a")
               if "data-area" in a]
        self.assertEqual(ids, ["10", "11", "12", "14"])
        self.assertEqual(len(doc.elements("main")), 1)

    def test_removed_roles_have_no_navigation(self):
        for path in (PUBLIC, ADMIN):
            doc = read(path)
            for tag, attrs in doc.nodes:
                self.assertNotIn(attrs.get("data-role"), {"5", "6", "8", "9", "13"})
                self.assertNotIn(attrs.get("data-area"), {"5", "6", "8", "9", "13"})

    def test_no_data_forms_scripts_or_tracking(self):
        forbidden = {"form", "input", "textarea", "select", "button", "script",
                     "iframe", "img", "video", "audio"}
        for path in (PUBLIC, ADMIN):
            self.assertFalse(forbidden & {tag for tag, _ in read(path).nodes})

    def test_no_remote_link_or_resources(self):
        for path in (PUBLIC, ADMIN):
            doc = read(path)
            for tag, attrs in doc.nodes:
                for name in ("href", "src", "action"):
                    value = attrs.get(name, "")
                    self.assertFalse(value.startswith(
                        ("https:", "http:", "//", "javascript:", "data:")))
            csp = [m["content"] for m in doc.elements("meta")
                   if m.get("http-equiv") == "Content-Security-Policy"]
            self.assertEqual(len(csp), 1)
            self.assertIn("default-src 'none'", csp[0])
            self.assertIn("form-action 'none'", csp[0])

    def test_local_navigation_resolves(self):
        for path in (PUBLIC, ADMIN):
            doc = read(path)
            ids = [attrs["id"] for _, attrs in doc.nodes if "id" in attrs]
            self.assertEqual(len(ids), len(set(ids)))
            for attrs in doc.elements("a"):
                url = attrs.get("href", "")
                if url.startswith("#"):
                    self.assertIn(url[1:], ids)
                else:
                    self.assertIn(url, ("index.html", "admin.html"))

    def test_both_pages_link_to_each_other(self):
        for path in (PUBLIC, ADMIN):
            urls = {a.get("href") for a in read(path).elements("a")}
            self.assertIn("index.html", urls)
            self.assertIn("admin.html", urls)

    def test_only_one_local_stylesheet(self):
        for path in (PUBLIC, ADMIN):
            links = [a.get("href") for a in read(path).elements("link")
                     if a.get("rel") == "stylesheet"]
            self.assertEqual(links, ["styles.css"])
        self.assertTrue(CSS.is_file())
        self.assertNotIn("@import", CSS.read_text(encoding="utf-8"))

    def test_correct_first_slices_and_same_fake_household(self):
        household = " ".join(read(PUBLIC).text)
        admin = " ".join(read(ADMIN).text)
        self.assertIn("CORE-D1-A", household)
        self.assertIn("CORE-D1-A", admin)
        self.assertIn("CORE-E0-A", admin)
        self.assertIn("DEMO-H01", household)
        self.assertIn("DEMO-H01", admin)
        self.assertIn("DEMO-SOURCE-01", admin)

    def test_export_research_is_not_sale_or_licensed_source(self):
        txt = " ".join(read(ADMIN).text)
        self.assertIn("بررسی نشده", txt)
        self.assertIn("خریدار یا قرارداد", txt)
        self.assertIn("وجود ندارد", txt)

    def test_admin_links_are_not_security(self):
        txt = " ".join(read(ADMIN).text)
        self.assertIn("کنترل دسترسی نیست", txt)
        self.assertIn("سمت سرور", txt)

    def test_deferred_experiences_are_not_implemented(self):
        txt = " ".join(read(PUBLIC).text)
        self.assertIn("غیرفعال", txt)
        self.assertIn("بدون", txt)

    def test_accessible_navigation_and_motion(self):
        for path in (PUBLIC, ADMIN):
            doc = read(path)
            self.assertTrue(any(a.get("class") == "skip" and a.get("href") == "#main"
                                for a in doc.elements("a")))
        styles = CSS.read_text(encoding="utf-8")
        self.assertIn("prefers-reduced-motion", styles)
        self.assertIn("@media(max-width:", styles)


if __name__ == "__main__":
    unittest.main()
