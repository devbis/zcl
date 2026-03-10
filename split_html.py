#!/usr/bin/env python3
"""Split converted ZCL HTML into multiple section files and rewrite anchors."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

SECTION_ID_RE = re.compile(r"^section-(\d+)(?:-.*)?$")
FIGURE_TABLE_ID_RE = re.compile(r"^(?:figure|table)-(\d+)(?:-.*)?$", re.IGNORECASE)
CHAPTER_HEADING_RE = re.compile(r"^\s*CHAPTER\s+(\d+)\b", re.IGNORECASE)


def root_from_anchor_id(anchor_id: str | None) -> str | None:
    if not anchor_id:
        return None
    match = SECTION_ID_RE.match(anchor_id)
    if not match:
        match = FIGURE_TABLE_ID_RE.match(anchor_id)
        if not match:
            return None
    return match.group(1)


def root_from_chapter_heading(node: Tag) -> str | None:
    if node.name not in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return None
    heading_text = node.get_text(" ", strip=True)
    match = CHAPTER_HEADING_RE.match(heading_text)
    if not match:
        return None
    return match.group(1)


def clone_source_html(source_soup: BeautifulSoup) -> BeautifulSoup:
    return BeautifulSoup(str(source_soup), "html.parser")


def main_container(soup: BeautifulSoup) -> Tag:
    container = soup.select_one("body .container")
    if container is not None:
        return container
    if soup.body is None:
        raise ValueError("Input HTML has no <body> element")
    return soup.body


def collect_chunks(source_soup: BeautifulSoup) -> tuple[dict[str, list[str]], dict[str, str]]:
    container = main_container(source_soup)
    chunks: dict[str, list[str]] = {"index": []}
    id_to_root: dict[str, str] = {}
    current_root: str | None = None

    for node in list(container.children):
        if isinstance(node, NavigableString):
            text = str(node)
            if not text.strip():
                continue
            bucket = current_root if current_root is not None else "index"
            chunks.setdefault(bucket, []).append(text)
            continue

        if not isinstance(node, Tag):
            continue

        node_root = root_from_anchor_id(node.get("id"))
        chapter_root = root_from_chapter_heading(node)
        if chapter_root is not None:
            current_root = chapter_root
        if node_root is not None:
            current_root = node_root

        for tagged in node.find_all(attrs={"id": True}):
            section_id = tagged.get("id")
            if not isinstance(section_id, str):
                continue
            tagged_root = root_from_anchor_id(section_id)
            if tagged_root is not None:
                id_to_root[section_id] = tagged_root

        if node.get("id"):
            section_id = str(node.get("id"))
            node_id_root = root_from_anchor_id(section_id)
            if node_id_root is not None:
                id_to_root[section_id] = node_id_root

        bucket = current_root if current_root is not None else "index"
        chunks.setdefault(bucket, []).append(str(node))

    return chunks, id_to_root


def rewrite_links(container: Tag, current_root: str | None, id_to_root: dict[str, str]) -> None:
    for link in container.select('a[href^="#"]'):
        href = link.get("href")
        if not isinstance(href, str):
            continue
        target_id = href[1:]
        target_root = id_to_root.get(target_id) or root_from_anchor_id(target_id)
        if target_root is None:
            continue
        if current_root == target_root:
            link["href"] = f"#{target_id}"
        else:
            link["href"] = f"section-{target_root}.html#{target_id}"


def write_chunk(
    source_soup: BeautifulSoup,
    fragments: list[str],
    output_path: Path,
    current_root: str | None,
    id_to_root: dict[str, str],
) -> None:
    doc = clone_source_html(source_soup)
    container = main_container(doc)
    container.clear()

    for fragment in fragments:
        fragment_soup = BeautifulSoup(fragment, "html.parser")
        for item in fragment_soup.contents:
            container.append(item)

    rewrite_links(container, current_root=current_root, id_to_root=id_to_root)
    output_path.write_text(str(doc), encoding="utf-8")


def split_html(input_file: Path, output_dir: Path) -> None:
    if not input_file.exists():
        raise FileNotFoundError(f"Input HTML does not exist: {input_file}")

    source_soup = BeautifulSoup(input_file.read_text(encoding="utf-8"), "html.parser")
    chunks, id_to_root = collect_chunks(source_soup)

    output_dir.mkdir(parents=True, exist_ok=True)

    for key, fragments in chunks.items():
        if not fragments:
            continue
        filename = "index.html" if key == "index" else f"section-{key}.html"
        current_root = None if key == "index" else key
        write_chunk(
            source_soup=source_soup,
            fragments=fragments,
            output_path=output_dir / filename,
            current_root=current_root,
            id_to_root=id_to_root,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split converted HTML by section and rewrite links.")
    parser.add_argument("input_html", type=Path, help="Source .html file")
    parser.add_argument("output_dir", type=Path, help="Directory for split .html files")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    split_html(args.input_html, args.output_dir)


if __name__ == "__main__":
    main()
