#!/usr/bin/env python3
"""
build_pdf.py — merge extract.py output with the agent's analysis.json into a plain, readable PDF.

Usage:
    python build_pdf.py extracted.json analysis.json out.pdf [--font /path/to/cjk.ttf]

English passage paragraphs, question stems and options come from extracted.json (never re-typed
by the agent). The agent supplies only: Chinese translations, per-question answer/evidence/reasoning.

analysis.json:
{
  "cn": ["译文 P1", "译文 P2", ...],                 # one per paragraph, same order
  "q": {
    "27": {"p": 1, "ans": "NO", "cn": "题干中文", "ev": "English evidence (short)", "why": "解题思路(中文)"},
    "31": {"p": 3, "ans": "B",  "cn": "...", "ev": "...", "why": "B 正确:…\nA 错误:…"},
    "35": {"p": 7, "ans": "G",  "cn": "...", "ev": "...", "why": "..."}
  }
}
Optional: "title_cn". Use "\n" inside "why" for line breaks.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

NAVY = colors.HexColor("#1f3a5f")
GREEN = colors.HexColor("#1b5e20")
BROWN = colors.HexColor("#7a3b00")

FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0),
    ("C:/Windows/Fonts/msyh.ttc", 0),
    ("C:/Windows/Fonts/msyh.ttf", 0),
    ("C:/Windows/Fonts/simsun.ttc", 0),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Songti.ttc", 0),
    ("/Library/Fonts/Arial Unicode.ttf", 0),
]


def setup_cjk_font(user_font=None):
    cands = [(user_font, 0)] if user_font else []
    cands += FONT_CANDIDATES
    try:  # anything fontconfig knows for zh; CFF-based fonts fail and are skipped
        out = subprocess.run(["fc-list", ":lang=zh", "file"], capture_output=True, text=True).stdout
        cands += [(l.split(":")[0].strip(), 0) for l in out.splitlines() if l.strip()]
    except Exception:
        pass
    for path, idx in cands:
        if path and Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont("CJK", path, subfontIndex=idx))
                return "CJK"
            except Exception:
                continue
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))  # not embedded; viewers substitute
    return "STSong-Light"


def esc(s):
    return escape(str(s)).replace("\n", "<br/>")


def build(ext, ana, out_path, font_path=None):
    F = setup_cjk_font(font_path)
    EN = "Times-Roman"

    st = {
        "title": ParagraphStyle("title", fontName=F, fontSize=18, leading=24, textColor=NAVY),
        "sub": ParagraphStyle("sub", fontName=F, fontSize=10, leading=15, textColor=colors.HexColor("#555555")),
        "h": ParagraphStyle("h", fontName=F, fontSize=12, leading=16, textColor=colors.white, backColor=NAVY,
                            borderPadding=(3, 6, 3, 6), spaceBefore=14, spaceAfter=8, keepWithNext=1),
        "lab": ParagraphStyle("lab", fontName=F, fontSize=9, leading=12, textColor=NAVY, spaceBefore=6, spaceAfter=2, keepWithNext=1),
        "en": ParagraphStyle("en", fontName=EN, fontSize=10, leading=13.5, backColor=colors.HexColor("#f3f5f8"),
                             borderPadding=(4, 6, 4, 6), alignment=TA_LEFT),
        "cn": ParagraphStyle("cn", fontName=F, fontSize=10, leading=16, wordWrap="CJK"),
        "qtitle": ParagraphStyle("qtitle", fontName=F, fontSize=10, leading=14, textColor=BROWN, spaceBefore=10, spaceAfter=3, keepWithNext=1),
        "qh": ParagraphStyle("qh", fontName=F, fontSize=10.5, leading=15, spaceBefore=4, wordWrap="CJK"),
        "stem": ParagraphStyle("stem", fontName=EN, fontSize=10, leading=13.5),
        "opt": ParagraphStyle("opt", fontName=EN, fontSize=10, leading=13.5, leftIndent=12),
        "stemcn": ParagraphStyle("stemcn", fontName=F, fontSize=9.5, leading=14, textColor=colors.HexColor("#444444"), wordWrap="CJK"),
        "body": ParagraphStyle("body", fontName=F, fontSize=9.5, leading=15, wordWrap="CJK", spaceBefore=1),
        "bankcell": ParagraphStyle("bankcell", fontName=EN, fontSize=9.5, leading=12.5),
        "fn": ParagraphStyle("fn", fontName=EN, fontSize=8.5, leading=11.5, textColor=colors.HexColor("#555555"), spaceBefore=2),
        "fncn": ParagraphStyle("fncn", fontName=F, fontSize=8.5, leading=13, textColor=colors.HexColor("#555555"), wordWrap="CJK", spaceBefore=2),
        "bank": ParagraphStyle("bank", fontName=EN, fontSize=9.5, leading=13, backColor=colors.HexColor("#fafafa"),
                               borderPadding=(3, 5, 3, 5), spaceBefore=2, spaceAfter=6),
    }

    # n -> (group, item)
    qmap = {it["n"]: (g, it) for g in ext["groups"] for it in g["items"]}
    aq = {int(k): v for k, v in ana.get("q", {}).items()}

    warns = []
    paras = ext["paragraphs"]
    cn = ana.get("cn", [])
    if len(cn) != len(paras):
        warns.append(f"cn has {len(cn)} entries but passage has {len(paras)} paragraphs")
    missing = [n for n in qmap if n not in aq]
    if missing:
        warns.append(f"no analysis for questions: {missing}")
    extra = [n for n in aq if n not in qmap]
    if extra:
        warns.append(f"analysis has unknown question numbers: {extra}")
    for n, v in aq.items():
        if "p" not in v or not isinstance(v["p"], int) or not (1 <= v["p"] <= len(paras)):
            warns.append(f"Q{n}: missing/invalid 'p' (paragraph number 1..{len(paras)})")

    import re as _re
    if not ext.get("title"):
        warns.append("extracted.json has no title (file name used)")
    for i_, p_ in enumerate(paras, 1):
        if p_["text"].lstrip().startswith(("*", "†")):
            warns.append(f"paragraph {i_} looks like a footnote — fix extraction instead of hand-editing")
        if p_.get("footnote") and str(i_) not in ana.get("fn", {}):
            warns.append(f"paragraph {i_} has a footnote but analysis.json has no fn['{i_}'] (Chinese footnote)")
    for g_ in ext["groups"]:
        for it_ in g_["items"]:
            v_ = aq.get(it_["n"])
            if g_["type"] == "items" and _re.search(r"\bA\b.*\bB\b.*\bC\b.*\bD\b", it_["stem"]):
                warns.append(f"Q{it_['n']}: options seem merged into the stem (mcq options not parsed)")
            if g_["type"] == "gap" and v_ is not None:
                a_ = str(v_.get("ans", "")).strip()
                if len(a_) <= 2 and a_[:1].isalpha() and a_[:1] not in g_.get("wordbank", {}):
                    warns.append(f"Q{it_['n']}: answer '{a_}' not found in the parsed word bank {list(g_.get('wordbank', {}))}")

    def ans_line(n, g, it, v):
        a = str(v.get("ans", "?")).strip()
        letter = a.split()[0].rstrip(".:") if a else ""
        if g["type"] == "mcq" and letter in it.get("options", {}):
            return f"{letter} — {it['options'][letter]}"
        if g["type"] == "gap" and letter in g.get("wordbank", {}) and len(a) <= 2:
            return f"{letter} {g['wordbank'][letter]}"
        return a

    def q_block(n):
        g, it = qmap[n]
        v = aq[n]
        parts = [Paragraph(f"<b>Q{n}</b>　<font color='#1b5e20'>答案:{esc(ans_line(n, g, it, v))}</font>", st["qh"])]
        stem = it["stem"] if g["type"] == "gap" else f"{n} {it['stem']}"
        parts.append(Paragraph(esc(stem), st["stem"]))
        if v.get("cn"):
            parts.append(Paragraph(esc(v["cn"]), st["stemcn"]))
        for k, t in it.get("options", {}).items():
            parts.append(Paragraph(esc(f"{k}  {t}"), st["opt"]))
        lab = {"gap": "填空依据", "tfng": "判断依据"}.get(g["type"], "原文依据")
        why_lab = "选择思路" if g["type"] == "mcq" else "解题思路"
        if v.get("ev"):
            parts.append(Paragraph(f"<font color='#1f3a5f'><b>{lab}:</b></font> "
                                   f"<font name='{EN}'>{esc(v['ev'])}</font>", st["body"]))
        if v.get("why"):
            parts.append(Paragraph(f"<font color='#1f3a5f'><b>{why_lab}:</b></font> {esc(v['why'])}", st["body"]))
        parts.append(Spacer(1, 5))
        return KeepTogether(parts)

    story = []
    story.append(Paragraph(esc(ext["title"] or Path(ext["source"]).stem), st["title"]))
    if ext.get("subtitle"):
        story.append(Paragraph(esc(ext["subtitle"]), st["sub"]))
    if ana.get("subtitle_cn"):
        story.append(Paragraph(esc(ana["subtitle_cn"]), st["sub"]))
    if ana.get("title_cn"):
        story.append(Paragraph(esc(ana["title_cn"]), st["sub"]))
    story.append(Spacer(1, 4))

    bank_shown = set()
    for i, p in enumerate(paras, 1):
        head = f"第 {i} 段" + (f"({p['label']})" if p.get("label") else "")
        story.append(Paragraph(head, st["h"]))
        story.append(Paragraph("原文", st["lab"]))
        sub = " ".join(x for x in (p.get("label"), p.get("heading")) if x)
        story.append(Paragraph((f"<b>{esc(sub)}</b><br/>" if sub else "") + esc(p["text"]), st["en"]))
        if p.get("footnote"):
            story.append(Paragraph(esc(p["footnote"]), st["fn"]))
        story.append(Paragraph("译文", st["lab"]))
        story.append(Paragraph(esc(cn[i - 1] if i - 1 < len(cn) else "(缺失)"), st["cn"]))
        if p.get("footnote") and ana.get("fn", {}).get(str(i)):
            story.append(Paragraph(esc(ana["fn"][str(i)]), st["fncn"]))

        ns = sorted(n for n, v in aq.items() if v.get("p") == i and n in qmap)
        if ns:
            story.append(Paragraph("本段涉及题目:" + "、".join(f"Q{n}" for n in ns), st["qtitle"]))
            for n in ns:
                g, _ = qmap[n]
                gid = tuple(g["range"])
                if g["type"] == "gap" and g.get("wordbank") and gid not in bank_shown:
                    bank_shown.add(gid)
                    story.append(Paragraph(f"选项(Questions {gid[0]}–{gid[1]} 共用)", st["lab"]))
                    items_ = list(g["wordbank"].items())
                    rows_ = []
                    for s0 in range(0, len(items_), 3):
                        ch = items_[s0:s0 + 3]
                        rows_.append([Paragraph(esc(f"{k}  {v}"), st["bankcell"]) for k, v in ch] + [""] * (3 - len(ch)))
                    bt = Table(rows_, colWidths=[(A4[0] - 36 * mm) / 3] * 3)
                    bt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
                                            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8b8b8")),
                                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
                    story.append(bt)
                    story.append(Spacer(1, 4))
                story.append(q_block(n))

    def short_ans(n):
        g, _ = qmap[n]
        a = str(aq[n].get("ans", "?")).strip()
        return a.split()[0].rstrip(".:") if g["type"] in ("mcq", "gap") and a else a

    # answer summary
    ordered = sorted(n for n in aq if n in qmap)
    if ordered:
        story.append(Paragraph("答案汇总", st["h"]))
        cells_per_row = 7
        rows = []
        for s in range(0, len(ordered), cells_per_row):
            chunk = ordered[s:s + cells_per_row]
            rows.append([str(n) for n in chunk] + [""] * (cells_per_row - len(chunk)))
            rows.append([short_ans(n) for n in chunk] + [""] * (cells_per_row - len(chunk)))
        tbl = Table(rows, colWidths=[24 * mm] * cells_per_row)
        style = [("FONT", (0, 0), (-1, -1), F, 9.5), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                 ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c5cdd9"))]
        for r in range(0, len(rows), 2):
            style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#e9eef5")))
        tbl.setStyle(TableStyle(style))
        story.append(tbl)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillGray(0.45)
        canvas.drawCentredString(A4[0] / 2, 10 * mm, str(doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=18 * mm,
                            title=(ext["title"] or ext["source"]) + " 解析")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return warns, len(qmap), len(aq)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("extracted")
    ap.add_argument("analysis")
    ap.add_argument("out")
    ap.add_argument("--font")
    a = ap.parse_args()
    ext = json.loads(Path(a.extracted).read_text(encoding="utf-8"))
    ana = json.loads(Path(a.analysis).read_text(encoding="utf-8"))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    warns, nq, na = build(ext, ana, a.out, a.font)
    print(f"OK {a.out}  (questions {na}/{nq})")
    for w in warns:
        print("[WARN]", w)
    if warns:
        sys.exit(2)


if __name__ == "__main__":
    main()
