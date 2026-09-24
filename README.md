# 觉傲博客

## 每日科技新闻

`.github/workflows/daily-tech-news.yml` 每天 UTC 01:15（北京时间 09:15）运行，也可以在
Actions 页面用 **workflow_dispatch** 手动运行。它从 `scripts/fetch_news.py` 中的公开
RSS 源抓取英文科技/编程新闻，用 OpenAI 整理为中文文章并写入 `_posts/`。

一次性配置：

1. 在仓库 **Settings → Actions → General → Workflow permissions** 选择允许读写仓库内容。
2. 在 **Settings → Secrets and variables → Actions** 添加名为 `OPENAI_API_KEY` 的
   repository secret。没有该 secret 时任务会明确失败，不会生成空文章。
3. 若使用组织策略限制 Actions，请允许该 workflow 使用 `contents: write`。

本地运行（需要 Python 3.9+，不会把密钥写入文件）：

```bash
OPENAI_API_KEY=sk-... python scripts/fetch_news.py
python -m unittest discover -s scripts -p 'test_*.py'
```

可通过环境变量 `NEWS_FEEDS`（逗号分隔）替换 RSS 源，`NEWS_MAX_ARTICLES` 限制每次
文章数，`OPENAI_MODEL` 更换模型；也可以用重复的 `--feed URL` 参数临时指定源。
修改 workflow 中的 cron 即可调整调度。脚本会读取已有文章的 `source_url` 去重，没
有新文章时不会创建或提交任何文件。
