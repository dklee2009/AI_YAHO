"""체크리스트를 표 형식 워드 문서(.docx)로 만든다.

열 구성: 선택 | 번호 | 검토 분야 | 체크리스트 | 확인 필요사항 | 담당자 | 소속
머리행은 남색 배경 + 흰 글씨, 본문은 한 줄씩 옅은 회청색 줄무늬.
"""
import io

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

FONT = "맑은 고딕"
HEADER_FILL = "1F3864"
STRIPE_FILL = "EEF3F8"
BORDER_COLOR = "BFC8D6"
NUMBER_COLOR = RGBColor(0x1F, 0x38, 0x64)

# (머리글, 폭 cm, 가운데 정렬 여부) — 가로 A4 본문 폭(약 26.7cm)에 맞춤
COLUMNS = [
    ("선택", 1.5, True),
    ("번호", 1.8, True),
    ("검토 분야", 3.0, True),
    ("체크리스트", 9.2, False),
    ("확인 필요사항", 5.0, False),
    ("담당자", 2.4, True),
    ("소속", 3.8, False),
]


def _shade(cell, fill: str):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def _set_borders(table):
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:color"), BORDER_COLOR)
        borders.append(el)
    tbl_pr.append(borders)


def _row_flag(row, tag: str):
    tr_pr = row._tr.get_or_add_trPr()
    el = OxmlElement(f"w:{tag}")
    el.set(qn("w:val"), "true")
    tr_pr.append(el)


def _write(cell, text: str, *, center: bool, bold=False, color=None, size=9.5, font=FONT,
           keep_with_next=False):
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    para = cell.paragraphs[0]
    para.paragraph_format.keep_with_next = keep_with_next
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.LEFT
    para.paragraph_format.space_before = Pt(3)
    para.paragraph_format.space_after = Pt(3)
    run = para.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = font
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), font)
    if color is not None:
        run.font.color.rgb = color


def _setup_document() -> Document:
    doc = Document()
    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Cm(29.7), Cm(21.0)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Cm(1.5))

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT)
    return doc


def _heading(doc, text: str, size: float, space_after: float):
    para = doc.add_paragraph()
    para.paragraph_format.space_after = Pt(space_after)
    para.paragraph_format.keep_with_next = True
    run = para.add_run(text)
    run.bold = True
    run.font.size = Pt(size)
    run.font.color.rgb = NUMBER_COLOR
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT)


def _add_table(doc, items: list[dict]):
    table = doc.add_table(rows=1, cols=len(COLUMNS))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    _set_borders(table)

    header = table.rows[0]
    _row_flag(header, "tblHeader")  # 페이지가 넘어가면 머리행 반복
    for cell, (label, width, _) in zip(header.cells, COLUMNS):
        cell.width = Cm(width)
        _shade(cell, HEADER_FILL)
        # 머리행이 페이지 끝에 홀로 남지 않도록 첫 데이터 행과 붙여 둔다.
        _write(cell, label, center=True, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF), keep_with_next=True)

    for idx, item in enumerate(items):
        owner = item.get("owner") or {}
        values = [
            "☑" if item.get("done") else "☐",
            item.get("no", ""),
            item.get("area") or "-",
            item.get("text", ""),
            item.get("check") or "-",
            f"{owner['name']} {owner['title']}" if owner else "미지정",
            " / ".join(p for p in (owner.get("dept"), owner.get("team")) if p) or "-",
        ]
        row = table.add_row()
        _row_flag(row, "cantSplit")  # 한 행이 두 페이지로 쪼개지지 않게
        for col, (cell, value, (_, width, center)) in enumerate(zip(row.cells, values, COLUMNS)):
            cell.width = Cm(width)
            if idx % 2 == 1:
                _shade(cell, STRIPE_FILL)
            if col == 0:
                _write(cell, value, center=True, size=13, font="Segoe UI Symbol")
            elif col == 1:
                _write(cell, value, center=True, bold=True, color=NUMBER_COLOR)
            else:
                _write(cell, value, center=center)


def build_checklist_docx(categories: list[dict], title: str = "IT 프로젝트 검토 체크리스트") -> bytes:
    doc = _setup_document()
    _heading(doc, title, size=16, space_after=10)

    for i, category in enumerate(c for c in categories if c["items"]):
        if i:
            doc.add_paragraph()  # 표 사이 간격 (마지막 뒤에는 넣지 않아 빈 페이지 방지)
        _heading(doc, category["title"], size=11.5, space_after=4)
        _add_table(doc, category["items"])

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
