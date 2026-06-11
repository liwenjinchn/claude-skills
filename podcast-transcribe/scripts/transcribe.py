#!/usr/bin/env python3
"""播客链接 → 音频下载 → whisper 转录 → 带时间戳 Markdown。

用法: python3 transcribe.py "<小宇宙链接|音频直链|本地音频文件>" [--output DIR] [--model HF_REPO]
引擎: 优先 mlx-whisper (Apple GPU)，缺失时回退本机 whisper CLI
输出: <DIR>/<标题slug>.md，stdout 打印路径
"""
import re, sys, os, html, json, argparse, subprocess, tempfile, shutil, pathlib
from datetime import date

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def curl(url, out=None, timeout=1800):
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-H", f"User-Agent: {UA}", url]
    if out:
        subprocess.run(cmd + ["-o", out], timeout=timeout + 60, check=True)
        return out
    return subprocess.run(cmd, capture_output=True, timeout=timeout + 60).stdout.decode("utf-8", "ignore")


def resolve(src, tmpdir):
    """返回 (本地音频路径, 标题)。支持本地文件 / 音频直链 / 小宇宙等带 og:audio 的页面。"""
    if os.path.exists(src):
        return src, pathlib.Path(src).stem
    if re.search(r"\.(mp3|m4a|wav|aac|ogg)(\?|$)", src, re.I):
        audio_url, title = src, "episode"
    else:
        page = curl(src, timeout=30)
        og = lambda p: re.search(rf'<meta property="og:{p}" content="([^"]+)"', page)
        m = og("audio")
        if not m:
            sys.exit("FAILED: 页面里找不到 og:audio。兜底：试音频直链，或 yt-dlp（喜马拉雅/B站/YouTube）")
        audio_url = html.unescape(m.group(1))
        title = html.unescape(og("title").group(1)) if og("title") else "episode"
    ext = (re.search(r"\.(mp3|m4a|wav|aac|ogg)", audio_url, re.I) or [".mp3", "mp3"])[1]
    path = os.path.join(tmpdir, f"audio.{ext}")
    print(f"⬇️  下载音频: {audio_url[:80]}...", file=sys.stderr)
    curl(audio_url, out=path)
    if os.path.getsize(path) < 100_000:
        sys.exit("FAILED: 下载文件过小，可能不是音频")
    return path, title


def transcribe(audio, model):
    """返回 [(start_sec, text)]。优先 mlx-whisper，回退 whisper CLI(small)。"""
    try:
        import mlx_whisper
        print(f"🎙  mlx-whisper ({model}) 转录中...", file=sys.stderr)
        r = mlx_whisper.transcribe(audio, path_or_hf_repo=model)
        return [(s["start"], s["text"].strip()) for s in r["segments"]], f"mlx-whisper/{model.split('/')[-1]}"
    except ImportError:
        print("⚠️  无 mlx_whisper，回退 whisper CLI small（CPU，较慢）", file=sys.stderr)
        outdir = tempfile.mkdtemp(prefix="whisper-cli-")
        try:
            subprocess.run(["whisper", audio, "--model", "small", "--output_format", "json",
                            "--output_dir", outdir], check=True)
            j = json.load(open(next(pathlib.Path(outdir).glob("*.json"))))
            return [(s["start"], s["text"].strip()) for s in j["segments"]], "whisper-cli/small"
        finally:
            shutil.rmtree(outdir, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--output", "-o", default=str(pathlib.Path.home() / "Archive/podcasts"))
    ap.add_argument("--model", default="mlx-community/whisper-large-v3-turbo")
    a = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="podcast-") as tmpdir:
        audio, title = resolve(a.source, tmpdir)
        segs, engine = transcribe(audio, a.model)

        ts = lambda s: f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{int(s % 60):02d}"
        body = "\n".join(f"[{ts(t)}] {txt}" for t, txt in segs if txt)
        dur = ts(segs[-1][0]) if segs else "?"
        slug = re.sub(r'[\\/:*?"<>|\s，。！？]+', "-", title).strip("-")[:60]
        out = pathlib.Path(a.output) / f"{slug}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"---\ntitle: {title}\nsource: {a.source}\nduration: {dur}\n"
                       f"engine: {engine}\ntranscribed: {date.today()}\ntags: [播客]\n---\n\n"
                       f"# {title}\n\n{body}\n", encoding="utf-8")
        print(f"✅ {title} | 时长 {dur} | 段数 {len(segs)}", file=sys.stderr)
        print(out)


if __name__ == "__main__":
    main()
