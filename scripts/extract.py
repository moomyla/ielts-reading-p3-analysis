#!/usr/bin/env python3
"""
extract.py — parse a text-layer IELTS Reading PDF into structured JSON.

Usage:
    python extract.py input.pdf [-o work/name.extracted.json]

Writes the JSON and prints a compact "brief" (numbered paragraphs + questions)
to stdout. The brief is all the agent needs to read. English text never has to
be re-typed by the agent: build_pdf.py pulls it from the JSON.

Requires: poppler-utils (pdftotext).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DASH = r"[–—‒\-]"
# A "Questions X-Y" header covers a range; a single trailing question ("Question 40")
# has no dash and no second number — both forms occur in real papers, so the second
# group is optional and falls back to the first number.
Q_HEAD = re.compile(rf"^\s*Questions?\s+(\d+)(?:\s*{DASH}\s*(\d+))?\s*$", re.I)
OVERVIEW = re.compile(rf"\bQuestions?\s+(\d+)\s*{DASH}\s*(\d+)\b", re.I)
ITEM = re.compile(r"^\s*(\d{1,2})\s+(\S.*)$")
OPT = re.compile(r"^\s*([A-K])\s{2,}(\S.*)$")
# Instruction lines that precede a standalone "Question N" item (no leading number
# on the stem itself, since there's nothing to disambiguate it from) — skip these
# rather than swallowing them into the stem text.
INSTR = re.compile(r"^(Choose|Write|Circle|Select|Complete)\b.*\b(letter|letters|box|boxes|answer|answers|sheet)\b", re.I)
BLANK = re.compile(r"(?P<n>\d{1,2})\s*(?:…+|\.{4,}|_{3,})(?P<dot>\.)?")
HEADER = re.compile(r"READING PASSAGE|You should spend|Reading\s+Passage\s+\d+\s+below", re.I)
LABEL = re.compile(r"^(?:[A-J]|[ivx]{1,4}|[IVX]{1,4})$")
SUBHEAD = re.compile(r"^(i{1,3}|iv|vi{0,3}|ix|x)\s+(\S.{0,60})$")   # "i The closed-nose yawn"
BANK_LINE = re.compile(r"^\s*[A-K]\s+\S")


def indent(line):
    return len(line) - len(line.lstrip())


def pdf_text(path):
    try:
        return subprocess.run(["pdftotext", "-layout", str(path), "-"],
                              capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        sys.exit("pdftotext not found. Install poppler-utils (apt install poppler-utils / brew install poppler).")


def join_lines(lines):
    out = ""
    for ln in (l.strip() for l in lines):
        if not ln:
            continue
        if out.endswith("-") and ln[:1].islower():
            out += ln          # 'attention-' + 'seeking'
        else:
            out += (" " if out else "") + ln
    return out


def split_blocks(page_lines):
    blocks, cur = [], []
    for ln in page_lines:
        if ln.strip():
            cur.append(ln)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


def parse_passage(pages, qpage, qline):
    """pages: list of list-of-lines. Passage = everything before the first 'Questions X–Y'."""
    body_pages = [p[:] for p in pages[:qpage + 1]]
    body_pages[qpage] = pages[qpage][:qline]

    blocks = []  # (lines, is_first_on_page)
    for pi, plines in enumerate(body_pages):
        for bi, b in enumerate(split_blocks(plines)):
            blocks.append((b, pi > 0 and bi == 0))

    # drop header blocks
    while blocks and HEADER.search(join_lines(blocks[0][0])):
        blocks.pop(0)

    # title block: centred (indented) lines, or a short block without a final full stop
    title = subtitle = ""
    if blocks:
        b = blocks[0][0]
        short = all(len(l.strip()) < 120 for l in b)
        centred = len(b) <= 4 and all(indent(l) >= 2 for l in b) and short
        plain = len(b) <= 3 and short and not b[-1].strip().endswith(".")
        if centred or plain:
            title = b[0].strip()
            subtitle = join_lines(b[1:])
            blocks.pop(0)

    maxlen = max((len(l.strip()) for b, _ in blocks for l in b if indent(l) < 2), default=0)

    paras, footnotes = [], []
    pending_label = None
    for lines, first_on_page in blocks:
        first = lines[0].strip()
        if first and first[0] in "*†":                       # footnote -> attach to its paragraph later
            footnotes.append(join_lines(lines))
            continue
        if len(lines) == 1 and LABEL.match(first):
            pending_label = first
            continue
        label, heading = pending_label, None
        m = SUBHEAD.match(first)
        if m and len(lines) >= 2 and not first.endswith("."):  # "i The closed-nose yawn" + body
            label, heading = m.group(1), m.group(2).strip()
            lines = lines[1:]
        elif first_on_page and paras and label is None:
            last = paras[-1]["lines"][-1].strip()
            if len(last) >= 0.88 * maxlen:                   # full line => paragraph continues across page break
                paras[-1]["lines"].extend(lines)
                continue
        paras.append({"label": label, "heading": heading, "lines": list(lines)})
        pending_label = None

    out = [{"label": p["label"], "heading": p["heading"], "text": join_lines(p["lines"])} for p in paras]

    for fn in footnotes:
        m = re.match(r"^[*†]+\s*([^:：]{1,60})[:：]", fn)
        term = m.group(1).strip().lower() if m else ""
        target = None
        if term:
            target = next((i for i, p in enumerate(out) if (term + "*") in p["text"].lower()), None)
            if target is None:
                target = next((i for i, p in enumerate(out) if term in p["text"].lower()), None)
        if target is None and out:
            target = len(out) - 1
        if target is not None:
            out[target]["footnote"] = (out[target].get("footnote", "") + " " + fn).strip()

    return title, subtitle, out


def parse_bank_text(text):
    """'A form and function B long yawns C 3 seconds ...' -> {'A': 'form and function', ...} (sequential letters)."""
    m = re.match(r"\s*A\s+", text)
    if not m:
        return {}
    bank, cur, start = {}, "A", m.end()
    for nxt in "BCDEFGHIJK":
        m2 = re.compile(rf"\s{nxt}\s+").search(text, start)
        if not m2:
            break
        bank[cur] = text[start:m2.start()].strip()
        cur, start = nxt, m2.end()
    bank[cur] = text[start:].strip()
    return bank


def find_bank(lines):
    """Find the word bank (A–K list) anywhere in the group: top or bottom, single/multi-space, blank rows between."""
    runs, cur = [], []
    for i, l in enumerate(lines):
        if BANK_LINE.match(l):
            cur.append(i)
        elif l.strip() and cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    for run in runs:
        bank = parse_bank_text(" ".join(lines[i].strip() for i in run))
        if len(bank) >= 3:
            rs = set(run)
            return bank, [l for i, l in enumerate(lines) if i not in rs]
    return {}, lines


def parse_gap(lo, hi, lines):
    wordbank, lines = find_bank(lines)
    idx = max((i for i, l in enumerate(lines[:14]) if re.match(r"^\s*(Write|In boxes)\b", l)), default=-1)
    body = [l for l in lines[idx + 1:] if l.strip()]

    summary_title = ""
    if body and not BLANK.search(body[0]) and not body[0].strip().endswith("."):
        summary_title = body.pop(0).strip()
    text = join_lines(body)

    # Sanity check: trust the blanks actually present in the summary text over the
    # declared header range. Source PDFs are sometimes internally inconsistent (an
    # instruction line saying "boxes 27-31" while the summary itself has blanks up
    # to 33) — silently looping only over the declared range drops real questions.
    found = sorted({int(m.group("n")) for m in BLANK.finditer(text)})
    range_warning = None
    if found and (found[0], found[-1]) != (lo, hi):
        real_lo, real_hi = found[0], found[-1]
        range_warning = (f"gap header said Questions {lo}-{hi} but blanks {real_lo}-{real_hi} "
                         f"were found in the summary text; using {real_lo}-{real_hi}")
        lo, hi = min(lo, real_lo), max(hi, real_hi)

    def rep(m):
        n = m.group("n")
        # a trailing '.' is a sentence end only if followed by a capital letter or end of text
        tail = text[m.end():m.end() + 3]
        ends = m.group("dot") and (not tail.strip() or re.match(r"\s+[A-Z]", tail))
        return f"⟦{n}⟧" + ("." if ends else "")
    marked = BLANK.sub(rep, text)
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z⟦])", marked)

    items = []
    for n in range(lo, hi + 1):
        s = next((s for s in sents if f"⟦{n}⟧" in s), "")
        s = re.sub(r"⟦(\d+)⟧", r"\1 ……", s)
        items.append({"n": n, "stem": s})
    g = {"type": "gap", "summary_title": summary_title, "wordbank": wordbank, "items": items, "range": [lo, hi]}
    if range_warning:
        g["_range_warning"] = range_warning
    return g


def parse_items(lo, hi, lines, raw_text):
    items, cur, expected = [], None, lo
    for ln in lines:
        m, o = ITEM.match(ln), OPT.match(ln)
        if m and int(m.group(1)) == expected and expected <= hi:
            cur = {"n": expected, "stem": m.group(2).strip()}
            items.append(cur)
            expected += 1
        elif o and cur is not None:
            cur.setdefault("options", {})[o.group(1)] = o.group(2).strip()
            cur["_last_opt"] = o.group(1)
        elif ln.strip() and cur is not None:
            if "options" in cur:
                k = cur["_last_opt"]
                cur["options"][k] += " " + ln.strip()
            else:
                cur["stem"] += " " + ln.strip()

    # A standalone "Question N" header (lo == hi) has no leading number on its own
    # stem line — nothing to number it against. Fall back to: skip instruction
    # lines, accumulate everything else as the stem until the first option letter.
    if not items and lo == hi:
        stem_lines, cur2 = [], None
        for ln in lines:
            if not ln.strip():
                continue
            o = OPT.match(ln)
            if o:
                if cur2 is None:
                    cur2 = {"n": lo, "stem": " ".join(stem_lines).strip()}
                    items.append(cur2)
                cur2.setdefault("options", {})[o.group(1)] = o.group(2).strip()
                cur2["_last_opt"] = o.group(1)
            elif cur2 is not None:
                cur2["options"][cur2["_last_opt"]] += " " + ln.strip()
            elif INSTR.match(ln.strip()):
                continue
            else:
                stem_lines.append(ln.strip())
        if cur2 is None and stem_lines:
            items.append({"n": lo, "stem": " ".join(stem_lines).strip()})

    for it in items:
        it.pop("_last_opt", None)
    if any("options" in it for it in items):
        typ = "mcq"
    elif re.search(r"NOT GIVEN", raw_text):
        typ = "tfng"
    else:
        typ = "items"
    return {"type": typ, "items": items}


def parse_questions(qlines, warnings):
    heads = [(i, int(m.group(1)), int(m.group(2) or m.group(1)))
             for i, l in enumerate(qlines) if (m := Q_HEAD.match(l))]
    groups = []
    for k, (i, lo, hi) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(qlines)
        lines = qlines[i + 1:end]
        raw = "\n".join(lines)
        task = next((l.strip() for l in lines if l.strip()), "")
        if BLANK.search(raw):
            g = parse_gap(lo, hi, lines)
        else:
            g = parse_items(lo, hi, lines, raw)
        range_warning = g.pop("_range_warning", None)
        if range_warning:
            warnings.append(range_warning)
        # parse_gap already owns its (possibly self-corrected) range; other group
        # types keep the header-declared range so a shortfall (fewer items parsed
        # than declared) stays visible as a "parsed items != declared range"
        # warning in main(), instead of being silently masked here.
        g.setdefault("range", [lo, hi])
        g["task"] = task
        if not g["items"]:
            g["raw"] = raw.strip()
        groups.append(g)
    return groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()

    pdf = Path(a.pdf)
    out = Path(a.out) if a.out else pdf.with_suffix(".extracted.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    raw = pdf_text(pdf)
    page_texts = raw.split("\f")
    if page_texts and not page_texts[-1].strip():
        page_texts.pop()
    pages = [t.split("\n") for t in page_texts]
    warnings = []

    # locate first "Questions X–Y"
    qpage = qline = None
    for pi, pl in enumerate(pages):
        for li, l in enumerate(pl):
            if Q_HEAD.match(l):
                qpage, qline = pi, li
                break
        if qpage is not None:
            break
    if qpage is None:
        sys.exit("No 'Questions X–Y' heading found — is this a text-layer PDF? (scanned PDFs need OCR)")

    title, subtitle, paragraphs = parse_passage(pages, qpage, qline)

    qlines = pages[qpage][qline:]
    for pl in pages[qpage + 1:]:
        qlines += pl
    for i, l in enumerate(qlines):                      # cut boilerplate footer
        if re.match(r"^\s*Disclaimer\b", l):
            qlines = qlines[:i]
            break
    groups = parse_questions(qlines, warnings)

    image_only = [i + 1 for i, t in enumerate(page_texts) if len(t.strip()) < 5]
    if not paragraphs:
        warnings.append("no paragraphs parsed")
    if not title:
        warnings.append("no title detected (build_pdf will fall back to the file name)")
    for g in groups:
        got = [it["n"] for it in g["items"]]
        want = list(range(g["range"][0], g["range"][1] + 1))
        if got != want:
            warnings.append(f"Questions {g['range'][0]}–{g['range'][1]}: parsed items {got or 'none'} (check 'raw' in JSON)")
        if g["type"] == "gap" and not g.get("wordbank"):
            warnings.append(f"Questions {g['range'][0]}–{g['range'][1]}: gap-fill without word bank (free-text answers?)")

    # Overall coverage check: the passage intro usually states the true total range
    # ("You should spend about 20 minutes on Questions 27-40, ..."). Compare it against
    # the union of every parsed group's question numbers. This is the safety net that
    # catches a whole question (or group) silently going unparsed — e.g. a lone final
    # question like "Question 40" with no dash, which a stricter header regex would
    # miss entirely, leaving no trace anywhere else in the JSON.
    overview = OVERVIEW.search(" ".join(pages[0])) if pages else None
    if overview:
        decl_lo, decl_hi = int(overview.group(1)), int(overview.group(2))
        got_all = {n for g in groups for n in range(g["range"][0], g["range"][1] + 1)}
        missing = sorted(set(range(decl_lo, decl_hi + 1)) - got_all)
        if missing:
            warnings.append(f"passage declares Questions {decl_lo}-{decl_hi} but nothing was parsed for: {missing} "
                            f"(a whole question/group may have been dropped — check the raw PDF text near these numbers)")

    data = {"source": pdf.name, "title": title, "subtitle": subtitle, "paragraphs": paragraphs,
            "groups": groups, "image_only_pages": image_only, "warnings": warnings}
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- compact brief for the agent ----
    print(f"# {title} | {subtitle}")
    for i, p in enumerate(paragraphs, 1):
        head = " ".join(x for x in (p.get("label"), p.get("heading")) if x)
        head = f"({head}) " if head else ""
        fn = f"  [FOOTNOTE: {p['footnote']}]" if p.get("footnote") else ""
        print(f"[P{i}] {head}{p['text']}{fn}")
    for g in groups:
        print(f"\n## Q{g['range'][0]}–{g['range'][1]} [{g['type']}] {g['task']}")
        if g["type"] == "gap":
            if g.get("summary_title"):
                print(f"(summary: {g['summary_title']})")
            if g.get("wordbank"):
                print("WORDBANK: " + " | ".join(f"{k} {v}" for k, v in g["wordbank"].items()))
        for it in g["items"]:
            print(f"{it['n']}. {it['stem']}")
            for k, v in it.get("options", {}).items():
                print(f"   {k}. {v}")
        if g.get("raw"):
            print(g["raw"])
    print()
    print(f"[paragraphs={len(paragraphs)} groups={len(groups)} json={out}]")
    if image_only:
        print(f"[image-only pages (answer key?): {image_only}  ->  render through the PDF's LAST page, not just "
              f"these — a page can carry a scanned table under a heading with just enough real text to dodge this "
              f"heuristic. Get the true page count first: pdftoppm -r 100 -f {image_only[0]} -l <last page from "
              f"`pdfinfo '{pdf}'`> -png '{pdf}' key   (or use scripts/render_answer_key.py, which does this for you.)]")
    for w in warnings:
        print(f"[WARN] {w}")


if __name__ == "__main__":
    main()
