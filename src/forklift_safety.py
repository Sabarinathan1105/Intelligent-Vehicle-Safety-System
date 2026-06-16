import cv2
import threading
import tkinter as tk
from ultralytics import YOLO
from queue import PriorityQueue
import time
import numpy as np
import pythoncom
import win32com.client
from collections import defaultdict, deque
from datetime import datetime
from flask import Flask as _Flask, jsonify as _jsonify

# ── CONFIGURATION ─────────────────────────────────────────────────

ESP32_CAM_URL        = "http://192.168.137.38:81/stream"
MODEL_PATH           = "yolov8n.pt"
CONFIDENCE_THRESHOLD = 0.68
NMS_IOU_THRESHOLD    = 0.40
LOW_LIGHT_ENABLE     = True
CLAHE_CLIP_LIMIT     = 3.0
CLAHE_TILE_SIZE      = (8, 8)
FRAME_SKIP           = 2

# Only classes genuinely present on a warehouse/factory floor.
# suitcase and backpack removed — YOLO maps any cardboard box, bundle,
# or pile of goods to these, causing constant false alerts in a warehouse.
SAFETY_CLASSES = {
    "person",
    "car",
    "truck",
    "motorcycle",
    "bicycle",
    "bench",
    "chair",
    "potted plant",
    "dining table",
    "bottle",
    "vase",
    "fire hydrant",
    "stop sign",
    "traffic light",
    "parking meter",
}

# Proxy classes (COCO stand-ins for industrial objects) require higher
# confidence than real objects to avoid false positives from clutter.
CLASS_MIN_CONF = {
    "person":        0.60,
    "car":           0.45,
    "truck":         0.45,
    "motorcycle":    0.55,
    "bicycle":       0.55,
    "potted plant":  0.78,
    "dining table":  0.78,
    "bench":         0.75,
    "chair":         0.75,
    "bottle":        0.80,
    "vase":          0.80,
    "fire hydrant":  0.60,
    "stop sign":     0.60,
    "traffic light": 0.60,
    "parking meter": 0.65,
}

CLASS_PRIORITY = {
    "person":        1,
    "car":           2,
    "truck":         2,
    "motorcycle":    2,
    "bicycle":       2,
    "fire hydrant":  3,
    "stop sign":     3,
    "traffic light": 3,
    "potted plant":  3,
    "parking meter": 3,
    "bench":         4,
    "dining table":  4,
    "chair":         5,
    "bottle":        5,
    "vase":          5,
}

CLASS_SPEECH_NAME = {
    "person":        "worker",
    "car":           "vehicle",
    "truck":         "heavy vehicle",
    "motorcycle":    "vehicle",
    "bicycle":       "bicycle",
    "potted plant":  "bollard or post",
    "bench":         "workbench",
    "dining table":  "pallet",
    "bottle":        "canister",
    "vase":          "cylindrical object",
    "fire hydrant":  "emergency equipment",
    "stop sign":     "stop zone",
    "traffic light": "warning signal",
    "parking meter": "fixed post",
    "chair":         "obstacle",
}

CLASS_COOLDOWN = {
    "person":        2.5,
    "car":           3.0,
    "truck":         3.0,
    "motorcycle":    3.0,
    "bicycle":       3.5,
    "fire hydrant":  8.0,
    "stop sign":     8.0,
    "traffic light": 6.0,
    "parking meter": 8.0,
    "potted plant":  6.0,
    "bench":         8.0,
    "dining table":  6.0,
    "chair":         8.0,
    "bottle":        6.0,
    "vase":          6.0,
}

STATIC_HAZARDS = {
    "bench", "chair", "potted plant", "dining table", "parking meter", "vase",
}

# ── ZONE THRESHOLDS ───────────────────────────────────────────────

DANGER_ZONE_X  = (0.30, 0.70)
WARNING_ZONE_X = (0.10, 0.90)
CLOSE_ZONE_Y   = 0.45
SIZE_DANGER    = 0.15
SIZE_WARNING   = 0.05

# ── RISK CONSTANTS ────────────────────────────────────────────────

RISK_SAFE    = "SAFE"
RISK_CAUTION = "CAUTION"
RISK_WARNING = "WARNING"
RISK_DANGER  = "DANGER"

RISK_COLORS = {
    RISK_SAFE:    "#2ecc71",
    RISK_CAUTION: "#f39c12",
    RISK_WARNING: "#e67e22",
    RISK_DANGER:  "#e74c3c",
}

BOX_BGR = {
    RISK_DANGER:  (0, 0, 255),
    RISK_WARNING: (0, 140, 255),
    RISK_CAUTION: (0, 200, 255),
}

RISK_RANK = {RISK_SAFE: 0, RISK_CAUTION: 1, RISK_WARNING: 2, RISK_DANGER: 3}

# ── GLOBAL STATE ──────────────────────────────────────────────────

last_speech_per_class = defaultdict(float)
speech_queue          = PriorityQueue()
system_running        = True
currently_detected    = set()
frame_risk_global     = RISK_SAFE

# API state — written by detection loop, read by the API thread
_api_lock = threading.Lock()
_api_state = {
    "risk":      "SAFE",
    "detected":  [],
    "danger":    0,
    "warning":   0,
    "caution":   0,
    "log":       deque(maxlen=200),
    "session_start": datetime.now().strftime("%H:%M"),
}

# ── MODEL ─────────────────────────────────────────────────────────

print(f"[INIT] Loading model: {MODEL_PATH}")
model = YOLO(MODEL_PATH)
print("[INIT] Model ready.")

# ── LOW-LIGHT PREPROCESSING ───────────────────────────────────────

clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=CLAHE_TILE_SIZE)

def enhance_frame(frame: np.ndarray) -> np.ndarray:
    if not LOW_LIGHT_ENABLE:
        return frame
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = clahe.apply(l)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)

# ── RISK CLASSIFICATION ───────────────────────────────────────────

def classify_risk(x1, y1, x2, y2, frame_w, frame_h) -> str:
    cx   = (x1 + x2) / 2 / frame_w
    cy   = (y1 + y2) / 2 / frame_h
    area = ((x2 - x1) * (y2 - y1)) / (frame_w * frame_h)

    if area > SIZE_DANGER:
        return RISK_DANGER
    if area > SIZE_WARNING and cy > CLOSE_ZONE_Y:
        return RISK_DANGER
    if DANGER_ZONE_X[0] <= cx <= DANGER_ZONE_X[1]:
        return RISK_DANGER if cy > CLOSE_ZONE_Y else RISK_WARNING
    if WARNING_ZONE_X[0] <= cx <= WARNING_ZONE_X[1]:
        return RISK_WARNING if cy > CLOSE_ZONE_Y else RISK_CAUTION
    return RISK_CAUTION

def build_alert(label: str, risk: str) -> str:
    name = CLASS_SPEECH_NAME.get(label, label)
    if label in STATIC_HAZARDS:
        return {
            RISK_DANGER:  f"DANGER! {name} blocking path. Stop now!",
            RISK_WARNING: f"Warning! {name} ahead. Reduce speed!",
            RISK_CAUTION: f"Caution. {name} detected nearby.",
        }.get(risk, f"{name} detected.")
    else:
        return {
            RISK_DANGER:  f"DANGER! {name} in path. Stop immediately!",
            RISK_WARNING: f"Warning! {name} detected ahead. Slow down!",
            RISK_CAUTION: f"Caution. {name} nearby.",
        }.get(risk, f"{name} detected.")

# ── SPEECH ENGINE ─────────────────────────────────────────────────

def speech_worker():
    pythoncom.CoInitialize()
    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    speaker.Rate   = -1
    speaker.Volume = 100
    while system_running:
        try:
            priority, ts, label, text = speech_queue.get(timeout=1.0)
            # Only discard system messages if path has fully cleared (label is None means system msg)
            if label is not None and frame_risk_global == RISK_SAFE:
                speech_queue.task_done()
                continue
            speaker.Speak(text)
            speech_queue.task_done()
        except Exception:
            pass

threading.Thread(target=speech_worker, daemon=True).start()

def try_speak(label: str, risk: str):
    if risk == RISK_SAFE:
        return
    now = time.time()
    if now - last_speech_per_class[label] < CLASS_COOLDOWN.get(label, 3.0):
        return
    last_speech_per_class[label] = now
    text = build_alert(label, risk)
    # Queue tuple includes label so speech_worker can validity-check it
    speech_queue.put((CLASS_PRIORITY.get(label, 5), now, label, text))
    display = CLASS_SPEECH_NAME.get(label, label)
    root.after(0, log_message, f"🔊 [{risk}] {display.upper()} — {text}", risk)

def speak(text: str, priority: int = 3):
    # System messages use label=None — always played regardless of detection state
    speech_queue.put((priority, time.time(), None, text))

def clear_speech_queue():
    while not speech_queue.empty():
        try:
            speech_queue.get_nowait()
            speech_queue.task_done()
        except Exception:
            break

# ── UI ────────────────────────────────────────────────────────────

root = tk.Tk()
root.title("Industrial Forklift Safety System")
root.geometry("600x500")
root.configure(bg="#1a1a2e")

risk_var     = tk.StringVar(value="● SAFE")
detected_var = tk.StringVar(value="No hazards detected")

risk_label = tk.Label(
    root, textvariable=risk_var,
    font=("Arial", 22, "bold"),
    bg=RISK_COLORS[RISK_SAFE], fg="white",
    pady=10
)
risk_label.pack(fill=tk.X, padx=10, pady=(10, 4))

tk.Label(
    root, textvariable=detected_var,
    font=("Arial", 11), bg="#16213e", fg="#a0aec0",
    anchor="w", padx=10, pady=5
).pack(fill=tk.X, padx=10)

tk.Label(root, text="Event Log", font=("Arial", 10, "bold"),
         bg="#1a1a2e", fg="#718096").pack(anchor="w", padx=12)

log_frame = tk.Frame(root, bg="#1a1a2e")
log_frame.pack(expand=True, fill=tk.BOTH, padx=10, pady=(0, 10))

scrollbar = tk.Scrollbar(log_frame)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

log_box = tk.Text(
    log_frame, wrap=tk.WORD, font=("Consolas", 10),
    bg="#0f3460", fg="#e2e8f0",
    yscrollcommand=scrollbar.set, relief="flat"
)
log_box.pack(expand=True, fill=tk.BOTH)
scrollbar.config(command=log_box.yview)

log_box.tag_config("DANGER",  foreground="#fc8181")
log_box.tag_config("WARNING", foreground="#f6ad55")
log_box.tag_config("CAUTION", foreground="#f6e05e")
log_box.tag_config("INFO",    foreground="#90cdf4")

def log_message(msg: str, level: str = "INFO"):
    ts  = datetime.now().strftime("%H:%M:%S")
    tag = level if level in ("DANGER", "WARNING", "CAUTION") else "INFO"
    log_box.insert(tk.END, f"[{ts}] {msg}\n", tag)
    log_box.see(tk.END)
    with _api_lock:
        _api_state["log"].append({"ts": ts, "msg": msg, "level": tag})
        if level == "DANGER":  _api_state["danger"]  += 1
        elif level == "WARNING": _api_state["warning"] += 1
        elif level == "CAUTION": _api_state["caution"] += 1

def update_ui(risk: str, objects: list):
    labels = {
        RISK_SAFE:    "● SAFE",
        RISK_CAUTION: "⚠ CAUTION",
        RISK_WARNING: "⚠ WARNING",
        RISK_DANGER:  "🔴 DANGER",
    }
    risk_var.set(labels.get(risk, risk))
    risk_label.configure(bg=RISK_COLORS.get(risk, "#718096"))
    detected_var.set(
        ("Detected: " + ", ".join(objects)) if objects else "No hazards detected"
    )
    with _api_lock:
        _api_state["risk"]     = risk
        _api_state["detected"] = objects

# Tracks last logged state to suppress duplicate log lines
last_log_labels = set()
last_log_risk   = RISK_SAFE

# ── DETECTION LOOP ────────────────────────────────────────────────

def detection_loop():
    global last_log_labels, last_log_risk
    cap = cv2.VideoCapture(ESP32_CAM_URL)
    if not cap.isOpened():
        root.after(0, log_message, "ERROR: Cannot connect to ESP32-CAM.", "INFO")
        speak("Camera unavailable. System offline.", priority=1)
        return

    root.after(0, log_message, "✅ ESP32-CAM connected. Monitoring active.", "INFO")
    speak("Safety system active.", priority=3)

    frame_count = 0

    while system_running:
        ret, raw_frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue

        frame_count += 1
        if frame_count % FRAME_SKIP != 0:
            continue

        frame = enhance_frame(raw_frame)
        h, w  = frame.shape[:2]

        results = model(frame, conf=CONFIDENCE_THRESHOLD, iou=NMS_IOU_THRESHOLD, verbose=False)

        frame_risk    = RISK_SAFE
        frame_objects = []

        for r in results:
            for box in r.boxes:
                label = model.names[int(box.cls[0])]

                if label not in SAFETY_CLASSES:
                    continue

                conf = float(box.conf[0])
                if conf < CLASS_MIN_CONF.get(label, CONFIDENCE_THRESHOLD):
                    continue

                x1, y1, x2, y2 = map(int, box.xyxy[0])
                risk      = classify_risk(x1, y1, x2, y2, w, h)
                color     = BOX_BGR.get(risk, (0, 255, 0))
                disp_name = CLASS_SPEECH_NAME.get(label, label)

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(
                    frame,
                    f"{disp_name} {conf:.2f} [{risk}]",
                    (x1, max(y1 - 10, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2
                )

                frame_objects.append(label)
                try_speak(label, risk)

                if RISK_RANK[risk] > RISK_RANK[frame_risk]:
                    frame_risk = risk

        cv2.line(frame, (int(w * DANGER_ZONE_X[0]), 0), (int(w * DANGER_ZONE_X[0]), h), (60, 60, 200), 1)
        cv2.line(frame, (int(w * DANGER_ZONE_X[1]), 0), (int(w * DANGER_ZONE_X[1]), h), (60, 60, 200), 1)
        cv2.putText(frame, f"Risk: {frame_risk}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, BOX_BGR.get(frame_risk, (0, 220, 0)), 2)

        unique_labels  = list(set(frame_objects))
        friendly_names = [CLASS_SPEECH_NAME.get(l, l) for l in unique_labels]

        currently_detected.clear()
        currently_detected.update(unique_labels)

        global frame_risk_global
        frame_risk_global = frame_risk

        # Flush queue only when path fully clears
        if frame_risk == RISK_SAFE:
            clear_speech_queue()

        root.after(0, update_ui, frame_risk, friendly_names)

        # Only log when detected objects or risk level actually changes
        current_label_set = set(unique_labels)
        if current_label_set != last_log_labels or frame_risk != last_log_risk:
            last_log_labels = current_label_set
            last_log_risk   = frame_risk
            if unique_labels:
                msg = f"Detected: {', '.join(friendly_names)} | Zone risk: {frame_risk}"
                root.after(0, log_message, msg, frame_risk)
            elif last_log_labels:
                root.after(0, log_message, "Path clear.", "INFO")

        cv2.imshow("Forklift Safety — ESC to quit", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break

    cap.release()
    cv2.destroyAllWindows()

# ── LOCAL API (port 5001) — read by launcher dashboard ────────────

_api_app = _Flask("safety_api")

@_api_app.route("/api/state")
def _api_state_route():
    with _api_lock:
        return _jsonify({
            "risk":          _api_state["risk"],
            "detected":      _api_state["detected"],
            "danger":        _api_state["danger"],
            "warning":       _api_state["warning"],
            "caution":       _api_state["caution"],
            "session_start": _api_state["session_start"],
            "log":           list(_api_state["log"])[-80:],
        })

def _api_server():
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    _api_app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False)

threading.Thread(target=_api_server, daemon=True).start()

# ── START ─────────────────────────────────────────────────────────

threading.Thread(target=detection_loop, daemon=True).start()

log_message("✅ Industrial Forklift Safety System started.", "INFO")
log_message(f"   Model      : {MODEL_PATH}", "INFO")
log_message(f"   Confidence : {CONFIDENCE_THRESHOLD}", "INFO")
log_message(f"   Low light  : {'ENABLED' if LOW_LIGHT_ENABLE else 'DISABLED'}", "INFO")
log_message(f"   Monitoring : {', '.join(sorted(SAFETY_CLASSES))}", "INFO")

root.mainloop()
system_running = False
