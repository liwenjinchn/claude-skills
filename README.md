# claude-skills

个人在用的 Claude Code skills。粘贴一个链接，自动路由到对应 skill 完成「抓取 → 落盘 → 分析」。

| Skill | 触发 | 做什么 |
|---|---|---|
| [`wechat-article`](wechat-article/) | 粘贴 `mp.weixin.qq.com` 链接 | 抓正文（保留段落结构）+ **下载全部配图**，Agent 逐张读图后连同文字一起分析 |
| [`podcast-transcribe`](podcast-transcribe/) | 粘贴小宇宙链接 / 音频直链 / 本地音频 | 提取音频 → mlx-whisper 转录（Apple GPU，2.5h 节目约 10 分钟）→ 带时间戳 Markdown → 内容分析 |

两个 skill 的脚本都是独立 CLI，不依赖 Claude Code，其他 Agent（Codex 等）或者直接命令行也能用。

## 为什么自己写

市面上同类工具的公众号抓取普遍只取纯文本——而研报类文章的核心证据（图表、数据图、结构图）全在图片里。`wechat-article` 会把 `data-src` 里的全部配图下载到本地，配合多模态模型逐张读图，信息量完全不同。

`podcast-transcribe` 则是为 Apple Silicon 选型：mlx-whisper large-v3-turbo 走 GPU，比 CPU 跑 faster-whisper / openai-whisper 快得多，长播客才真正可用。

## 安装

### Claude Code

```bash
git clone https://github.com/liwenjinchn/claude-skills.git
cp -r claude-skills/wechat-article claude-skills/podcast-transcribe ~/.claude/skills/
```

之后在会话里直接粘贴链接即可触发；也可显式调用 `/wechat-article <url>`、`/podcast-transcribe <url>`。

### 依赖

```bash
# wechat-article
pip3 install beautifulsoup4

# podcast-transcribe（Apple Silicon 推荐）
pip3 install mlx-whisper          # 首跑自动下载模型 ~1.6GB
brew install ffmpeg
# 非 Apple Silicon：装 openai-whisper，脚本会自动回退（CPU，较慢）
```

## 直接命令行使用

```bash
# 公众号文章 → ~/Archive/articles/<标题>/article.md + img/
python3 wechat-article/scripts/fetch.py "https://mp.weixin.qq.com/s/xxx"

# 播客 → ~/Archive/podcasts/<标题>.md（带 [hh:mm:ss] 时间戳）
python3 podcast-transcribe/scripts/transcribe.py "https://www.xiaoyuzhoufm.com/episode/xxx"

# 输出目录均可用 --output 覆盖
```

过程文件（音频、中间产物）在临时目录，脚本退出时自动清理，成功失败都不留痕迹。

## 已知限制

- 公众号反爬是概率事件：被拦截时脚本明确报 `BLOCKED`（不静默失败），可换网络重试或退回手动粘贴全文
- 纯图片排版的文章无法提取正文（会明确报错）
- 转录中文准确率约 90–95%，专有名词常错，引用原话前需校对；不支持说话人分离

## 致谢

播客音频地址的 `og:audio` 提取思路参考了 [chubbyguan/chubbyskills](https://github.com/chubbyguan/chubbyskills)。

## License

MIT
