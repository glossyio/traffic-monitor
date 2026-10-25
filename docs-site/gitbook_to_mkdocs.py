#!/usr/bin/env python3
"""Convert docs/ from GitBook-flavored Markdown to Material for MkDocs.

A one-time migration helper. It's kept until every branch written before the
move has been converted, then deleted. It's safe to re-run. From the repo
root:

    python3 docs-site/gitbook_to_mkdocs.py

What it does:
- {% hint %} blocks become admonitions (!!! info, warning, ...).
- "mention" links become plain links, titled after the page or heading they
  point to. GitBook ignored their link text, which is often just a filename.
- GitBook <figure>/<picture> images become Markdown images, which MkDocs
  checks and rewrites. Side-by-side <div> pairs become Material grids.
- Images move from docs/.gitbook/assets/ to docs/assets/images/, because
  MkDocs skips folders that start with a dot. Spaces and parentheses are
  removed from filenames.
- Pages in MOVES move so their file path matches the URL GitBook served.
- Links to https://docs.trafficmonitor.ai become relative links.
- GitBook's `icon:` front matter and trailing `&#x20;` entities are dropped.

GitBook card tables (<table data-view="cards">) are left for hand-editing.
"""

import posixpath
import re
import subprocess
import unicodedata
from pathlib import Path

DOCS = Path("docs")
OLD_ASSETS = ".gitbook/assets"
NEW_ASSETS = "assets/images"
SITE = "https://docs.trafficmonitor.ai"

# Pages whose file moves so its path matches the URL GitBook served.
MOVES = {
    "recommended-hardware.md": "build-your-own-device-diy/recommended-hardware.md",
}

# GitBook URL paths that don't match a file path.
URL_ALIASES = {
    "build-your-own-device-diy/software-installation": "software-installation.md",
    "sensor-payloads/events-payload": "data-and-payloads/events-payload.md",
    "sensor-payloads/radar-payload": "data-and-payloads/radar-payload.md",
    "sensor-payloads/air-quality-aq-payload": "data-and-payloads/air-quality-aq-payload.md",
}

LINK_RE = re.compile(r'(!?)\[((?:[^\[\]]|\[[^\]]*\])*)\]\((<[^<>\n]*>|[^()\s]+(?:\([^()\s]*\))?[^()\s]*)(?:\s+"([^"]*)")?\)')
ATTR_RE = re.compile(r'\b(href|src|srcset)="([^"]*)"')
FENCE_RE = re.compile(r"^( *)(```|~~~).*?^\1\2[ \t]*$", re.M | re.S)
HINT_RE = re.compile(r'^\{% hint style="(\w+)" %\}[ \t]*\n(.*?)\n?^\{% endhint %\}[ \t]*$', re.M | re.S)
FIGURE_RE = re.compile(r"<figure>(.*?)</figure>", re.S)
DIV_PAIR_RE = re.compile(r"^<div>((?:\s*<figure>.*?</figure>)+)\s*</div>[ \t]*$", re.M | re.S)
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)


def asset_name(name):
    stem, dot, ext = name.rpartition(".")
    stem = re.sub(r"[\s()]+", "-", stem).strip("-")
    return f"{stem}.{ext}" if dot else re.sub(r"[\s()]+", "-", name).strip("-")


def new_path(old):
    """Map a docs-relative path from GitBook's layout to the new one."""
    if old in MOVES:
        return MOVES[old]
    if old.startswith(OLD_ASSETS + "/"):
        return NEW_ASSETS + "/" + asset_name(old[len(OLD_ASSETS) + 1:])
    return old


def plain(text):
    """Heading or link text as plain text: no markup, escapes, or HTML."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("&#x20;", " ").replace("&#x26;", "&")
    text = re.sub(r"\\(.)", r"\1", text)
    return re.sub(r"[*`]", "", text).strip()


def mkdocs_slug(text):
    # Python-Markdown's default toc slugify.
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def gitbook_slug(text):
    text = re.sub(r"[^\w\s.-]", "", text.lower())
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return "id-" + text if text[:1].isdigit() else text


def page_info(text):
    """Title (first H1) and {anchor: (mkdocs anchor, heading text)} of a page."""
    title, anchors = None, {}
    for level, raw in HEADING_RE.findall(strip_code(text)):
        heading = plain(raw)
        if level == "#" and title is None:
            title = heading
        slug = mkdocs_slug(heading)
        anchors.setdefault(slug, (slug, heading))
        anchors.setdefault(gitbook_slug(heading), (slug, heading))
    return title, anchors


def strip_code(text):
    return FENCE_RE.sub("", text)


def outside_code(text, func):
    """Apply func to the parts of text that aren't fenced code blocks."""
    out, pos = [], 0
    for m in FENCE_RE.finditer(text):
        out.append(func(text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(func(text[pos:]))
    return "".join(out)


class Converter:
    def __init__(self):
        self.pages = {}  # old docs-relative path -> text
        for f in sorted(DOCS.rglob("*.md")):
            rel = f.relative_to(DOCS).as_posix()
            if not rel.startswith("."):
                self.pages[rel] = f.read_text(encoding="utf-8")
        self.info = {new_path(p): page_info(t) for p, t in self.pages.items()}

    def resolve(self, target, page_old):
        """New docs-relative path and fragment for a link target, or None if
        it isn't a link into the docs."""
        if target.startswith(SITE):
            url = target[len(SITE):]
            url, _, frag = url.partition("#")
            url = url.strip("/")
            if url in URL_ALIASES:
                return URL_ALIASES[url], frag
            for cand in ([url + ".md", url + "/README.md"] if url else ["README.md"]):
                if cand in self.info:
                    return cand, frag
            return None
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
            return None
        path, _, frag = target.partition("#")
        if not path:
            return new_path(page_old), frag
        path = path.replace("%20", " ")
        old = posixpath.normpath(posixpath.join(posixpath.dirname(page_old), path))
        if path.endswith("/") or (DOCS / old).is_dir():
            old = posixpath.join(old, "README.md")
        return new_path(old), frag

    def relink(self, target, page_old, page_new):
        resolved = self.resolve(target, page_old)
        if resolved is None:
            return target, None
        dest, frag = resolved
        info = self.info.get(dest)
        heading = None
        if info and frag:
            anchors = info[1]
            # GitBook kept anchors of renamed headings ("#temporary" for
            # "Temporary deployments"), so fall back to a heading that starts
            # with the anchor.
            key = frag if frag in anchors else next(
                (k for k in anchors if k.startswith(frag + "-")), None)
            if key:
                frag, heading = anchors[key]
        rel = posixpath.relpath(dest, posixpath.dirname(page_new) or ".")
        if dest == page_new and frag:
            rel = ""
        new = rel + ("#" + frag if frag else "")
        text = None
        if dest.endswith(".md") and info:
            text = heading if frag else info[0]
        return new, text

    def convert_links(self, text, page_old, page_new):
        def md_link(m):
            bang, label, target, title = m.groups()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            new, nice = self.relink(target, page_old, page_new)
            if title == "mention":
                title = None
                if not nice and label.startswith("#"):
                    nice = plain(label[1:]).replace("-", " ").capitalize()
                if nice:
                    label = nice.replace("[", "\\[").replace("]", "\\]")
            if " " in new:
                new = f"<{new}>"
            title_part = f' "{title}"' if title else ""
            return f"{bang}[{label}]({new}{title_part})"

        def attr(m):
            name, value = m.groups()
            new, _ = self.relink(value, page_old, page_new)
            return f'{name}="{new}"'

        text = LINK_RE.sub(md_link, text)
        return ATTR_RE.sub(attr, text)

    def convert(self, page_old):
        text = self.pages[page_old]
        page_new = new_path(page_old)
        text = re.sub(r"\A(---\n.*?)^icon:.*\n(.*?---\n)", r"\1\2", text, flags=re.M | re.S)
        text = re.sub(r"&#x20;[ \t]*$", "", text, flags=re.M)
        text = DIV_PAIR_RE.sub(convert_div_pair, text)
        text = FIGURE_RE.sub(convert_figure, text)
        text = outside_code(text, lambda part: self.convert_links(part, page_old, page_new))
        text = HINT_RE.sub(convert_hint, text)
        return page_new, text

    def run(self):
        results = {p: self.convert(p) for p in self.pages}
        moves = [(DOCS / p, DOCS / n) for p, (n, _) in results.items() if n != p]
        assets = DOCS / OLD_ASSETS
        if assets.is_dir():
            for f in sorted(assets.iterdir()):
                moves.append((f, DOCS / new_path(f"{OLD_ASSETS}/{f.name}")))
        for src, dst in moves:
            dst.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "mv", "-k", str(src), str(dst)], check=True)
            if src.exists():  # not tracked by git
                src.rename(dst)
        for p, (n, text) in results.items():
            path = DOCS / n
            if path.read_text(encoding="utf-8") != text:
                path.write_text(text, encoding="utf-8")
                print(f"converted {n}")
        for d in (DOCS / ".gitbook/assets", DOCS / ".gitbook"):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()


def convert_hint(m):
    style, body = m.groups()
    body = "\n".join("    " + line if line.strip() else "" for line in body.strip("\n").split("\n"))
    return f"!!! {style}\n\n{body}"


def figure_md(inner, indent=""):
    """Markdown for the inside of a GitBook <figure>."""
    cap = re.search(r"<figcaption>(.*?)</figcaption>", inner, re.S)
    caption = re.sub(r"^<p>(.*)</p>$", r"\1", cap.group(1).strip(), flags=re.S) if cap else ""
    imgs = []
    dark = re.search(r'<source srcset="([^"]*)" media="\(prefers-color-scheme: dark\)">', inner)
    for img in re.finditer(r'<img src="([^"]*)"(?: alt="([^"]*)")?[^>]*>', inner):
        src, alt = img.group(1), img.group(2) or ""
        if dark:
            imgs.append(f"![{alt}](<{src}#only-light>)")
            imgs.append(f"![{alt}](<{dark.group(1)}#only-dark>)")
        else:
            imgs.append(f"![{alt}](<{src}>)")
    if not caption:
        return "\n".join(indent + i for i in imgs)
    lines = [f'{indent}<figure markdown="span">']
    lines += [f"{indent}  {i}" for i in imgs]
    lines += [f"{indent}  <figcaption>{caption}</figcaption>", f"{indent}</figure>"]
    return "\n".join(lines)


def convert_figure(m):
    return figure_md(m.group(1))


def convert_div_pair(m):
    figures = [figure_md(f) for f in FIGURE_RE.findall(m.group(1))]
    return '<div class="grid" markdown>\n\n' + "\n\n".join(figures) + "\n\n</div>"


if __name__ == "__main__":
    Converter().run()
