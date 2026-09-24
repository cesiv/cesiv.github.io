#!/usr/bin/env python3
"""Fetch English technology news, summarize it in Chinese, and write Jekyll posts."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence


DEFAULT_FEEDS = (
    "https://hnrss.org/frontpage",
    "https://github.blog/feed/",
    "https://www.infoq.com/feed/",
)
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_MAX_ARTICLES = 5
DEFAULT_TIMEOUT = 20


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    description: str
    source: str
    published: str = ""


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def text_content(element: Optional[ET.Element]) -> str:
    if element is None:
        return ""
    return " ".join(" ".join(element.itertext()).split())


def strip_html(value: str) -> str:
    value = html.unescape(value or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def parse_feed(payload: bytes, feed_url: str) -> List[Article]:
    """Parse RSS 2.0 and Atom feeds, rejecting malformed entries."""
    root = ET.fromstring(payload)
    entries = [node for node in root.iter() if local_name(node.tag) in {"item", "entry"}]
    articles: List[Article] = []
    for entry in entries:
        fields = {local_name(child.tag): child for child in entry}
        title = strip_html(text_content(fields.get("title")))
        link_node = fields.get("link")
        url = ""
        if link_node is not None:
            url = (link_node.attrib.get("href") or text_content(link_node)).strip()
        description = strip_html(
            text_content(fields.get("description"))
            or text_content(fields.get("summary"))
            or text_content(fields.get("content"))
        )
        published = text_content(fields.get("pubdate") or fields.get("published") or fields.get("updated"))
        if title and url.startswith(("http://", "https://")):
            articles.append(Article(title, url, description, feed_url, published))
    return articles


def fetch_feed(url: str, timeout: int = DEFAULT_TIMEOUT) -> List[Article]:
    request = urllib.request.Request(url, headers={"User-Agent": "cesiv.github.io news bot/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return parse_feed(response.read(), url)


def deduplicate(articles: Iterable[Article], seen_urls: Iterable[str] = ()) -> List[Article]:
    seen = {url.rstrip("/") for url in seen_urls if url}
    result: List[Article] = []
    for article in articles:
        key = article.url.rstrip("/")
        if key in seen or not article.description:
            continue
        seen.add(key)
        result.append(article)
    return result


def slugify(title: str, max_length: int = 70) -> str:
    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return (slug[:max_length].rstrip("-") or "tech-news")


def existing_source_urls(posts_dir: Path) -> set[str]:
    urls: set[str] = set()
    for path in posts_dir.glob("*.md"):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        urls.update(re.findall(r"^source_url:\s*[\"']?(\S+?)[\"']?\s*$", content, re.MULTILINE))
    return urls


def request_summary(article: Article, api_key: str, model: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    prompt = (
        "请将下面这篇英文科技/编程新闻整理成中文。只返回 JSON，字段必须为 "
        "title（中文标题）、summary（不超过120字摘要）、key_points（3条中文关键点数组）。"
        f"\n标题：{article.title}\n正文：{article.description[:6000]}\n原文链接：{article.url}"
    )
    body = json.dumps({
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "你是严谨的中文科技新闻编辑，不要编造原文没有的信息。"},
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read())
        content = data["choices"][0]["message"]["content"]
        result = json.loads(content)
        if not isinstance(result.get("key_points"), list):
            raise ValueError("key_points must be an array")
        if not result.get("title") or not result.get("summary"):
            raise ValueError("summary response is missing title or summary")
        return result
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"OpenAI summarization failed for {article.url}: {exc}") from exc


def yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def render_post(article: Article, summary: dict, published_date: dt.date) -> str:
    points = "\n".join(f"  - {yaml_quote(str(point))}" for point in summary["key_points"][:5])
    return (
        "---\n"
        "layout: post\n"
        f"title: {yaml_quote(str(summary['title']))}\n"
        "published: true\n"
        "categories:\n"
        "  - 科技新闻\n"
        "tags:\n"
        "  - 编程\n"
        "  - 科技\n"
        f"date: {published_date.isoformat()}\n"
        f"source_url: {yaml_quote(article.url)}\n"
        f"source: {yaml_quote(article.source)}\n"
        "---\n\n"
        f"{summary['summary']}\n\n"
        "### 关键点\n\n"
        f"{points}\n\n"
        f"[阅读原文]({article.url})\n"
    )


def run(posts_dir: Path, feeds: Sequence[str], max_articles: int, api_key: str, model: str) -> int:
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required; add it to the environment or GitHub Actions secret.")
    all_articles: List[Article] = []
    failures: List[str] = []
    for feed in feeds:
        try:
            all_articles.extend(fetch_feed(feed))
        except (OSError, ET.ParseError, ValueError) as exc:
            failures.append(f"{feed}: {exc}")
    if not all_articles:
        detail = "; ".join(failures) or "feeds returned no valid entries"
        raise RuntimeError(f"No valid news items were fetched ({detail}).")
    candidates = deduplicate(all_articles, existing_source_urls(posts_dir))[:max_articles]
    if not candidates:
        print("No new articles to publish.")
        return 0
    today = dt.date.today()
    written = 0
    for article in candidates:
        summary = request_summary(article, api_key, model)
        path = posts_dir / f"{today.isoformat()}-{slugify(summary['title'])}.md"
        if path.exists():
            path = posts_dir / f"{today.isoformat()}-{slugify(summary['title'])}-{slugify(article.url)[-12:]}.md"
        path.write_text(render_post(article, summary, today), encoding="utf-8")
        written += 1
        time.sleep(0.2)
    if failures:
        print("Warning: some feeds failed: " + "; ".join(failures), file=sys.stderr)
    print(f"Published {written} article(s).")
    return written


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--posts-dir", type=Path, default=Path("_posts"))
    parser.add_argument("--feed", action="append", dest="feeds", help="Override feeds; repeat for multiple URLs.")
    parser.add_argument("--max-articles", type=int, default=int(os.getenv("NEWS_MAX_ARTICLES", DEFAULT_MAX_ARTICLES)))
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
    args = parser.parse_args(argv)
    feeds = args.feeds or tuple(filter(None, os.getenv("NEWS_FEEDS", ",".join(DEFAULT_FEEDS)).split(",")))
    if args.max_articles < 1:
        raise RuntimeError("--max-articles must be at least 1")
    return run(args.posts_dir, feeds, args.max_articles, os.getenv("OPENAI_API_KEY", ""), args.model)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
