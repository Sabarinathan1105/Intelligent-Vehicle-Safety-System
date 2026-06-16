import cv2
import time
import threading
import numpy as np
import os
import io
from datetime import datetime
from collections import deque
from ultralytics import YOLO
from flask import Flask, jsonify, render_template_string, send_file
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image as RLImage
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# ── CONFIGURATION ─────────────────────────────────────────────────

ESP32_CAM_URL      = "http://192.168.137.140:81/stream"
MODEL_PATH         = "yolov8n.pt"
PERSON_CLASS_ID    = 0
MOVEMENT_THRESHOLD = 20
WORKING_THRESHOLD  = 5
QUEUE_LENGTH       = 5
WINDOW_DURATION    = 5
HISTORY_MINUTES    = 60
REPORTS_DIR        = "shift_reports"

os.makedirs(REPORTS_DIR, exist_ok=True)

# ── SHARED STATE ──────────────────────────────────────────────────

state_lock = threading.Lock()

shared = {
    "status":          "Initializing",
    "efficiency":      0.0,
    "active_secs":     0.0,
    "idle_secs":       0.0,
    "absent_secs":     0.0,
    "peak_efficiency": 0.0,
    "peak_time":       None,
    "longest_idle":    0.0,
    "current_idle":    0.0,
    "shift_start":     datetime.now(),
    "head_count":      0,
    "history":         deque(maxlen=HISTORY_MINUTES * (60 // WINDOW_DURATION)),
}

# ── ACTIVITY SCORING ──────────────────────────────────────────────
#
# Three states replace the old two:
#   Worker Active  — large movement (>MOVEMENT_THRESHOLD px)  → score 10
#   Worker Working — small movement, still engaged             → score 7
#   Worker Idle    — essentially stationary                    → score 2
#   No Person      — nobody in frame                          → score 0
#
# "Moving" (old first-detection bug) is gone — first detection
# defaults to Worker Working instead.

ACTIVITY_SCORES = {
    "Worker Active":  10,
    "Worker Working": 7,
    "Worker Idle":    2,
    "No Person":      0,
}

def get_centroid(box):
    x1, y1, x2, y2 = box
    return int((x1 + x2) / 2), int((y1 + y2) / 2)

def classify_status(dist):
    if dist is None:
        return "Worker Working"
    if dist > MOVEMENT_THRESHOLD:
        return "Worker Active"
    if dist > WORKING_THRESHOLD:
        return "Worker Working"
    return "Worker Idle"

def fmt_duration(secs):
    secs = int(secs)
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"

# ── VISION THREAD ─────────────────────────────────────────────────

def vision_thread():
    model = YOLO(MODEL_PATH)
    cap   = cv2.VideoCapture(ESP32_CAM_URL)

    positions    = deque(maxlen=QUEUE_LENGTH)
    activity_buf = []
    window_start = time.time()
    last_tick    = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue

        now     = time.time()
        elapsed = now - last_tick
        last_tick = now

        results    = model(frame, verbose=False)
        status     = "No Person"
        head_count = 0

        for r in results[0].boxes:
            if int(r.cls[0]) == PERSON_CLASS_ID:
                head_count += 1
                if head_count == 1:
                    box      = r.xyxy[0].tolist()
                    centroid = get_centroid(box)
                    dist     = None
                    if positions:
                        px, py = positions[-1]
                        dist   = float(np.hypot(centroid[0] - px, centroid[1] - py))
                    status = classify_status(dist)
                    positions.append(centroid)

        activity_buf.append(ACTIVITY_SCORES[status])

        with state_lock:
            shared["status"]     = status
            shared["head_count"] = head_count
            if status == "No Person":
                shared["absent_secs"]  += elapsed
                shared["current_idle"]  = 0
            elif status == "Worker Idle":
                shared["idle_secs"]    += elapsed
                shared["current_idle"] += elapsed
                if shared["current_idle"] > shared["longest_idle"]:
                    shared["longest_idle"] = shared["current_idle"]
            else:
                shared["active_secs"]  += elapsed
                shared["current_idle"]  = 0

        if now - window_start >= WINDOW_DURATION:
            avg = float(np.mean(activity_buf)) if activity_buf else 0.0
            eff = round((avg / 10.0) * 100, 1)
            ts  = datetime.now()
            with state_lock:
                shared["efficiency"] = eff
                shared["history"].append({"t": ts, "e": eff})
                if eff > shared["peak_efficiency"]:
                    shared["peak_efficiency"] = eff
                    shared["peak_time"]        = ts
            activity_buf.clear()
            window_start = now

        status_colors = {
            "Worker Active":  (0, 255, 100),
            "Worker Working": (0, 200, 255),
            "Worker Idle":    (0, 140, 255),
            "No Person":      (80, 80, 80),
        }
        with state_lock:
            eff_disp = shared["efficiency"]

        cv2.putText(frame, f"Status: {status}", (10, 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    status_colors.get(status, (200, 200, 200)), 2)
        cv2.putText(frame, f"Efficiency: {eff_disp:.1f}%", (10, 68),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.putText(frame, f"Workers: {head_count}", (10, 102),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)

        cv2.imshow("Workplace Monitor", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

# ── CHART HELPERS ─────────────────────────────────────────────────

def make_efficiency_chart(history, width_cm=16, height_cm=6):
    if not history:
        return None
    times = [h["t"] for h in history]
    effs  = [h["e"] for h in history]

    fig, ax = plt.subplots(figsize=(width_cm / 2.54, height_cm / 2.54))
    ax.fill_between(times, effs, alpha=0.15, color="#1D9E75")
    ax.plot(times, effs, color="#1D9E75", linewidth=1.8)
    ax.axhline(y=float(np.mean(effs)), color="#BA7517", linewidth=1,
               linestyle="--", label=f"Avg {float(np.mean(effs)):.1f}%")
    ax.set_ylim(0, 105)
    ax.set_ylabel("Efficiency %", fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=30, ha="right")
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf

def make_pie_chart(active, idle, absent, width_cm=7, height_cm=7):
    total = active + idle + absent
    if total == 0:
        return None
    data   = [(active, "Active", "#1D9E75"),
              (idle,   "Idle",   "#EF9F27"),
              (absent, "Absent", "#888780")]
    sizes  = [d[0] for d in data if d[0] > 0]
    labels = [d[1] for d in data if d[0] > 0]
    clrs   = [d[2] for d in data if d[0] > 0]

    fig, ax = plt.subplots(figsize=(width_cm / 2.54, height_cm / 2.54))
    ax.pie(sizes, labels=labels, autopct="%1.0f%%", colors=clrs,
           startangle=140, textprops={"fontsize": 8})
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf

# ── PDF REPORT ────────────────────────────────────────────────────

def generate_pdf_report():
    with state_lock:
        snap = {k: (list(v) if isinstance(v, deque) else v)
                for k, v in shared.items()}

    now       = datetime.now()
    shift_dur = (now - snap["shift_start"]).total_seconds()
    total     = max(snap["active_secs"] + snap["idle_secs"] + snap["absent_secs"], 1)

    filename  = now.strftime("shift_%Y-%m-%d_%H-%M-%S.pdf")
    filepath  = os.path.join(REPORTS_DIR, filename)

    doc = SimpleDocTemplate(
        filepath, pagesize=A4,
        topMargin=2*cm, bottomMargin=2*cm,
        leftMargin=2*cm, rightMargin=2*cm
    )

    styles = getSampleStyleSheet()

    def sty(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    title_sty   = sty("T", fontSize=20, fontName="Helvetica-Bold",
                       textColor=colors.HexColor("#0F6E56"), spaceAfter=14)
    sub_sty     = sty("S", fontSize=10, textColor=colors.HexColor("#5F5E5A"),
                       spaceAfter=2)
    section_sty = sty("H", fontSize=12, fontName="Helvetica-Bold",
                       textColor=colors.HexColor("#085041"),
                       spaceBefore=14, spaceAfter=6)
    body_sty    = sty("B", fontSize=9, textColor=colors.HexColor("#3d3d3a"),
                       leading=14)
    cell_sty    = sty("C", fontSize=9, textColor=colors.HexColor("#3d3d3a"))
    cell_bold   = sty("CB", fontSize=9, fontName="Helvetica-Bold",
                       textColor=colors.HexColor("#0F6E56"))
    footer_sty  = sty("F", fontSize=7, textColor=colors.HexColor("#888780"),
                       alignment=TA_CENTER, spaceBefore=4)

    story = []

    # Header
    story.append(Paragraph("Workplace Efficiency Report", title_sty))
    peak_str = snap["peak_time"].strftime("%H:%M") if snap["peak_time"] else "—"
    story.append(Paragraph(
        f"Generated: {now.strftime('%d %B %Y, %H:%M')}  &nbsp;|&nbsp; "
        f"Shift started: {snap['shift_start'].strftime('%H:%M')}  &nbsp;|&nbsp; "
        f"Duration: {fmt_duration(shift_dur)}",
        sub_sty
    ))
    story.append(HRFlowable(width="100%", thickness=1.5,
                             color=colors.HexColor("#1D9E75"), spaceAfter=14))

    # KPI table
    story.append(Paragraph("Shift summary", section_sty))
    rows = [
        ["Metric", "Value"],
        ["Current efficiency",      f"{snap['efficiency']:.1f}%"],
        ["Peak efficiency",          f"{snap['peak_efficiency']:.1f}%  (at {peak_str})"],
        ["Total active time",        fmt_duration(snap["active_secs"])],
        ["Total idle time",          fmt_duration(snap["idle_secs"])],
        ["Total absent / no-show",   fmt_duration(snap["absent_secs"])],
        ["Longest idle streak",      fmt_duration(snap["longest_idle"])],
        ["Active share of shift",    f"{snap['active_secs'] / total * 100:.1f}%"],
    ]
    tbl_data = []
    for i, row in enumerate(rows):
        s = cell_bold if i == 0 else (cell_bold if i % 2 == 0 else cell_sty)
        tbl_data.append([Paragraph(row[0], cell_sty if i > 0 else cell_bold),
                         Paragraph(row[1], s)])

    kpi_tbl = Table(tbl_data, colWidths=[10*cm, 7*cm])
    kpi_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  colors.HexColor("#E1F5EE")),
        ("GRID",         (0, 0), (-1, -1), 0.4, colors.HexColor("#9FE1CB")),
        ("ROWBACKGROUNDS",(0,1), (-1, -1),
         [colors.white, colors.HexColor("#F8FDFB")]),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(kpi_tbl)
    story.append(Spacer(1, 0.4*cm))

    # Efficiency trend chart
    history = snap["history"]
    if history:
        story.append(Paragraph("Efficiency over time", section_sty))
        buf = make_efficiency_chart(history)
        if buf:
            story.append(RLImage(buf, width=16*cm, height=6*cm))
            story.append(Spacer(1, 0.3*cm))

    # Time breakdown — pie + insight text side by side
    story.append(Paragraph("Time breakdown", section_sty))

    active_pct = snap["active_secs"] / total * 100
    idle_pct   = snap["idle_secs"]   / total * 100
    absent_pct = snap["absent_secs"] / total * 100

    if active_pct >= 70:
        rating, rcol = "Good", "#1D9E75"
    elif active_pct >= 50:
        rating, rcol = "Average", "#BA7517"
    else:
        rating, rcol = "Needs attention", "#A32D2D"

    insight_items = [
        Paragraph(
            f'<font color="#1D9E75">&#9679;</font>  '
            f'<b>Active:</b> {active_pct:.1f}%  ({fmt_duration(snap["active_secs"])})',
            body_sty),
        Spacer(1, 6),
        Paragraph(
            f'<font color="#EF9F27">&#9679;</font>  '
            f'<b>Idle:</b> {idle_pct:.1f}%  ({fmt_duration(snap["idle_secs"])})',
            body_sty),
        Spacer(1, 6),
        Paragraph(
            f'<font color="#888780">&#9679;</font>  '
            f'<b>Absent:</b> {absent_pct:.1f}%  ({fmt_duration(snap["absent_secs"])})',
            body_sty),
        Spacer(1, 12),
        Paragraph(
            f'Overall rating: <font color="{rcol}"><b>{rating}</b></font>',
            body_sty),
    ]

    pie_buf = make_pie_chart(
        snap["active_secs"], snap["idle_secs"], snap["absent_secs"])
    if pie_buf:
        side = Table([[RLImage(pie_buf, width=7*cm, height=7*cm), insight_items]],
                     colWidths=[7.5*cm, 9*cm])
        side.setStyle(TableStyle([
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING",   (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
        ]))
        story.append(side)
    else:
        for item in insight_items:
            story.append(item)

    # Footer
    story.append(Spacer(1, 0.6*cm))
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=colors.HexColor("#9FE1CB")))
    story.append(Paragraph(
        f"Workplace Monitoring System  ·  Saved: {filepath}", footer_sty))

    doc.build(story)
    return filepath

# ── FLASK APP ─────────────────────────────────────────────────────

app = Flask(__name__)

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Workplace Monitor</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',sans-serif;background:#0d1117;color:#e2e8f0;min-height:100vh;padding:24px}
  h1{font-size:20px;font-weight:600;margin-bottom:4px}
  .sub{font-size:12px;color:#718096;margin-bottom:20px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
  .card{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:16px}
  .card .lbl{font-size:11px;color:#718096;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}
  .card .val{font-size:26px;font-weight:600}
  .card .hint{font-size:11px;color:#718096;margin-top:4px}
  .green{color:#1D9E75}.amber{color:#EF9F27}.red{color:#E24B4A}.gray{color:#718096}
  .pill{display:inline-block;padding:4px 12px;border-radius:20px;font-size:13px;font-weight:500}
  .pa{background:#0F6E56;color:#9FE1CB}
  .pw{background:#154060;color:#85B7EB}
  .pi{background:#4a3a10;color:#FAC775}
  .pn{background:#2a2a2a;color:#888780}
  .section{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:16px;margin-bottom:16px}
  .section h2{font-size:11px;font-weight:600;color:#a0aec0;margin-bottom:12px;text-transform:uppercase;letter-spacing:.06em}
  canvas{width:100%!important}
  .bar-wrap{display:flex;height:18px;border-radius:6px;overflow:hidden;margin-bottom:8px}
  .seg{transition:width .6s ease}
  .bar-labels{display:flex;gap:16px;font-size:11px;color:#718096}
  .dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px}
  .btn{background:#0F6E56;color:#E1F5EE;border:none;padding:10px 20px;border-radius:8px;font-size:13px;font-weight:500;cursor:pointer}
  .btn:hover{background:#1D9E75}
  .btn:disabled{background:#21262d;color:#718096;cursor:not-allowed}
  #rmsg{font-size:12px;color:#1D9E75;margin-top:8px;min-height:18px}
</style>
</head>
<body>
<h1>Workplace Monitor</h1>
<div class="sub" id="shift-info">Loading...</div>

<div class="grid">
  <div class="card">
    <div class="lbl">Status</div>
    <div id="status-pill"><span class="pill pn">Initializing</span></div>
  </div>
  <div class="card">
    <div class="lbl">Efficiency</div>
    <div class="val" id="eff-val">—</div>
    <div class="hint">current window</div>
  </div>
  <div class="card">
    <div class="lbl">Peak efficiency</div>
    <div class="val green" id="peak-val">—</div>
    <div class="hint" id="peak-time">—</div>
  </div>
  <div class="card">
    <div class="lbl">Head count</div>
    <div class="val" id="hc-val">—</div>
    <div class="hint">workers in frame</div>
  </div>
  <div class="card">
    <div class="lbl">Longest idle</div>
    <div class="val amber" id="idle-val">—</div>
    <div class="hint">streak this shift</div>
  </div>
</div>

<div class="section">
  <h2>Time breakdown</h2>
  <div class="bar-wrap">
    <div class="seg" style="background:#1D9E75" id="b-active"></div>
    <div class="seg" style="background:#EF9F27" id="b-idle"></div>
    <div class="seg" style="background:#444441" id="b-absent"></div>
  </div>
  <div class="bar-labels">
    <span><span class="dot" style="background:#1D9E75"></span>Active <span id="l-active">—</span></span>
    <span><span class="dot" style="background:#EF9F27"></span>Idle <span id="l-idle">—</span></span>
    <span><span class="dot" style="background:#444441"></span>Absent <span id="l-absent">—</span></span>
  </div>
</div>

<div class="section">
  <h2>Efficiency trend — last 60 min</h2>
  <canvas id="chart" height="80"></canvas>
</div>

<div class="section">
  <h2>Shift report</h2>
  <button class="btn" id="rbtn" onclick="genReport()">Generate PDF report</button>
  <div id="rmsg"></div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
function dur(s){
  s=Math.floor(s);
  const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=s%60;
  return h?(h+'h '+String(m).padStart(2,'0')+'m'):(m+'m '+String(sec).padStart(2,'0')+'s');
}
function pillCls(s){
  if(s==='Worker Active')  return 'pill pa';
  if(s==='Worker Working') return 'pill pw';
  if(s==='Worker Idle')    return 'pill pi';
  return 'pill pn';
}
function effCls(e){ return e>=70?'val green':e>=40?'val amber':'val red'; }

const ctx=document.getElementById('chart').getContext('2d');
const chart=new Chart(ctx,{
  type:'line',
  data:{labels:[],datasets:[{data:[],borderColor:'#1D9E75',backgroundColor:'rgba(29,158,117,0.1)',
    borderWidth:2,pointRadius:0,fill:true,tension:0.3}]},
  options:{animation:false,responsive:true,
    plugins:{legend:{display:false}},
    scales:{
      x:{ticks:{color:'#718096',maxTicksLimit:8,font:{size:10}},grid:{color:'#21262d'}},
      y:{min:0,max:100,ticks:{color:'#718096',font:{size:10},callback:v=>v+'%'},grid:{color:'#21262d'}}
    }}
});

async function poll(){
  try{
    const d=await(await fetch('/api/state')).json();
    document.getElementById('status-pill').innerHTML=
      '<span class="'+pillCls(d.status)+'">'+d.status+'</span>';
    const ev=document.getElementById('eff-val');
    ev.textContent=d.efficiency.toFixed(1)+'%'; ev.className=effCls(d.efficiency);
    document.getElementById('peak-val').textContent=d.peak_efficiency.toFixed(1)+'%';
    document.getElementById('peak-time').textContent=d.peak_time?'at '+d.peak_time:'—';
    document.getElementById('hc-val').textContent=d.head_count;
    document.getElementById('idle-val').textContent=dur(d.longest_idle);
    document.getElementById('shift-info').textContent=
      'Shift started '+d.shift_start+' · Duration '+dur(d.shift_dur);
    const tot=d.active_secs+d.idle_secs+d.absent_secs||1;
    document.getElementById('b-active').style.width=(d.active_secs/tot*100).toFixed(1)+'%';
    document.getElementById('b-idle').style.width=(d.idle_secs/tot*100).toFixed(1)+'%';
    document.getElementById('b-absent').style.width=(d.absent_secs/tot*100).toFixed(1)+'%';
    document.getElementById('l-active').textContent=dur(d.active_secs);
    document.getElementById('l-idle').textContent=dur(d.idle_secs);
    document.getElementById('l-absent').textContent=dur(d.absent_secs);
    if(d.history.length){
      chart.data.labels=d.history.map(h=>h.t);
      chart.data.datasets[0].data=d.history.map(h=>h.e);
      chart.update('none');
    }
  }catch(e){}
}

async function genReport(){
  const btn=document.getElementById('rbtn');
  const msg=document.getElementById('rmsg');
  btn.disabled=true; btn.textContent='Generating...'; msg.textContent='';
  try{
    const res=await fetch('/api/report',{method:'POST'});
    if(!res.ok){
      const e=await res.json();
      msg.style.color='#E24B4A';
      msg.textContent='Error: '+(e.error||res.statusText);
    } else {
      const blob=await res.blob();
      const cd=res.headers.get('Content-Disposition')||'';
      const match=cd.match(/filename="?([^"]+)"?/);
      const fname=match?match[1]:'shift_report.pdf';
      const url=URL.createObjectURL(blob);
      const a=document.createElement('a');
      a.href=url; a.download=fname; a.click();
      URL.revokeObjectURL(url);
      msg.style.color='#1D9E75';
      msg.textContent='Download started: '+fname;
    }
  }catch(e){msg.style.color='#E24B4A';msg.textContent='Request failed.';}
  btn.disabled=false; btn.textContent='Generate PDF report';
}

poll(); setInterval(poll,2000);
</script>
</body>
</html>"""


@app.route("/")
def dashboard():
    return DASHBOARD_HTML


@app.route("/api/state")
def api_state():
    with state_lock:
        now      = datetime.now()
        dur_secs = (now - shared["shift_start"]).total_seconds()
        hist     = [{"t": h["t"].strftime("%H:%M"), "e": h["e"]}
                    for h in shared["history"]]
        return jsonify({
            "status":          shared["status"],
            "efficiency":      round(shared["efficiency"], 1),
            "active_secs":     round(shared["active_secs"], 1),
            "idle_secs":       round(shared["idle_secs"], 1),
            "absent_secs":     round(shared["absent_secs"], 1),
            "peak_efficiency": round(shared["peak_efficiency"], 1),
            "peak_time":       (shared["peak_time"].strftime("%H:%M")
                                if shared["peak_time"] else None),
            "longest_idle":    round(shared["longest_idle"], 1),
            "head_count":      shared["head_count"],
            "shift_start":     shared["shift_start"].strftime("%H:%M"),
            "shift_dur":       round(dur_secs),
            "history":         hist,
        })


@app.route("/api/report", methods=["POST"])
def api_report():
    try:
        path     = generate_pdf_report()
        filename = os.path.basename(path)
        return send_file(
            path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)}), 500


def flask_thread():
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=5002, debug=False, use_reloader=False)


# ── MAIN ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("[INIT] Starting workplace monitor...")
    print("[INIT] Dashboard  →  http://localhost:5000")
    print(f"[INIT] Reports    →  ./{REPORTS_DIR}/")
    threading.Thread(target=vision_thread, daemon=True).start()
    threading.Thread(target=flask_thread,  daemon=True).start()
    while True:
        time.sleep(1)
