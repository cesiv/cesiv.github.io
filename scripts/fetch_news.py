#!/usr/bin/env python3
"""Fetch public RSS/Atom news feeds and write source-preserving Jekyll posts."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class FeedConfig:
    url: str
    source: str
    category: str


DEFAULT_FEEDS = (
    FeedConfig("https://hnrss.org/frontpage", "Hacker News", "技术/编程"),
    FeedConfig("https://github.blog/feed/", "GitHub Blog", "技术/编程"),
    FeedConfig("https://www.infoq.com/feed/", "InfoQ", "技术/编程"),
    FeedConfig("https://feeds.feedburner.com/TechCrunch/", "TechCrunch", "科技财经"),
    FeedConfig("https://www.cnbc.com/id/19854910/device/rss/rss.html", "CNBC Technology", "科技财经"),
)
DEFAULT_MAX_ARTICLES = 5
DEFAULT_TIMEOUT = 20
USER_AGENT = "cesiv.github.io public RSS news bot/1.0"


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    description: str
    source: str
    published: str = ""
    author: str = ""
    category: str = "技术/编程"


class _HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._ignored:
            self._ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            self.parts.append(data)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def text_content(element: Optional[ET.Element]) -> str:
    return "" if element is None else " ".join(" ".join(element.itertext()).split())


def strip_html(value: str) -> str:
    parser = _HTMLTextParser()
    parser.feed(html.unescape(value or ""))
    parser.close()
    return " ".join(" ".join(parser.parts).split()).strip()


def _field(fields: dict[str, ET.Element], *names: str) -> str:
    for name in names:
        value = text_content(fields.get(name))
        if value:
            return value
    return ""


def _entry_url(entry: ET.Element) -> str:
    links = [child for child in entry if local_name(child.tag) == "link"]
    for link in links:
        if link.attrib.get("rel", "alternate") in {"alternate", ""} and link.attrib.get("href"):
            return link.attrib["href"].strip()
    for link in links:
        value = link.attrib.get("href") or text_content(link)
        if value.strip():
            return value.strip()
    return ""


def parse_feed(
    payload: bytes,
    feed_url: str,
    source: str = "",
    category: str = "技术/编程",
) -> List[Article]:
    """Parse RSS 2.0 or Atom, skipping entries without a usable title/link."""
    root = ET.fromstring(payload)
    entries = [node for node in root.iter() if local_name(node.tag) in {"item", "entry"}]
    articles: List[Article] = []
    for index, entry in enumerate(entries, 1):
        fields = {local_name(child.tag): child for child in entry}
        title = strip_html(_field(fields, "title"))
        url = _entry_url(entry)
        if not title or not url.startswith(("http://", "https://")):
            print(f"Warning: skipped entry {index} in {feed_url}: missing title or HTTP(S) link.", file=sys.stderr)
            continue
        description = strip_html(_field(fields, "description", "summary", "content", "encoded"))
        published = _field(fields, "pubdate", "published", "updated", "date")
        author = strip_html(_field(fields, "author", "creator"))
        articles.append(Article(title, url, description, source or feed_url, published, author, category))
    return articles


def fetch_feed(config: FeedConfig, timeout: int = DEFAULT_TIMEOUT) -> List[Article]:
    request = urllib.request.Request(config.url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return parse_feed(response.read(), config.url, config.source, config.category)


def canonical_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/") or "/", parsed.query, ""))


def deduplicate(articles: Iterable[Article], seen_urls: Iterable[str] = ()) -> List[Article]:
    seen = {canonical_url(url) for url in seen_urls if url}
    result: List[Article] = []
    for article in articles:
        key = canonical_url(article.url)
        if key in seen:
            continue
        seen.add(key)
        result.append(article)
    return result


def slugify(title: str, max_length: int = 70) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not normalized:
        normalized = "tech-news"
    return normalized[:max_length].rstrip("-") or "tech-news"


def article_filename(article: Article, published_date: dt.date) -> str:
    digest = hashlib.sha256(canonical_url(article.url).encode("utf-8")).hexdigest()[:10]
    return f"{published_date.isoformat()}-{slugify(article.title)}-{digest}.md"


def existing_source_urls(posts_dir: Path) -> set[str]:
    urls: set[str] = set()
    for path in posts_dir.glob("*.md"):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        urls.update(canonical_url(url) for url in re.findall(r"^source_url:\s*[\"']?(\S+?)[\"']?\s*$", content, re.MULTILINE))
    return urls


def yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def render_post(article: Article, published_date: dt.date) -> str:
    description = article.description or "Feed 未提供摘要，请阅读原文。"
    return (
        "---\n"
        "layout: post\n"
        f"title: {yaml_quote(article.title)}\n"
        "published: true\n"
        "categories:\n"
        f"  - {yaml_quote(article.category)}\n"
        "tags:\n"
        "  - 科技\n"
        f"date: {published_date.isoformat()}\n"
        f"source_url: {yaml_quote(article.url)}\n"
        f"source: {yaml_quote(article.source)}\n"
        f"author: {yaml_quote(article.author)}\n"
        f"published_at: {yaml_quote(article.published)}\n"
        "---\n\n"
        "> 自动抓取/原文摘要；未使用 AI 翻译或改写。\n\n"
        f"**来源**：{article.source}  \n"
        f"**分类**：{article.category}  \n"
        f"**发布时间**：{article.published or 'Feed 未提供'}  \n\n"
        "### 原文标题\n\n"
        f"{article.title}\n\n"
        "### 原文摘要\n\n"
        f"{description}\n\n"
        f"[阅读原文]({article.url})\n"
    )


def _feed_configs(feed_urls: Sequence[str]) -> List[FeedConfig]:
    defaults_by_url = {feed.url: feed for feed in DEFAULT_FEEDS}
    return [defaults_by_url.get(url.strip(), FeedConfig(url.strip(), url.strip(), "技术/编程")) for url in feed_urls if url.strip()]


def run(posts_dir: Path, feeds: Sequence[str], max_articles: int) -> int:
    all_articles: List[Article] = []
    failures: List[str] = []
    for config in _feed_configs(feeds):
        try:
            articles = fetch_feed(config)
            print(f"Fetched {len(articles)} item(s) from {config.source}.")
            all_articles.extend(articles)
        except (OSError, ET.ParseError, ValueError) as exc:
            failures.append(f"{config.url}: {exc}")
            print(f"Warning: skipped feed {config.url}: {exc}", file=sys.stderr)
    if not all_articles:
        detail = "; ".join(failures) or "feeds returned no valid entries"
        raise RuntimeError(f"No valid news items were fetched ({detail}).")
    candidates = deduplicate(all_articles, existing_source_urls(posts_dir))[:max_articles]
    if not candidates:
        if failures:
            print("Warning: some feeds failed: " + "; ".join(failures), file=sys.stderr)
        print("No new articles to publish.")
        return 0
    today = dt.date.today()
    posts_dir.mkdir(parents=True, exist_ok=True)
    for article in candidates:
        path = posts_dir / article_filename(article, today)
        if not path.exists():
            path.write_text(render_post(article, today), encoding="utf-8")
    if failures:
        print("Warning: some feeds failed: " + "; ".join(failures), file=sys.stderr)
    print(f"Published {len(candidates)} article(s).")
    return len(candidates)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--posts-dir", type=Path, default=Path("_posts"))
    parser.add_argument("--feed", action="append", dest="feeds", help="Override feeds; repeat for multiple URLs.")
    parser.add_argument("--max-articles", type=int, default=int(os.getenv("NEWS_MAX_ARTICLES", DEFAULT_MAX_ARTICLES)))
    args = parser.parse_args(argv)
    feeds = args.feeds or tuple(filter(None, os.getenv("NEWS_FEEDS", ",".join(feed.url for feed in DEFAULT_FEEDS)).split(",")))
    if args.max_articles < 1:
        raise RuntimeError("--max-articles must be at least 1")
    return run(args.posts_dir, feeds, args.max_articles)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
