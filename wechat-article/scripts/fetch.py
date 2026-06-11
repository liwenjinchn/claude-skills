#!/usr/bin/env python3
"""公众号文章 → Markdown(保结构) + 全部配图下载。

用法: python3 fetch.py "https://mp.weixin.qq.com/s/xxx" [--output DIR]
输出: <DIR>/<标题slug>/article.md + img/NN.png，stdout 打印 article.md 路径
"""
import re, sys, argparse, subprocess, pathlib

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
BLOCK = re.compile("环境异常|请在微信客户端|访问过于频繁")


def get(url: str) -> bytes:
    r = subprocess.run(["curl", "-sL", "--max-time", "30", "-H", f"User-Agent: {UA}", url],
                       capture_output=True, timeout=40)
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--output", "-o", default=str(pathlib.Path.home() / "Archive/articles"))
    a = ap.parse_args()

    html = get(a.url).decode("utf-8", "ignore")
    if BLOCK.search(html):
        sys.exit("BLOCKED: 微信反爬拦截。兜底方案：grok-search web_fetch（拿正文，无图）")

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    meta = lambda p: (soup.find("meta", attrs={"property": p}) or {}).get("content", "")
    h1 = soup.find("h1", class_="rich_media_title")
    title = h1.get_text(strip=True) if h1 else (meta("og:title") or "未命名")
    nick = soup.find("span", class_="rich_media_meta_nickname")
    author = nick.get_text(strip=True) if nick else meta("og:article:author")
    body = soup.find("div", id="js_content") or soup.find("div", class_="rich_media_content")
    if body is None:
        sys.exit("FAILED: 找不到正文容器（可能是纯图片文/已删除）。兜底：grok web_fetch")

    slug = re.sub(r'[\\/:*?"<>|\s，。！？]+', "-", title).strip("-")[:40]
    outdir = pathlib.Path(a.output) / slug
    (outdir / "img").mkdir(parents=True, exist_ok=True)

    # 图片：下载 data-src，并把 <img> 节点替换为 markdown 占位
    n_img = 0
    for img in body.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if not src.startswith("http"):
            img.decompose(); continue
        n_img += 1
        m = re.search(r"wx_fmt=(\w+)", src)
        ext = {"jpeg": "jpg"}.get(m.group(1), m.group(1)) if m else "png"
        p = outdir / "img" / f"{n_img:02d}.{ext}"
        data = get(src)
        if len(data) > 1000:
            p.write_bytes(data)
            img.replace_with(f"\n\n![图{n_img}](img/{p.name})\n\n")
        else:
            img.decompose(); n_img -= 1

    # 只取叶子块级元素，保段落结构、防嵌套重复
    blocks = ["p", "section", "h1", "h2", "h3", "h4", "h5", "blockquote", "li", "pre"]
    lines = []
    for blk in body.find_all(blocks):
        if blk.find(blocks):
            continue
        txt = blk.get_text().strip()
        if txt:
            lines.append(txt)
    if not lines:
        lines = [body.get_text("\n", strip=True)]

    from datetime import date
    md = (f"---\ntitle: {title}\nauthor: {author}\nsource: {a.url}\n"
          f"fetched: {date.today()}\nimages: {n_img}\ntags: [公众号]\n---\n\n# {title}\n\n"
          + "\n\n".join(lines) + "\n")
    md = re.sub(r"\n{3,}", "\n\n", md)
    out = outdir / "article.md"
    out.write_text(md, encoding="utf-8")
    print(f"✅ {title} | 图片 {n_img} 张", file=sys.stderr)
    print(out)


if __name__ == "__main__":
    main()
