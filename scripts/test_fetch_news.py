import tempfile
import unittest
from pathlib import Path

from fetch_news import Article, deduplicate, parse_feed, render_post, slugify


class FetchNewsTests(unittest.TestCase):
    def test_parse_rss_and_skip_invalid_entries(self):
        payload = b"""<rss><channel><item><title>Hello &amp; Code</title><link>https://example.com/a</link><description><![CDATA[<p>Useful story</p>]]></description></item><item><title>No URL</title></item></channel></rss>"""
        articles = parse_feed(payload, "https://feed.example/rss")
        self.assertEqual(articles[0].title, "Hello & Code")
        self.assertEqual(articles[0].description, "Useful story")
        self.assertEqual(len(articles), 1)

    def test_deduplicate_urls_and_missing_content(self):
        first = Article("A", "https://example.com/a", "body", "feed")
        duplicate = Article("A again", "https://example.com/a/", "body", "feed")
        empty = Article("Empty", "https://example.com/b", "", "feed")
        self.assertEqual(deduplicate([first, duplicate, empty]), [first])

    def test_slug_is_safe_and_stable(self):
        self.assertEqual(slugify("C++: The Future of AI / Tools!"), "c-the-future-of-ai-tools")
        self.assertEqual(slugify("中文标题"), "tech-news")

    def test_render_post_contains_front_matter_and_source(self):
        article = Article("Original", "https://example.com/story", "body", "https://feed.example")
        content = render_post(article, {"title": "中文标题", "summary": "摘要", "key_points": ["重点一", "重点二"]}, __import__("datetime").date(2026, 1, 2))
        self.assertTrue(content.startswith("---\n"))
        self.assertIn('source_url: "https://example.com/story"', content)
        self.assertIn("### 关键点", content)


if __name__ == "__main__":
    unittest.main()
