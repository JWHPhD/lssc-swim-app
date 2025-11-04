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

# PDF generation
from reportlab.lib.pagesizes import landscape, letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors

app = FastAPI()

# Allow frontend & local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def read_root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_path):
        return HTMLResponse("<h1>Lakeshore Swim App</h1><p>static/index.html not found.</p>")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


# ---------- API ---------- #

@app.post("/list-swimmers")
async def list_swimmers(file: UploadFile = File(...)):
    text = extract_text_from_upload(file.content_type, await file.read())
    events = parse_heat_sheet(text)
    return {"count": len(events), "swimmers": get_unique_swimmers(events)}


@app.post("/extract")
async def extract_swimmer_events(swimmer_name: str = Form(...), file: UploadFile = File(...)):
    text = extract_text_from_upload(file.content_type, await file.read())
    events = sorted(parse_heat_sheet(text), key=lambda e: e["event_number"])
    matched = filter_for_swimmer(events, swimmer_name)
    return {"swimmer": swimmer_name, "count": len(matched), "events": matched}


@app.post("/generate-pdf")
async def generate_swimmer_pdf(swimmer_name: str = Form(...), file: UploadFile = File(...)):
    text = extract_text_from_upload(file.content_type, await file.read())
    events = sorted(parse_heat_sheet(text), key=lambda e: e["event_number"])
    matched = filter_for_swimmer(events, swimmer_name)

    tmp_path = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf").name
    doc = SimpleDocTemplate(tmp_path, pagesize=landscape(letter), leftMargin=30, rightMargin=30)
    elements = [
        Paragraph(f"Swim Schedule – {swimmer_name}", ParagraphStyle("title", fontSize=16, spaceAfter=6)),
        Paragraph("Lakeshore Swim Club", ParagraphStyle("sub", fontSize=9, textColor=colors.grey)),
        Paragraph(datetime.now().strftime("%B %d, %Y %I:%M %p"), ParagraphStyle("sub", fontSize=9)),
        Spacer(1, 12)
    ]

    data = [["Event", "Heat", "Lane", "Seed", "Results"]]
    for ev in matched:
        total = ev.get("total_heats")
        heat_display = f"{ev['heat']} of {total}" if total else str(ev["heat"])
        data.append([
            Paragraph(f"#{ev['event_number']} – {ev['event_name']}", ParagraphStyle("ev", fontSize=9)),
            heat_display,
            ev.get("lane", ""),
            ev.get("seed_time", ""),
            "Time: __________   Place: ______"
        ])
    if len(data) == 1:
        data.append(["No events found", "", "", "", ""])

    table = Table(data, colWidths=[240, 70, 50, 60, 200])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#007bff")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 1), (3, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
        ("PADDING", (0, 0), (-1, -1), 4)
    ]))
    elements += [table, Spacer(1, 14), Paragraph("Notes:", ParagraphStyle("label", fontSize=9))]
    for _ in range(3):
        elements.append(Paragraph("_________________________________________________________", ParagraphStyle("sub", fontSize=8)))

    doc.build(elements)
    return FileResponse(tmp_path, media_type="application/pdf", filename=f"{swimmer_name.replace(' ', '_')}_schedule.pdf")


# ---------- HELPERS ---------- #

def extract_text_from_upload(content_type: str, content_bytes: bytes) -> str:
    if content_type == "application/pdf":
        pdf = PdfReader(BytesIO(content_bytes))
        return "\n".join([page.extract_text() or "" for page in pdf.pages])
    return content_bytes.decode("utf-8", errors="ignore")


def preprocess_text(text: str) -> str:
    """
    Clean & normalize lines before parsing.
    Handles:
    - Heat 6 of 10 (#7 ...)
    - Heat 6 (#7 ...)
    """
    text = re.sub(r"Heat\s+(\d+)\s+of\s+(\d+)\s+\(#(\d+)\s+([^)]+)\)", r"#\3 \4\nHeat \1 of \2", text)
    text = re.sub(r"Heat\s+(\d+)\s+\(#(\d+)\s+([^)]+)\)", r"#\2 \3\nHeat \1", text)
    text = re.sub(r"(?<!\n)(#\d+\s+)", r"\n\1", text)
    text = re.sub(r"(?<!\n)(Heat\s+\d+)", r"\n\1", text)
    return text


def parse_heat_sheet(text: str):
    text = preprocess_text(text)
    lines = text.splitlines()
    events: List[dict] = []
    current_event_number = current_event_name = current_heat = None
    current_total_heats = None

    event_re = re.compile(r"^#(\d+)\s+(.*)")
    heat_of_re = re.compile(r"^Heat\s+(\d+)\s+of\s+(\d+)", re.IGNORECASE)
    heat_re = re.compile(r"^Heat\s+(\d+)\b", re.IGNORECASE)

    for line in lines:
        line = line.strip()
        if not line:
            continue
        m_event = event_re.match(line)
        if m_event:
            current_event_number = int(m_event.group(1))
            current_event_name = m_event.group(2).strip().rstrip(")")
            current_heat = None
            continue
        m_heat_of = heat_of_re.match(line)
        if m_heat_of:
            current_heat = int(m_heat_of.group(1))
            current_total_heats = int(m_heat_of.group(2))
            continue
        m_heat = heat_re.match(line)
        if m_heat:
            current_heat = int(m_heat.group(1))
            # keep last known total_heats
            continue
        if current_event_number and current_heat:
            name = extract_name(line)
            if name:
                events.append({
                    "event_number": current_event_number,
                    "event_name": current_event_name,
                    "heat": current_heat,
                    "total_heats": current_total_heats,
                    "lane": extract_lane(line),
                    "seed_time": extract_seed_time(line),
                    "raw_line": line,
                    "swimmer_name": name
                })
    return events


def extract_lane(line: str):
    m = re.search(r"(\d+)\s*$", line)
    return int(m.group(1)) if m else None


def extract_seed_time(line: str):
    m = re.search(r"(\d+:\d+\.\d+|\d+\.\d+)", line)
    return m.group(1) if m else None


def extract_name(line: str):
    m = re.search(r"([A-Za-z'\-]+,\s+[A-Za-z'\-]+(?:\s+[A-Za-z.]+)?)", line)
    return m.group(1).strip() if m else None


def filter_for_swimmer(events: List[dict], swimmer_name: str):
    target = swimmer_name.lower().strip()
    return [e for e in events if e.get("swimmer_name") and target in e["swimmer_name"].lower()]


def get_unique_swimmers(events: List[dict]):
    return sorted({e["swimmer_name"] for e in events if e.get("swimmer_name")}, key=str.lower)







