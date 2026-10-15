"""Documents in, corrected documents out.

parse()  turns a PDF, PPTX, DOCX, TXT or MD file into text blocks with stable ids
         (slide.shape.paragraph, paragraph, table cell, page.paragraph). The browser joins the
         blocks with blank lines, so Room reads a deck or a document like any script.
export() takes the original file and the blocks the writer changed, rewrites only those
         paragraphs, and returns the corrected file. Inside a paragraph only the changed words
         move, so bold, colour and links on the rest of the line survive.
         Word files come back with tracked changes by "Room" and a comment carrying each reason:
         Accept All gives the clean text, Reject All gives the original. A PDF comes back as a
         tracked Word document, since a PDF holds positioned glyphs rather than editable paragraphs.
         A deck gets its edits in place plus a change log in each touched slide's speaker notes.

Hostile files stop at the door: zip bombs, macro payloads, password-locked and oversized PDFs.

Libraries: python-pptx (MIT), python-docx (MIT), pypdf (BSD-3-Clause).
"""

import copy
import difflib
import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import PurePath

MAX_BYTES = 12 * 1024 * 1024
MAX_CHARS = 40000
MAX_PAGES = 60
ZIP_LIMITS = {"entries": 3000, "total": 120 * 1024 * 1024, "entry": 30 * 1024 * 1024, "ratio": 120}
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


def _check_zip(data: bytes):
    """Office files are zip packages. Refuse bombs and macro payloads before any parser unpacks them."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise DocError("That file is damaged or is a different kind of file under an Office name.") from e
    infos = z.infolist()
    if len(infos) > ZIP_LIMITS["entries"]:
        raise DocError("That file holds too many parts to open safely.")
    total = 0
    for i in infos:
        total += i.file_size
        if i.file_size > ZIP_LIMITS["entry"] or total > ZIP_LIMITS["total"]:
            raise DocError("That file unpacks too large to open safely.")
        if i.file_size > 1024 * 1024 and i.compress_size and i.file_size / i.compress_size > ZIP_LIMITS["ratio"]:
            raise DocError("That file is compressed suspiciously hard, so Room leaves it closed.")
        if i.filename.lower().endswith("vbaproject.bin"):
            raise DocError("That file carries macros. Save it as a plain .pptx or .docx and try again.")


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
    if reader.is_encrypted:
        try:
            ok = reader.decrypt("")
        except Exception as e:
            raise DocError("That PDF is password-locked. Unlock it and try again.") from e
        if not ok:
            raise DocError("That PDF is password-locked. Unlock it and try again.")
    for n, page in enumerate(reader.pages):
        if n >= MAX_PAGES:
            break
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


def _docx_text(p) -> str:
    """A Word paragraph as the reader sees it with tracked changes accepted: insertions in, deletions out."""
    return "".join(t for _, t in _Tracker.atoms(p._p))


# ---------- parse ----------

def parse(name: str, data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        raise DocError("Room reads files up to 12 MB.")
    kind = kind_of(name)
    if kind in ("pptx", "docx"):
        _check_zip(data)
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
                add(bid, where, _docx_text(p))
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


# ---------- decks and plain paragraphs: only the changed words move ----------

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


# ---------- Word: tracked changes with a reason on each ----------

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_TOKEN = re.compile(r"\s+|\w+|[^\w\s]")


def _word_diff(a: str, b: str) -> list[tuple[int, int, str]]:
    """Minimal word-level edits turning a into b, as (start, end, replacement) offsets in a."""
    ta, tb = _TOKEN.findall(a), _TOKEN.findall(b)
    off = [0]
    for t in ta:
        off.append(off[-1] + len(t))
    return [(off[i1], off[i2], "".join(tb[j1:j2]))
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes()
            if tag != "equal"]


def _set_t(node, text: str):
    node.text = text
    if text and (text[0].isspace() or text[-1].isspace()):
        node.set(XML_SPACE, "preserve")
    elif XML_SPACE in node.attrib:
        del node.attrib[XML_SPACE]


class _Tracker:
    """Writes revisions into Word paragraphs the way Word does: w:del around removed runs, w:ins around
    new ones, and a comment spanning the change. Ported from the tested research prototype
    (spike/docs_proto.py), which Word 16, PowerPoint 16 and LibreOffice all opened cleanly."""

    def __init__(self, doc, author: str = "Room"):
        self.doc, self.author = doc, author
        self.date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ids = [int(el.get(W + "id")) for el in doc.element.body.iter(W + "ins", W + "del")
               if (el.get(W + "id") or "").isdigit()]
        self.next_id = max(ids + [9000]) + 1

    def _id(self) -> str:
        self.next_id += 1
        return str(self.next_id)

    @staticmethod
    def atoms(p) -> list[tuple[object, str]]:
        out = []

        def walk(el):
            for ch in el:
                tag = ch.tag
                if not isinstance(tag, str) or tag in (W + "pPr", W + "rPr", W + "del", W + "moveFrom"):
                    continue
                if tag == W + "t":
                    out.append((ch, ch.text or ""))
                elif tag in (W + "tab", W + "ptab"):
                    out.append((ch, "\t"))
                elif tag in (W + "br", W + "cr"):
                    out.append((ch, "\n"))
                else:
                    walk(ch)

        walk(p)
        return out

    @staticmethod
    def _split_run(r, idx):
        rpr = r.find(W + "rPr")
        r2 = r.makeelement(r.tag, dict(r.attrib))
        if rpr is not None:
            r2.append(copy.deepcopy(rpr))
        for ch in list(r)[idx:]:
            r2.append(ch)
        r.addnext(r2)

    def _split(self, p, off):
        """Make `off` fall on a run boundary."""
        pos = 0
        for node, text in self.atoms(p):
            s, e = pos, pos + len(text)
            pos = e
            if not text:
                continue
            if s < off < e and node.tag == W + "t":
                k = off - s
                t2 = node.makeelement(W + "t", {})
                _set_t(node, text[:k])
                _set_t(t2, text[k:])
                node.addnext(t2)
                r = node.getparent()
                self._split_run(r, list(r).index(t2))
                return
            if off == e:
                r = node.getparent()
                if r.tag == W + "r":
                    kids = list(r)
                    i = kids.index(node)
                    if i + 1 < len(kids):
                        self._split_run(r, i + 1)
                return

    def _runs_at(self, p, s, e):
        runs, pos = [], 0
        for node, text in self.atoms(p):
            a0, a1 = pos, pos + len(text)
            pos = a1
            if text and s <= a0 and a1 <= e:
                r = node.getparent()
                if r.tag == W + "r" and r not in runs:
                    runs.append(r)
        return runs

    def _run_before(self, p, off):
        pos, last = 0, None
        for node, text in self.atoms(p):
            a1 = pos + len(text)
            if text and a1 <= off:
                last = node.getparent()
            pos = a1
        return last

    def edit(self, p, s, e, new):
        """Track replacing [s, e) of the paragraph text with new. Returns (first, last) nodes or None."""
        mk = p.makeelement
        rev = {W + "author": self.author, W + "date": self.date}
        first = last = rpr = None
        if s < e:
            self._split(p, s)
            self._split(p, e)
            runs = self._runs_at(p, s, e)
            if not runs:
                return None
            rpr = runs[0].find(W + "rPr")
            groups: list[list] = []
            for r in runs:
                if groups and groups[-1][-1].getnext() is r:
                    groups[-1].append(r)
                else:
                    groups.append([r])
            for g in groups:
                d = mk(W + "del", {W + "id": self._id(), **rev})
                g[0].addprevious(d)
                for r in g:
                    d.append(r)
                    for t in r.iter(W + "t"):
                        t.tag = W + "delText"
                first = first if first is not None else d
                last = d
        else:
            self._split(p, s)
            last = self._run_before(p, s)
            if last is not None:
                rpr = last.find(W + "rPr")
        if new:
            ins = mk(W + "ins", {W + "id": self._id(), **rev})
            r = mk(W + "r", {})
            if rpr is not None:
                r.append(copy.deepcopy(rpr))
            t = mk(W + "t", {})
            _set_t(t, new)
            r.append(t)
            ins.append(r)
            if last is not None:
                last.addnext(ins)
            else:
                ppr = p.find(W + "pPr")
                (ppr.addnext(ins) if ppr is not None else p.insert(0, ins))
            first = first if first is not None else ins
            last = ins
        return (first, last) if first is not None else None

    def comment(self, first, last, why: str):
        c = self.doc.comments.add_comment(text=why, author=self.author, initials="R")
        cid = str(c.comment_id)
        mk = first.makeelement
        first.addprevious(mk(W + "commentRangeStart", {W + "id": cid}))
        end = mk(W + "commentRangeEnd", {W + "id": cid})
        ref_run = mk(W + "r", {})
        ref_run.append(mk(W + "commentReference", {W + "id": cid}))
        last.addnext(end)
        end.addnext(ref_run)


def _track_paragraph(tracker: _Tracker, p, old: str, new: str, why: str = ""):
    """Track the edits that turn the paragraph text `old` into `new`, word by word, last offsets first."""
    raw = "".join(t for _, t in tracker.atoms(p))
    ops = _word_diff(old, new) if len(raw) == len(old) else [(0, len(raw), new)]
    span_first = span_last = None
    for s, e, rep in sorted(ops, reverse=True):
        got = tracker.edit(p, s, e, rep)
        if got:
            span_first = got[0]
            if span_last is None:
                span_last = got[1]
    if why and span_first is not None and span_last is not None:
        try:
            tracker.comment(span_first, span_last, why)
        except Exception:
            pass  # a comment is a courtesy; the revision stands on its own


# ---------- export ----------

def export(name: str, data: bytes, changes: list[dict], audience: str = "") -> tuple[str, bytes, str]:
    kind = kind_of(name)
    if kind in ("pptx", "docx"):
        _check_zip(data)
    want = {c["id"]: str(c.get("text", "")) for c in changes if c.get("id")}
    why = {c["id"]: str(c.get("why") or "")[:500] for c in changes if c.get("id")}
    tag = f"Room · {audience}" if audience else "Room"
    stem = PurePath(name).stem
    if kind == "pptx":
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
        log: dict[int, list[str]] = {}
        for bid, _, p in _pptx_paragraphs(prs):
            if bid in want:
                old = _clean(_para_text(p))
                _set_runs(p, want[bid])
                if ".notes." not in bid:
                    si = int(bid.split(".")[0][1:])
                    note = f"“{old}” → “{want[bid]}”" if want[bid] else f"Cut: “{old}”"
                    log.setdefault(si, []).append(note + (f" ({why[bid]})" if why.get(bid) else ""))
        for si, lines in log.items():
            notes = prs.slides[si].notes_slide.notes_text_frame
            notes.add_paragraph().text = f"{tag} changed this slide:"
            for ln in lines:
                notes.add_paragraph().text = ln
        out = io.BytesIO()
        prs.save(out)
        return f"{stem} (Room).pptx", out.getvalue(), MEDIA["pptx"]
    if kind == "docx":
        from docx import Document
        doc = Document(io.BytesIO(data))
        tracker = _Tracker(doc, tag)
        for bid, _, p in _docx_paragraphs(doc):
            if bid in want:
                _track_paragraph(tracker, p._p, _clean(_docx_text(p)), want[bid], why.get(bid, ""))
        out = io.BytesIO()
        doc.save(out)
        return f"{stem} (Room).docx", out.getvalue(), MEDIA["docx"]
    if kind == "pdf":
        from docx import Document
        doc = Document()
        tracker = _Tracker(doc, tag)
        page = None
        for bid, where, text in _pdf_blocks(data):
            if where != page:
                doc.add_heading(where, level=3)
                page = where
            original = _clean(text)
            para = doc.add_paragraph(original)
            if bid in want and want[bid] != original:
                _track_paragraph(tracker, para._p, original, want[bid], why.get(bid, ""))
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
