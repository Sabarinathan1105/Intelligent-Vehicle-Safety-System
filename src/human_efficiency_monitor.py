import cv2
import time
import threading
import numpy as np
from ultralytics import YOLO
from flask import Flask, render_template_string
from collections import deque

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------
PERSON_CLASS_ID = 0
MOVEMENT_THRESHOLD = 20
QUEUE_LENGTH = 5
WINDOW_DURATION = 1  # seconds

# --------------------------------------------------
# GLOBAL SHARED VARIABLES
# --------------------------------------------------
human_efficiency = 0.0
current_status = "Initializing"

# --------------------------------------------------
# UTILITY FUNCTIONS
# --------------------------------------------------
def get_centroid(box):
    x1, y1, x2, y2 = box
    return int((x1 + x2) / 2), int((y1 + y2) / 2)

def activity_score(status):
    return {
        "Worker Active": 10,
        "Moving": 6,
        "Worker Idle": 2,
        "No Person": 0
    }.get(status, 0)

# --------------------------------------------------
# YOLO + HUMAN EFFICIENCY THREAD
# --------------------------------------------------
def vision_thread():
    global human_efficiency, current_status

    model = YOLO("yolov8n.pt")
    cap = cv2.VideoCapture("http://192.168.137.140:81/stream")
# ESP32-CAM / Webcam

    positions = deque(maxlen=QUEUE_LENGTH)
    activity_buffer = []
    window_start = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        results = model(frame, verbose=False)
        status = "No Person"

        for r in results[0].boxes:
            if int(r.cls[0]) == PERSON_CLASS_ID:
                box = r.xyxy[0].tolist()
                centroid = get_centroid(box)

                if positions:
                    px, py = positions[-1]
                    dist = np.hypot(centroid[0] - px, centroid[1] - py)
                    status = "Worker Active" if dist > MOVEMENT_THRESHOLD else "Worker Idle"
                else:
                    status = "Moving"

                positions.append(centroid)
                break

        current_status = status
        activity_buffer.append(activity_score(status))

        # ⏱️ WINDOW CALCULATION
        if time.time() - window_start >= WINDOW_DURATION:
            avg_activity = np.mean(activity_buffer) if activity_buffer else 0
            human_efficiency = (avg_activity / 10) * 100

            activity_buffer.clear()
            window_start = time.time()

        # 🔴 DISPLAY
        cv2.putText(frame, f"Status: {current_status}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

        cv2.putText(frame, f"Human Efficiency: {human_efficiency:.1f}%",
                    (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        cv2.imshow("Human Efficiency Monitoring", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

# --------------------------------------------------
# FLASK WEB DASHBOARD
# --------------------------------------------------
app = Flask(__name__)

@app.route("/")
def dashboard():
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <title>Human Efficiency Dashboard</title>
    <meta http-equiv="refresh" content="2">
    <style>
        body {
            margin: 0;
            height: 100vh;
            font-family: 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #141e30, #243b55);
            display: flex;
            justify-content: center;
            align-items: center;
            color: white;
        }
        .card {
            background: rgba(255,255,255,0.15);
            padding: 40px;
            width: 460px;
            border-radius: 20px;
            backdrop-filter: blur(12px);
            box-shadow: 0 25px 45px rgba(0,0,0,0.4);
        }
        h2 {
            text-align: center;
            margin-bottom: 25px;
        }
        .row {
            font-size: 20px;
            margin: 14px 0;
        }
        .value {
            float: right;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="card">
        <h2>Live Human Efficiency</h2>
        <div class="row">Worker Status <span class="value">{{status}}</span></div>
        <div class="row">Human Efficiency <span class="value">{{human}} %</span></div>
        <div class="row">Camera Source <span class="value">ESP32 / Webcam</span></div>
    </div>
</body>
</html>
""",
    status=current_status,
    human=round(human_efficiency, 2)
)

def flask_thread():
    app.run(host="0.0.0.0", port=5000, debug=False)

# --------------------------------------------------
# MAIN
# --------------------------------------------------
if __name__ == "__main__":
    threading.Thread(target=vision_thread, daemon=True).start()
    threading.Thread(target=flask_thread, daemon=True).start()

    while True:
        time.sleep(1)
