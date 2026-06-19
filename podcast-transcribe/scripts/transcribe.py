#!/usr/bin/env python3
"""播客链接 → 音频下载 → whisper 转录 → 带时间戳 Markdown。

用法: python3 transcribe.py "<小宇宙链接|音频直链|本地音频文件>" [--output DIR] [--model HF_REPO]
引擎: 优先 mlx-whisper (Apple GPU)，缺失时回退本机 whisper CLI
输出: <DIR>/<标题slug>.md，stdout 打印路径
"""
import re, sys, os, html, json, argparse, subprocess, tempfile, shutil, pathlib
from datetime import date, datetime

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def curl(url, out=None, timeout=1800):
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-H", f"User-Agent: {UA}", url]
    if out:
        subprocess.run(cmd + ["-o", out], timeout=timeout + 60, check=True)
        return out
    return subprocess.run(cmd, capture_output=True, timeout=timeout + 60).stdout.decode("utf-8", "ignore")


def slugify(title):
    return re.sub(r'[\\/:*?"<>|\s，。！？]+', "-", title).strip("-")[:60] or "episode"


def ts(sec):
    sec = max(0, float(sec))
    return f"{int(sec // 3600):02d}:{int(sec % 3600 // 60):02d}:{int(sec % 60):02d}"


def probe_duration(path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(r.stdout.strip())
    except (FileNotFoundError, ValueError, subprocess.CalledProcessError):
        return None


def write_status(workdir, **data):
    status = pathlib.Path(workdir) / "status.json"
    current = {}
    if status.exists():
        try:
            current = json.loads(status.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    current.update(data)
    current["updated_at"] = datetime.now().isoformat(timespec="seconds")
    status.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_markdown(title, source, duration, engine, segs):
    body = "\n".join(f"[{ts(t)}] {txt}" for t, txt in segs if txt)
    return (f"---\ntitle: {title}\nsource: {source}\nduration: {ts(duration) if duration else '?'}\n"
            f"engine: {engine}\ntranscribed: {date.today()}\ntags: [播客]\n---\n\n"
            f"# {title}\n\n{body}\n")


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


def transcribe(audio, model, offset=0):
    """返回 [(start_sec, text)]。优先 mlx-whisper，回退 whisper CLI(small)。"""
    try:
        import mlx_whisper
        print(f"🎙  mlx-whisper ({model}) 转录中...", file=sys.stderr)
        r = mlx_whisper.transcribe(audio, path_or_hf_repo=model)
        return [(offset + s["start"], s["text"].strip()) for s in r["segments"]], f"mlx-whisper/{model.split('/')[-1]}"
    except ImportError:
        print("⚠️  无 mlx_whisper，回退 whisper CLI small（CPU，较慢）", file=sys.stderr)
        outdir = tempfile.mkdtemp(prefix="whisper-cli-")
        try:
            subprocess.run(["whisper", audio, "--model", "small", "--output_format", "json",
                            "--output_dir", outdir], check=True)
            j = json.load(open(next(pathlib.Path(outdir).glob("*.json"))))
            return [(offset + s["start"], s["text"].strip()) for s in j["segments"]], "whisper-cli/small"
        finally:
            shutil.rmtree(outdir, ignore_errors=True)


def split_audio(audio, chunk_dir, chunk_seconds):
    chunk_dir.mkdir(parents=True, exist_ok=True)
    ext = pathlib.Path(audio).suffix or ".m4a"
    pattern = str(chunk_dir / f"chunk-%05d{ext}")
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", audio,
        "-f", "segment", "-segment_time", str(chunk_seconds), "-c", "copy", pattern,
    ], check=True)
    return sorted(chunk_dir.glob("chunk-*.m4a"))


def save_segments(path, segs):
    path.write_text(json.dumps(segs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_segments(path):
    return [(float(t), str(txt)) for t, txt in json.loads(path.read_text(encoding="utf-8"))]


def transcribe_long(audio, title, source, model, out, duration, chunk_minutes):
    """长音频分段转录。每段完成后写入 workdir，可断点续跑。"""
    workdir = out.with_suffix(".work")
    chunk_dir = workdir / "chunks"
    segment_dir = workdir / "segments"
    segment_dir.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix(".partial.md")
    write_status(workdir, state="splitting", source=source, title=title, duration_seconds=duration)

    chunk_seconds = max(1, int(chunk_minutes * 60))
    chunks = sorted(chunk_dir.glob("chunk-*.*")) or split_audio(audio, chunk_dir, chunk_seconds)
    total = len(chunks)
    all_segs, engine = [], None
    default_engine = f"mlx-whisper/{model.split('/')[-1]}"
    print(f"🧩 长音频模式: {ts(duration)}，切成 {total} 段，每段约 {chunk_minutes:g} 分钟", file=sys.stderr)

    for idx, chunk in enumerate(chunks, start=1):
        seg_file = segment_dir / f"{chunk.stem}.json"
        offset = (idx - 1) * chunk_seconds
        write_status(workdir, state="transcribing", chunk=idx, total_chunks=total,
                     chunk_path=str(chunk), partial_path=str(partial))
        if seg_file.exists():
            segs = load_segments(seg_file)
            engine = engine or default_engine
            print(f"↩️  复用第 {idx}/{total} 段: {chunk.name}", file=sys.stderr)
        else:
            print(f"🎙  转录第 {idx}/{total} 段: {chunk.name} (+{ts(offset)})", file=sys.stderr)
            segs, engine = transcribe(str(chunk), model, offset=offset)
            save_segments(seg_file, segs)
        all_segs.extend(segs)
        partial.write_text(render_markdown(title, source, duration, engine or "unknown", all_segs), encoding="utf-8")

    out.write_text(render_markdown(title, source, duration, engine or "unknown", all_segs), encoding="utf-8")
    write_status(workdir, state="done", chunk=total, total_chunks=total, output_path=str(out),
                 partial_path=str(partial), segments=len(all_segs))
    return all_segs, engine or "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--output", "-o", default=str(pathlib.Path.home() / "Archive/podcasts"))
    ap.add_argument("--model", default="mlx-community/whisper-large-v3-turbo")
    ap.add_argument("--long-threshold-minutes", type=float, default=60,
                    help="超过该时长自动分段转录，默认 60 分钟")
    ap.add_argument("--chunk-minutes", type=float, default=30,
                    help="长音频分段分钟数，默认 30")
    ap.add_argument("--force-single", action="store_true",
                    help="强制整条音频一次性转录")
    a = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="podcast-") as tmpdir:
        audio, title = resolve(a.source, tmpdir)
        duration = probe_duration(audio)
        slug = slugify(title)
        out = pathlib.Path(a.output) / f"{slug}.md"
        out.parent.mkdir(parents=True, exist_ok=True)

        if duration:
            print(f"⏱  音频时长: {ts(duration)}", file=sys.stderr)
        should_chunk = duration and not a.force_single and duration >= a.long_threshold_minutes * 60
        if should_chunk:
            segs, engine = transcribe_long(audio, title, a.source, a.model, out, duration, a.chunk_minutes)
        else:
            segs, engine = transcribe(audio, a.model)
            duration = duration or (segs[-1][0] if segs else 0)
            out.write_text(render_markdown(title, a.source, duration, engine, segs), encoding="utf-8")

        print(f"✅ {title} | 时长 {ts(duration) if duration else '?'} | 段数 {len(segs)}", file=sys.stderr)
        print(out)


if __name__ == "__main__":
    main()
