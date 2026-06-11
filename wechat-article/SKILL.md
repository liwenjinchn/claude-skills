---
name: wechat-article
description: >
  公众号文章抓取 + 图文分析。当用户粘贴 mp.weixin.qq.com 链接（无论是否附带其他指令）时使用：
  抓正文（保留段落结构）并下载全部配图到本地，然后逐张读图，连同文字一起分析。
  触发词：公众号链接、"分析这篇文章"、"抓一下这篇"、mp.weixin.qq.com URL。
---

# 公众号文章抓取分析

## 流程

1. **抓取**（正文 + 全部配图落盘）：

   ```bash
   python3 ~/.claude/skills/wechat-article/scripts/fetch.py "<mp.weixin.qq.com 链接>"
   ```

   - 输出 `~/Archive/articles/<标题slug>/article.md` + `img/NN.png`，stdout 是 article.md 路径
   - 依赖 beautifulsoup4（已装）

2. **读取**：Read article.md，然后 **逐张 Read img/ 下的图片**——研报类文章的核心证据
   （图表、数据图、结构图）往往全在图里，跳过读图等于丢一半信息。

3. **分析**：默认输出「速读卡」——
   - **核心论点**（1-3 条，文章真正想证明什么）
   - **关键证据**（文字论据 + 图表各自说了什么，注明"图N"）
   - **值得深挖的问题**（2-3 个，文章没回答或回答得心虚的）

   用户明确要深度分析时，再升级为五维拆解（核心论点/框架方法/数据证据/洞见盲点/个人启发）。

## 失败兜底（按顺序）

1. 脚本报 `BLOCKED`（微信反爬）→ 用 grok-search `web_fetch` 拿正文（保结构但无图），并告知用户图片层缺失
2. grok 也失败 → 请用户微信里"复制链接"重试一次（链接可能带过期 token），或直接粘贴全文

## 注意

- 纯图片排版的文章（正文容器为空）脚本会明确报错，不要静默当成功
- 图片下载小于 1KB 视为失败自动跳过，`images:` frontmatter 记录的是实际落盘数
