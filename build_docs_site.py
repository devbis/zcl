#!/usr/bin/env python3
"""Build a navigable documentation site from split section HTML files."""

from __future__ import annotations

import argparse
import html
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, Tag

SECTION_FILE_RE = re.compile(r"^section-(\d+)\.html$", re.IGNORECASE)
HEADING_TAG_RE = re.compile(r"^h([1-6])$", re.IGNORECASE)
PILCROW_TAIL_RE = re.compile(r"(?:\s*¶\s*)+$")


@dataclass
class OnPageItem:
    anchor_id: str
    text: str
    level: int


@dataclass
class Page:
    filename: str
    source_path: Path
    title: str
    chapter_number: int | None
    content_html: str
    on_page_items: list[OnPageItem]


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def normalize_nav_text(value: str) -> str:
    cleaned = normalize_text(value)
    return PILCROW_TAIL_RE.sub("", cleaned).strip()


def chapter_from_filename(filename: str) -> int | None:
    match = SECTION_FILE_RE.match(filename)
    if not match:
        return None
    return int(match.group(1))


def source_container(soup: BeautifulSoup) -> Tag:
    container = soup.select_one("body .container")
    if container is not None:
        return container
    if soup.body is not None:
        return soup.body
    return soup


def derive_title(container: Tag, filename: str) -> str:
    headings = container.find_all(HEADING_TAG_RE)
    if filename == "index.html":
        for heading in headings:
            text = normalize_nav_text(heading.get_text(" ", strip=True))
            if "TABLE OF CONTENTS" in text.upper():
                return text
        return "Table of Contents"
    for heading in headings:
        text = normalize_nav_text(heading.get_text(" ", strip=True))
        if text:
            return text
    return Path(filename).stem


def collect_on_page_items(container: Tag) -> list[OnPageItem]:
    items: list[OnPageItem] = []
    seen_ids: set[str] = set()
    for heading in container.find_all(HEADING_TAG_RE):
        anchor_id = heading.get("id")
        if not isinstance(anchor_id, str) or not anchor_id.strip():
            continue
        if anchor_id in seen_ids:
            continue
        text = normalize_nav_text(heading.get_text(" ", strip=True))
        if not text:
            continue
        level_match = HEADING_TAG_RE.match(heading.name or "")
        level = int(level_match.group(1)) if level_match else 2
        seen_ids.add(anchor_id)
        items.append(OnPageItem(anchor_id=anchor_id, text=text, level=level))
    return items


def load_page(path: Path) -> Page:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    container = source_container(soup)
    title = derive_title(container, path.name)
    on_page_items = collect_on_page_items(container)
    content_html = "".join(str(node) for node in container.contents)
    return Page(
        filename=path.name,
        source_path=path,
        title=title,
        chapter_number=chapter_from_filename(path.name),
        content_html=content_html,
        on_page_items=on_page_items,
    )


def ids_in_content(content_html: str) -> set[str]:
    soup = BeautifulSoup(f"<div>{content_html}</div>", "html.parser")
    return {
        tag_id
        for tag in soup.find_all(True)
        for tag_id in [tag.get("id")]
        if isinstance(tag_id, str) and tag_id
    }


def infer_compact_section_link(
    compact_value: str,
    known_filenames: set[str],
    ids_by_file: dict[str, set[str]],
) -> tuple[str, str] | None:
    for split_idx in range(1, len(compact_value)):
        chapter_raw = compact_value[:split_idx]
        section_raw = compact_value[split_idx:]
        try:
            chapter = int(chapter_raw)
            section = int(section_raw)
        except ValueError:
            continue
        target_file = f"section-{chapter}.html"
        if target_file not in known_filenames:
            continue
        target_id = f"section-{chapter}-{section}"
        if target_id in ids_by_file.get(target_file, set()):
            return target_file, target_id
    return None


def rewrite_links_in_content(
    content_html: str,
    current_filename: str,
    known_filenames: set[str],
    ids_by_file: dict[str, set[str]],
    first_heading_by_file: dict[str, str | None],
) -> str:
    wrapper = BeautifulSoup(f"<div>{content_html}</div>", "html.parser")
    local_ids = ids_by_file.get(current_filename, set())
    section_prefix_re = re.compile(r"^section-\d+$")

    for link in wrapper.select("a[href]"):
        href = link.get("href")
        if not isinstance(href, str) or not href or href.startswith(("http://", "https://", "mailto:")):
            continue

        if href.startswith("#"):
            target_id = href[1:]
            if target_id and target_id not in local_ids:
                link.replace_with(link.get_text())
            continue

        file_part, sep, anchor = href.partition("#")
        target_name = Path(file_part).name

        if target_name in known_filenames:
            if not sep or not anchor:
                continue
            target_ids = ids_by_file.get(target_name, set())
            if anchor in target_ids:
                continue
            if section_prefix_re.fullmatch(anchor):
                fallback = next((item for item in target_ids if item.startswith(anchor + "-")), None)
                if fallback is not None:
                    link["href"] = f"{target_name}#{fallback}"
                    continue
            first_heading = first_heading_by_file.get(target_name)
            if first_heading is not None:
                link["href"] = f"{target_name}#{first_heading}"
                continue
            link.replace_with(link.get_text())
            continue

        if sep and anchor:
            compact_match = re.fullmatch(r"section-(\d+)", anchor)
            if compact_match:
                inferred = infer_compact_section_link(
                    compact_match.group(1), known_filenames=known_filenames, ids_by_file=ids_by_file
                )
                if inferred is not None:
                    inferred_file, inferred_id = inferred
                    link["href"] = f"{inferred_file}#{inferred_id}"
                    continue

        link.replace_with(link.get_text())

    host = wrapper.find("div")
    return "".join(str(node) for node in host.contents) if host is not None else content_html


def discover_pages(input_dir: Path) -> list[Path]:
    index_path = input_dir / "index.html"
    if not index_path.exists():
        raise FileNotFoundError(f"Missing index.html in {input_dir}")

    section_paths = []
    for path in input_dir.glob("section-*.html"):
        chapter = chapter_from_filename(path.name)
        if chapter is None:
            continue
        section_paths.append((chapter, path))
    section_paths.sort(key=lambda entry: entry[0])
    return [index_path] + [path for _, path in section_paths]


def build_sidebar(pages: list[Page], current_filename: str) -> str:
    items = []
    for page in pages:
        label = page.title
        if page.chapter_number is not None:
            label = f"Chapter {page.chapter_number}: {label}"
        active_class = " active" if page.filename == current_filename else ""
        items.append(
            '<li class="docs-sidebar-item">'
            f'<a class="docs-sidebar-link{active_class}" href="{html.escape(page.filename)}">'
            f"{html.escape(label)}</a></li>"
        )
    return (
        '<div class="docs-sidebar-inner">'
        '<h2 class="docs-sidebar-title">Navigation</h2>'
        '<ul class="docs-sidebar-list">'
        + "".join(items)
        + "</ul></div>"
    )


def build_on_this_page(items: list[OnPageItem]) -> str:
    if not items:
        return '<p class="docs-toc-empty">No headings on this page</p>'
    links = []
    for item in items:
        indent_class = f"toc-level-{min(max(item.level, 1), 6)}"
        links.append(
            '<li class="docs-toc-item">'
            f'<a class="docs-toc-link {indent_class}" href="#{html.escape(item.anchor_id)}">'
            f"{html.escape(item.text)}</a></li>"
        )
    return '<ul class="docs-toc-list">' + "".join(links) + "</ul>"


def build_prev_next(pages: list[Page], index: int) -> tuple[Page | None, Page | None]:
    prev_page = pages[index - 1] if index > 0 else None
    next_page = pages[index + 1] if index + 1 < len(pages) else None
    return prev_page, next_page


def render_page_html(site_title: str, pages: list[Page], page_index: int) -> str:
    page = pages[page_index]
    prev_page, next_page = build_prev_next(pages, page_index)
    sidebar_html = build_sidebar(pages, current_filename=page.filename)
    on_page_html = build_on_this_page(page.on_page_items)

    prev_html = (
        f'<a class="btn btn-outline-secondary btn-sm" href="{html.escape(prev_page.filename)}">← Previous</a>'
        if prev_page
        else '<span class="btn btn-outline-secondary btn-sm disabled">← Previous</span>'
    )
    next_html = (
        f'<a class="btn btn-outline-secondary btn-sm" href="{html.escape(next_page.filename)}">Next →</a>'
        if next_page
        else '<span class="btn btn-outline-secondary btn-sm disabled">Next →</span>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(page.title)} - {html.escape(site_title)}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css"/>
  <style>
    body {{ background: #f8fafc; }}
    .docs-layout {{ min-height: 100vh; }}
    .docs-sidebar {{
      border-right: 1px solid #e5e7eb;
      background: #ffffff;
      padding: 1.25rem 1rem;
    }}
    .docs-sidebar-inner {{ position: sticky; top: 1rem; max-height: calc(100vh - 2rem); overflow: auto; }}
    .docs-sidebar-title {{ font-size: 1rem; margin-bottom: 0.75rem; }}
    .docs-sidebar-list {{ list-style: none; margin: 0; padding: 0; }}
    .docs-sidebar-item {{ margin-bottom: 0.35rem; }}
    .docs-sidebar-link {{
      display: block; padding: 0.35rem 0.5rem; border-radius: 0.4rem;
      text-decoration: none; color: #334155; font-size: 0.92rem;
    }}
    .docs-sidebar-link:hover {{ background: #eef2ff; color: #1e3a8a; }}
    .docs-sidebar-link.active {{ background: #dbeafe; color: #1d4ed8; font-weight: 600; }}
    .docs-main {{ padding: 1.5rem 1.5rem 2rem 1.5rem; }}
    .docs-topbar {{
      display: flex; justify-content: space-between; align-items: center; gap: 0.75rem;
      margin-bottom: 1rem; flex-wrap: wrap;
    }}
    .docs-content {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 0.75rem; padding: 1.25rem; overflow-x: auto; }}
    .docs-content img {{ max-width: 100%; height: auto; }}
    .docs-content table {{ font-size: 0.92rem; }}
    .docs-toc {{
      border-left: 1px solid #e5e7eb;
      background: #ffffff;
      padding: 1.25rem 1rem;
    }}
    .docs-toc-inner {{ position: sticky; top: 1rem; max-height: calc(100vh - 2rem); overflow: auto; }}
    .docs-toc-title {{ font-size: 1rem; margin-bottom: 0.75rem; }}
    .docs-toc-list {{ list-style: none; margin: 0; padding: 0; }}
    .docs-toc-item {{ margin-bottom: 0.3rem; }}
    .docs-toc-link {{ text-decoration: none; color: #475569; display: block; font-size: 0.88rem; }}
    .docs-toc-link:hover {{ color: #1d4ed8; }}
    .toc-level-1, .toc-level-2 {{ padding-left: 0; }}
    .toc-level-3 {{ padding-left: 0.6rem; }}
    .toc-level-4 {{ padding-left: 1rem; }}
    .toc-level-5 {{ padding-left: 1.4rem; }}
    .toc-level-6 {{ padding-left: 1.8rem; }}
    .docs-toc-empty {{ color: #64748b; font-size: 0.9rem; margin: 0; }}
    @media (max-width: 991px) {{
      .docs-sidebar, .docs-toc {{ border: 0; }}
      .docs-sidebar-inner, .docs-toc-inner {{ position: static; max-height: none; }}
    }}
  </style>
</head>
<body>
  <div class="container-fluid docs-layout">
    <div class="row">
      <aside class="col-12 col-lg-3 col-xl-2 docs-sidebar">{sidebar_html}</aside>
      <main class="col-12 col-lg-7 col-xl-8 docs-main">
        <div class="docs-topbar">
          <div class="d-flex gap-2 align-items-center">
            <a class="btn btn-primary btn-sm" href="index.html">Home</a>
            <span class="text-muted small">{html.escape(site_title)}</span>
          </div>
          <div class="d-flex gap-2">{prev_html}{next_html}</div>
        </div>
        <article class="docs-content">{page.content_html}</article>
      </main>
      <aside class="col-12 col-lg-2 docs-toc">
        <div class="docs-toc-inner">
          <h2 class="docs-toc-title">On this page</h2>
          {on_page_html}
        </div>
      </aside>
    </div>
  </div>
</body>
</html>
"""


def copy_non_html_assets(input_dir: Path, output_dir: Path) -> None:
    for entry in input_dir.iterdir():
        if entry.name.endswith(".html"):
            continue
        target = output_dir / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        elif entry.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, target)


def build_docs_site(input_dir: Path, output_dir: Path, site_title: str) -> None:
    page_paths = discover_pages(input_dir)
    pages = [load_page(path) for path in page_paths]
    known_filenames = {page.filename for page in pages}
    ids_by_file = {page.filename: ids_in_content(page.content_html) for page in pages}
    first_heading_by_file = {
        page.filename: page.on_page_items[0].anchor_id if page.on_page_items else None for page in pages
    }

    for page in pages:
        page.content_html = rewrite_links_in_content(
            content_html=page.content_html,
            current_filename=page.filename,
            known_filenames=known_filenames,
            ids_by_file=ids_by_file,
            first_heading_by_file=first_heading_by_file,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    copy_non_html_assets(input_dir, output_dir)

    for index, page in enumerate(pages):
        rendered = render_page_html(site_title=site_title, pages=pages, page_index=index)
        (output_dir / page.filename).write_text(rendered, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a navigable docs site from a folder containing index.html + section-*.html files."
    )
    parser.add_argument("input_dir", type=Path, help="Folder with split HTML files")
    parser.add_argument("output_dir", type=Path, help="Output folder for generated docs site")
    parser.add_argument("--title", default="ZCL Documentation", help="Site title shown in page header")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_docs_site(input_dir=args.input_dir, output_dir=args.output_dir, site_title=args.title)


if __name__ == "__main__":
    main()
