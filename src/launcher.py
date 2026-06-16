"""
Industrial Vehicle Safety System — Launcher
============================================
Run:  python launcher.py
Open: http://localhost:5000

Folder layout (all in same directory):
  launcher.py
  forklift_safety.py
  workplace_monitor.py
"""

import subprocess
import sys
import os
import threading
import time
import json
import urllib.request
import urllib.error
from datetime import datetime
from collections import deque
from flask import Flask, jsonify, send_file

app    = Flask(__name__)
LOCK   = threading.Lock()
PROCS  = {"safety": None, "efficiency": None}
BASE   = os.path.dirname(os.path.abspath(__file__))
SCRIPT = {
    "safety":     os.path.join(BASE, "forklift_safety.py"),
    "efficiency": os.path.join(BASE, "workplace_monitor.py"),
}

# ── PROCESS HELPERS ───────────────────────────────────────────────

def is_running(name):
    with LOCK:
        p = PROCS[name]
        return p is not None and p.poll() is None

def launch(name):
    with LOCK:
        p = PROCS[name]
        if p is not None and p.poll() is None:
            return False, "already running"
        if not os.path.exists(SCRIPT[name]):
            return False, f"{os.path.basename(SCRIPT[name])} not found"
        PROCS[name] = subprocess.Popen([sys.executable, SCRIPT[name]], cwd=BASE)
        return True, "launched"

def stop(name):
    with LOCK:
        p = PROCS[name]
        if p is None or p.poll() is not None:
            PROCS[name] = None
            return False, "not running"
        p.terminate()
        try:
            p.wait(timeout=4)
        except subprocess.TimeoutExpired:
            p.kill()
        PROCS[name] = None
        return True, "stopped"

# ── HOME PAGE ─────────────────────────────────────────────────────

HOME = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Industrial Vehicle Safety System</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{
  font-family:'Segoe UI',sans-serif;
  background:#0d1117;
  color:#e2e8f0;
  min-height:100vh;
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:center;
  padding:48px 24px;
}
.header{text-align:center;margin-bottom:56px}
.eyebrow{
  font-size:10px;letter-spacing:.2em;text-transform:uppercase;
  color:#444441;margin-bottom:16px;
}
h1{
  font-size:28px;font-weight:700;color:#e2e8f0;
  line-height:1.3;margin-bottom:12px;max-width:580px;
}
.tagline{font-size:13px;color:#718096;line-height:1.8;max-width:500px;margin:0 auto}

.grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;width:100%;max-width:780px;margin-bottom:40px}

.card{
  background:#161b22;border:1px solid #21262d;border-radius:20px;
  padding:38px 28px 32px;
  display:flex;flex-direction:column;align-items:center;
  transition:border-color .2s,transform .15s;
}
.card:hover{border-color:#30363d;transform:translateY(-2px)}

.icon-wrap{
  width:100px;height:100px;border-radius:24px;
  display:flex;align-items:center;justify-content:center;
  margin-bottom:22px;
}
.icon-red  {background:#130808;border:2px solid #3d1515}
.icon-teal {background:#03180f;border:2px solid #074030}

.card-title{font-size:16px;font-weight:700;color:#e2e8f0;text-align:center;margin-bottom:10px}
.card-desc {font-size:12px;color:#718096;text-align:center;line-height:1.7;margin-bottom:24px;min-height:56px}

.status-row{display:flex;align-items:center;gap:8px;margin-bottom:20px}
.dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.dot-idle   {background:#444441}
.dot-running{background:#1D9E75;animation:blink 1.6s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
.status-text{font-size:12px;font-weight:500}
.status-idle   {color:#718096}
.status-running{color:#1D9E75}

.btn-go{
  display:block;width:100%;padding:14px;
  border-radius:12px;border:none;
  font-size:14px;font-weight:600;cursor:pointer;
  text-align:center;text-decoration:none;
  transition:background .2s,transform .1s;
}
.btn-go:active{transform:scale(.97)}
.btn-red  {background:#7f1d1d;color:#fecaca}
.btn-red:hover{background:#991b1b}
.btn-teal {background:#064e3b;color:#a7f3d0}
.btn-teal:hover{background:#065f46}

.footer{font-size:11px;color:#444441;text-align:center;line-height:1.8}
.footer code{
  background:#161b22;border:1px solid #21262d;
  border-radius:4px;padding:1px 6px;font-size:10px;color:#718096
}
</style>
</head>
<body>

<div class="header">
  <div class="eyebrow">AI-Powered Industrial Monitoring</div>
  <h1>Industrial Vehicle Safety System<br>for Workplace &amp; Public Safety</h1>
  <p class="tagline">
    Real-time computer vision and intelligent sensor fusion for collision prevention,
    hazard detection, and workforce productivity monitoring in industrial environments.
  </p>
</div>

<div class="grid">

  <div class="card">
    <div class="icon-wrap icon-red">
      <svg width="54" height="54" viewBox="0 0 54 54" fill="none">
        <path d="M27 7L49 43H5L27 7Z" fill="#1a0808" stroke="#dc2626" stroke-width="1.8" stroke-linejoin="round"/>
        <line x1="27" y1="20" x2="27" y2="32" stroke="#dc2626" stroke-width="2.5" stroke-linecap="round"/>
        <circle cx="27" cy="37" r="2.2" fill="#dc2626"/>
      </svg>
    </div>
    <div class="card-title">Collision Avoidance &amp;<br>Hazard Detection</div>
    <div class="card-desc">
      Real-time obstacle detection with zone-based risk classification,
      instant voice alerts, and a live safety event log.
    </div>
    <div class="status-row">
      <div class="dot" id="dot-safety"></div>
      <span class="status-text" id="txt-safety">Inactive</span>
    </div>
    <a class="btn-go btn-red" href="/safety">Open Safety Dashboard</a>
  </div>

  <div class="card">
    <div class="icon-wrap icon-teal">
      <svg width="54" height="54" viewBox="0 0 54 54" fill="none">
        <rect x="5"  y="34" width="9" height="15" rx="2.5" fill="#065f46"/>
        <rect x="18" y="26" width="9" height="23" rx="2.5" fill="#047857"/>
        <rect x="31" y="18" width="9" height="31" rx="2.5" fill="#059669"/>
        <rect x="44" y="11" width="9" height="38" rx="2.5" fill="#10b981"/>
        <polyline points="9.5,32 22.5,24 35.5,16 48.5,9"
          stroke="#6ee7b7" stroke-width="2.2" fill="none"
          stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="48.5" cy="9" r="3" fill="#6ee7b7"/>
      </svg>
    </div>
    <div class="card-title">Workforce Productivity &amp;<br>Efficiency Monitoring</div>
    <div class="card-desc">
      Activity classification, shift-based efficiency scoring,
      idle time tracking, and automated PDF shift reports.
    </div>
    <div class="status-row">
      <div class="dot" id="dot-efficiency"></div>
      <span class="status-text" id="txt-efficiency">Inactive</span>
    </div>
    <a class="btn-go btn-teal" href="/efficiency">Open Efficiency Dashboard</a>
  </div>

</div>

<div class="footer">
  Safety module: <code>forklift_safety.py</code> &nbsp;·&nbsp;
  Efficiency module: <code>workplace_monitor.py</code><br>
  Clicking "Open Dashboard" navigates to that module — launch the camera from inside the dashboard.
</div>

<script>
async function poll(){
  try{
    const d = await fetch('/api/status').then(r=>r.json());
    for(const name of ['safety','efficiency']){
      const running = d[name];
      const dot = document.getElementById('dot-'+name);
      const txt = document.getElementById('txt-'+name);
      dot.className = 'dot ' + (running ? 'dot-running' : 'dot-idle');
      txt.className = 'status-text ' + (running ? 'status-running' : 'status-idle');
      txt.textContent = running ? 'Running' : 'Inactive';
    }
  }catch(e){}
}
poll(); setInterval(poll, 2500);
</script>
</body>
</html>"""

# ── SAFETY DASHBOARD ──────────────────────────────────────────────

SAFETY_DASH = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Safety Monitor — Industrial Vehicle Safety System</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',sans-serif;background:#0d1117;color:#e2e8f0;min-height:100vh;padding:20px 24px}

.topbar{display:flex;align-items:center;gap:14px;margin-bottom:20px;flex-wrap:wrap}
.back{
  font-size:12px;color:#718096;text-decoration:none;
  padding:6px 12px;border:1px solid #21262d;border-radius:8px;
  transition:color .15s,border-color .15s;flex-shrink:0;
}
.back:hover{color:#e2e8f0;border-color:#444}
.page-title{font-size:18px;font-weight:700;color:#e2e8f0}
.page-sub{font-size:12px;color:#718096;margin-left:auto}

.risk-banner{
  border-radius:14px;padding:18px 22px;margin-bottom:18px;
  display:flex;align-items:center;gap:16px;
  transition:background .3s;
}
.risk-banner .risk-icon{font-size:28px;line-height:1}
.risk-banner .risk-label{font-size:22px;font-weight:800;letter-spacing:.02em}
.risk-banner .risk-detected{font-size:13px;opacity:.85;margin-top:3px}
.risk-SAFE    {background:#064e3b}
.risk-CAUTION {background:#451a03}
.risk-WARNING {background:#431407}
.risk-DANGER  {background:#450a0a}

.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:16px}
.kpi{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:14px}
.kpi .lbl{font-size:10px;color:#718096;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.kpi .val{font-size:22px;font-weight:700}
.kpi .hint{font-size:11px;color:#718096;margin-top:3px}
.c-red{color:#f87171}.c-amber{color:#fbbf24}.c-green{color:#34d399}.c-gray{color:#718096}

.section{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:16px;margin-bottom:14px}
.section-title{font-size:10px;font-weight:700;color:#a0aec0;text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px}

.log-box{
  height:240px;overflow-y:auto;font-size:11px;font-family:'Consolas',monospace;
  background:#0d1117;border-radius:8px;padding:10px;
}
.log-box::-webkit-scrollbar{width:4px}
.log-box::-webkit-scrollbar-thumb{background:#21262d;border-radius:4px}
.log-DANGER {color:#f87171;background:#1c0a0a;padding:2px 6px;border-radius:3px;margin-bottom:2px;display:block}
.log-WARNING{color:#fbbf24;background:#1c1200;padding:2px 6px;border-radius:3px;margin-bottom:2px;display:block}
.log-CAUTION{color:#f59e0b;background:#1c1500;padding:2px 6px;border-radius:3px;margin-bottom:2px;display:block}
.log-INFO   {color:#60a5fa;padding:2px 6px;margin-bottom:2px;display:block}

.btn-row{display:flex;gap:10px;flex-wrap:wrap}
.btn{
  padding:11px 22px;border-radius:10px;border:none;
  font-size:13px;font-weight:600;cursor:pointer;
  transition:background .2s,transform .1s;flex-shrink:0;
}
.btn:active{transform:scale(.97)}
.btn:disabled{opacity:.45;cursor:not-allowed;transform:none}
.btn-launch{background:#7f1d1d;color:#fecaca}
.btn-launch:hover:not(:disabled){background:#991b1b}
.btn-stop  {background:#21262d;color:#a0aec0;border:1px solid #30363d}
.btn-stop:hover:not(:disabled){background:#30363d;color:#e2e8f0}
.cam-note{font-size:12px;color:#718096;margin-top:8px;line-height:1.6}
</style>
</head>
<body>

<div class="topbar">
  <a class="back" href="/">&#8592; Home</a>
  <span class="page-title">Collision Avoidance &amp; Hazard Detection</span>
  <span class="page-sub" id="session-info">—</span>
</div>

<div class="risk-banner risk-SAFE" id="risk-banner">
  <div class="risk-icon" id="risk-icon">●</div>
  <div>
    <div class="risk-label" id="risk-label">SAFE</div>
    <div class="risk-detected" id="risk-detected">No hazards detected</div>
  </div>
</div>

<div class="kpi-grid">
  <div class="kpi">
    <div class="lbl">DANGER events</div>
    <div class="val c-red" id="k-danger">0</div>
    <div class="hint">this session</div>
  </div>
  <div class="kpi">
    <div class="lbl">WARNING events</div>
    <div class="val c-amber" id="k-warning">0</div>
    <div class="hint">this session</div>
  </div>
  <div class="kpi">
    <div class="lbl">CAUTION events</div>
    <div class="val" id="k-caution" style="color:#f59e0b">0</div>
    <div class="hint">this session</div>
  </div>
  <div class="kpi">
    <div class="lbl">Total alerts</div>
    <div class="val c-gray" id="k-total">0</div>
    <div class="hint">combined</div>
  </div>
</div>

<div class="section">
  <div class="section-title">Live event log</div>
  <div class="log-box" id="log-box"></div>
</div>

<div class="section">
  <div class="section-title">Camera &amp; detection</div>
  <div class="btn-row">
    <button class="btn btn-launch" id="btn-launch" onclick="launchModule()">
      Launch Camera &amp; Detection
    </button>
    <button class="btn btn-stop" id="btn-stop" onclick="stopModule()" disabled>
      Stop
    </button>
  </div>
  <p class="cam-note" id="cam-note">
    Clicking Launch opens the Tkinter safety dashboard and the live annotated camera feed.
    Voice alerts will activate when hazards are detected.
  </p>
</div>

<script>
const RISK_CFG = {
  SAFE:    {cls:'risk-SAFE',    icon:'●',  label:'SAFE'},
  CAUTION: {cls:'risk-CAUTION', icon:'⚠',  label:'CAUTION'},
  WARNING: {cls:'risk-WARNING', icon:'⚠',  label:'WARNING'},
  DANGER:  {cls:'risk-DANGER',  icon:'🔴', label:'DANGER'},
};

let safetyLog = [];

async function pollSafety(){
  try{
    const d = await fetch('/api/safety/state').then(r=>r.json());
    const cfg = RISK_CFG[d.risk] || RISK_CFG.SAFE;
    const banner = document.getElementById('risk-banner');
    banner.className = 'risk-banner ' + cfg.cls;
    document.getElementById('risk-icon').textContent    = cfg.icon;
    document.getElementById('risk-label').textContent   = cfg.label;
    document.getElementById('risk-detected').textContent =
      d.detected.length ? 'Detected: ' + d.detected.join(', ') : 'No hazards detected';
    document.getElementById('k-danger').textContent  = d.danger;
    document.getElementById('k-warning').textContent = d.warning;
    document.getElementById('k-caution').textContent = d.caution;
    document.getElementById('k-total').textContent   = d.danger + d.warning + d.caution;
    document.getElementById('session-info').textContent = 'Session started ' + d.session_start;

    const box   = document.getElementById('log-box');
    const atBot = box.scrollHeight - box.scrollTop <= box.clientHeight + 24;
    box.innerHTML = d.log.slice(-80).map(e =>
      '<span class="log-'+e.level+'">['+e.ts+'] '+e.msg+'</span>'
    ).join('');
    if(atBot) box.scrollTop = box.scrollHeight;
  }catch(e){}
}

async function pollStatus(){
  try{
    const d = await fetch('/api/status').then(r=>r.json());
    const running = d.safety;
    document.getElementById('btn-launch').disabled = running;
    document.getElementById('btn-stop').disabled   = !running;
    document.getElementById('cam-note').textContent = running
      ? 'Safety system is active. Camera and detection are running.'
      : 'Clicking Launch opens the Tkinter safety dashboard and the live annotated camera feed.';
  }catch(e){}
}

async function launchModule(){
  document.getElementById('btn-launch').disabled = true;
  await fetch('/api/launch/safety', {method:'POST'});
  setTimeout(pollStatus, 800);
}
async function stopModule(){
  document.getElementById('btn-stop').disabled = true;
  await fetch('/api/stop/safety', {method:'POST'});
  setTimeout(pollStatus, 800);
}

pollSafety(); pollStatus();
setInterval(pollSafety, 2000);
setInterval(pollStatus, 2500);
</script>
</body>
</html>"""

# ── EFFICIENCY DASHBOARD ──────────────────────────────────────────

EFFICIENCY_DASH = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Efficiency Monitor — Industrial Vehicle Safety System</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',sans-serif;background:#0d1117;color:#e2e8f0;min-height:100vh;padding:20px 24px}

.topbar{display:flex;align-items:center;gap:14px;margin-bottom:20px;flex-wrap:wrap}
.back{
  font-size:12px;color:#718096;text-decoration:none;
  padding:6px 12px;border:1px solid #21262d;border-radius:8px;
  transition:color .15s,border-color .15s;flex-shrink:0;
}
.back:hover{color:#e2e8f0;border-color:#444}
.page-title{font-size:18px;font-weight:700;color:#e2e8f0}
.page-sub{font-size:12px;color:#718096;margin-left:auto}

.eff-banner{
  background:#064e3b;border-radius:14px;padding:18px 22px;
  margin-bottom:18px;display:flex;align-items:center;gap:20px;
}
.eff-number{font-size:42px;font-weight:800;color:#34d399;line-height:1}
.eff-unit  {font-size:18px;font-weight:600;color:#6ee7b7;margin-top:6px}
.eff-status{font-size:14px;color:#a7f3d0;margin-top:4px}
.eff-sub   {font-size:12px;color:#6ee7b7;margin-top:2px;opacity:.8}

.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:16px}
.kpi{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:14px}
.kpi .lbl{font-size:10px;color:#718096;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.kpi .val{font-size:22px;font-weight:700}
.kpi .hint{font-size:11px;color:#718096;margin-top:3px}
.c-green{color:#34d399}.c-amber{color:#fbbf24}.c-red{color:#f87171}.c-gray{color:#718096}

.section{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:16px;margin-bottom:14px}
.section-title{font-size:10px;font-weight:700;color:#a0aec0;text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px}

.bar-wrap{display:flex;height:18px;border-radius:6px;overflow:hidden;margin-bottom:8px;background:#0d1117}
.seg{transition:width .6s ease}
.bar-labels{display:flex;gap:18px;font-size:11px;color:#718096;flex-wrap:wrap}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px}

canvas{width:100%!important}

.pill{display:inline-block;padding:4px 12px;border-radius:16px;font-size:12px;font-weight:600}
.pa{background:#064e3b;color:#6ee7b7}
.pw{background:#1e3a5f;color:#93c5fd}
.pi{background:#451a03;color:#fcd34d}
.pn{background:#1c2128;color:#718096}

.btn-row{display:flex;gap:10px;flex-wrap:wrap}
.btn{
  padding:11px 22px;border-radius:10px;border:none;
  font-size:13px;font-weight:600;cursor:pointer;
  transition:background .2s,transform .1s;flex-shrink:0;
}
.btn:active{transform:scale(.97)}
.btn:disabled{opacity:.45;cursor:not-allowed;transform:none}
.btn-launch {background:#064e3b;color:#a7f3d0}
.btn-launch:hover:not(:disabled){background:#065f46}
.btn-stop   {background:#21262d;color:#a0aec0;border:1px solid #30363d}
.btn-stop:hover:not(:disabled){background:#30363d;color:#e2e8f0}
.btn-report {background:#1e3a5f;color:#93c5fd}
.btn-report:hover:not(:disabled){background:#1d4ed8}
.cam-note{font-size:12px;color:#718096;margin-top:8px;line-height:1.6}
#rmsg{font-size:12px;margin-top:8px;min-height:16px}
</style>
</head>
<body>

<div class="topbar">
  <a class="back" href="/">&#8592; Home</a>
  <span class="page-title">Workforce Productivity &amp; Efficiency Monitoring</span>
  <span class="page-sub" id="shift-info">—</span>
</div>

<div class="eff-banner">
  <div>
    <div style="font-size:12px;color:#6ee7b7;margin-bottom:4px;text-transform:uppercase;letter-spacing:.08em">Current Efficiency</div>
    <div style="display:flex;align-items:baseline;gap:6px">
      <span class="eff-number" id="eff-big">—</span>
      <span class="eff-unit">%</span>
    </div>
  </div>
  <div style="margin-left:20px;border-left:1px solid #065f46;padding-left:20px">
    <div style="margin-bottom:8px">Worker status</div>
    <div id="status-pill"><span class="pill pn">Initializing</span></div>
  </div>
</div>

<div class="kpi-grid">
  <div class="kpi">
    <div class="lbl">Peak efficiency</div>
    <div class="val c-green" id="k-peak">—</div>
    <div class="hint" id="k-peak-time">—</div>
  </div>
  <div class="kpi">
    <div class="lbl">Head count</div>
    <div class="val" id="k-hc">—</div>
    <div class="hint">workers in frame</div>
  </div>
  <div class="kpi">
    <div class="lbl">Active time</div>
    <div class="val c-green" id="k-active">—</div>
    <div class="hint">this shift</div>
  </div>
  <div class="kpi">
    <div class="lbl">Idle time</div>
    <div class="val c-amber" id="k-idle">—</div>
    <div class="hint">this shift</div>
  </div>
  <div class="kpi">
    <div class="lbl">Longest idle</div>
    <div class="val c-amber" id="k-longest">—</div>
    <div class="hint">streak</div>
  </div>
</div>

<div class="section">
  <div class="section-title">Shift time breakdown</div>
  <div class="bar-wrap">
    <div class="seg" style="background:#059669" id="b-active"></div>
    <div class="seg" style="background:#d97706" id="b-idle"></div>
    <div class="seg" style="background:#374151" id="b-absent"></div>
  </div>
  <div class="bar-labels">
    <span><span class="dot" style="background:#059669"></span>Active <b id="l-active">—</b></span>
    <span><span class="dot" style="background:#d97706"></span>Idle <b id="l-idle">—</b></span>
    <span><span class="dot" style="background:#374151"></span>Absent <b id="l-absent">—</b></span>
  </div>
</div>

<div class="section">
  <div class="section-title">Efficiency trend — last 60 min</div>
  <canvas id="trend-chart" height="80"></canvas>
</div>

<div class="section">
  <div class="section-title">Camera &amp; detection</div>
  <div class="btn-row">
    <button class="btn btn-launch" id="btn-launch" onclick="launchModule()">
      Launch Camera &amp; Detection
    </button>
    <button class="btn btn-stop" id="btn-stop" onclick="stopModule()" disabled>
      Stop
    </button>
  </div>
  <p class="cam-note" id="cam-note">
    Clicking Launch opens the workplace monitoring dashboard and the live annotated camera feed.
  </p>
</div>

<div class="section">
  <div class="section-title">Shift report</div>
  <div class="btn-row">
    <button class="btn btn-report" id="btn-report" onclick="downloadReport()">
      Download PDF Shift Report
    </button>
  </div>
  <div id="rmsg"></div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
function dur(s){
  s=Math.floor(s);
  const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sc=s%60;
  return h?(h+'h '+String(m).padStart(2,'0')+'m'):(m+'m '+String(sc).padStart(2,'0')+'s');
}
function pillCls(s){
  if(s==='Worker Active')  return 'pill pa';
  if(s==='Worker Working') return 'pill pw';
  if(s==='Worker Idle')    return 'pill pi';
  return 'pill pn';
}
function effColor(e){ return e>=70?'#34d399':e>=40?'#fbbf24':'#f87171'; }

const ctx = document.getElementById('trend-chart').getContext('2d');
const chart = new Chart(ctx,{
  type:'line',
  data:{labels:[],datasets:[{
    data:[],borderColor:'#059669',backgroundColor:'rgba(5,150,105,0.1)',
    borderWidth:2,pointRadius:0,fill:true,tension:0.35
  }]},
  options:{
    animation:false,responsive:true,
    plugins:{legend:{display:false}},
    scales:{
      x:{ticks:{color:'#718096',maxTicksLimit:8,font:{size:10}},grid:{color:'#1c2128'}},
      y:{min:0,max:100,
         ticks:{color:'#718096',font:{size:10},callback:v=>v+'%'},
         grid:{color:'#1c2128'}}
    }
  }
});

async function pollEfficiency(){
  try{
    const d = await fetch('/api/efficiency/state').then(r=>r.json());
    const eff = d.efficiency;
    const bigEl = document.getElementById('eff-big');
    bigEl.textContent = eff.toFixed(1);
    bigEl.style.color = effColor(eff);
    document.getElementById('status-pill').innerHTML = '<span class="'+pillCls(d.status)+'">'+d.status+'</span>';
    document.getElementById('shift-info').textContent = 'Shift started '+d.shift_start+' · Duration '+dur(d.shift_dur);
    document.getElementById('k-peak').textContent     = d.peak_efficiency.toFixed(1)+'%';
    document.getElementById('k-peak-time').textContent= d.peak_time ? 'at '+d.peak_time : '—';
    document.getElementById('k-hc').textContent       = d.head_count;
    document.getElementById('k-active').textContent   = dur(d.active_secs);
    document.getElementById('k-idle').textContent     = dur(d.idle_secs);
    document.getElementById('k-longest').textContent  = dur(d.longest_idle);
    const tot = d.active_secs + d.idle_secs + d.absent_secs || 1;
    document.getElementById('b-active').style.width  = (d.active_secs/tot*100).toFixed(1)+'%';
    document.getElementById('b-idle').style.width    = (d.idle_secs/tot*100).toFixed(1)+'%';
    document.getElementById('b-absent').style.width  = (d.absent_secs/tot*100).toFixed(1)+'%';
    document.getElementById('l-active').textContent  = dur(d.active_secs);
    document.getElementById('l-idle').textContent    = dur(d.idle_secs);
    document.getElementById('l-absent').textContent  = dur(d.absent_secs);
    if(d.history.length){
      chart.data.labels = d.history.map(h=>h.t);
      chart.data.datasets[0].data = d.history.map(h=>h.e);
      chart.update('none');
    }
  }catch(e){}
}

async function pollStatus(){
  try{
    const d = await fetch('/api/status').then(r=>r.json());
    const running = d.efficiency;
    document.getElementById('btn-launch').disabled = running;
    document.getElementById('btn-stop').disabled   = !running;
    document.getElementById('cam-note').textContent = running
      ? 'Workplace monitoring is active. Camera and detection are running.'
      : 'Clicking Launch opens the workplace monitoring dashboard and the live annotated camera feed.';
  }catch(e){}
}

async function launchModule(){
  document.getElementById('btn-launch').disabled = true;
  await fetch('/api/launch/efficiency',{method:'POST'});
  setTimeout(pollStatus, 800);
}
async function stopModule(){
  document.getElementById('btn-stop').disabled = true;
  await fetch('/api/stop/efficiency',{method:'POST'});
  setTimeout(pollStatus, 800);
}

async function downloadReport(){
  const btn = document.getElementById('btn-report');
  const msg = document.getElementById('rmsg');
  btn.disabled = true; btn.textContent = 'Generating...'; msg.textContent = '';
  try{
    const res = await fetch('/api/report/efficiency',{method:'POST'});
    if(res.ok){
      const blob = await res.blob();
      const cd   = res.headers.get('Content-Disposition')||'';
      const m    = cd.match(/filename="?([^"]+)"?/);
      const fname= m ? m[1] : 'shift_report.pdf';
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href=url; a.download=fname; a.click();
      URL.revokeObjectURL(url);
      msg.style.color='#34d399'; msg.textContent='Downloaded: '+fname;
    } else {
      const e = await res.json();
      msg.style.color='#f87171'; msg.textContent='Error: '+(e.error||res.statusText);
    }
  }catch(e){msg.style.color='#f87171'; msg.textContent='Request failed.';}
  btn.disabled=false; btn.textContent='Download PDF Shift Report';
}

pollEfficiency(); pollStatus();
setInterval(pollEfficiency, 2000);
setInterval(pollStatus, 2500);
</script>
</body>
</html>"""

# ── FLASK ROUTES ──────────────────────────────────────────────────

@app.route("/")
def home():
    return HOME

@app.route("/safety")
def safety_page():
    return SAFETY_DASH

@app.route("/efficiency")
def efficiency_page():
    return EFFICIENCY_DASH

@app.route("/api/status")
def api_status():
    return jsonify({name: is_running(name) for name in PROCS})

@app.route("/api/launch/<name>", methods=["POST"])
def api_launch(name):
    if name not in PROCS:
        return jsonify({"ok": False, "error": "unknown module"}), 400
    ok, msg = launch(name)
    return jsonify({"ok": ok, "msg": msg})

@app.route("/api/stop/<name>", methods=["POST"])
def api_stop(name):
    if name not in PROCS:
        return jsonify({"ok": False, "error": "unknown module"}), 400
    ok, msg = stop(name)
    return jsonify({"ok": ok, "msg": msg})

# ── PROXY HELPERS ─────────────────────────────────────────────────

def _proxy_get(url, fallback):
    """Fetch JSON from a subprocess API; return fallback dict if not reachable."""
    try:
        with urllib.request.urlopen(url, timeout=1.5) as r:
            return json.loads(r.read())
    except Exception:
        return fallback

def _proxy_post(url):
    """POST to a subprocess API; return response dict."""
    try:
        req = urllib.request.Request(url, data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=4) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}

_SAFETY_FALLBACK = {
    "risk": "SAFE", "detected": [], "danger": 0,
    "warning": 0, "caution": 0,
    "session_start": "—", "log": [],
}
_EFF_FALLBACK = {
    "status": "Initializing", "efficiency": 0.0,
    "active_secs": 0.0, "idle_secs": 0.0, "absent_secs": 0.0,
    "peak_efficiency": 0.0, "peak_time": None, "longest_idle": 0.0,
    "head_count": 0, "shift_start": "—", "shift_dur": 0, "history": [],
}

@app.route("/api/safety/state")
def api_safety_state():
    data = _proxy_get("http://127.0.0.1:5001/api/state", _SAFETY_FALLBACK)
    return jsonify(data)

@app.route("/api/efficiency/state")
def api_efficiency_state():
    data = _proxy_get("http://127.0.0.1:5002/api/state", _EFF_FALLBACK)
    return jsonify(data)

@app.route("/api/report/efficiency", methods=["POST"])
def api_report_efficiency():
    try:
        import io
        req = urllib.request.Request(
            "http://127.0.0.1:5002/api/report", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            content_type = r.headers.get("Content-Type", "")
            raw = r.read()

        # If the subprocess returned an error JSON instead of a PDF, surface it
        if "application/pdf" not in content_type:
            try:
                err = json.loads(raw.decode("utf-8", errors="replace"))
                return jsonify(err), 500
            except Exception:
                return jsonify({"ok": False, "error": "Report generation failed"}), 500

        ts       = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"shift_report_{ts}.pdf"
        return send_file(io.BytesIO(raw), mimetype="application/pdf",
                         as_attachment=True, download_name=filename)
    except urllib.error.URLError:
        return jsonify({"ok": False,
                        "error": "Efficiency monitor is not running. Launch it first."}), 503
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)}), 500

# ── MAIN ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("  Industrial Vehicle Safety System")
    print("  ══════════════════════════════════════════")
    print("  Home page        →  http://localhost:5000")
    print("  Safety dashboard →  http://localhost:5000/safety")
    print("  Efficiency dash  →  http://localhost:5000/efficiency")
    print()
    print("  Required in same folder:")
    print("    forklift_safety.py")
    print("    workplace_monitor.py")
    print()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
