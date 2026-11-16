"""
==============================================================================
Aqua-Sentry Live Teleoperation, AI Trash Classifier & Data Logging Console
==============================================================================
Features:
  1. Live Video Stream with HUD & Central Intake Guides.
  2. Multi-Class Trash Identification & Water Reflection (Anti-Glint) Rejection:
     - Distinguishes Plastic Bottles, Drink Cans, Styrofoam, and Plastic Bags.
     - Ignores transient sun glints, wave ripples, and foam.
  3. Real-time Mission Data Logger:
     - Automatically logs detected and collected items into trash_data/mission_log.csv.
     - Exports mission statistics to trash_data/mission_summary.json upon exit.
  4. Active Dataset Harvester [H key]:
     - Auto-saves cropped images & YOLO labels to trash_data/dataset/ for model training.
  5. Teleoperation Controls:
     - [W/A/S/D] Steering | [SPACE] Brake | [X] Emergency Kill
     - [M] Manual Mode | [K] Auto Mode | [C] Toggle Collector
     - [T] Toggle AI Autonomous Trash Hunting | [P] Screenshot | [Q] Exit
==============================================================================
"""

import cv2
import time
import os
import urllib.request
from datetime import datetime

from trash_classifier import TrashClassifier
from trash_logger import TrashLogger

# Network Configuration
BASE_URL = "http://192.168.4.1"
STREAM_URL = f"{BASE_URL}:81/stream"
CONTROL_URL = f"{BASE_URL}/control?cmd="
WINDOW_NAME = "Aqua-Sentry AI Vision & Teleoperation Console"

# Distinct visualization colors per waste class (BGR)
CLASS_COLORS = {
    "Plastic Bottle": (255, 165, 0),    # Orange
    "Drink Can":      (0, 215, 255),    # Yellow/Gold
    "Styrofoam":      (255, 255, 255),  # White
    "Plastic Bag":    (204, 0, 204),    # Magenta
    "Plastic Debris": (0, 255, 128)     # Mint Green
}

def send_boat_command(cmd_char):
    """Sends non-blocking HTTP control commands to the catamaran."""
    try:
        url = f"{CONTROL_URL}{cmd_char}"
        req = urllib.request.Request(url, headers={'User-Agent': 'AquaSentryClient'})
        urllib.request.urlopen(req, timeout=0.15)
    except Exception:
        pass

def main():
    print("=" * 68)
    print("  Aqua-Sentry AI Trash Classifier & Telemetry Console")
    print("=" * 68)
    print("Connecting to live stream at:", STREAM_URL)
    print("Controls:")
    print("  [W] Forward  | [S] Reverse  | [A] Left  | [D] Right  | [SPACE] Brake")
    print("  [M] Manual   | [K] Auto     | [C] Collector | [X] EMERGENCY KILL")
    print("  [T] Toggle AI Trash Hunting | [H] Toggle Dataset Harvester")
    print("  [P] Screenshot | [Q] Exit & Save Mission Summary\n")

    cap = cv2.VideoCapture(STREAM_URL)
    if not cap.isOpened():
        print("[WARN] Port 81 failed, trying fallback port 80...")
        cap = cv2.VideoCapture(f"{BASE_URL}/stream")
        if not cap.isOpened():
            print("[FATAL] Could not connect to camera stream. Check Wi-Fi connection to 'AquaSentry-Vision'.")
            return

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 960, 640)

    # Initialize AI Classifier and Mission Data Logger
    classifier = TrashClassifier(use_yolo=False)
    logger = TrashLogger(data_dir="trash_data")

    ai_hunting_enabled = False
    harvest_dataset_enabled = False
    current_mode_label = "MANUAL"
    last_ai_steering_time = 0
    prev_time = time.time()
    fps = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            cap.release()
            cap = cv2.VideoCapture(STREAM_URL)
            continue

        # FPS smoothing
        now = time.time()
        fps = 0.9 * fps + 0.1 * (1.0 / max(now - prev_time, 0.0001))
        prev_time = now

        h, w, _ = frame.shape
        center_x = w // 2

        # Central intake channel boundary lines (35% to 65% width)
        intake_left = int(w * 0.35)
        intake_right = int(w * 0.65)
        cv2.line(frame, (intake_left, int(h * 0.45)), (intake_left, h), (0, 255, 255), 2)
        cv2.line(frame, (intake_right, int(h * 0.45)), (intake_right, h), (0, 255, 255), 2)

        # ----------------------------------------------------
        # 1. AI TRASH IDENTIFICATION & ANTI-GLINT FILTERING
        # ----------------------------------------------------
        verified_debris = classifier.process_frame(frame)
        active_target = None

        if verified_debris:
            # Sort by proximity to boat (highest Y centroid first)
            verified_debris.sort(key=lambda d: d["centroid"][1], reverse=True)
            active_target = verified_debris[0]

            for item in verified_debris:
                x, y, bw, bh = item["bbox"]
                cx, cy = item["centroid"]
                c_name = item["class_name"]
                conf = item["confidence"]
                status = item["status"]
                t_id = item["track_id"]

                color = CLASS_COLORS.get(c_name, (0, 255, 0))
                is_lead = (item["track_id"] == active_target["track_id"])

                # Draw bounding box
                cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2 if is_lead else 1)
                label_text = f"#{t_id} {c_name} {int(conf * 100)}%"
                cv2.putText(frame, label_text, (x, max(y - 8, 18)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                # Log to CSV telemetry
                logger.log_detection(t_id, c_name, conf, (x, y, bw, bh), bw * bh, status)

                # Dataset Harvester (if active and item newly verified)
                if harvest_dataset_enabled and status == "VERIFIED" and (now % 2.0 < 0.1):
                    logger.harvest_dataset_sample(frame, (x, y, bw, bh), 0, c_name)

            # Draw target lock vector to the primary lead debris
            px, py, pw, ph = active_target["bbox"]
            pcx, pcy = active_target["centroid"]
            cv2.line(frame, (center_x, h - 20), (pcx, pcy), (0, 255, 0), 2)

            # ----------------------------------------------------
            # 2. AI VISUAL SERVOING (AUTONOMOUS STEERING)
            # ----------------------------------------------------
            if ai_hunting_enabled and (now - last_ai_steering_time > 0.4):
                error_x = pcx - center_x
                deadband = int(w * 0.08)

                if error_x < -deadband:
                    send_boat_command('L')
                    cv2.putText(frame, "<< STEER LEFT", (intake_left - 130, h - 50),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
                elif error_x > deadband:
                    send_boat_command('R')
                    cv2.putText(frame, "STEER RIGHT >>", (intake_right + 10, h - 50),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
                else:
                    send_boat_command('F')
                    cv2.putText(frame, "== INTAKE ALIGNED (CRUISE) ==", (center_x - 130, h - 50),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                last_ai_steering_time = now

        # ----------------------------------------------------
        # 3. ON-SCREEN TELEMETRY & DATA HUD
        # ----------------------------------------------------
        hud_bg = frame[0:80, 0:w].copy()
        cv2.rectangle(frame, (0, 0), (w, 80), (15, 15, 15), -1)
        cv2.addWeighted(hud_bg, 0.35, frame[0:80, 0:w], 0.65, 0, frame[0:80, 0:w])

        cv2.putText(frame, "AQUA-SENTRY MISSION CONSOLE", (15, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (88, 166, 255), 2)
        cv2.putText(frame, f"FPS: {fps:.1f}", (15, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        ai_color = (0, 255, 0) if ai_hunting_enabled else (120, 120, 120)
        cv2.putText(frame, f"AI HUNT [T]: {'ON' if ai_hunting_enabled else 'OFF'}", 
                    (120, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, ai_color, 2)

        cv2.putText(frame, f"COLLECTED: {logger.total_collected}", 
                    (280, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
        cv2.putText(frame, f"IN SIGHT: {len(verified_debris)}", 
                    (440, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        harvest_color = (0, 255, 0) if harvest_dataset_enabled else (100, 100, 100)
        cv2.putText(frame, f"DATASET HARVEST [H]: {'REC' if harvest_dataset_enabled else 'OFF'}", 
                    (570, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, harvest_color, 1)

        cv2.imshow(WINDOW_NAME, frame)

        # ----------------------------------------------------
        # 4. KEYBOARD EVENT HANDLER
        # ----------------------------------------------------
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:
            print("[INFO] Ending mission session...")
            break
        elif key == ord('w'):
            send_boat_command('F')
        elif key == ord('s'):
            send_boat_command('B')
        elif key == ord('a'):
            send_boat_command('L')
        elif key == ord('d'):
            send_boat_command('R')
        elif key == 32: # SPACE
            send_boat_command('S')
        elif key == ord('x'):
            send_boat_command('X')
            print("[ALERT] EMERGENCY STOP SENT!")
        elif key == ord('m'):
            send_boat_command('M')
            current_mode_label = "MANUAL"
        elif key == ord('k'):
            send_boat_command('A')
            current_mode_label = "AUTONOMOUS"
        elif key == ord('c'):
            send_boat_command('C')
        elif key == ord('t'):
            ai_hunting_enabled = not ai_hunting_enabled
            if ai_hunting_enabled:
                send_boat_command('M')
                current_mode_label = "AI_HUNTING"
            print(f"[AI] Trash Tracking: {'ENABLED' if ai_hunting_enabled else 'DISABLED'}")
        elif key == ord('h'):
            harvest_dataset_enabled = not harvest_dataset_enabled
            print(f"[DATASET] Harvester: {'RECORDING SAMPLES' if harvest_dataset_enabled else 'OFF'}")
        elif key == ord('p'):
            t_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            f_path = f"captures/deck_{t_stamp}.jpg"
            cv2.imwrite(f_path, frame)
            print(f"[SAVED] Screenshot saved to: {f_path}")

    # Export final summary report
    summary = logger.export_summary()
    print("\n" + "=" * 50)
    print("         MISSION SUMMARY REPORT")
    print("=" * 50)
    print(f"Duration:          {summary['mission_duration_min']} minutes")
    print(f"Total Collected:   {summary['total_items_collected']} items")
    print(f"Collection Rate:   {summary['collection_rate_per_min']} items/min")
    print(f"Waste Breakdown:   {summary['composition_breakdown']}")
    print(f"Mission Log Saved: trash_data/mission_log.csv")
    print(f"Summary Exported:  trash_data/mission_summary.json")
    print("=" * 50)

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
