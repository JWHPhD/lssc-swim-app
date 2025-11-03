from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from typing import List
import re
from PyPDF2 import PdfReader
from io import BytesIO
import tempfile
import os
from datetime import datetime

# reportlab for PDF generation
from reportlab.lib.pagesizes import landscape, letter
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors


app = FastAPI()

# allow local frontend / browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can narrow this later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ensure static folder exists and mount it
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def read_root():
    """
    Serve the frontend page.
    """
    index_path = os.path.join(STATIC_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


@app.post("/list-swimmers")
async def list_swimmers(file: UploadFile = File(...)):
    """
    Upload a heat sheet (PDF or text) and get back a list of swimmer names found.
    Used to populate the dropdown on the frontend.
    """
    content_bytes = await file.read()
    text = extract_text_from_upload(file.content_type, content_bytes)
    events = parse_heat_sheet(text)
    swimmers = get_unique_swimmers(events)
    return {"count": len(swimmers), "swimmers": swimmers}


@app.post("/extract")
async def extract_swimmer_events(
    swimmer_name: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Returns just the selected swimmer's events as JSON (for preview).
    """
    content_bytes = await file.read()
    text = extract_text_from_upload(file.content_type, content_bytes)
    events = parse_heat_sheet(text)
    # sort events by event number
    events = sorted(events, key=lambda e: e["event_number"])
    matched = filter_for_swimmer(events, swimmer_name)

    return {
        "swimmer": swimmer_name,
        "count": len(matched),
        "events": matched,
    }


@app.post("/generate-pdf")
async def generate_swimmer_pdf(
    swimmer_name: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Generates a polished, easy-to-read PDF for just this swimmer.
    No long raw lines, no text overruns, alternating rows, notes at bottom.
    """
    # read file
    content_bytes = await file.read()
    text = extract_text_from_upload(file.content_type, content_bytes)

    # parse + filter
    events = parse_heat_sheet(text)
    # sort by event number so it looks clean
    events = sorted(events, key=lambda e: e["event_number"])
    matched = filter_for_swimmer(events, swimmer_name)

    # temp file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp_path = tmp.name
    tmp.close()

    # document setup
    doc = SimpleDocTemplate(
        tmp_path,
        pagesize=landscape(letter),
        leftMargin=30,
        rightMargin=30,
        topMargin=30,
        bottomMargin=30,
    )
    elements = []

    # styles
    title_style = ParagraphStyle("title", fontSize=16, spaceAfter=6, leading=18)
    sub_style = ParagraphStyle("sub", fontSize=9, spaceAfter=4, textColor=colors.grey)
    notes_label_style = ParagraphStyle("label", fontSize=9, spaceAfter=2)

    # header
    elements.append(Paragraph(f"Swim Schedule – {swimmer_name}", title_style))
    elements.append(Paragraph("Lake Shore Swim Club (LSSC)", sub_style))
    elements.append(
        Paragraph(
            f"Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}",
            sub_style,
        )
    )
    elements.append(Spacer(1, 12))

    # table header
    data = [["Event", "Heat", "Lane", "Seed", "Results"]]

    if matched:
        for ev in matched:
            event_text = f"#{ev['event_number']} – {ev['event_name']}"
            data.append(
                [
                    Paragraph(
                        event_text,
                        ParagraphStyle("ev", fontSize=9, leading=11),
                    ),
                    ev["heat"],
                    ev["lane"] if ev["lane"] is not None else "",
                    ev["seed_time"] or "",
                    "Time: __________   Place: ______",
                ]
            )
    else:
        data.append(["No events found for this swimmer", "", "", "", ""])

    # table with nice widths
    table = Table(
        data,
        colWidths=[240, 50, 50, 60, 200],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#007bff")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ALIGN", (1, 1), (3, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    elements.append(table)
    elements.append(Spacer(1, 14))

    # notes area
    elements.append(Paragraph("Notes:", notes_label_style))
    elements.append(Spacer(1, 4))
    for _ in range(3):
        elements.append(
            Paragraph("_______________________________________________________________", sub_style)
        )

    # build PDF
    doc.build(elements)

    return FileResponse(
        tmp_path,
        media_type="application/pdf",
        filename=f"{swimmer_name.replace(' ', '_')}_schedule.pdf",
    )


# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------


def extract_text_from_upload(content_type: str, content_bytes: bytes) -> str:
    """
    Turn uploaded bytes into text. Supports PDF and plain text.
    """
    if content_type == "application/pdf":
        pdf_stream = BytesIO(content_bytes)
        reader = PdfReader(pdf_stream)
        text_chunks = []
        for page in reader.pages:
            text_chunks.append(page.extract_text() or "")
        return "\n".join(text_chunks)
    else:
        return content_bytes.decode("utf-8", errors="ignore")


def parse_heat_sheet(text: str):
    """
    Very simple parser for HY-TEK-like heat sheets.
    Detects:
      - event lines: "#4 Mixed 12 & Under 50 Yard Backstroke"
      - heat lines: "Heat 7 of 10"
      - swimmer lines that follow
    """
    lines = text.splitlines()
    events: List[dict] = []

    current_event_number = None
    current_event_name = None
    current_heat = None

    event_header_re = re.compile(r"#(\d+)\s+(.*)")
    heat_re = re.compile(r"Heat\s+(\d+)\s+of\s+(\d+)", re.IGNORECASE)

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # event header
        m_event = event_header_re.match(line)
        if m_event:
            current_event_number = int(m_event.group(1))
            current_event_name = m_event.group(2).strip()
            current_heat = None
            continue

        # heat header
        m_heat = heat_re.search(line)
        if m_heat:
            current_heat = int(m_heat.group(1))
            continue

        # swimmer row
        if current_event_number is not None and current_heat is not None:
            lane = extract_lane(line)
            seed_time = extract_seed_time(line)
            name = extract_name(line)

            if name:
                events.append(
                    {
                        "event_number": current_event_number,
                        "event_name": current_event_name,
                        "heat": current_heat,
                        "lane": lane,
                        "seed_time": seed_time,
                        "raw_line": line,
                        "swimmer_name": name,
                    }
                )

    return events


def extract_lane(line: str):
    m = re.search(r"(\d+)\s*$", line)
    if m:
        return int(m.group(1))
    return None


def extract_seed_time(line: str):
    m = re.search(r"(\d+:\d+\.\d+|\d+\.\d+)", line)
    if m:
        return m.group(1)
    return None


def extract_name(line: str):
    # matches "Hammond, Dillon J"
    m = re.search(r"([A-Za-z'\-]+,\s+[A-Za-z'\-]+(?:\s+[A-Za-z.]+)?)", line)
    if m:
        return m.group(1).strip()
    return None


def filter_for_swimmer(events: List[dict], swimmer_name: str):
    target = swimmer_name.lower().strip()
    matched = []
    for ev in events:
        if ev["swimmer_name"] and target in ev["swimmer_name"].lower():
            matched.append(ev)
    return matched


def get_unique_swimmers(events: List[dict]) -> List[str]:
    names = set()
    for ev in events:
        if ev.get("swimmer_name"):
            names.add(ev["swimmer_name"])
    return sorted(names, key=lambda x: x.lower())

