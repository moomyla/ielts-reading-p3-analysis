---
name: ielts-reading-pdf
description: Turn an IELTS Reading passage PDF (机经 / 阅读真题, text layer) into a plain, readable analysis PDF — paragraph-by-paragraph English original + Chinese translation + every related question with answer, evidence and reasoning. Use when the user gives one or many IELTS reading PDFs and asks for 逐段翻译 / 题目解析 / 解析PDF. Uses scripts so the model only writes a small JSON (no HTML/CSS, no re-typing English, no rendering checks).
---

# IELTS Reading → 解析 PDF (low-token workflow)

The model's only creative work is the **Chinese translation** and the **per-question analysis**.
Everything else (parsing the PDF, English text, layout, fonts, page numbers) is done by scripts.

## Workflow (per PDF — do not skip steps, do not add steps)

1. **Extract** (one command; prints a compact brief, writes JSON):
   ```bash
   python scripts/extract.py "<in.pdf>" -o work/<stem>.extracted.json
   ```
   Read the printed brief. It has the title/subtitle, numbered paragraphs `[P1]…` (sub-headings such as
   `(i The closed-nose yawn)` and `[FOOTNOTE: …]` are already handled), all questions with options, and the word bank.
   Do NOT open the PDF any other way, and do not re-print the JSON.
   **Never hand-edit or regenerate `extracted.json`.** If the brief looks wrong (empty title, a footnote or the subtitle
   shown as a paragraph, options merged into a stem, word bank missing letters), stop and report it in the final
   summary — the parser needs fixing, not the data. `[WARN]` lines from extract/build are the signal — see
   **Warnings** below for what each one means and whether it's actionable.

2. **Answers — always visually verify against the scanned key. This step is mandatory, not optional.**
   Text extraction (`pdftotext`) cannot read scanned images, and IELTS answer keys are very often a scanned
   table/screenshot on the last page(s) rather than real text. A model without vision (or one that skips this
   step) will guess at answers from the passage alone — usually plausible-sounding, sometimes simply wrong,
   with no error or warning anywhere to flag it. Concretely, this pipeline has produced silently-wrong output
   from skipping this step: scrambled diagram-label answers, swapped paragraph-matching answers, and (see
   **Known extraction bugs, now fixed** below) entire dropped questions.

   - If the brief ends with `[image-only pages …]`, render the key and read it yourself before writing anything:
     ```bash
     python scripts/render_answer_key.py "<in.pdf>" --extracted work/<stem>.extracted.json -o work/keys -r 120
     ```
     This renders from the **first flagged image-only page through the PDF's true last page** (via `pdfinfo`),
     not just the pages the `<5 characters` heuristic happened to flag — that heuristic under-reports: a page
     can carry a small amount of real text (a header, a page number) while its main content is still a scanned
     table, so the *last* page of a multi-page key is the one most often missed if you stop at the flagged pages.
     Read every rendered PNG (View/Read tool) and cross-check **every** question's answer, evidence sentence and
     reasoning against the official key — not just the ones you're unsure about. Reuse the key's own evidence
     wording where given; don't re-derive from scratch.
   - No image-only pages / no scanned key → solve the questions yourself from the passage text.
   - If your own judgement disagrees with the key, keep the key's answer, but tell the user in the
     final report (one line: which question, why).

3. **Write ONE file** `work/<stem>.analysis.json` (schema below). Write it in a single tool call.
   Never write HTML/CSS, never re-type English paragraphs, stems or options.
   **`ev` must be pure English** — it's a literal quote from the passage and is rendered in an English-only
   font style; any Chinese characters placed inside it render as garbled/blank glyphs in the final PDF, not
   as text. Put Chinese reasoning in `why`, never in `ev`.

4. **Build**:
   ```bash
   python scripts/build_pdf.py work/<stem>.extracted.json work/<stem>.analysis.json "out/<stem>_解析.pdf"
   ```
   Exit code 0 = done. If it prints `[WARN]` (missing question / paragraph count mismatch), fix the JSON
   and rebuild. Do a quick visual spot-check of the rendered PDF for any question whose `ev` field is not
   pure English (see step 3) — that's the one class of error `build_pdf.py`'s own structural checks cannot
   catch, since the JSON is structurally valid either way.

5. **Report**: one line per file (output path, question count, any `[WARN]` you couldn't fix, and any
   answer you overrode against your own judgement per step 2).

## analysis.json schema

```json
{
  "title_cn": "可选,中文标题",
  "subtitle_cn": "可选,副标题的中文(brief 第一行 '# 标题 | 副标题' 里有副标题时才写)",
  "cn": ["P1 中文译文", "P2 中文译文", "... 与 extracted 段落一一对应"],
  "fn": {"2": "*脚注的中文译文(只有 brief 里出现 [FOOTNOTE: …] 的段落才需要,键为段落号)"},
  "q": {
    "27": {"p": 1, "ans": "NO",
           "cn": "题干中文翻译",
           "ev": "English evidence, a short quote from the passage",
           "why": "解题思路(中文)。选择题用换行分别写每个选项为何对/错。"}
  }
}
```

- Paragraph numbering follows the brief (`[P1]`…): title, subtitle and footnotes are not paragraphs; sub-headed
  blocks like "i / ii / iii …" are each one paragraph. This matches how answer keys count paragraphs.
  For sub-headed paragraphs start `cn[i]` with the label/heading in Chinese on its own line
  (e.g. `"i 捏鼻哈欠\n受试者被要求……"`).
- `p` = which paragraph (1-based) holds the evidence — the question is printed under that paragraph.
  A question with evidence in several paragraphs goes under the first one; mention the others in `why`.
- `ans`: `YES/NO/NOT GIVEN` (or `TRUE/FALSE/NOT GIVEN`) as written; for MCQ / word-bank gap-fill give the
  **letter only** (`"B"`, `"G"`) — the script prints the option text itself. For free-text gap-fill,
  give the words.
- `\n` inside `why` makes a line break. See `templates/analysis.example.json` for a complete example
  (copy its style and level of detail).

## Style rules

- Translation: plain, faithful, 平实, no embellishment; keep names/terms in English on first mention;
  translate paragraph by paragraph so `cn[i]` matches `[P{i+1}]`.
- `ev`: shortest quote that proves the answer (usually one sentence; use `...` to skip). **Pure English —
  see step 3.**
- `why` for T/F/NG: state the judgement rule (contradicts / matches / info missing) and which words in
  the stem are paraphrased or newly added. For MCQ: why the answer is right, then one short line per wrong
  option. For gap-fill: which words in the passage map to the answer, and why nearby distractors fail.
- MCQ `why`: one line per option, right answer first ("B 正确:…\nA 错误:…"). Only call an option wrong for a
  reason that is really in the passage (don't say "not discussed" if the passage does mention the term —
  say what the passage says about it instead).
- Do not print instruction blocks ("Write the correct letter…", answer-format rules) — the scripts already omit them.
- No small talk, no summaries of the passage beyond the translation.

## Token discipline (why this is cheap)

- English text and layout live in scripts, not in the model's output.
- One read of the brief, one visual check of the rendered key (when there is one), one JSON write, one
  build command per PDF. No open-ended visual QA loops beyond that single key-verification pass.
- Batch: process each PDF independently (fresh context or sub-task per file); reuse nothing between files
  except this skill. Skip files whose `out/…_解析.pdf` already exists.
- If `extract.py` reports `No 'Questions X–Y' heading found`, the PDF is scanned — say so and skip it
  (don't OCR by default).

## Warnings — what each one means

`extract.py` and `build_pdf.py` print `[WARN]` lines to stdout and store the same text in the JSON's
`warnings` array. Not all warnings are equally actionable:

- **`no title detected`** — cosmetic; `build_pdf.py` falls back to the file name. Common and harmless.
- **`no paragraphs parsed`** — the passage's paragraph markers (A/B/C… labels) weren't detected as separate
  paragraphs. Has occurred on a handful of passages with letter-lettered paragraphs (A–G/A–H) without
  blocking correct output — the model can usually still work from the printed brief's raw text. Report it,
  don't silently proceed if the brief actually looks garbled.
- **`gap-fill without word bank (free-text answers?)`** — expected for gap-fill questions that take a word
  from the passage rather than a lettered word bank. Not an error by itself; just confirms which `ans`
  format to use (words, not a letter).
- **`Questions X–Y: parsed items […] (check 'raw' in JSON)`** — the parser found fewer (or different)
  question numbers than the header declared. This is the important one: check `raw` in the JSON for that
  group and figure out whether a question was genuinely dropped (fix by hand, or report it) versus the
  source PDF's own text being unusually laid out.
- **`gap header said Questions X-Y but blanks A-B were found …`** — the parser already self-corrected (see
  **Known extraction bugs, now fixed** below); it's telling you the source PDF's own instruction line
  ("boxes 27-31") disagreed with the actual blanks in the summary text (up to 33) and it used the wider,
  actually-correct range. No action needed unless the corrected range still looks wrong.
- **`passage declares Questions X-Y but nothing was parsed for: […]`** — the passage's intro sentence
  ("Questions 27–40, which are based on...") claims a wider range than any question group actually covers.
  Sometimes this is a real dropped question/group (investigate `raw` PDF text near that number); sometimes
  it's simply an inaccurate intro sentence in the source exam PDF itself (seen in practice: the passage's own
  questions only start at 28, but the boilerplate "spend 20 minutes on Questions 27-40" sentence says 27).
  Either way, check it — don't assume it's benign, and don't assume it's a bug either.

## Known extraction bugs, now fixed

Two root-cause bugs in `extract.py` were found and fixed after they silently dropped whole questions from
real passages (found via the mandatory visual-audit step above, then confirmed against ~40 passages):

1. A "Questions X-Y" header regex required two dash-separated numbers, so a standalone **"Question 40"**
   header (a single trailing question, no range) never matched at all — the entire question, including its
   options, silently vanished with no warning. Fixed: the second number is now optional.
2. Gap-fill parsing trusted the header's declared range ("boxes 27-31") over the blanks actually present in
   the summary text, so when a source PDF's instruction line disagreed with its own summary (blanks really
   went up to 33), the extra questions (32, 33) were silently dropped. Fixed: the parser now finds every
   blank actually in the text and widens the range to match, with a warning (see above).

A general safety net was added alongside these two specific fixes: `extract.py` now compares the union of
all parsed question numbers against the passage's own declared "Questions X–Y" range and warns about any
gap. This does not replace the visual-audit step — it only catches whole-group drops, not wrong answers
from a model without vision, or wrong extraction *within* a group.

## Troubleshooting

- Verified on ~40 passages spanning T/F/NG, Y/N/NG, MCQ, matching headings/information, summary/gap-fill
  (with and without word bank), sentence completion, and diagram labeling; sub-headed paragraphs and
  footnotes. Question types parsed as generic `items` or `raw` should still be answered the same way in
  `q`; if a group has `raw`, its stems weren't parsed — still key `q` by question number and put the stem
  in `cn`/`why`.
- `pdftotext`/`pdfinfo`/`pdftoppm not found` → install poppler-utils (`apt install poppler-utils` /
  `brew install poppler`).
- `pip install reportlab` if missing. CJK font is auto-detected (WenQuanYi / Microsoft YaHei / macOS Songti);
  pass `--font /path/to/font.ttf` to `build_pdf.py` to force one (must be TrueType-outline, not CFF/OTF).
  If no font is found it falls back to the built-in `STSong-Light` (not embedded; fine in most viewers).
