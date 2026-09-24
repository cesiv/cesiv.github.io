import datetime as dt
import tempfile
import unittest
from pathlib import Path

from fetch_news import Article, article_filename, deduplicate, existing_source_urls, parse_feed, render_post, slugify, strip_html


class FetchNewsTests(unittest.TestCase):
    def test_parse_rss_and_atom(self):
        rss = b"""<rss><channel><item><title>Hello &amp; Code</title><link>https://example.com/a</link><description><![CDATA[<p>Useful <b>story</b></p><script>bad</script>]]></description><dc:creator xmlns:dc="x">Ada</dc:creator></item></channel></rss>"""
        atom = b"""<feed xmlns="urn:x"><entry><title>Atom story</title><link href="https://example.com/b" /><summary>Summary</summary><author><name>Ada</name></author></entry></feed>"""
        self.assertEqual(parse_feed(rss, "feed", "RSS", "科技财经")[0].description, "Useful story")
        atom_article = parse_feed(atom, "feed", "Atom")[0]
        self.assertEqual((atom_article.title, atom_article.url), ("Atom story", "https://example.com/b"))

    def test_deduplicate_urls_and_keep_empty_feed_summary(self):
        first = Article("A", "https://EXAMPLE.com/a#fragment", "", "feed")
        duplicate = Article("A again", "https://example.com/a/", "body", "feed")
        self.assertEqual(deduplicate([first, duplicate]), [first])

    def test_html_cleaning_and_safe_stable_slug(self):
        self.assertEqual(strip_html("<p>Hello&nbsp;<b>world</b></p><script>x</script>"), "Hello world")
        self.assertEqual(slugify("C++: The Future of AI / Tools!"), "c-the-future-of-ai-tools")
        self.assertEqual(slugify("中文标题"), "tech-news")

    def test_front_matter_filename_and_idempotency(self):
        article = Article("Original", "https://example.com/story", "body", "Example", "2026-01-02", "Ada", "科技财经")
        content = render_post(article, dt.date(2026, 1, 2))
        self.assertTrue(content.startswith("---\n"))
        self.assertIn('source_url: "https://example.com/story"', content)
        self.assertIn("自动抓取/原文摘要", content)
        self.assertEqual(article_filename(article, dt.date(2026, 1, 2)), article_filename(article, dt.date(2026, 1, 2)))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "post.md"
            path.write_text(content, encoding="utf-8")
            self.assertIn("https://example.com/story", existing_source_urls(Path(directory)))


if __name__ == "__main__":
    unittest.main()
