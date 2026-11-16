"""
==============================================================================
Aqua-Sentry Water-Surface Autonomous Cleaning Console (Water-Roomba Mode)
==============================================================================
Functionality:
  1. Live Video Stream with Intake Guidance & Real-time Collection Telemetry.
  2. Autonomous Cleaning Loop (Roomba for Water):
     - SEARCH_PATROL: Scans surrounding waterway for floating trash.
     - TARGET_APPROACH: Automatically steers and closes distance onto debris.
     - INGEST_RUNOVER: Runs over the trash with the paddle wheel spinning,
       drawing it through the pontoon channel and into the rear cover netting.
     - VERIFY_COLLECTED: Confirms collection and automatically locks onto the next target!
  3. Safety & Teleoperation:
     - Touch ANY key (W/A/S/D/SPACE) to instantly interrupt AI and take manual control.
     - [X] One-Touch EMERGENCY KILL SWITCH cuts all motors and thrusters.
     - [A] Enter Autonomous Water-Roomba Cleaning Mode.
     - [M] Switch to Manual Standby.
==============================================================================
"""

import cv2
import time
import os
import urllib.request
from datetime import datetime

from trash_classifier import TrashClassifier
from trash_logger import TrashLogger
from autonomous_cleaner import AutonomousCleaner, CleanerState

# Network Configuration
BASE_URL = "http://192.168.4.1"
STREAM_URL = f"{BASE_URL}:81/stream"
CONTROL_URL = f"{BASE_URL}/control?cmd="
WINDOW_NAME = "Aqua-Sentry Autonomous Cleaning Console"

CLASS_COLORS = {
    "Plastic Bottle": (255, 165, 0),    # Orange
    "Drink Can":      (0, 215, 255),    # Yellow
    "Styrofoam":      (255, 255, 255),  # White
    "Plastic Bag":    (204, 0, 204),    # Magenta
    "Plastic Debris": (0, 255, 128)     # Mint Green
}

def send_boat_command(cmd_char):
    """Transmits HTTP control commands to the catamaran over Wi-Fi."""
    try:
        url = f"{CONTROL_URL}{cmd_char}"
        req = urllib.request.Request(url, headers={'User-Agent': 'AquaSentryClient'})
        urllib.request.urlopen(req, timeout=0.15)
    except Exception:
        pass

def main():
    print("=" * 72)
    print("  Aqua-Sentry Autonomous Cleaning Robot Console (Water-Roomba Mode)")
    print("=" * 72)
    print("Connecting to live video stream at:", STREAM_URL)
    print("Operating Modes:")
    print("  [A] Autonomous Cleaning (Scan -> Approach -> Scoop into Rear Net -> Next Target)")
    print("  [M] Manual Standby Mode")
    print("  [W/A/S/D] Steering (Touching any key immediately overrides autonomous mode)")
    print("  [SPACE] Instant Brake | [X] EMERGENCY KILL SWITCH")
    print("  [C] Toggle Collector Paddle | [P] Screenshot | [Q] Exit\n")

    cap = cv2.VideoCapture(STREAM_URL)
    if not cap.isOpened():
        print("[WARN] Port 81 failed, trying fallback port 80...")
        cap = cv2.VideoCapture(f"{BASE_URL}/stream")
        if not cap.isOpened():
            print("[FATAL] Unable to connect. Ensure your laptop is connected to Wi-Fi 'AquaSentry-Vision'.")
            return

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 960, 640)

    # Initialize Modules
    classifier = TrashClassifier(use_yolo=False)
    logger = TrashLogger(data_dir="trash_data")
    cleaner = AutonomousCleaner(send_cmd_fn=send_boat_command)

    prev_time = time.time()
    fps = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            cap.release()
            cap = cv2.VideoCapture(STREAM_URL)
            continue

        # FPS calculation
        now = time.time()
        fps = 0.9 * fps + 0.1 * (1.0 / max(now - prev_time, 0.0001))
        prev_time = now

        h, w, _ = frame.shape
        center_x = w // 2

        # Central intake channel guidelines (35% to 65% width)
        intake_left = int(w * 0.35)
        intake_right = int(w * 0.65)
        cv2.line(frame, (intake_left, int(h * 0.45)), (intake_left, h), (0, 255, 255), 2)
        cv2.line(frame, (intake_right, int(h * 0.45)), (intake_right, h), (0, 255, 255), 2)
        cv2.putText(frame, "REAR COLLECTION COVER CORRIDOR", (intake_left + 10, h - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)

        # ----------------------------------------------------
        # 1. AI TRASH IDENTIFICATION & REFLECTION FILTERING
        # ----------------------------------------------------
        verified_debris = classifier.process_frame(frame)

        for item in verified_debris:
            x, y, bw, bh = item["bbox"]
            c_name = item["class_name"]
            conf = item["confidence"]
            t_id = item["track_id"]
            color = CLASS_COLORS.get(c_name, (0, 255, 0))

            cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
            cv2.putText(frame, f"#{t_id} {c_name} {int(conf * 100)}%", 
                        (x, max(y - 8, 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 2)

        # ----------------------------------------------------
        # 2. AUTONOMOUS CLEANING LOGIC (WATER-ROOMBA DECISION)
        # ----------------------------------------------------
        decision = cleaner.update(frame, verified_debris, logger)
        target_box = decision["target_box"]
        target_vector = decision["target_vector"]
        hud_color = decision["hud_color"]
        status_msg = decision["status_message"]

        # Draw Target Vector to locked debris
        if target_vector:
            pt1, pt2 = target_vector
            cv2.line(frame, pt1, pt2, (0, 255, 0), 2)
            cv2.circle(frame, pt2, 6, (0, 0, 255), -1)

        # Draw lock box
        if target_box:
            tx, ty, tw, th = target_box
            cv2.rectangle(frame, (tx - 3, ty - 3), (tx + tw + 6, ty + th + 6), (0, 255, 0), 3)
            cv2.putText(frame, "TARGET LOCK", (tx, max(ty - 12, 22)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

        # ----------------------------------------------------
        # 3. MISSION CONTROL & TELEMETRY HUD
        # ----------------------------------------------------
        hud_bg = frame[0:90, 0:w].copy()
        cv2.rectangle(frame, (0, 0), (w, 90), (12, 12, 12), -1)
        cv2.addWeighted(hud_bg, 0.35, frame[0:90, 0:w], 0.65, 0, frame[0:90, 0:w])

        # Header Line
        cv2.putText(frame, "AQUA-SENTRY WATER CLEANING ROBOT", (15, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (88, 166, 255), 2)
        cv2.putText(frame, f"FPS: {fps:.1f}", (15, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

        # State & Stats
        cv2.putText(frame, f"STATE: {cleaner.state}", (120, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, hud_color, 2)
        cv2.putText(frame, f"COLLECTED: {cleaner.collected_count}", (360, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 255, 255), 2)
        cv2.putText(frame, f"IN SIGHT: {len(verified_debris)}", (520, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1)

        # Status Message Ribbon
        cv2.putText(frame, status_msg, (15, 78),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (230, 230, 230), 1)

        cv2.imshow(WINDOW_NAME, frame)

        # ----------------------------------------------------
        # 4. KEYBOARD INTERRUPTS & SAFETY FAILSAFES
        # ----------------------------------------------------
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:
            print("[INFO] Shutting down console...")
            break
        elif key == ord('a'): # Activate Autonomous Roomba Mode
            cleaner.set_mode("AUTO")
        elif key == ord('m'): # Switch to Manual Standby
            cleaner.set_mode("MANUAL")
        elif key == ord('x'): # EMERGENCY KILL SWITCH
            cleaner.set_mode("KILL")
            print("[ALERT] EMERGENCY STOP ACTIVATED! PROPELLERS KILLED.")
        elif key == ord('c'): # Toggle Collector Motor
            send_boat_command('C')
        elif key == ord('p'): # Screenshot
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            cap_file = f"captures/cleanup_{timestamp}.jpg"
            cv2.imwrite(cap_file, frame)
            print(f"[SNAPSHOT] Saved: {cap_file}")

        # Direct Manual Steering (Instantly interrupts auto mode for safety!)
        elif key in (ord('w'), ord('s'), ord('a'), ord('d'), 32):
            if cleaner.state != CleanerState.MANUAL_STANDBY:
                cleaner.set_mode("MANUAL") # Take over control immediately
            
            if key == ord('w'):   send_boat_command('F')
            elif key == ord('s'): send_boat_command('B')
            elif key == ord('a'): send_boat_command('L')
            elif key == ord('d'): send_boat_command('R')
            elif key == 32:       send_boat_command('S') # Space = Brake

    # Export Mission Summary upon exit
    summary = logger.export_summary()
    print("\n" + "=" * 55)
    print("             MISSION SUMMARY REPORT")
    print("=" * 55)
    print(f"Mission Duration:      {summary['mission_duration_min']} mins")
    print(f"Total Trash Collected: {cleaner.collected_count} items")
    print(f"Collection Rate:       {summary['collection_rate_per_min']} items/min")
    print(f"Composition Breakdown: {summary['composition_breakdown']}")
    print(f"Mission Log:           trash_data/mission_log.csv")
    print(f"Summary Export:        trash_data/mission_summary.json")
    print("=" * 55)

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
