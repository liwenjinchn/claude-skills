---
name: podcast-transcribe
description: >
  播客转录 + 内容分析。当用户粘贴 xiaoyuzhoufm.com 链接、播客音频直链（.mp3/.m4a）
  或本地音频文件并希望转文字/分析时使用：下载音频 → mlx-whisper 转录（Apple GPU）→
  带时间戳 Markdown → 内容分析。触发词：小宇宙链接、"转录这个播客"、"听一下这期"。
---

# 播客转录分析

## 流程

1. **转录**（下载 + mlx-whisper large-v3-turbo，2.5h 音频约 8-15 分钟，建议 run_in_background）：

   ```bash
   python3 ~/.claude/skills/podcast-transcribe/scripts/transcribe.py "<小宇宙链接或音频直链>"
   ```

   - 输出 `~/Archive/podcasts/<标题slug>.md`（frontmatter + `[hh:mm:ss] 文本` 逐段）
   - 转录前先看页面 `"duration"` 字段估时长，超过 1 小时务必后台跑，期间可干别的

2. **读取**：转录文件可能很长（2h ≈ 2000+ 段），先 Read 开头确认质量，再分段读或用 Grep 定位主题

3. **分析**：默认输出——
   - **本期核心观点**（3-5 条，带 [时间戳] 方便回听定位）
   - **嘉宾的关键判断/预测**（明确区分事实陈述 vs 个人观点）
   - **值得追问的点**（主持人没追、嘉宾没展开的）

## 引擎与兜底

- 优先 `mlx_whisper`（已装，模型 mlx-community/whisper-large-v3-turbo，首跑自动下载 ~1.6GB）
- HuggingFace 下载慢/失败 → `HF_ENDPOINT=https://hf-mirror.com` 重试
- mlx 不可用 → 脚本自动回退本机 `whisper` CLI small（CPU 慢且准确率低，仅应急）
- 页面无 og:audio（非小宇宙平台）→ 用 `yt-dlp -x` 下音频（支持喜马拉雅/B站/YouTube），再把本地文件传给脚本

## 注意

- 中文转录准确率 ~90-95%，专有名词（人名/公司名）常错，引用原话时注明"转录稿，未校对"
- 不支持说话人分离，多人对谈需靠上下文判断谁在说
