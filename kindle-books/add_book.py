#!/usr/bin/env python3
"""Fetch an ebook (e.g. from mek.oszk.hu), make it Kindle-readable, and
update the static site in ./site (books/ folder, books.json, index.html).

Usage: python3 add_book.py <url> [title override]
"""
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

SITE = Path("site")
BOOKS = SITE / "books"
INDEX_JSON = SITE / "books.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; personal-ebook-fetcher)"}

# Preference order when a page offers several formats.
PREFERENCE = [".mobi", ".azw3", ".azw", ".epub", ".pdf", ".txt"]


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read(), resp.headers.get_content_charset()


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def decode_page(raw, header_charset):
    charset = header_charset
    if not charset:
        m = re.search(rb'charset=["\']?([A-Za-z0-9_-]+)', raw[:4096])
        charset = m.group(1).decode() if m else "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def ext_of(url):
    return Path(urlparse(url).path).suffix.lower()


def find_file(url):
    """Return (file_url, page_title or None)."""
    if ext_of(url) in PREFERENCE:
        return url, None
    raw, cs = fetch(url)
    parser = PageParser()
    parser.feed(decode_page(raw, cs))
    candidates = {}
    for href in parser.links:
        full = urljoin(url, href)
        ext = ext_of(full)
        if ext in PREFERENCE and ext not in candidates:
            candidates[ext] = full
    for ext in PREFERENCE:
        if ext in candidates:
            return candidates[ext], html.unescape(parser.title).strip() or None
    sys.exit("No .mobi/.azw3/.epub/.pdf/.txt link found on that page.")


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:60] or "book"


def convert_epub(src, dst):
    subprocess.run(["ebook-convert", str(src), str(dst)], check=True)


def write_index(books):
    rows = "\n".join(
        f'<a href="books/{html.escape(b["file"])}">{html.escape(b["title"])}</a>'
        for b in books
    ) or "<p>No books yet.</p>"
    page = f"""<!doctype html>
<html lang="hu"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width">
<title>Books</title>
<style>
body{{font-family:serif;font-size:1.3em;margin:1em;color:#000;background:#fff}}
a{{display:block;padding:.8em 0;border-bottom:1px solid #000;color:#000;text-decoration:none}}
</style></head><body>
<h1>Books</h1>
{rows}
</body></html>
"""
    (SITE / "index.html").write_text(page, encoding="utf-8")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    url = sys.argv[1].strip()
    override = sys.argv[2].strip() if len(sys.argv) > 2 else ""

    file_url, page_title = find_file(url)
    ext = ext_of(file_url)
    fallback_name = unquote(Path(urlparse(file_url).path).stem)
    title = override or page_title or fallback_name
    slug = slugify(title)

    BOOKS.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {file_url}")
    data, _ = fetch(file_url)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{ext}"
        src.write_bytes(data)
        if ext == ".epub":
            out_name = f"{slug}.mobi"
            convert_epub(src, BOOKS / out_name)
        else:
            out_name = f"{slug}{ext}"
            shutil.copy(src, BOOKS / out_name)

    books = json.loads(INDEX_JSON.read_text("utf-8")) if INDEX_JSON.exists() else []
    books = [b for b in books if b["file"] != out_name]
    books.insert(0, {"title": title, "file": out_name, "added": str(date.today())})
    INDEX_JSON.write_text(json.dumps(books, ensure_ascii=False, indent=2), "utf-8")
    write_index(books)
    print(f"Added: {title} -> books/{out_name}")


if __name__ == "__main__":
    main()
