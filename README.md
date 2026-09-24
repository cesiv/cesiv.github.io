# 觉傲博客

## 每日科技新闻

`.github/workflows/daily-tech-news.yml` 每天 UTC 01:15（北京时间 09:15）运行，也可以在
Actions 页面用 **workflow_dispatch** 手动运行。它使用 Python 标准库抓取公开 RSS/Atom
源，生成保留原文标题和 feed 摘要的 Jekyll 文章，不调用 AI 服务，也不需要任何 Secret。

默认来源覆盖技术/编程和科技财经：

- Hacker News、GitHub Blog、InfoQ（技术/编程）
- TechCrunch、CNBC Technology（科技财经）

来源配置在 `scripts/fetch_news.py` 的 `DEFAULT_FEEDS` 中，包含 URL、来源名称和分类，
可以直接修改。也可以通过 `NEWS_FEEDS`（逗号分隔 URL）临时替换，或重复使用
`--feed URL`；`NEWS_MAX_ARTICLES` 限制每次文章数。

本地运行（Python 3.9+，无需环境变量或密钥）：

```bash
python scripts/fetch_news.py
python -m unittest discover -s scripts -p 'test_*.py'
```

文章明确标注“自动抓取/原文摘要”，不会伪造中文翻译或 AI 摘要；如果需要中文翻译，
请另接可信的翻译服务，但该功能不属于本流程，也不会成为 workflow 的 Secret 依赖。
脚本按原文链接稳定去重，重复运行不会重复生成文章；feed 超时、无效 XML、缺标题或
链接的条目会被清晰记录并跳过。仅使用来源公开提供的 RSS/Atom，不绕过登录、robots
限制或付费墙，也不会高频抓取。
