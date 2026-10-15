import io, sys
sys.path.insert(0, "service")
import docs
from pptx import Presentation
from pptx.util import Inches, Pt
from docx import Document

OUT = "spike/out/docs_mine/"
# ---- PPTX: title with a reference split across two runs, a table, notes
prs = Presentation()
s = prs.slides.add_slide(prs.slide_layouts[5])
tf = s.shapes.title.text_frame
p = tf.paragraphs[0]
r1 = p.add_run(); r1.text = "Summer starts at Gre"
r2 = p.add_run(); r2.text = "ggs"; r2.font.bold = True
r3 = p.add_run(); r3.text = " with friends."; r3.font.italic = True
box = s.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(1))
box.text_frame.text = "Play Coronation Street on the big screen."
tbl = s.shapes.add_table(2, 2, Inches(1), Inches(3.5), Inches(6), Inches(1)).table
tbl.cell(0, 0).text = "Snack"; tbl.cell(0, 1).text = "Nando's peri-peri"
s.notes_slide.notes_text_frame.text = "Mention Tim Hortons in the toast."
s2 = prs.slides.add_slide(prs.slide_layouts[1]); s2.shapes.title.text = "Slide two"; s2.placeholders[1].text = "Wawa runs at midnight."
b = io.BytesIO(); prs.save(b); pptx_bytes = b.getvalue(); open(OUT + "in.pptx", "wb").write(pptx_bytes)
parsed = docs.parse("deck.pptx", pptx_bytes)
for blk in parsed["blocks"]: print("PPTX", blk)
want = {x["id"]: x["text"] for x in parsed["blocks"]}
changes = []
for bid, t in want.items():
    if "Greggs" in t: changes.append({"id": bid, "text": t.replace("Greggs", "Chick-fil-A")})
    if "Nando's" in t: changes.append({"id": bid, "text": t.replace("Nando's", "Zaxby's")})
    if "Tim Hortons" in t: changes.append({"id": bid, "text": "Raise a glass in the toast."})
name, out, media = docs.export("deck.pptx", pptx_bytes, changes)
open(OUT + name, "wb").write(out)
re = docs.parse(name, out)
print("PPTX after:", [x["text"] for x in re["blocks"]])
prs2 = Presentation(io.BytesIO(out))
runs = [(r.text, r.font.bold, r.font.italic) for r in prs2.slides[0].shapes.title.text_frame.paragraphs[0].runs]
print("PPTX title runs:", runs)
assert any("Chick-fil-A" in x["text"] for x in re["blocks"]) and any("Zaxby" in x["text"] for x in re["blocks"])
assert runs[-1] == (" with friends.", None, True), "italic tail run survives"
assert "Raise a glass" in prs2.slides[0].notes_slide.notes_text_frame.text

# ---- DOCX: bold run in the middle, table, unchanged paragraph keeps its runs
d = Document()
para = d.add_paragraph(); para.add_run("We met at "); rr = para.add_run("Wetherspoons"); rr.bold = True; para.add_run(" in Peckham.")
d.add_paragraph("He still quotes Love Actually every Christmas.")
t = d.add_table(rows=1, cols=2); t.cell(0, 0).text = "Team"; t.cell(0, 1).text = "Arsenal forever"
b = io.BytesIO(); d.save(b); docx_bytes = b.getvalue()
parsed = docs.parse("toast.docx", docx_bytes)
print("DOCX", parsed["blocks"])
changes = [{"id": x["id"], "text": x["text"].replace("Wetherspoons", "a pub")} for x in parsed["blocks"] if "Wetherspoons" in x["text"]]
name, out, media = docs.export("toast.docx", docx_bytes, changes)
d2 = Document(io.BytesIO(out))
print("DOCX runs:", [(r.text, r.bold) for r in d2.paragraphs[0].runs])
assert d2.paragraphs[0].text == "We met at a pub in Peckham."
assert [(r.text, r.bold) for r in d2.paragraphs[0].runs] == [("We met at ", None), ("a pub", True), (" in Peckham.", None)], "replacement keeps the bold"

# ---- TXT keeps spacing
txt = "First line with Greggs.\n\n\nSecond paragraph.\n"
parsed = docs.parse("set.txt", txt.encode())
print("TXT", parsed["blocks"])
name, out, _ = docs.export("set.txt", txt.encode(), [{"id": "b0", "text": "First line with Chuy's."}])
print("TXT out:", repr(out.decode()))
assert out.decode() == "First line with Chuy's.\n\n\nSecond paragraph.\n"
print("ALL OK")
