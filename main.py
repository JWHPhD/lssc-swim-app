from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Tuple
from io import BytesIO
from datetime import datetime, timedelta
from threading import Lock
from time import time
import tempfile
import re
import os
import json

# PDF reading
from PyPDF2 import PdfReader

# PDF generation
from reportlab.lib.pagesizes import landscape, letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors

# --------------------------------------------------------------------------------------
# App setup & config
# --------------------------------------------------------------------------------------
app = FastAPI(title="SwimDay Simplified API")

ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    # add your Render domain(s) here:
    "https://lssc-swim-app.onrender.com","https://lssc-swim-app-timeline-dev.onrender.com",
]

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
PARENT_PIN = "lssc2025"
PREMIUM_CODE = "lssc-pro-2025"

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --------------------------------------------------------------------------------------
# Root -> serve SPA
# --------------------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def read_root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_path):
        return HTMLResponse("<h1>SwimDay Simplified</h1><p>Put index.html in /static.</p>")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


# --------------------------------------------------------------------------------------
# Auth (PIN + Pro unlock)
# --------------------------------------------------------------------------------------
@app.post("/auth")
def auth(pin: str = Form(...)):
    if pin == PARENT_PIN:
        return {"ok": True}
    raise HTTPException(status_code=401, detail="Invalid PIN")

@app.post("/premium-auth")
def premium_auth(code: str = Form(...)):
    if code.strip() == PREMIUM_CODE:
        return {"ok": True}
    raise HTTPException(status_code=401, detail="Invalid premium code")


# --------------------------------------------------------------------------------------
# Core PDF parsing routes
# --------------------------------------------------------------------------------------
@app.post("/list-swimmers")
async def list_swimmers(file: UploadFile = File(...)):
    content = await _read_upload(file)
    text = _extract_text(file.content_type, content)
    events = _parse_heat_sheet(text)
    swimmers = _unique_swimmers(events)
    return {"count": len(swimmers), "swimmers": swimmers}

@app.post("/extract")
async def extract_swimmer_events(swimmer_name: str = Form(...), file: UploadFile = File(...)):
    content = await _read_upload(file)
    text = _extract_text(file.content_type, content)
    events = _parse_heat_sheet(text)
    events = sorted(events, key=lambda e: (e["event_number"], e.get("heat") or 0))
    matched = [e for e in events if e.get("swimmer_name") and swimmer_name.lower() in e["swimmer_name"].lower()]
    return {"swimmer": swimmer_name, "count": len(matched), "events": matched}

@app.post("/extract-all-events")
async def extract_all_events(file: UploadFile = File(...)):
    content = await _read_upload(file)
    text = _extract_text(file.content_type, content)
    events = _parse_heat_sheet(text)
    events = sorted(events, key=lambda e: (e["event_number"], e.get("heat") or 0))
    return {"count": len(events), "events": events}


# --------------------------------------------------------------------------------------
# PDF generation (free + results + pro team)
# --------------------------------------------------------------------------------------
@app.post("/generate-pdf")
async def generate_swimmer_pdf(swimmer_name: str = Form(...), file: UploadFile = File(...)):
    content = await _read_upload(file)
    text = _extract_text(file.content_type, content)
    events = _parse_heat_sheet(text)
    events = sorted(events, key=lambda e: (e["event_number"], e.get("heat") or 0))
    matched = [e for e in events if e.get("swimmer_name") and swimmer_name.lower() in e["swimmer_name"].lower()]
    path = _build_schedule_pdf(swimmer_name, matched)
    return FileResponse(path, media_type="application/pdf", filename=f"{_safe(swimmer_name)}_schedule.pdf")

@app.post("/generate-results-pdf")
async def generate_results_pdf(swimmer_name: str = Form(...), results_json: str = Form(...)):
    try:
        results = json.loads(results_json)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad results data")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf"); tmp.close()
    doc = SimpleDocTemplate(tmp.name, pagesize=landscape(letter), leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    title_style = ParagraphStyle("title", fontSize=16, spaceAfter=6, leading=18)
    sub_style = ParagraphStyle("sub", fontSize=9, spaceAfter=4, textColor=colors.grey)

    elements.append(Paragraph(f"SwimDay Simplified – Results for {swimmer_name}", title_style))
    elements.append(Paragraph("Lakeshore Swim Club", sub_style))
    elements.append(Paragraph(datetime.now().strftime("%B %d, %Y %I:%M %p"), sub_style))
    elements.append(Spacer(1, 12))

    data = [["Event", "Heat", "Lane", "Seed", "Final", "Δ (Final - Seed)"]]
    for ev in results:
        seed = ev.get("seed_time") or ""
        final = ev.get("final_time") or ""
        delta = ""
        if seed and final:
            try:
                delta_seconds = _t2s(final) - _t2s(seed)
                delta = f"{delta_seconds:+.2f}s"
            except Exception:
                delta = ""
        heat_display = f"{ev.get('heat')}" + (f" of {ev.get('total_heats')}" if ev.get("total_heats") else "")
        data.append([
            f"#{ev.get('event_number')} – {ev.get('event_name','')}",
            heat_display,
            ev.get("lane") or "",
            seed,
            final,
            delta
        ])

    table = Table(data, colWidths=[240, 70, 50, 60, 70, 90])
    table.setStyle(_std_table_style())
    elements.append(table)
    doc.build(elements)

    return FileResponse(tmp.name, media_type="application/pdf", filename=f"{_safe(swimmer_name)}_results.pdf")

@app.post("/generate-team-pdf")
async def generate_team_pdf(
    file: UploadFile = File(...),
    swimmers_json: str = Form(...),
    order_by: str = Form("swimmer")
):
    try:
        swimmers = [s.strip() for s in json.loads(swimmers_json) if s.strip()]
        if not swimmers:
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400, detail="Bad swimmers list")

    content = await _read_upload(file)
    text = _extract_text(file.content_type, content)
    events = _parse_heat_sheet(text)

    combined = []
    for sw in swimmers:
        for ev in events:
            if ev.get("swimmer_name") and sw.lower() in ev["swimmer_name"].lower():
                combined.append({
                    "swimmer": ev["swimmer_name"],
                    "event_number": ev["event_number"],
                    "event_name": ev["event_name"],
                    "heat": ev["heat"],
                    "total_heats": ev.get("total_heats"),
                    "lane": ev.get("lane"),
                    "seed_time": ev.get("seed_time") or "",
                })

    if order_by == "event":
        combined.sort(key=lambda x: (x["event_number"], x["heat"] or 0, x["swimmer"].lower()))
    else:
        combined.sort(key=lambda x: (x["swimmer"].lower(), x["event_number"], x["heat"] or 0))

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf"); tmp.close()
    doc = SimpleDocTemplate(tmp.name, pagesize=landscape(letter), leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    title_style = ParagraphStyle("title", fontSize=16, spaceAfter=6, leading=18)
    sub_style = ParagraphStyle("sub", fontSize=9, spaceAfter=4, textColor=colors.grey)

    elements.append(Paragraph("SwimDay Simplified – Team Schedule", title_style))
    elements.append(Paragraph("Lakeshore Swim Club", sub_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')} — Order by: {order_by.capitalize()}", sub_style))
    elements.append(Spacer(1, 12))

    data = [["Swimmer", "Event", "Heat", "Lane", "Seed"]]
    for r in combined:
        evt_text = f"#{r['event_number']} – {r['event_name']}"
        heat_disp = f"{r['heat']}" + (f" of {r['total_heats']}" if r.get("total_heats") else "")
        data.append([
            r["swimmer"],
            evt_text,
            heat_disp,
            r["lane"] if r["lane"] is not None else "",
            r["seed_time"]
        ])

    table = Table(data, colWidths=[160, 290, 70, 50, 70])
    table.setStyle(_std_table_style())
    elements.append(table)
    doc.build(elements)

    return FileResponse(tmp.name, media_type="application/pdf", filename="team_schedule.pdf")


# --------------------------------------------------------------------------------------
# Optional server-side timeline estimator (not required by HTML; offered as utility)
# --------------------------------------------------------------------------------------
@app.post("/timeline/estimate")
async def timeline_estimate(
    file: UploadFile = File(...),
    start_hhmm: str = Form(...),  # "HH:MM" (24h or 12h both ok), date handled client-side
    seconds_between_heats: int = Form(20),
    seconds_between_events: int = Form(60),
):
    content = await _read_upload(file)
    text = _extract_text(file.content_type, content)
    events = _parse_heat_sheet(text)
    events = sorted(events, key=lambda e: (e["event_number"], e.get("heat") or 0))

    # Build event->heat->durations using "first seed in heat" heuristic
    per_heat_seconds: Dict[Tuple[int, int], float] = {}
    first_seen: Dict[Tuple[int, int], Optional[str]] = {}

    for ev in events:
        key = (ev["event_number"], ev["heat"] or 0)
        if key not in first_seen and ev.get("seed_time"):
            first_seen[key] = ev["seed_time"]

    for key, t in first_seen.items():
        per_heat_seconds[key] = _t2s(t) if t else 60.0  # default 60s if missing

    # Walk the whole meet from start_hhmm and assign absolute times to each heat
    start_dt = _parse_hhmm_to_today(start_hhmm)
    schedule_map: Dict[Tuple[int, int], datetime] = {}
    last_event = None
    cursor = start_dt

    seen_pairs = sorted({(e["event_number"], e["heat"] or 0) for e in events})
    for (ev_no, heat_no) in seen_pairs:
        if last_event is not None and ev_no != last_event:
            cursor += timedelta(seconds=seconds_between_events)
        schedule_map[(ev_no, heat_no)] = cursor
        duration = per_heat_seconds.get((ev_no, heat_no), 60.0)
        cursor += timedelta(seconds=duration + seconds_between_heats)
        last_event = ev_no

    # Return back a list for rendering
    out = []
    for ev in events:
        when = schedule_map.get((ev["event_number"], ev["heat"] or 0))
        out.append({
            "swimmer_name": ev["swimmer_name"],
            "event_number": ev["event_number"],
            "event_name": ev["event_name"],
            "heat": ev["heat"],
            "total_heats": ev.get("total_heats"),
            "lane": ev.get("lane"),
            "seed_time": ev.get("seed_time"),
            "estimated_dt": when.isoformat() if when else None,
        })

    return {"count": len(out), "items": out, "start": start_dt.isoformat()}


# --------------------------------------------------------------------------------------
# Crowd Assist (in-memory)
# --------------------------------------------------------------------------------------
_CROWD: Dict[str, Dict[str, Any]] = {}
_LOCK = Lock()

class CrowdUpdate(BaseModel):
    meet_code: str
    display_name: str
    event_number: int
    heat_number: int
    note: Optional[str] = None

def _now() -> float:
    return time()

def _ensure_meet(code: str):
    if code not in _CROWD:
        _CROWD[code] = {"latest": None, "history": [], "updated_at": 0.0}

@app.post("/crowd/broadcast")
def crowd_broadcast(update: CrowdUpdate):
    code = update.meet_code.strip().upper()
    name = update.display_name.strip()
    if not code or not name:
        raise HTTPException(status_code=400, detail="Missing meet_code or display_name")
    if update.event_number < 1 or update.heat_number < 1:
        raise HTTPException(status_code=400, detail="Bad event/heat")

    with _LOCK:
        _ensure_meet(code)
        payload = {
            "display_name": name,
            "event_number": update.event_number,
            "heat_number": update.heat_number,
            "note": (update.note or "").strip(),
            "server_ts": _now(),
        }
        row = _CROWD[code]
        row["latest"] = payload
        row["history"].append(payload)
        row["updated_at"] = payload["server_ts"]

    return {"ok": True}

@app.get("/crowd/updates")
def crowd_updates(meet_code: str, since: float = 0.0):
    code = meet_code.strip().upper()
    with _LOCK:
        if code not in _CROWD:
            return {"latest": None, "updated_at": 0.0}
        row = _CROWD[code]
        if row["updated_at"] > since:
            return {"latest": row["latest"], "updated_at": row["updated_at"]}
        return {"latest": None, "updated_at": row["updated_at"]}


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
async def _read_upload(file: UploadFile) -> bytes:
    b = await file.read()
    if len(b) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (10MB)")
    return b

def _extract_text(content_type: str, content_bytes: bytes) -> str:
    if not content_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    # content_type can be "application/octet-stream" depending on browser; allow it.
    try:
        reader = PdfReader(BytesIO(content_bytes))
        texts = []
        for page in reader.pages:
            texts.append(page.extract_text() or "")
        return "\n".join(texts)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read PDF. Upload a standard PDF heat sheet.")

def _normalize(text: str) -> str:
    text = re.sub(r"Heat\s+(\d+)\s+of\s+(\d+)\s+\(#(\d+)\s+([^)]+)\)", r"#\3 \4\nHeat \1 of \2", text)
    text = re.sub(r"Heat\s+(\d+)\s+\(#(\d+)\s+([^)]+)\)", r"#\2 \3\nHeat \1", text)
    text = re.sub(r"(?<!\n)(#\d+\s+)", r"\n\1", text)
    text = re.sub(r"(?<!\n)(Heat\s+\d+)", r"\n\1", text)
    return text

def _parse_heat_sheet(text: str) -> List[Dict[str, Any]]:
    text = _normalize(text)
    lines = text.splitlines()

    events: List[Dict[str, Any]] = []

    ev_re = re.compile(r"^#(\d+)\s+(.*)")
    heat_of = re.compile(r"^Heat\s+(\d+)\s+of\s+(\d+)", re.I)
    heat_only = re.compile(r"^Heat\s+(\d+)\b", re.I)

    cur_ev = None
    cur_name = None
    cur_heat = None
    cur_total = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        m = ev_re.match(line)
        if m:
            cur_ev = int(m.group(1))
            cur_name = m.group(2).strip().rstrip(")")
            cur_heat = None
            cur_total = None
            continue

        m = heat_of.match(line)
        if m:
            cur_heat = int(m.group(1))
            cur_total = int(m.group(2))
            continue

        m = heat_only.match(line)
        if m:
            cur_heat = int(m.group(1))
            continue

        if cur_ev is not None and cur_heat is not None:
            name = _name_from_line(line)
            if name:
                events.append({
                    "event_number": cur_ev,
                    "event_name": cur_name,
                    "heat": cur_heat,
                    "total_heats": cur_total,
                    "lane": _lane_from_line(line),
                    "seed_time": _seed_from_line(line),
                    "swimmer_name": name,
                })

    return events

def _lane_from_line(line: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*$", line)
    return int(m.group(1)) if m else None

def _seed_from_line(line: str) -> Optional[str]:
    m = re.search(r"(\d+:\d+\.\d+|\d+\.\d+)", line)
    return m.group(1) if m else None

def _name_from_line(line: str) -> Optional[str]:
    m = re.search(r"([A-Za-z'\-]+,\s+[A-Za-z'\-]+(?:\s+[A-Za-z.]+)?)", line)
    return m.group(1).strip() if m else None

def _unique_swimmers(events: List[Dict[str, Any]]) -> List[str]:
    names = {e["swimmer_name"] for e in events if e.get("swimmer_name")}
    return sorted(names, key=lambda s: s.lower())

def _std_table_style():
    return TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#007bff")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.whitesmoke),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,0),10),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("ALIGN",(0,0),(0,-1),"LEFT"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("GRID",(0,0),(-1,-1),0.4,colors.grey),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.whitesmoke, colors.lightgrey]),
        ("LEFTPADDING",(0,0),(-1,-1),4),
        ("RIGHTPADDING",(0,0),(-1,-1),4),
    ])

def _t2s(t: str) -> float:
    t = t.strip()
    if ":" in t:
        m, s = t.split(":", 1)
        return int(m) * 60 + float(s)
    return float(t)

def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", name.strip())

def _parse_hhmm_to_today(hhmm: str) -> datetime:
    """Accepts 'HH:MM' in 24h or 12h (no AM/PM) and maps to today."""
    hhmm = hhmm.strip()
    if not re.match(r"^\d{1,2}:\d{2}$", hhmm):
        # fallback to noon
        return datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    h, m = hhmm.split(":")
    h = int(h); m = int(m)
    now = datetime.now()
    # clamp to 0-23
    if h > 23: h = 23
    if m > 59: m = 59
    return now.replace(hour=h, minute=m, second=0, microsecond=0)

def _build_schedule_pdf(swimmer_name: str, matched: List[Dict[str, Any]]) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf"); tmp.close()
    doc = SimpleDocTemplate(tmp.name, pagesize=landscape(letter), leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    title_style = ParagraphStyle("title", fontSize=16, spaceAfter=6, leading=18)
    sub_style = ParagraphStyle("sub", fontSize=9, spaceAfter=4, textColor=colors.grey)

    elements.append(Paragraph(f"SwimDay Simplified – {swimmer_name}", title_style))
    elements.append(Paragraph("Lakeshore Swim Club", sub_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}", sub_style))
    elements.append(Spacer(1, 12))

    data = [["Event", "Heat", "Lane", "Seed", "Results"]]
    if not matched:
        data.append(["No events found for this swimmer", "", "", "", ""])
    else:
        for ev in matched:
            evt_text = f"#{ev['event_number']} – {ev['event_name']}"
            heat_disp = f"{ev['heat']}" + (f" of {ev.get('total_heats')}" if ev.get("total_heats") else "")
            data.append([
                Paragraph(evt_text, ParagraphStyle("ev", fontSize=9, leading=11)),
                heat_disp,
                ev.get("lane") or "",
                ev.get("seed_time") or "",
                "Time: ______  Place: ____"
            ])

    table = Table(data, colWidths=[240, 70, 50, 60, 200])
    table.setStyle(_std_table_style())
    elements.append(table)
    doc.build(elements)
    return tmp.name
