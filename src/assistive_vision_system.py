import cv2
import threading

import tkinter as tk
from ultralytics import YOLO
from queue import Queue
import time
import pythoncom
import win32com.client


# ================= YOLO =================
model = YOLO("yolov8n.pt")

# ================= SPEECH QUEUE =================
speech_queue = Queue()
is_answering = False
last_object_speech = 0

# ================= SPEECH THREAD (COM SAFE) =================
def speech_worker():
    pythoncom.CoInitialize()   # 🔴 REQUIRED
    speaker = win32com.client.Dispatch("SAPI.SpVoice")

    while True:
        text = speech_queue.get()
        try:
            speaker.Speak(text)
        except Exception as e:
            print("TTS error:", e)
        speech_queue.task_done()

threading.Thread(target=speech_worker, daemon=True).start()

def speak(text):
    speech_queue.put(text)
    log_message(f"🔊 {text}")

def clear_speech_queue():
    while not speech_queue.empty():
        try:
            speech_queue.get_nowait()
            speech_queue.task_done()
        except:
            break

# ================= TKINTER UI =================
root = tk.Tk()
root.title("Assistive Vision System")
root.geometry("520x420")



log_box = tk.Text(root, wrap=tk.WORD, font=("Arial", 11))
log_box.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

def log_message(msg):
    log_box.insert(tk.END, msg + "\n")
    log_box.see(tk.END)

# ================= OBJECT DETECTION =================
def object_detection():
    global last_object_speech

    ESP32_CAM_URL = "http://192.168.137.140:81/stream"
    cap = cv2.VideoCapture(ESP32_CAM_URL)

    if not cap.isOpened():
        speak("ESP32 camera not available")
        return

    speak("Object detection started")

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        results = model(frame, conf=0.5)
        detected = set()

        for r in results:
            for box in r.boxes:
                label = model.names[int(box.cls[0])]
                detected.add(label)

                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, label, (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        now = time.time()
        if detected and not is_answering and now - last_object_speech > 1.5:
            speak(", ".join(detected) + " detected")
            last_object_speech = now

        cv2.imshow("ESP32-CAM Object Detection", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break

    cap.release()
    cv2.destroyAllWindows()

# ================= SPEECH + WIKIPEDIA =================

# ================= START THREADS =================
threading.Thread(target=object_detection, daemon=True).start()

speak("System is running")
log_message("✅ Assistive system started successfully")

root.mainloop()

