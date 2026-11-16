"""
==============================================================================
Aqua-Sentry Unified Web Mission Control Ground Station
==============================================================================
Serves an all-in-one interactive web dashboard on http://localhost:5000:
  - Live AI Video Stream (with classification boxes & intake guides)
  - Interactive 2D Geofence & Odometry Coverage Map
  - Real-Time Telemetry Gauges (Battery, Area m², Haul, Weight kg, Volume L)
  - Teleoperation D-Pad & Emergency Kill Switch
  - Live Debris Activity & Collection Feed Table
==============================================================================
"""

import os
import time
import json
import threading
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
import cv2
import numpy as np

from trash_classifier import TrashClassifier
from trash_logger import TrashLogger
from geofence_mapper import GeofenceMapper
from autonomous_cleaner import AutonomousCleaner, CleanerState

# Configuration
BOAT_IP = "192.168.4.1"
STREAM_URL = f"http://{BOAT_IP}:81/stream"
CONTROL_URL = f"http://{BOAT_IP}/control?cmd="
DASHBOARD_PORT = 5000

# Shared state between background video thread and HTTP handlers
class DashboardState:
    def __init__(self):
        self.lock = threading.Lock()
        self.latest_jpeg = None
        self.latest_map_jpeg = None
        self.fps = 0.0
        self.state_label = "MANUAL_STANDBY"
        self.status_message = "Ready. Standing by in Manual Mode."
        self.hud_color = "#388bfd"
        self.battery_v = 12.4
        self.metrics = {
            "area_covered_sqm": 0.0,
            "total_area_sqm": 500.0,
            "coverage_pct": 0.0,
            "distance_traveled_m": 0.0,
            "total_weight_kg": 0.0,
            "total_volume_l": 0.0
        }
        self.collected_count = 0
        self.in_sight_count = 0
        self.activity_log = []
        self.target_box = None
        self.target_vector = None

state = DashboardState()
geofence = GeofenceMapper(pond_width_m=20.0, pond_length_m=25.0, boat_swath_m=0.6)
classifier = TrashClassifier(use_yolo=False)
logger = TrashLogger(data_dir="trash_data")

def send_boat_command(cmd_char):
    """Transmits HTTP control commands to the catamaran."""
    try:
        url = f"{CONTROL_URL}{cmd_char}"
        req = urllib.request.Request(url, headers={'User-Agent': 'AquaSentryWeb'})
        urllib.request.urlopen(req, timeout=0.15)
    except Exception:
        pass

cleaner = AutonomousCleaner(send_cmd_fn=send_boat_command, geofence_mapper=geofence)

def video_worker():
    """Background worker that pulls frames, runs AI detection, and updates telemetry."""
    print(f"[WORKER] Starting video processing thread from {STREAM_URL}...")
    cap = cv2.VideoCapture(STREAM_URL)
    
    prev_time = time.time()
    fps = 0.0

    while True:
        if not cap.isOpened():
            cap = cv2.VideoCapture(STREAM_URL)
            time.sleep(1.0)
            continue

        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            cap.release()
            cap = cv2.VideoCapture(STREAM_URL)
            continue

        now = time.time()
        fps = 0.9 * fps + 0.1 * (1.0 / max(now - prev_time, 0.0001))
        prev_time = now

        h, w, _ = frame.shape
        center_x = w // 2

        # Draw central intake corridor
        intake_left = int(w * 0.35)
        intake_right = int(w * 0.65)
        cv2.line(frame, (intake_left, int(h * 0.45)), (intake_left, h), (0, 255, 255), 2)
        cv2.line(frame, (intake_right, int(h * 0.45)), (intake_right, h), (0, 255, 255), 2)

        # AI Detection & Reflection Rejection
        verified_debris = classifier.process_frame(frame)
        for item in verified_debris:
            bx, by, bw, bh = item["bbox"]
            t_id = item["track_id"]
            c_name = item["class_name"]
            conf = item["confidence"]
            cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)
            cv2.putText(frame, f"#{t_id} {c_name} {int(conf*100)}%", 
                        (bx, max(by - 8, 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 0), 2)

        # Autonomous Decision Cycle
        decision = cleaner.update(frame, verified_debris, logger)
        t_vector = decision["target_vector"]
        t_box = decision["target_box"]

        if t_vector:
            cv2.line(frame, t_vector[0], t_vector[1], (0, 255, 0), 2)
            cv2.circle(frame, t_vector[1], 5, (0, 0, 255), -1)

        if t_box:
            tx, ty, tw, th = t_box
            cv2.rectangle(frame, (tx - 2, ty - 2), (tx + tw + 4, ty + th + 4), (0, 255, 0), 3)

        # Render 2D Minimap
        minimap = geofence.render_minimap(map_size=280)
        _, map_buf = cv2.imencode('.jpg', minimap, [cv2.IMWRITE_JPEG_QUALITY, 80])

        # Encode main frame
        _, frame_buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])

        # Update global state
        metrics = geofence.get_metrics(logger.category_counts)
        with state.lock:
            state.latest_jpeg = frame_buf.tobytes()
            state.latest_map_jpeg = map_buf.tobytes()
            state.fps = fps
            state.state_label = cleaner.state
            state.status_message = decision["status_message"]
            state.collected_count = cleaner.collected_count
            state.in_sight_count = len(verified_debris)
            state.metrics = metrics

            # Log events
            if verified_debris and (len(state.activity_log) == 0 or state.activity_log[-1]["id"] != verified_debris[0]["track_id"]):
                lead = verified_debris[0]
                state.activity_log.append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "id": lead["track_id"],
                    "class": lead["class_name"],
                    "conf": f"{int(lead['confidence']*100)}%",
                    "status": lead["status"]
                })
                if len(state.activity_log) > 15:
                    state.activity_log.pop(0)

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self.get_html_page().encode("utf-8"))

        elif self.path == "/video_feed":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            while True:
                with state.lock:
                    jpeg = state.latest_jpeg
                if jpeg:
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
                time.sleep(0.04)

        elif self.path == "/map_feed":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            while True:
                with state.lock:
                    map_jpeg = state.latest_map_jpeg
                if map_jpeg:
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + map_jpeg + b"\r\n")
                time.sleep(0.2)

        elif self.path == "/api/telemetry":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with state.lock:
                data = {
                    "fps": round(state.fps, 1),
                    "state": state.state_label,
                    "status_message": state.status_message,
                    "battery_v": state.battery_v,
                    "collected": state.collected_count,
                    "in_sight": state.in_sight_count,
                    "metrics": state.metrics,
                    "log": state.activity_log
                }
            self.wfile.write(json.dumps(data).encode("utf-8"))

        elif self.path.startswith("/api/control"):
            # Handle action command
            cmd = None
            if "?cmd=" in self.path:
                cmd = self.path.split("?cmd=")[1].split("&")[0]
            
            if cmd == "AUTO": cleaner.set_mode("AUTO")
            elif cmd == "MANUAL": cleaner.set_mode("MANUAL")
            elif cmd == "KILL": cleaner.set_mode("KILL")
            elif cmd in ['F', 'B', 'L', 'R', 'S', 'C']:
                if cleaner.state != CleanerState.MANUAL_STANDBY and cmd in ['F', 'B', 'L', 'R', 'S']:
                    cleaner.set_mode("MANUAL")
                send_boat_command(cmd)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return # Suppress default terminal access logs for clean console

    def get_html_page(self):
        return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Aqua-Sentry Mission Control Station</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {
      --bg: #0d1117; --panel: #161b22; --border: #30363d;
      --accent: #58a6ff; --green: #238636; --red: #da3633; --yellow: #d29922;
      --text: #c9d1d9; --text-muted: #8b949e;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif; }
    body { background: var(--bg); color: var(--text); padding: 15px; }
    
    /* Header */
    header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 15px; border-bottom: 1px solid var(--border); margin-bottom: 15px; }
    .title-group h1 { font-size: 20px; color: var(--accent); display: flex; align-items: center; gap: 8px; }
    .badge { font-size: 12px; padding: 4px 8px; border-radius: 12px; background: #1f6feb26; color: var(--accent); border: 1px solid #1f6feb; }
    .badge.green { background: #23863626; color: #3fb950; border-color: #238636; }
    .badge.red { background: #da363326; color: #f85149; border-color: #da3633; }
    
    /* Layout Grid */
    .dashboard-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 15px; }
    @media(max-width: 992px) { .dashboard-grid { grid-template-columns: 1fr; } }
    
    .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
    .panel-header { font-size: 14px; font-weight: bold; color: var(--text-muted); margin-bottom: 10px; display: flex; justify-content: space-between; }
    
    /* Stream & Radar */
    .media-box { position: relative; background: #000; border-radius: 6px; overflow: hidden; border: 1px solid var(--border); display: flex; justify-content: center; }
    .media-box img { width: 100%; height: auto; max-height: 440px; object-fit: contain; display: block; }
    
    /* Metric Cards Grid */
    .metrics-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 15px; }
    .card { background: var(--panel); border: 1px solid var(--border); border-radius: 6px; padding: 10px; text-align: center; }
    .card .val { font-size: 20px; font-weight: bold; color: #fff; margin-top: 4px; }
    .card .lbl { font-size: 11px; color: var(--text-muted); text-transform: uppercase; }
    
    /* Controls Section */
    .d-pad { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; max-width: 200px; margin: 10px auto; }
    button { background: #21262d; color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 12px; font-size: 14px; font-weight: bold; cursor: pointer; transition: 0.15s; }
    button:hover { background: #30363d; border-color: #8b949e; }
    button:active { background: #1f6feb; color: #fff; }
    .btn-stop { background: var(--red); color: #fff; border-color: #f85149; }
    .btn-stop:hover { background: #b62324; }
    .btn-auto { background: var(--green); color: #fff; border-color: #2ea043; }
    .btn-manual { background: #1f6feb; color: #fff; border-color: #388bfd; }
    
    /* Activity Table */
    .table-container { margin-top: 15px; max-height: 180px; overflow-y: auto; font-size: 13px; }
    table { width: 100%; border-collapse: collapse; text-align: left; }
    th { color: var(--text-muted); border-bottom: 1px solid var(--border); padding: 6px; font-size: 11px; }
    td { padding: 6px; border-bottom: 1px solid #21262d; }
    
    /* Status Banner */
    .status-banner { background: #161b22; border: 1px solid var(--border); padding: 10px 14px; border-radius: 6px; margin-bottom: 15px; font-size: 13px; display: flex; align-items: center; justify-content: space-between; }
  </style>
</head>
<body>

  <header>
    <div class="title-group">
      <h1>🌊 Aqua-Sentry Ground Control Station</h1>
      <span class="badge" id="bot-mode">MODE: STANDBY</span>
    </div>
    <div style="display:flex; gap:10px; align-items:center;">
      <span class="badge green" id="bot-fps">FPS: --</span>
      <span class="badge" id="bot-battery">BAT: 12.4V</span>
      <button class="btn-stop" style="padding:6px 12px; font-size:12px;" onclick="sendCmd('KILL')">KILL SWITCH [X]</button>
    </div>
  </header>

  <div class="status-banner">
    <div><strong>STATUS:</strong> <span id="status-msg">Connecting to video feed...</span></div>
    <div style="font-size:11px; color:var(--text-muted);">Hotkeys: W/A/S/D Steering | Space Brake | A Auto | M Manual</div>
  </div>

  <div class="dashboard-grid">
    <!-- Left Column: Video & Telemetry Metrics -->
    <div>
      <div class="panel">
        <div class="panel-header">
          <span>AI CAMERA STREAM & INTAKE GUIDANCE</span>
          <span style="color:var(--accent);">Active Target Lock</span>
        </div>
        <div class="media-box">
          <img src="/video_feed" alt="Live Camera Feed">
        </div>
      </div>

      <!-- Quick Telemetry Cards -->
      <div class="metrics-row">
        <div class="card">
          <div class="lbl">Trash Collected</div>
          <div class="val" id="metric-collected" style="color:#7ee787;">0</div>
        </div>
        <div class="card">
          <div class="lbl">Area Swept</div>
          <div class="val" id="metric-area">0.0 m²</div>
        </div>
        <div class="card">
          <div class="lbl">Pond Coverage</div>
          <div class="val" id="metric-coverage">0.0%</div>
        </div>
        <div class="card">
          <div class="lbl">Payload Mass</div>
          <div class="val" id="metric-weight">0.00 kg</div>
        </div>
      </div>

      <!-- Activity Feed Table -->
      <div class="panel" style="margin-top:15px;">
        <div class="panel-header"><span>REAL-TIME DEBRIS TELEMETRY FEED</span></div>
        <div class="table-container">
          <table>
            <thead><tr><th>TIME</th><th>ID</th><th>CATEGORY</th><th>CONFIDENCE</th><th>STATUS</th></tr></thead>
            <tbody id="activity-tbody"><tr><td colspan="5" style="text-align:center; color:var(--text-muted);">Waiting for detections...</td></tr></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Right Column: Radar Map & Operator Controls -->
    <div>
      <div class="panel">
        <div class="panel-header"><span>2D GEOFENCE RADAR & COVERAGE MAP</span></div>
        <div class="media-box">
          <img src="/map_feed" alt="Geofence Mini-Map">
        </div>
      </div>

      <div class="panel" style="margin-top:15px;">
        <div class="panel-header"><span>MISSION OPERATOR CONTROLS</span></div>
        
        <div style="display:flex; gap:10px; margin-bottom:10px;">
          <button class="btn-auto" style="flex:1;" onclick="sendCmd('AUTO')">Start Auto [A]</button>
          <button class="btn-manual" style="flex:1;" onclick="sendCmd('MANUAL')">Manual [M]</button>
        </div>

        <div class="d-pad">
          <div></div><button onclick="sendCmd('F')">&#9650;<br>FWD</button><div></div>
          <button onclick="sendCmd('L')">&#9664;<br>LFT</button>
          <button class="btn-stop" onclick="sendCmd('S')">BRAKE</button>
          <button onclick="sendCmd('R')">RGT<br>&#9654;</button>
          <div></div><button onclick="sendCmd('B')">REV<br>&#9660;</button><div></div>
        </div>

        <div style="margin-top:12px;">
          <button style="width:100%;" onclick="sendCmd('C')">Toggle Paddle Collector [C]</button>
        </div>
      </div>
    </div>
  </div>

  <script>
    function sendCmd(cmd) {
      fetch('/api/control?cmd=' + cmd);
    }

    // Keyboard Shortcuts
    document.addEventListener('keydown', function(e) {
      if (e.key === 'w' || e.key === 'ArrowUp') sendCmd('F');
      else if (e.key === 's' || e.key === 'ArrowDown') sendCmd('B');
      else if (e.key === 'a' || e.key === 'ArrowLeft') sendCmd('L');
      else if (e.key === 'd' || e.key === 'ArrowRight') sendCmd('R');
      else if (e.key === ' ') sendCmd('S');
      else if (e.key === 'x' || e.key === 'X') sendCmd('KILL');
      else if (e.key === 'a' || e.key === 'A') sendCmd('AUTO');
      else if (e.key === 'm' || e.key === 'M') sendCmd('MANUAL');
      else if (e.key === 'c' || e.key === 'C') sendCmd('C');
    });

    // Telemetry Poller
    setInterval(function() {
      fetch('/api/telemetry')
        .then(res => res.json())
        .then(data => {
          document.getElementById('bot-fps').innerText = 'FPS: ' + data.fps;
          document.getElementById('bot-mode').innerText = 'STATE: ' + data.state;
          document.getElementById('status-msg').innerText = data.status_message;
          document.getElementById('metric-collected').innerText = data.collected;
          document.getElementById('metric-area').innerText = data.metrics.area_covered_sqm + ' m²';
          document.getElementById('metric-coverage').innerText = data.metrics.coverage_pct + '%';
          document.getElementById('metric-weight').innerText = data.metrics.total_weight_kg + ' kg';

          if (data.log && data.log.length > 0) {
            let html = '';
            data.log.slice().reverse().forEach(row => {
              html += `<tr><td>${row.time}</td><td>#${row.id}</td><td>${row.class}</td><td>${row.conf}</td><td><span style="color:#3fb950">${row.status}</span></td></tr>`;
            });
            document.getElementById('activity-tbody').innerHTML = html;
          }
        })
        .catch(err => console.log(err));
    }, 400);
  </script>
</body>
</html>
"""

def main():
    print("=" * 75)
    print("  Aqua-Sentry Unified Web Ground Control Station")
    print("=" * 75)
    print(f"Starting server on http://localhost:{DASHBOARD_PORT}")
    print("Open your browser to monitor video, geofence map, metrics, and teleop all in one view!")
    print("Press Ctrl+C to terminate.")

    # Start video capture & autonomous cleaner thread
    t = threading.Thread(target=video_worker, daemon=True)
    t.start()

    server = HTTPServer(('0.0.0.0', DASHBOARD_PORT), RequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Ground Station Server stopped.")

if __name__ == "__main__":
    main()
