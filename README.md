# PDF to HTML Converter for ZCL official documentation

Python converter for Zigbee Cluster Library PDFs to HTML.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python extract_pdf_to_html.py zcl-1-300.pdf -o out-1-300.html
python extract_pdf_to_html.py zcl-301-600.pdf -o out-301-600.html
python extract_pdf_to_html.py ZCL-07-5123-08-Zigbee-Cluster-Library.pdf -o out-full.html
```

With images:

```bash
python extract_pdf_to_html.py zcl-1-300.pdf -o out-1-300.html --images
```

This creates `out-1-300.images/` and inserts `<img ...>` tags at approximate positions from the PDF page layout.

## Anchors and copyable links

- Section headings get stable `id` anchors (e.g., `#section-2-6-2-7`).
- Lines starting with `Figure ...` and `Table ...` get stable anchors (e.g., `#figure-12-58`, `#table-6-14`).
- TOC entries for sections/chapters/figures/tables are converted to links to these anchors.
- Every element with an `id` displays a permalink marker:
  `<a class="headerlink" href="#..." title="Link to this heading/paragraph">¶</a>`

## GitHub Pages automation

Workflow: `.github/workflows/publish-pages.yml`

What it does:
1. Downloads the source PDF from Zigbee Alliance.
2. Converts it with `extract_pdf_to_html.py`.
3. Commits generated files to the `gh-pages` branch (clean overwrite each run).
4. GitHub Pages serves the site from `gh-pages`.

Trigger options:
- Manual: **Actions → Publish ZCL HTML to Pages → Run workflow**
- Scheduled: every Monday at 03:00 UTC

Before first run, set **Settings → Pages → Deploy from a branch**, then choose:
- Branch: `gh-pages`
- Folder: `/ (root)`

## Split HTML by sections

```bash
python split_html.py out-full.html split-output/
```

Arguments:
- `input_html`: source converted HTML file
- `output_dir`: directory for generated files (`index.html`, `section-<N>.html`) split by chapters

Links like `#section-X`, `#figure-X-Y`, and `#table-X-Y` are rewritten to
`section-<N>.html#...` when the target anchor is in another file.
