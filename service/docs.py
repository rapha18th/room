"""Documents in, corrected documents out.

parse()  turns a PDF, PPTX, DOCX, TXT or MD file into text blocks with stable ids
         (slide.shape.paragraph, paragraph, table cell, page.paragraph). The browser joins the
         blocks with blank lines, so Room reads a deck or a document like any script.
export() takes the original file and the blocks the writer changed, rewrites only those
         paragraphs, and returns the corrected file. Inside a paragraph only the changed words
         move, so bold, colour and links on the rest of the line survive. A PDF comes back as
         DOCX, since a PDF holds positioned glyphs rather than editable paragraphs.

Libraries: python-pptx (MIT), python-docx (MIT), pypdf (BSD-3-Clause).
"""

import io
import re
from pathlib import PurePath

MAX_BYTES = 12 * 1024 * 1024
MAX_CHARS = 40000
KINDS = {".pdf": "pdf", ".pptx": "pptx", ".docx": "docx", ".txt": "txt", ".md": "md", ".markdown": "md"}
MEDIA = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
}


class DocError(ValueError):
    pass


def kind_of(name: str) -> str:
    k = KINDS.get(PurePath(name or "").suffix.lower())
    if not k:
        raise DocError("Room reads PDF, PowerPoint (.pptx), Word (.docx), text and Markdown files.")
    return k


def _clean(text: str) -> str:
    # Blocks are joined with blank lines, so a block may hold single line breaks and never a blank line.
    text = (text or "").replace("\r", "").replace("\x0b", "\n").replace(" ", " ")
    return re.sub(r"\n\s*\n+", "\n", text).strip()


# ---------- walking the files: one order for parse and export ----------

def _pptx_paragraphs(prs):
    """Yield (id, where, paragraph) for every text paragraph in slides, tables, groups and notes."""
    def shapes(container, prefix):
        for shape in container:
            sid = f"{prefix}{shape.shape_id}"
            if shape.shape_type == 6 and hasattr(shape, "shapes"):  # group
                yield from shapes(shape.shapes, sid + "g")
                continue
            if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                for pi, p in enumerate(shape.text_frame.paragraphs):
                    yield f"{sid}.{pi}", p
            if getattr(shape, "has_table", False) and shape.has_table:
                for ri, row in enumerate(shape.table.rows):
                    for ci, cell in enumerate(row.cells):
                        for pi, p in enumerate(cell.text_frame.paragraphs):
                            yield f"{sid}.t{ri}.{ci}.{pi}", p

    for si, slide in enumerate(prs.slides):
        for pid, p in shapes(slide.shapes, f"s{si}."):
            yield pid, f"Slide {si + 1}", p
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            for pi, p in enumerate(slide.notes_slide.notes_text_frame.paragraphs):
                yield f"s{si}.notes.{pi}", f"Slide {si + 1} notes", p


def _docx_paragraphs(doc):
    for i, p in enumerate(doc.paragraphs):
        yield f"p{i}", "Body", p
    for ti, table in enumerate(doc.tables):
        for ri, row in enumerate(table.rows):
            for ci, cell in enumerate(row.cells):
                for pi, p in enumerate(cell.paragraphs):
                    yield f"t{ti}.{ri}.{ci}.{pi}", f"Table {ti + 1}", p


def _pdf_blocks(data: bytes):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    for n, page in enumerate(reader.pages):
        # Layout mode keeps vertical gaps, so paragraphs arrive separated by blank lines.
        try:
            raw = page.extract_text(extraction_mode="layout") or ""
        except Exception:
            raw = page.extract_text() or ""
        raw = re.sub(r"[ \t]{2,}", " ", raw)
        # Paragraphs are separated by blank lines; lines inside one are joined, mending hyphenated breaks.
        for k, para in enumerate(re.split(r"\n\s*\n", raw)):
            lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
            if not lines:
                continue
            text = ""
            for ln in lines:
                if text.endswith("-") and ln[:1].islower():
                    text = text[:-1] + ln
                else:
                    text = f"{text} {ln}" if text else ln
            yield f"pg{n}.{k}", f"Page {n + 1}", text


def _para_text(p) -> str:
    return "".join(r.text for r in p.runs) if p.runs else p.text


# ---------- parse ----------

def parse(name: str, data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        raise DocError("Room reads files up to 12 MB.")
    kind = kind_of(name)
    blocks, total, truncated = [], 0, False

    def add(bid, where, text):
        nonlocal total, truncated
        text = _clean(text)
        if not text or truncated:
            return
        if total + len(text) > MAX_CHARS:
            truncated = True
            return
        blocks.append({"id": bid, "where": where, "text": text})
        total += len(text) + 2

    try:
        if kind == "pptx":
            from pptx import Presentation
            for bid, where, p in _pptx_paragraphs(Presentation(io.BytesIO(data))):
                add(bid, where, _para_text(p))
        elif kind == "docx":
            from docx import Document
            for bid, where, p in _docx_paragraphs(Document(io.BytesIO(data))):
                add(bid, where, p.text)
        elif kind == "pdf":
            for bid, where, text in _pdf_blocks(data):
                add(bid, where, text)
        else:
            text = data.decode("utf-8-sig", errors="replace")
            for i, para in enumerate(re.split(r"\n\s*\n", text)):
                add(f"b{i}", "Text", para)
    except DocError:
        raise
    except Exception as e:
        raise DocError(f"Room could not open that file ({type(e).__name__}).") from e
    if not blocks:
        raise DocError("That file holds no text Room can read. Scanned PDFs need OCR first.")
    return {"name": name, "kind": kind, "blocks": blocks, "truncated": truncated}


# ---------- export ----------

def _set_runs(p, new: str):
    """Rewrite a paragraph so only the changed middle moves; runs outside it keep their formatting."""
    runs = list(p.runs)
    old = "".join(r.text for r in runs)
    if not runs or old != (p.text or ""):
        # Text lives outside plain runs (line breaks, fields, hyperlinks): set the paragraph whole.
        p.text = new
        return
    a = 0
    while a < len(old) and a < len(new) and old[a] == new[a]:
        a += 1
    b = 0
    while b < len(old) - a and b < len(new) - a and old[-1 - b] == new[-1 - b]:
        b += 1
    cut_from, cut_to, middle = a, len(old) - b, new[a:len(new) - b]
    spans, pos = [], 0
    for r in runs:
        spans.append((pos, pos + len(r.text)))
        pos += len(r.text)

    # The new words take the formatting of the run that held most of the old ones (a bold brand stays bold).
    def overlap(i):
        s, e = spans[i]
        return max(0, min(e, cut_to) - max(s, cut_from))

    if cut_to > cut_from:
        target = max(range(len(runs)), key=lambda i: (overlap(i), -i))
    else:
        target = next((i for i, (s, e) in enumerate(spans) if s < cut_from <= e), len(runs) - 1)
    for i, r in enumerate(runs):
        s, e = spans[i]
        t = r.text
        lo, hi = min(max(cut_from - s, 0), len(t)), min(max(cut_to - s, 0), len(t))
        r.text = t[:lo] + (middle if i == target else "") + t[hi:]
    for r in runs:
        if r.text == "" and r._r.getparent() is not None:
            r._r.getparent().remove(r._r)


def export(name: str, data: bytes, changes: list[dict]) -> tuple[str, bytes, str]:
    kind = kind_of(name)
    want = {c["id"]: c["text"] for c in changes if c.get("id")}
    stem = PurePath(name).stem
    if kind == "pptx":
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
        for bid, _, p in _pptx_paragraphs(prs):
            if bid in want:
                _set_runs(p, want[bid])
        out = io.BytesIO()
        prs.save(out)
        return f"{stem} (Room).pptx", out.getvalue(), MEDIA["pptx"]
    if kind == "docx":
        from docx import Document
        doc = Document(io.BytesIO(data))
        for bid, _, p in _docx_paragraphs(doc):
            if bid in want:
                _set_runs(p, want[bid])
        out = io.BytesIO()
        doc.save(out)
        return f"{stem} (Room).docx", out.getvalue(), MEDIA["docx"]
    if kind == "pdf":
        from docx import Document
        doc = Document()
        page = None
        for bid, where, text in _pdf_blocks(data):
            if where != page:
                doc.add_heading(where, level=3)
                page = where
            final = want.get(bid, _clean(text))
            if final:
                doc.add_paragraph(final)
        out = io.BytesIO()
        doc.save(out)
        return f"{stem} (Room).docx", out.getvalue(), MEDIA["docx"]
    text = data.decode("utf-8-sig", errors="replace")
    paras = re.split(r"(\n\s*\n)", text)  # keeps the separators, so the file's spacing survives
    for k in range(0, len(paras), 2):
        bid = f"b{k // 2}"
        if bid in want:
            paras[k] = want[bid]
    return f"{stem} (Room){PurePath(name).suffix}", "".join(paras).encode("utf-8"), MEDIA[kind]
