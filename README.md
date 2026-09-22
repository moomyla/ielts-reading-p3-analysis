# ielts-reading-pdf

A Claude Code / Claude skill that turns an IELTS Reading passage PDF (机经 / 阅读真题)
into a bilingual 解析 PDF: paragraph-by-paragraph English original + Chinese
translation, plus every question with its answer, evidence quote and reasoning.

The heavy lifting — PDF parsing, English text, page layout, fonts — lives in
scripts, so the model's only job is to write the Chinese translation and the
per-question analysis as a small JSON file. See [`SKILL.md`](./SKILL.md) for
the full workflow, the `analysis.json` schema, and the answer-key visual-audit
step that this skill requires (answer keys are frequently scanned images, not
text, so a vision-capable check against the rendered key is mandatory before
writing the analysis — see `SKILL.md` for why and how).

## Layout

```
SKILL.md                       full workflow + schema + style rules for the model
scripts/extract.py             PDF -> structured JSON (paragraphs, questions, word banks)
scripts/render_answer_key.py   renders scanned answer-key pages to PNG for visual verification
scripts/build_pdf.py           extracted.json + analysis.json -> final bilingual PDF (ReportLab)
templates/analysis.example.json  a complete worked example of the analysis.json format
```

`work/` (intermediate JSON per passage) and `out/` (finished PDFs) are created
at runtime and are not part of this repo — see `.gitignore`.

## Requirements

- Python 3, `pip install reportlab`
- `poppler-utils` (`pdftotext`, `pdfinfo`, `pdftoppm`) — `apt install poppler-utils` / `brew install poppler`
- A CJK-capable TrueType font for nicer PDF output (auto-detected; falls back
  to a built-in font if none is found — see `SKILL.md` → Troubleshooting).

## Usage

```bash
python scripts/extract.py "<passage>.pdf" -o work/<stem>.extracted.json
# read the printed brief; if there's a scanned answer key:
python scripts/render_answer_key.py "<passage>.pdf" --extracted work/<stem>.extracted.json -o work/keys
# write work/<stem>.analysis.json by hand (or have the model write it), then:
python scripts/build_pdf.py work/<stem>.extracted.json work/<stem>.analysis.json "out/<stem>_解析.pdf"
```

`SKILL.md` is written to be loaded as a Claude Code / Claude skill so an agent
follows this workflow automatically; the scripts above also run standalone.
