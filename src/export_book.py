"""成稿导出：把 data/<书>/manuscript/*.txt 合成可投稿的 docx / md / txt。

只读取成稿，不改动任何数据；docx 依赖 python-docx，未安装时只影响 docx 格式。
"""
from __future__ import annotations

import io
import json
import os
import re

from paths import book_dir, book_chapters, book_decomposed

FMT_CTYPE = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "md": "text/markdown; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
}


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _no_of(name):
    m = re.search(r"(\d+)", os.path.basename(name))
    return int(m.group(1)) if m else 0


def _titles(meta):
    """章号 → 章名（chapters.json 里的标题）。"""
    out = {}
    for i, ch in enumerate(meta.get("chapters") or []):
        if not isinstance(ch, dict):
            continue
        no = ch.get("no")
        if no is None:
            m = re.search(r"\d+", str(ch.get("chapter_id") or ""))
            no = int(m.group(0)) if m else i + 1
        try:
            out[int(no)] = str(ch.get("title") or "").strip()
        except (TypeError, ValueError):
            continue
    return out


def collect(book):
    """按章号收集成稿：返回 (chapters_meta, [{no,title,text}])。"""
    meta = _read(book_chapters(book), {})
    titles = _titles(meta)
    mdir = os.path.join(book_dir(book), "manuscript")
    out = []
    if not os.path.isdir(mdir):
        return meta, out
    for fn in sorted(os.listdir(mdir), key=lambda x: (_no_of(x) or 99999, x)):
        if not fn.lower().endswith(".txt"):
            continue
        fp = os.path.join(mdir, fn)
        if not os.path.isfile(fp):
            continue
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                raw = f.read().replace("\r\n", "\n").strip("\n")
        except OSError:
            continue
        if not raw.strip():
            continue
        no = _no_of(fn)
        first = raw.split("\n", 1)[0].strip().lstrip("#").strip()
        title = titles.get(no) or ""
        body = raw
        # 成稿首行若已是「第N章 …」，用它当标题并从正文里去掉，避免重复
        if re.match(r"^第\s*[\d一二三四五六七八九十百零]+\s*章", first):
            title, body = first, (raw.split("\n", 1)[1] if "\n" in raw else "")
        out.append({"no": no, "title": title or f"第{no}章", "text": body.strip()})
    return meta, out


def _book_meta(meta, book):
    """书名 / 简介：chapters.json 的 story_bible 优先，其次 decomposed.json。"""
    title, intro = book, ""
    raw = meta.get("story_bible")
    if isinstance(raw, dict):
        intro = str(raw.get("synopsis") or "").strip()
    elif isinstance(raw, str) and raw.strip():
        try:
            from story_bible import parse
            fields, _cards, _factions = parse(raw)
            intro = str(fields.get("synopsis") or "").strip()
        except Exception:      # 设定库格式异常不影响导出
            pass
    if not intro:
        dec = _read(book_decomposed(book), {})
        sb = dec.get("story_bible")
        if isinstance(sb, dict):
            intro = str(sb.get("synopsis") or "").strip()
        elif isinstance(sb, str) and sb.strip():
            try:
                from story_bible import parse
                intro = str(parse(sb)[0].get("synopsis") or "").strip()
            except Exception:
                intro = ""
        intro = intro or str(dec.get("book_summary") or "").strip()
    return title, intro


def _to_txt(title, intro, chs):
    lines = [title, ""]
    if intro:
        lines += [intro, ""]
    for c in chs:
        head = c["title"] if c["title"].startswith("第") else f"第{c['no']}章 {c['title']}"
        lines += [head, "", c["text"], ""]
    return "\n".join(lines).strip() + "\n"


def _to_md(title, intro, chs):
    lines = [f"# {title}", ""]
    if intro:
        lines += ["> " + intro.replace("\n", "\n> "), ""]
    for c in chs:
        head = c["title"] if c["title"].startswith("第") else f"第{c['no']}章 {c['title']}"
        lines += [f"## {head}", ""]
        for p in c["text"].split("\n"):
            if p.strip():
                lines += [p.strip(), ""]
    return "\n".join(lines).strip() + "\n"


def _to_docx_minimal(title, intro, chs):
    """不依赖 python-docx 的最小 docx 生成器（手机端用）。

    docx 本质是一个 zip：写入 document.xml 即可被 Word / WPS 正常打开。
    只保留导出真正用到的排版：标题居中加粗、正文首行缩进、1.5 倍行距、章标题居中。
    """
    import zipfile
    from xml.sax.saxutils import escape

    def clean(text):
        """去掉 XML 1.0 不允许的控制字符（爬取来的正文里偶尔混有 \x0b 之类）。"""
        s = str(text or "")
        out = []
        for ch in s:
            o = ord(ch)
            if ch in "\t\n\r" or 0x20 <= o <= 0xD7FF or 0xE000 <= o <= 0xFFFD \
                    or 0x10000 <= o <= 0x10FFFF:
                out.append(ch)
        return escape("".join(out))

    def par(text, size=None, bold=False, center=False, indent=False, before=0, after=0):
        ppr = ['<w:spacing w:before="%d" w:after="%d" w:line="360" w:lineRule="auto"/>'
               % (before, after)]
        if center:
            ppr.append('<w:jc w:val="center"/>')
        if indent:
            ppr.append('<w:ind w:firstLine="420"/>')
        rpr = ['<w:rFonts w:ascii="宋体" w:eastAsia="宋体" w:hAnsi="宋体"/>']
        if bold:
            rpr.append("<w:b/><w:bCs/>")
        if size:
            rpr.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (size, size))
        return ('<w:p><w:pPr>%s</w:pPr><w:r><w:rPr>%s</w:rPr>'
                '<w:t xml:space="preserve">%s</w:t></w:r></w:p>'
                % ("".join(ppr), "".join(rpr), clean(text)))

    parts = [par(title, size=44, bold=True, center=True, after=240)]
    if intro:
        for line in str(intro).split("\n"):
            if line.strip():
                parts.append(par(line.strip(), indent=True, after=0))
    for c in chs:
        head = c["title"] if c["title"].startswith("第") else f"第{c['no']}章 {c['title']}"
        parts.append(par(head, size=32, bold=True, center=True, before=360, after=240))
        for line in c["text"].split("\n"):
            s = line.strip()
            if s:
                parts.append(par(s, indent=True, after=0))

    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body>" + "".join(parts) +
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
                "</w:body></w:document>")
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                     "</Types>")
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
    return buf.getvalue()


def _to_docx(title, intro, chs):
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.shared import Cm, Pt
    except ImportError:
        # 手机端没有 python-docx：用内置最小生成器，导出功能保持一致
        return _to_docx_minimal(title, intro, chs)

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(12)
    style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(title)
    run.bold = True
    run.font.size = Pt(22)

    if intro:
        p = doc.add_paragraph(intro)
        p.paragraph_format.first_line_indent = Cm(0.74)
        p.paragraph_format.line_spacing = 1.5

    for c in chs:
        h = doc.add_paragraph()
        h.alignment = WD_ALIGN_PARAGRAPH.CENTER
        h.paragraph_format.space_before = Pt(18)
        h.paragraph_format.space_after = Pt(12)
        head = c["title"] if c["title"].startswith("第") else f"第{c['no']}章 {c['title']}"
        hr = h.add_run(head)
        hr.bold = True
        hr.font.size = Pt(16)
        for line in c["text"].split("\n"):
            s = line.strip()
            if not s:
                continue
            p = doc.add_paragraph(s)
            pf = p.paragraph_format
            pf.first_line_indent = Cm(0.74)
            pf.line_spacing = 1.5
            pf.space_after = Pt(0)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build(book, fmt="docx"):
    """生成导出文件：返回 (bytes, 文件名, content-type)。"""
    fmt = (fmt or "docx").lower()
    if fmt not in FMT_CTYPE:
        raise ValueError("导出格式只支持 docx / md / txt")
    meta, chs = collect(book)
    if not chs:
        raise ValueError("这本书还没有成稿，先到「正文」页生成或保存章节")
    title, intro = _book_meta(meta, book)
    if fmt == "docx":
        data = _to_docx(title, intro, chs)
    elif fmt == "md":
        data = _to_md(title, intro, chs).encode("utf-8")
    else:
        data = _to_txt(title, intro, chs).encode("utf-8")
    safe = re.sub(r'[\\/:*?"<>|\r\n]', "_", title).strip(" .") or "成稿"
    return data, f"{safe}.{fmt}", FMT_CTYPE[fmt]
