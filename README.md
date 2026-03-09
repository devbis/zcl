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

## GitHub Pages automation

Workflow: `.github/workflows/publish-pages.yml`

What it does:
1. Downloads the source PDF from Zigbee Alliance.
2. Converts it with `extract_pdf_to_html.py`.
3. Publishes `site/index.html` to GitHub Pages.

Trigger options:
- Manual: **Actions → Publish ZCL HTML to Pages → Run workflow**
- Scheduled: every Monday at 03:00 UTC

Before first run, set **Settings → Pages → Source = GitHub Actions**.
