from fastapi import FastAPI, UploadFile, File, Form, HTTPException
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
import json

# PDF generation
from reportlab.lib.pagesizes import landscape, letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors

app = FastAPI()

# Testing Pro Features Branch Setup
# --------------- SECURITY / CONFIG ---------------
ALLOWED_ORIGINS = [
    "https://lssc-swim-app.onrender.com",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
PARENT_PIN = os.getenv("PARENT_PIN", "lssc2025")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------- STATIC FILES ---------------
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


# --------------- AUTH (PIN) ---------------
@app.post("/auth")
async def verify_pin(pin: str = Form(...)):
    if pin == PARENT_PIN:
        return {"ok": True}
    raise HTTPException(status_code=401, detail="Invalid PIN")

# --------------- PREMIUM AUTH ---------------
PREMIUM_CODE = os.getenv("PREMIUM_CODE", "lssc-pro-2025")

@app.post("/premium-auth")
async def premium_auth(code: str = Form(...)):
    if code == PREMIUM_CODE:
        return {"ok": True}
    raise HTTPException(status_code=401, detail="Invalid premium code")



# --------------- MAIN API ENDPOINTS ---------------

@app.post("/list-swimmers")
async def list_swimmers(file: UploadFile = File(...)):
    content_bytes = await secure_read_upload(file)
    text = extract_text_from_upload(file.content_type, content_bytes)
    events = parse_heat_sheet(text)
    swimmers = get_unique_swimmers(events)
    return {"count": len(swimmers), "swimmers": swimmers}


@app.post("/extract")
async def extract_swimmer_events(
    swimmer_name: str = Form(...),
    file: UploadFile = File(...)
):
    content_bytes = await secure_read_upload(file)
    text = extract_text_from_upload(file.content_type, content_bytes)
    events = parse_heat_sheet(text)
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
    content_bytes = await secure_read_upload(file)
    text = extract_text_from_upload(file.content_type, content_bytes)
    events = parse_heat_sheet(text)
    events = sorted(events, key=lambda e: e["event_number"])
    matched = filter_for_swimmer(events, swimmer_name)

    tmp_path = build_schedule_pdf(swimmer_name, matched)
    return FileResponse(
        tmp_path,
        media_type="application/pdf",
        filename=f"{swimmer_name.replace(' ', '_')}_schedule.pdf",
    )

@app.post("/generate-team-pdf")
async def generate_team_pdf(
    swimmers_json: str = Form(...),
    file: UploadFile = File(...),
    order_by: str = Form("swimmer"),
):

    """
    Build a combined PDF for multiple swimmers from the same heat sheet.
    swimmers_json = '["Hammond, Dillon", "Smith, Alex"]'
    """
    # read and parse the PDF just like other endpoints
    content_bytes = await secure_read_upload(file)
    text = extract_text_from_upload(file.content_type, content_bytes)
    events = parse_heat_sheet(text)
    events = sorted(events, key=lambda e: e["event_number"])

    try:
        swimmer_names = json.loads(swimmers_json)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad swimmers list")

    # collect matched events for each swimmer
    all_rows = []  # list of dicts: swimmer, event, heat, lane, seed
    for name in swimmer_names:
        matched = filter_for_swimmer(events, name)
        for ev in matched:
            all_rows.append(
                {
                    "swimmer": name,
                    "event_number": ev["event_number"],
                    "event_name": ev["event_name"],
                    "heat": ev["heat"],
                    "total_heats": ev.get("total_heats"),
                    "lane": ev.get("lane"),
                    "seed_time": ev.get("seed_time"),
                }
            )
        # sort according to user choice
    if order_by == "event":
        # event -> heat -> swimmer
        all_rows.sort(
            key=lambda r: (
                r["event_number"],
                r["heat"] or 0,
                r["swimmer"].lower(),
            )
        )
    else:
        # default: swimmer -> event -> heat
        all_rows.sort(
            key=lambda r: (
                r["swimmer"].lower(),
                r["event_number"],
                r["heat"] or 0,
            )
        )


    # build PDF
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp_path = tmp.name
    tmp.close()

    doc = SimpleDocTemplate(
        tmp_path,
        pagesize=landscape(letter),
        leftMargin=30,
        rightMargin=30,
        topMargin=30,
        bottomMargin=30,
    )

    elements = []
    title_style = ParagraphStyle("title", fontSize=16, spaceAfter=6, leading=18)
    sub_style = ParagraphStyle("sub", fontSize=9, spaceAfter=4, textColor=colors.grey)

    elements.append(Paragraph("SwimDay Simplified – Team Schedule", title_style))
    elements.append(Paragraph("Lakeshore Swim Club", sub_style))
    elements.append(Paragraph(
        f"Swimmers: {', '.join(swimmer_names)}", sub_style
    ))
    elements.append(
        Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}", sub_style)
    )
    elements.append(Spacer(1, 12))

    data = [["Swimmer", "Event", "Heat", "Lane", "Seed"]]

    if all_rows:
        for row in all_rows:
            evt_text = f"#{row['event_number']} – {row['event_name']}"
            if row["total_heats"]:
                heat_display = f"{row['heat']} of {row['total_heats']}"
            else:
                heat_display = str(row["heat"])
            data.append(
                [
                    row["swimmer"],
                    evt_text,
                    heat_display,
                    row["lane"] if row["lane"] is not None else "",
                    row["seed_time"] or "",
                ]
            )
    else:
        data.append(["No events found for selected swimmers", "", "", "", ""])

    table = Table(
        data,
        colWidths=[130, 240, 70, 50, 70],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#007bff")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ALIGN", (2, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    elements.append(table)
    doc.build(elements)

    return FileResponse(
        tmp_path,
        media_type="application/pdf",
        filename="team_schedule.pdf",
    )

# --------------- NEW: RESULTS PDF ENDPOINT ---------------
@app.post("/generate-results-pdf")
async def generate_results_pdf(
    swimmer_name: str = Form(...),
    results_json: str = Form(...)
):
    """
    results_json should be a JSON array of:
    [
      {
        "event_number": 4,
        "event_name": "Mixed 12 & Under 50 Yard Backstroke",
        "heat": 7,
        "total_heats": 10,
        "lane": 7,
        "seed_time": "47.64",
        "final_time": "46.80"
      },
      ...
    ]
    """
    try:
        results = json.loads(results_json)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad results data")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp_path = tmp.name
    tmp.close()

    doc = SimpleDocTemplate(
        tmp_path,
        pagesize=landscape(letter),
        leftMargin=30,
        rightMargin=30,
        topMargin=30,
        bottomMargin=30,
    )
    elements = []

    title_style = ParagraphStyle("title", fontSize=16, spaceAfter=6, leading=18)
    sub_style = ParagraphStyle("sub", fontSize=9, spaceAfter=4, textColor=colors.grey)

    elements.append(Paragraph(f"SwimDay Simplified – Results for {swimmer_name}", title_style))
    elements.append(Paragraph("Lakeshore Swim Club", sub_style))
    elements.append(
        Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}", sub_style)
    )
    elements.append(Spacer(1, 12))

    data = [["Event", "Heat", "Lane", "Seed", "Final", "Δ (Final - Seed)"]]

    for ev in results:
        seed = ev.get("seed_time") or ""
        final = ev.get("final_time") or ""
        delta = ""
        if seed and final:
            delta_seconds = time_to_seconds(final) - time_to_seconds(seed)
            delta = f"{delta_seconds:+.2f}s"
        heat_display = ""
        if ev.get("total_heats"):
            heat_display = f"{ev.get('heat')} of {ev.get('total_heats')}"
        else:
            heat_display = str(ev.get("heat") or "")
        data.append(
            [
                f"#{ev.get('event_number')} – {ev.get('event_name','')}",
                heat_display,
                ev.get("lane") or "",
                seed,
                final,
                delta,
            ]
        )

    table = Table(
        data,
        colWidths=[240, 70, 50, 60, 70, 90],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#007bff")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    elements.append(table)
    doc.build(elements)

    return FileResponse(
        tmp_path,
        media_type="application/pdf",
        filename=f"{swimmer_name.replace(' ', '_')}_results.pdf",
    )


# --------------- HELPERS ---------------

async def secure_read_upload(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Max 10 MB.")
    return content


def extract_text_from_upload(content_type: str, content_bytes: bytes) -> str:
    if content_bytes is None:
        raise HTTPException(status_code=400, detail="Empty file.")
    if content_type not in ("application/pdf", "application/x-pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Only PDF heat sheets are supported.")
    try:
        pdf_stream = BytesIO(content_bytes)
        reader = PdfReader(pdf_stream)
        pages_text = []
        for page in reader.pages:
            pages_text.append(page.extract_text() or "")
        return "\n".join(pages_text)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read PDF. Please upload a standard PDF heat sheet.")


def preprocess_text(text: str) -> str:
    text = re.sub(
        r"Heat\s+(\d+)\s+of\s+(\d+)\s+\(#(\d+)\s+([^)]+)\)",
        r"#\3 \4\nHeat \1 of \2",
        text,
    )
    text = re.sub(
        r"Heat\s+(\d+)\s+\(#(\d+)\s+([^)]+)\)",
        r"#\2 \3\nHeat \1",
        text,
    )
    text = re.sub(r"(?<!\n)(#\d+\s+)", r"\n\1", text)
    text = re.sub(r"(?<!\n)(Heat\s+\d+)", r"\n\1", text)
    return text


def parse_heat_sheet(text: str):
    text = preprocess_text(text)
    lines = text.splitlines()
    events: List[dict] = []

    current_event_number = None
    current_event_name = None
    current_heat = None
    current_total_heats = None

    event_header_re = re.compile(r"^#(\d+)\s+(.*)")
    heat_of_re = re.compile(r"^Heat\s+(\d+)\s+of\s+(\d+)", re.IGNORECASE)
    heat_only_re = re.compile(r"^Heat\s+(\d+)\b", re.IGNORECASE)

    for line in lines:
        line = line.strip()
        if not line:
            continue

        m_ev = event_header_re.match(line)
        if m_ev:
            current_event_number = int(m_ev.group(1))
            current_event_name = m_ev.group(2).strip().rstrip(")")
            current_heat = None
            continue

        m_heat = heat_of_re.match(line)
        if m_heat:
            current_heat = int(m_heat.group(1))
            current_total_heats = int(m_heat.group(2))
            continue

        m_heat2 = heat_only_re.match(line)
        if m_heat2:
            current_heat = int(m_heat2.group(1))
            continue

        if current_event_number is not None and current_heat is not None:
            name = extract_name(line)
            if name:
                events.append(
                    {
                        "event_number": current_event_number,
                        "event_name": current_event_name,
                        "heat": current_heat,
                        "total_heats": current_total_heats,
                        "lane": extract_lane(line),
                        "seed_time": extract_seed_time(line),
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
    m = re.search(r"([A-Za-z'\-]+,\s+[A-Za-z'\-]+(?:\s+[A-Za-z.]+)?)", line)
    if m:
        return m.group(1).strip()
    return None


def filter_for_swimmer(events: List[dict], swimmer_name: str):
    target = swimmer_name.lower().strip()
    return [
        ev for ev in events
        if ev.get("swimmer_name") and target in ev["swimmer_name"].lower()
    ]


def get_unique_swimmers(events: List[dict]) -> List[str]:
    names = set()
    for ev in events:
        if ev.get("swimmer_name"):
            names.add(ev["swimmer_name"])
    return sorted(names, key=lambda x: x.lower())


def build_schedule_pdf(swimmer_name: str, matched: List[dict]) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp_path = tmp.name
    tmp.close()

    doc = SimpleDocTemplate(
        tmp_path,
        pagesize=landscape(letter),
        leftMargin=30,
        rightMargin=30,
        topMargin=30,
        bottomMargin=30,
    )
    elements = []

    title_style = ParagraphStyle("title", fontSize=16, spaceAfter=6, leading=18)
    sub_style = ParagraphStyle("sub", fontSize=9, spaceAfter=4, textColor=colors.grey)
    notes_label_style = ParagraphStyle("label", fontSize=9, spaceAfter=2)

    elements.append(Paragraph(f"SwimDay Simplified – {swimmer_name}", title_style))
    elements.append(Paragraph("Lakeshore Swim Club", sub_style))
    elements.append(
        Paragraph(
            f"Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}",
            sub_style,
        )
    )
    elements.append(Spacer(1, 12))

    data = [["Event", "Heat", "Lane", "Seed", "Results"]]
    if matched:
        for ev in matched:
            evt_text = f"#{ev['event_number']} – {ev['event_name']}"
            total_heats = ev.get("total_heats")
            if total_heats:
                heat_display = f"{ev['heat']} of {total_heats}"
            else:
                heat_display = str(ev["heat"])
            data.append(
                [
                    Paragraph(evt_text, ParagraphStyle("ev", fontSize=9, leading=11)),
                    heat_display,
                    ev["lane"] if ev["lane"] is not None else "",
                    ev["seed_time"] or "",
                    "Time: __________   Place: ______",
                ]
            )
    else:
        data.append(["No events found for this swimmer", "", "", "", ""])

    table = Table(
        data,
        colWidths=[240, 70, 50, 60, 200],
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
    elements.append(Paragraph("Notes:", notes_label_style))
    elements.append(Spacer(1, 4))
    for _ in range(3):
        elements.append(
            Paragraph("_______________________________________________________________", sub_style)
        )

    doc.build(elements)
    return tmp_path


def time_to_seconds(t: str) -> float:
    """
    Convert time strings like "1:05.32" or "47.64" to seconds.
    """
    t = t.strip()
    if ":" in t:
        mins, rest = t.split(":", 1)
        return int(mins) * 60 + float(rest)
    return float(t)

























