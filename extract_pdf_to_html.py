#!/usr/bin/env python3
"""Extract Zigbee Cluster Library PDF content to structured HTML."""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import fitz
from bs4 import BeautifulSoup

ALLOWED_TAGS = {
    "table",
    "tr",
    "th",
    "td",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "strong",
    "i",
    "u",
    "br",
    "ul",
    "ol",
    "li",
    "html",
    "head",
    "body",
    "div",
    "span",
    "link",
    "title",
    "meta",
    "a",
    "em",
    "img",
    "nav",
}

ALLOWED_ATTRS = {
    "link": {"href", "rel"},
    "meta": {"charset", "name", "content"},
    "a": {"href", "name", "id", "class"},
    "h1": {"id"},
    "h2": {"id"},
    "h3": {"id"},
    "h4": {"id"},
    "h5": {"id"},
    "h6": {"id"},
    "img": {"src", "alt", "class"},
    "nav": {"class"},
    "*": {"class"},
}

SECTION_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\b")
SECTION_ONLY_FULL_RE = re.compile(r"^\s*\d+(?:\.\d+){2,}\s*$")
SECTION_ONLY_RE = re.compile(r"^\s*\d+(?:\.\d+)+\s*$")
TOC_SECTION_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\s+(.+)$")
TOC_CHAPTER_RE = re.compile(r"^\s*Chapter\s+(\d+)\b", re.IGNORECASE)
TOC_CHAPTER_ONLY_RE = re.compile(r"^\s*Chapter\s+\d+\s*$", re.IGNORECASE)
TOC_SECTION_ONLY_RE = re.compile(r"^\s*\d+(?:\.\d+)+\s*$")


def is_bold(span: Dict) -> bool:
    flags = int(span.get("flags", 0))
    font_name = str(span.get("font", "")).lower()
    return bool(flags & 2) or "bold" in font_name or "black" in font_name


def is_italic(span: Dict) -> bool:
    flags = int(span.get("flags", 0))
    font_name = str(span.get("font", "")).lower()
    return bool(flags & 1) or "italic" in font_name or "oblique" in font_name


def heading_tag(font_size: float, has_bold: bool) -> str | None:
    if font_size >= 20:
        return "h1"
    if font_size >= 16:
        return "h2"
    if font_size >= 14:
        return "h3"
    if font_size >= 12.5:
        return "h4"
    if font_size >= 11 and has_bold:
        return "h5"
    return None


def section_depth_heading_tag(text: str) -> str | None:
    compact = " ".join(text.split())
    if not SECTION_ONLY_FULL_RE.match(compact):
        return None
    depth = compact.count(".") + 1
    level = max(3, min(6, depth))
    return f"h{level}"


def section_id(text: str) -> str | None:
    match = SECTION_RE.match(text)
    if not match:
        return None
    return f"section-{match.group(1).replace('.', '-')}"


def unique_anchor_id(anchor: str | None, used_ids: set[str]) -> str | None:
    if not anchor:
        return None
    if anchor not in used_ids:
        used_ids.add(anchor)
        return anchor

    suffix = 2
    while f"{anchor}-{suffix}" in used_ids:
        suffix += 1
    unique_id = f"{anchor}-{suffix}"
    used_ids.add(unique_id)
    return unique_id


def bbox_intersects(a: Sequence[float], b: Sequence[float]) -> bool:
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def is_header_footer_line(text: str, y_pos: float, page_height: float) -> bool:
    in_margin = y_pos < 72 or y_pos > page_height - 72
    if not in_margin:
        return False

    lowered = " ".join(text.lower().split())
    if "copyright" in lowered and "zigbee alliance" in lowered:
        return True
    if "zigbee alliance document" in lowered:
        return True
    if "zigbee document" in lowered and "075123" in lowered:
        return True
    if "zigbee cluster library specification" in lowered:
        return True
    if re.fullmatch(r"chapter\s+\d+\s+[a-z][a-z0-9/&(),\-\s]*", lowered):
        return True
    if re.fullmatch(r"page\s+\d+(?:-\d+)?", lowered):
        return True
    return False


def is_empty_cell(value: str | None) -> bool:
    return value is None or not str(value).strip()


def normalize_table_cell_text(value: str | None) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<!\w)_(?!\w)", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def clean_table_rows(rows: List[List[str | None]]) -> List[List[str]]:
    if not rows:
        return []

    max_cols = max(len(row) for row in rows)
    normalized: List[List[str]] = [
        [normalize_table_cell_text(cell) for cell in (row + [""] * (max_cols - len(row)))]
        for row in rows
    ]

    normalized = [row for row in normalized if not all(is_empty_cell(cell) for cell in row)]
    if not normalized:
        return []

    keep_cols: List[int] = []
    for col_index in range(max_cols):
        column_values = [row[col_index] for row in normalized]
        if not all(is_empty_cell(value) for value in column_values):
            keep_cols.append(col_index)

    if not keep_cols:
        return []

    cleaned = [[row[col_index] for col_index in keep_cols] for row in normalized]
    return cleaned


def should_use_header(first_row: Sequence[str]) -> bool:
    if not first_row:
        return False
    return all(cell.strip() and len(cell.strip()) < 50 for cell in first_row)


def table_to_html(rows: List[List[str]]) -> str:
    if not rows:
        return ""

    header = should_use_header(rows[0])
    content_rows = rows[1:] if header else rows

    html_parts = ['<table class="table table-bordered">']
    if header:
        html_parts.append("<tr>")
        for cell in rows[0]:
            html_parts.append(f"<th>{html.escape(cell)}</th>")
        html_parts.append("</tr>")

    for row in content_rows:
        html_parts.append("<tr>")
        for cell in row:
            html_parts.append(f"<td>{html.escape(cell)}</td>")
        html_parts.append("</tr>")

    html_parts.append("</table>")
    return "".join(html_parts)


def extract_tables(page: fitz.Page) -> Tuple[List[Dict], List[Tuple[float, float, float, float]]]:
    elements: List[Dict] = []
    regions: List[Tuple[float, float, float, float]] = []

    tables = page.find_tables(vertical_strategy="lines_strict", horizontal_strategy="lines_strict")
    if not tables.tables:
        tables = page.find_tables(vertical_strategy="lines", horizontal_strategy="lines")
    for table in tables.tables:
        raw_rows = table.extract() or []
        cleaned = clean_table_rows(raw_rows)
        if not cleaned:
            continue

        bbox = tuple(table.bbox)
        table_html = table_to_html(cleaned)
        if not table_html:
            continue

        regions.append((bbox[0], bbox[1], bbox[2], bbox[3]))
        elements.append({"type": "table", "y": bbox[1], "html": table_html})

    return elements, regions


def style_span(text: str, bold: bool, italic: bool) -> str:
    value = html.escape(text)
    if italic:
        value = f"<em>{value}</em>"
    if bold:
        value = f"<strong>{value}</strong>"
    return value


def extract_text_lines(
    page: fitz.Page,
    table_regions: Sequence[Tuple[float, float, float, float]],
    page_number: int,
) -> List[Dict]:
    text_dict = page.get_text("dict")
    page_height = float(page.rect.height)
    lines: List[Dict] = []

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            bbox = tuple(line.get("bbox", (0, 0, 0, 0)))
            if any(bbox_intersects(bbox, region) for region in table_regions):
                continue

            span_html_parts: List[str] = []
            span_plain_parts: List[str] = []
            max_size = 0.0
            has_bold = False

            for span in line.get("spans", []):
                text = str(span.get("text", ""))
                if not text:
                    continue

                bold = is_bold(span)
                italic = is_italic(span)
                size = float(span.get("size", 0.0))
                max_size = max(max_size, size)
                has_bold = has_bold or bold

                span_plain_parts.append(text)
                span_html_parts.append(style_span(text, bold=bold, italic=italic))

            plain_text = "".join(span_plain_parts).strip()
            if not plain_text:
                continue
            x_pos = float(bbox[0])
            if is_header_footer_line(plain_text, float(bbox[1]), page_height):
                continue
            if re.fullmatch(r"\d+", plain_text):
                if int(plain_text) >= 10000:
                    continue
            if re.fullmatch(r"\d{1,4}", plain_text) and x_pos < 100:
                continue

            html_text = "".join(span_html_parts).strip()
            lines.append(
                {
                    "x": x_pos,
                    "y": float(bbox[1]),
                    "page_number": page_number,
                    "plain": plain_text,
                    "html": html_text,
                    "font_size": max_size,
                    "has_bold": has_bold,
                }
            )

    lines.sort(key=lambda item: item["y"])
    return lines


def remove_strong(html_fragment: str) -> str:
    soup = BeautifulSoup(html_fragment, "html.parser")
    for strong in soup.find_all("strong"):
        strong.unwrap()
    return str(soup)


def strip_toc_line_number(text: str) -> str:
    compact = " ".join(text.split())
    if not compact:
        return compact
    tokens = compact.split()
    if len(tokens) >= 2 and tokens[-1].isdigit() and re.fullmatch(r"\d+(?:-\d+)?", tokens[-2]):
        tokens = tokens[:-1]
    return " ".join(tokens)


def toc_line_to_html(text: str) -> str:
    plain = strip_toc_line_number(text)
    if not plain:
        return ""

    if re.fullmatch(r"\d+(?:\.\d+)*", plain):
        return f'<a href="#section-{plain.replace(".", "-")}">{html.escape(plain)}</a>'

    section_match = TOC_SECTION_RE.match(plain)
    if section_match:
        section = section_match.group(1).replace(".", "-")
        return f'<a href="#section-{section}">{html.escape(plain)}</a>'

    chapter_match = TOC_CHAPTER_RE.match(plain)
    if chapter_match:
        chapter = chapter_match.group(1)
        return f'<a href="#section-{chapter}">{html.escape(plain)}</a>'

    return html.escape(plain)


def is_toc_like_line(text: str) -> bool:
    plain = strip_toc_line_number(text)
    if TOC_SECTION_RE.match(plain):
        return True
    if TOC_CHAPTER_RE.match(plain):
        return True
    return "...." in plain


def is_running_chapter_header(text: str) -> bool:
    plain = " ".join(text.split())
    if "..." in plain:
        return False
    if re.search(r"\d+-\d+$", plain):
        return False
    return bool(re.fullmatch(r"Chapter\s+\d+\s+[A-Za-z][A-Za-z0-9/&(),\-\s]*", plain))


def merge_split_headings(elements: List[Dict], headings: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    merged: List[Dict] = []
    i = 0
    while i < len(elements):
        current = elements[i]
        current_text = str(current.get("text", "")).strip()
        current_level = int(current.get("level", 2))
        nxt = elements[i + 1] if i + 1 < len(elements) else None
        can_merge_wrapped_heading = bool(
            nxt
            and current.get("type") == "heading"
            and nxt.get("type") == "heading"
            and not nxt.get("id")
            and current_level == int(nxt.get("level", 2))
            and 3 <= current_level <= 6
            and (
                SECTION_ONLY_RE.match(current_text)
                or current_text.endswith("-")
                or current.get("id")
            )
        )
        if (
            can_merge_wrapped_heading
        ):
            next_text = str(nxt.get("text", "")).strip()
            if current_text.endswith("-"):
                merged_text = f"{current_text[:-1].rstrip()}{next_text.lstrip()}".strip()
            else:
                merged_text = f"{current_text} {next_text}".strip()
            level = current_level
            anchor = current.get("id")
            current["text"] = merged_text
            if anchor:
                current["html"] = f'<h{level} id="{anchor}">{html.escape(merged_text)}</h{level}>'
            else:
                current["html"] = f"<h{level}>{html.escape(merged_text)}</h{level}>"
            merged.append(current)
            i += 2
            continue

        merged.append(current)
        i += 1

    merged_headings = [item for item in merged if item.get("type") == "heading" and item.get("id")]
    return merged, merged_headings


def merge_line(
    current_html: str,
    current_plain: str,
    line_html: str,
    line_plain: str,
) -> Tuple[str, str]:
    if not current_plain:
        return line_html, line_plain

    if current_plain.endswith("-") and line_plain and line_plain[0].islower():
        stripped_html = current_html[:-1] if current_html.endswith("-") else current_html
        return stripped_html + line_html.lstrip(), current_plain[:-1] + line_plain.lstrip()

    return current_html + " " + line_html.lstrip(), current_plain + " " + line_plain.lstrip()


def append_paragraph(elements: List[Dict], y_value: float, paragraph_html: str, paragraph_plain: str) -> None:
    compact = " ".join(paragraph_plain.split())
    if re.fullmatch(r"\d+", compact):
        return
    if re.fullmatch(r"Chapter\s+\d+", compact):
        return
    if is_running_chapter_header(compact):
        return
    elements.append({"type": "paragraph", "y": y_value, "html": f"<p>{paragraph_html}</p>"})


def is_bullet_paragraph(paragraph_html: str) -> bool:
    soup = BeautifulSoup(paragraph_html, "html.parser")
    text = soup.get_text(" ", strip=True)
    return text in {"•", "·"}


def unwrap_paragraph(paragraph_html: str) -> str:
    soup = BeautifulSoup(paragraph_html, "html.parser")
    p = soup.find("p")
    if p is None:
        return paragraph_html
    return "".join(str(child) for child in p.contents).strip()


def merge_bullet_paragraphs(elements: List[Dict]) -> List[Dict]:
    merged: List[Dict] = []
    i = 0
    while i < len(elements):
        current = elements[i]
        if current.get("type") != "paragraph" or not is_bullet_paragraph(str(current.get("html", ""))):
            merged.append(current)
            i += 1
            continue

        list_items: List[str] = []
        start_y = float(current.get("y", 0.0))
        while i < len(elements) and elements[i].get("type") == "paragraph" and is_bullet_paragraph(
            str(elements[i].get("html", ""))
        ):
            if i + 1 >= len(elements) or elements[i + 1].get("type") != "paragraph":
                i += 1
                break
            item_html = unwrap_paragraph(str(elements[i + 1]["html"]))
            if item_html:
                list_items.append(f"<li>{item_html}</li>")
            i += 2

        if list_items:
            merged.append({"type": "list", "y": start_y, "html": f"<ul>{''.join(list_items)}</ul>"})
        else:
            merged.append(current)

    return merged


def extract_numbered_item(paragraph_html: str) -> Tuple[int, str] | None:
    soup = BeautifulSoup(paragraph_html, "html.parser")
    text = soup.get_text(" ", strip=True)
    match = re.match(r"^(\d+)\.\s+(.+)$", text)
    if not match:
        return None

    number = int(match.group(1))
    inner_html = unwrap_paragraph(paragraph_html)
    cleaned_inner = re.sub(rf"^\s*{number}\.\s*", "", inner_html, count=1).strip()
    if not cleaned_inner:
        cleaned_inner = html.escape(match.group(2))
    return number, cleaned_inner


def merge_ordered_paragraphs(elements: List[Dict]) -> List[Dict]:
    merged: List[Dict] = []
    i = 0
    while i < len(elements):
        current = elements[i]
        if current.get("type") != "paragraph":
            merged.append(current)
            i += 1
            continue

        parsed = extract_numbered_item(str(current.get("html", "")))
        if not parsed or parsed[0] != 1:
            merged.append(current)
            i += 1
            continue

        start_y = float(current.get("y", 0.0))
        expected = 1
        list_items: List[str] = []
        j = i
        while j < len(elements) and elements[j].get("type") == "paragraph":
            parsed_j = extract_numbered_item(str(elements[j].get("html", "")))
            if not parsed_j:
                break
            if parsed_j[0] != expected:
                break
            list_items.append(parsed_j[1])
            expected += 1
            j += 1
            while j < len(elements) and elements[j].get("type") == "paragraph":
                continuation = extract_numbered_item(str(elements[j].get("html", "")))
                if continuation:
                    break
                continuation_html = unwrap_paragraph(str(elements[j].get("html", "")))
                if continuation_html:
                    list_items[-1] = f"{list_items[-1]} {continuation_html}".strip()
                j += 1

        if len(list_items) >= 2:
            list_html = "".join(f"<li>{item}</li>" for item in list_items)
            merged.append({"type": "list", "y": start_y, "html": f"<ol>{list_html}</ol>"})
            i = j
        else:
            merged.append(current)
            i += 1

    return merged


def build_text_elements(
    lines: Sequence[Dict],
    used_section_ids: set[str],
    toc_mode: bool = False,
    toc_start_page: int | None = None,
    toc_pending_prefix: str | None = None,
) -> Tuple[List[Dict], List[Dict], bool, int | None, str | None]:
    elements: List[Dict] = []
    headings: List[Dict] = []

    paragraph_html = ""
    paragraph_plain = ""
    paragraph_y = 0.0
    prev_y = 0.0
    prev_x = 0.0
    has_paragraph = False
    pending_heading_level: int | None = None
    for line in lines:
        if not toc_mode and is_running_chapter_header(line["plain"]):
            continue

        forced_tag = None if toc_mode else section_depth_heading_tag(line["plain"])
        continuation_tag = None
        if (
            not toc_mode
            and pending_heading_level is not None
            and line["has_bold"]
            and not section_depth_heading_tag(line["plain"])
            and 1 < len(line["plain"].strip()) < 120
        ):
            continuation_tag = f"h{pending_heading_level}"

        tag = forced_tag or continuation_tag or heading_tag(line["font_size"], line["has_bold"])
        if toc_mode and is_toc_like_line(line["plain"]):
            tag = None
        if tag:
            if has_paragraph:
                append_paragraph(elements, paragraph_y, paragraph_html, paragraph_plain)
                paragraph_html = ""
                paragraph_plain = ""
                has_paragraph = False

            heading_text = remove_strong(line["html"])
            anchor = unique_anchor_id(section_id(line["plain"]), used_section_ids)
            anchor_attr = f' id="{anchor}"' if anchor else ""
            level = int(tag[1])
            heading_html = f"<{tag}{anchor_attr}>{heading_text}</{tag}>"
            heading_plain = " ".join(line["plain"].split())
            heading_upper = heading_plain.upper()
            if "TABLE OF CONTENTS" in heading_plain.upper():
                toc_mode = True
                toc_start_page = line["page_number"]
            elif toc_mode and (
                "LIST OF FIGURES" in heading_upper or "LIST OF TABLES" in heading_upper
            ):
                pass
            elif toc_mode and (
                heading_upper.startswith("CHAPTER ")
                or bool(re.fullmatch(r"[A-Z0-9/&(),\-\s]{4,}", heading_upper))
            ):
                toc_mode = False
                toc_start_page = None
                toc_pending_prefix = None
            elif toc_mode and anchor:
                toc_mode = False
                toc_start_page = None
                toc_pending_prefix = None
            heading_data = {
                "type": "heading",
                "y": line["y"],
                "html": heading_html,
                "level": level,
                "id": anchor,
                "text": line["plain"],
            }
            elements.append(heading_data)
            if anchor:
                headings.append(heading_data)
            pending_heading_level = level if forced_tag else None
            prev_y = line["y"]
            continue

        line_plain = line["plain"]
        line_html = line["html"]
        if toc_mode:
            line_plain = strip_toc_line_number(line_plain)
            if not line_plain:
                continue
            if toc_pending_prefix:
                line_plain = f"{toc_pending_prefix} {line_plain}".strip()
                toc_pending_prefix = None
            elif TOC_CHAPTER_ONLY_RE.match(line_plain) or TOC_SECTION_ONLY_RE.match(line_plain):
                toc_pending_prefix = line_plain
                continue
            line_html = toc_line_to_html(line_plain)

        if not has_paragraph:
            paragraph_html = line_html
            paragraph_plain = line_plain
            paragraph_y = line["y"]
            prev_y = line["y"]
            prev_x = line["x"]
            has_paragraph = True
            continue

        gap = line["y"] - prev_y
        indent_shift = line["x"] - prev_x
        if gap > 14 or (not toc_mode and indent_shift > 12):
            append_paragraph(elements, paragraph_y, paragraph_html, paragraph_plain)
            paragraph_html = line_html
            paragraph_plain = line_plain
            paragraph_y = line["y"]
        elif toc_mode:
            paragraph_html = paragraph_html + "<br/>" + line_html
            paragraph_plain = paragraph_plain + "\n" + line_plain
        else:
            paragraph_html, paragraph_plain = merge_line(
                paragraph_html,
                paragraph_plain,
                line_html,
                line_plain,
            )

        prev_y = line["y"]
        prev_x = line["x"]
        pending_heading_level = None

    if has_paragraph:
        append_paragraph(elements, paragraph_y, paragraph_html, paragraph_plain)

    merged_elements, merged_headings = merge_split_headings(elements, headings)
    merged_elements = merge_bullet_paragraphs(merged_elements)
    merged_elements = merge_ordered_paragraphs(merged_elements)
    return merged_elements, merged_headings, toc_mode, toc_start_page, toc_pending_prefix


def extract_images(
    document: fitz.Document,
    page: fitz.Page,
    page_number: int,
    images_dir: Path,
) -> List[Dict]:
    elements: List[Dict] = []
    image_infos = page.get_images(full=True)

    for index, image_info in enumerate(image_infos, start=1):
        xref = image_info[0]
        rects = page.get_image_rects(xref)
        if not rects:
            continue

        image = document.extract_image(xref)
        image_bytes = image.get("image")
        if image_bytes is None:
            continue

        ext = image.get("ext", "png")
        filename = f"page{page_number}_img{index}.{ext}"
        output_path = images_dir / filename
        output_path.write_bytes(image_bytes)

        rel_path = f"{images_dir.name}/{filename}"
        elements.append(
            {
                "type": "image",
                "y": rects[0].y0,
                "html": f'<img src="{html.escape(rel_path)}" alt="Extracted image" class="img-fluid mb-3"/>',
            }
        )

    return elements


def build_toc(headings: Sequence[Dict]) -> str:
    if not headings:
        return ""

    parts = [
        '<nav class="toc mb-4">',
        '<h2 class="mb-3">Table of Contents</h2>',
        '<ul class="list-unstyled">',
    ]

    current_level = 1
    for heading in headings:
        heading_id = heading.get("id")
        if not heading_id:
            continue

        level = max(1, min(6, int(heading["level"])))
        while current_level < level:
            parts.append('<ul class="list-unstyled">')
            current_level += 1
        while current_level > level:
            parts.append("</ul>")
            current_level -= 1

        title = html.escape(str(heading["text"]))
        parts.append(f'<li class="toc-level-{level}"><a href="#{heading_id}">{title}</a></li>')

    while current_level > 1:
        parts.append("</ul>")
        current_level -= 1

    parts.append("</ul>")
    parts.append("</nav>")
    return "\n".join(parts)


def sanitize_html(input_html: str) -> str:
    soup = BeautifulSoup(input_html, "html.parser")

    for tag in soup.find_all(True):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
            continue

        allowed = set(ALLOWED_ATTRS.get(tag.name, set())) | set(ALLOWED_ATTRS.get("*", set()))
        for attr in list(tag.attrs):
            if attr not in allowed:
                del tag.attrs[attr]

    return str(soup)


def convert_pdf_to_html(pdf_path: Path, output_path: Path, extract_page_images: bool) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"Input PDF does not exist: {pdf_path}")

    images_dir = output_path.with_suffix(output_path.suffix + ".images")
    if extract_page_images:
        images_dir.mkdir(parents=True, exist_ok=True)

    document = fitz.open(pdf_path)
    all_elements: List[Dict] = []
    used_section_ids: set[str] = set()
    toc_mode = False
    toc_start_page: int | None = None
    toc_pending_prefix: str | None = None

    try:
        for page_index in range(len(document)):
            page = document[page_index]
            table_elements, table_regions = extract_tables(page)
            text_lines = extract_text_lines(page, table_regions, page_index + 1)
            text_elements, _, toc_mode, toc_start_page, toc_pending_prefix = build_text_elements(
                text_lines,
                used_section_ids,
                toc_mode=toc_mode,
                toc_start_page=toc_start_page,
                toc_pending_prefix=toc_pending_prefix,
            )
            image_elements = (
                extract_images(document, page, page_index + 1, images_dir) if extract_page_images else []
            )

            page_elements = text_elements + table_elements + image_elements
            page_elements.sort(key=lambda item: item["y"])

            all_elements.extend(page_elements)
    finally:
        document.close()

    all_elements, _ = merge_split_headings(all_elements, [])

    body_parts = [element["html"] for element in all_elements]

    html_doc = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset=\"UTF-8\"/>
    <title>Extracted Content</title>
    <link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css\" rel=\"stylesheet\"/>
</head>
<body class=\"p-4\">
<div class=\"container\"> 
{chr(10).join(body_parts)}
</div>
</body>
</html>
"""

    sanitized = sanitize_html(html_doc)
    output_path.write_text(sanitized, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert Zigbee Cluster Library PDF to structured HTML.",
    )
    parser.add_argument("pdf", type=Path, help="Input PDF file")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output HTML file")
    parser.add_argument("--images", action="store_true", help="Extract and embed image references")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    convert_pdf_to_html(args.pdf, args.output, extract_page_images=args.images)


if __name__ == "__main__":
    main()
