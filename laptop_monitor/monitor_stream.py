"""
==============================================================================
Aqua-Sentry Unified Desktop Ground Station & Teleoperation Console
==============================================================================
Displays an all-in-one multi-pane dashboard in a single widescreen window:
  - Left Pane: Live AI Video Feed with classification boxes, target vector, and intake guides.
  - Right Pane:
      1. 2D Geofence Radar Mini-Map (preset boundary, covered cells, boat trajectory).
      2. Telemetry Cards (Area swept m², coverage %, payload mass kg, volume L, haul count).
      3. Live State Ribbon & Safety Watchdog Indicator.
      4. Quick-action Keyboard Control Guide.
==============================================================================
"""

import cv2
import time
import os
import urllib.request
import numpy as np
from datetime import datetime

from trash_classifier import TrashClassifier
from trash_logger import TrashLogger
from geofence_mapper import GeofenceMapper
from autonomous_cleaner import AutonomousCleaner, CleanerState

# Network Configuration
BASE_URL = "http://192.168.4.1"
STREAM_URL = f"{BASE_URL}:81/stream"
CONTROL_URL = f"{BASE_URL}/control?cmd="
WINDOW_NAME = "Aqua-Sentry Unified Mission Control Console"

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
    print("=" * 75)
    print("  Aqua-Sentry Unified Ground Control Station (Multi-Pane Dashboard)")
    print("=" * 75)
    print("Connecting to live video stream at:", STREAM_URL)
    print("Controls:")
    print("  [A] Autonomous Roomba Mode | [M] Manual Standby Mode")
    print("  [W/A/S/D] Steering (Touching any key immediately overrides autonomous mode)")
    print("  [SPACE] Instant Brake | [X] EMERGENCY KILL SWITCH")
    print("  [C] Toggle Collector Paddle | [P] Screenshot | [Q] Exit\n")

    cap = cv2.VideoCapture(STREAM_URL)
    if not cap.isOpened():
        print("[WARN] Port 81 failed, trying fallback port 80...")
        cap = cv2.VideoCapture(f"{BASE_URL}/stream")
        if not cap.isOpened():
            print("[FATAL] Could not connect to camera stream. Check Wi-Fi connection to 'AquaSentry-Vision'.")
            return

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 1280, 720)

    # Initialize Modules (Preset: 20m x 25m water zone)
    geofence = GeofenceMapper(pond_width_m=20.0, pond_length_m=25.0, boat_swath_m=0.6)
    classifier = TrashClassifier(use_yolo=False)
    logger = TrashLogger(data_dir="trash_data")
    cleaner = AutonomousCleaner(send_cmd_fn=send_boat_command, geofence_mapper=geofence)

    prev_time = time.time()
    fps = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            cap.release()
            cap = cv2.VideoCapture(STREAM_URL)
            continue

        now = time.time()
        fps = 0.9 * fps + 0.1 * (1.0 / max(now - prev_time, 0.0001))
        prev_time = now

        # Resize video feed to 800x600 for left pane
        feed_w, feed_h = 800, 600
        feed = cv2.resize(frame, (feed_w, feed_h))
        center_x = feed_w // 2

        # Central intake channel guidelines
        intake_left = int(feed_w * 0.35)
        intake_right = int(feed_w * 0.65)
        cv2.line(feed, (intake_left, int(feed_h * 0.45)), (intake_left, feed_h), (0, 255, 255), 2)
        cv2.line(feed, (intake_right, int(feed_h * 0.45)), (intake_right, feed_h), (0, 255, 255), 2)
        cv2.putText(feed, "REAR COLLECTION COVER CORRIDOR", (intake_left + 10, feed_h - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1)

        # ----------------------------------------------------
        # 1. AI TRASH IDENTIFICATION & REFLECTION FILTERING
        # ----------------------------------------------------
        verified_debris = classifier.process_frame(feed)
        for item in verified_debris:
            bx, by, bw, bh = item["bbox"]
            c_name = item["class_name"]
            conf = item["confidence"]
            t_id = item["track_id"]
            color = CLASS_COLORS.get(c_name, (0, 255, 0))

            cv2.rectangle(feed, (bx, by), (bx + bw, by + bh), color, 2)
            cv2.putText(feed, f"#{t_id} {c_name} {int(conf * 100)}%", 
                        (bx, max(by - 8, 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.46, color, 2)

        # ----------------------------------------------------
        # 2. AUTONOMOUS CLEANING & GEOFENCE DECISION
        # ----------------------------------------------------
        decision = cleaner.update(feed, verified_debris, logger)
        target_box = decision["target_box"]
        target_vector = decision["target_vector"]
        hud_color = decision["hud_color"]
        status_msg = decision["status_message"]

        if target_vector:
            cv2.line(feed, target_vector[0], target_vector[1], (0, 255, 0), 2)
            cv2.circle(feed, target_vector[1], 5, (0, 0, 255), -1)

        if target_box:
            tx, ty, tw, th = target_box
            cv2.rectangle(feed, (tx - 3, ty - 3), (tx + tw + 6, ty + th + 6), (0, 255, 0), 3)

        # ----------------------------------------------------
        # 3. BUILD ALL-IN-ONE MULTI-PANE DASHBOARD CANVAS (1280x720)
        # ----------------------------------------------------
        canvas = np.full((720, 1280, 3), 15, dtype=np.uint8) # Dark theme background

        # Place Video Feed on Left (X: 15 to 815, Y: 100 to 700)
        canvas[100:700, 15:815] = feed

        # ---- TOP HEADER BAR (Y: 0 to 85) ----
        cv2.rectangle(canvas, (0, 0), (1280, 85), (22, 27, 34), -1)
        cv2.line(canvas, (0, 85), (1280, 85), (48, 54, 61), 1)

        cv2.putText(canvas, "AQUA-SENTRY UNIFIED MISSION CONTROL", (20, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (88, 166, 255), 2)
        cv2.putText(canvas, f"FPS: {fps:.1f} | WI-FI AP: 192.168.4.1", (20, 62),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (139, 148, 158), 1)

        # State Pill Badge
        cv2.rectangle(canvas, (550, 18), (815, 66), (33, 38, 45), -1)
        cv2.rectangle(canvas, (550, 18), (815, 66), hud_color, 1)
        cv2.putText(canvas, f"STATE: {cleaner.state[:16]}", (560, 46),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, hud_color, 2)

        # Emergency Kill Switch Banner
        cv2.rectangle(canvas, (840, 18), (1260, 66), (218, 54, 51), -1)
        cv2.putText(canvas, "EMERGENCY KILL SWITCH [X]", (875, 47),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # ---- RIGHT SIDEBAR: RADAR MAP & TELEMETRY (X: 835 to 1265) ----
        sidebar_x = 835
        cv2.rectangle(canvas, (sidebar_x, 100), (1265, 700), (22, 27, 34), -1)
        cv2.rectangle(canvas, (sidebar_x, 100), (1265, 700), (48, 54, 61), 1)

        # 1. 2D Radar Mini-Map
        map_size = 230
        minimap = geofence.render_minimap(map_size=map_size)
        map_start_x = sidebar_x + (430 - map_size) // 2
        canvas[115:115+map_size, map_start_x:map_start_x+map_size] = minimap

        # 2. Telemetry Metrics Cards
        metrics = geofence.get_metrics(logger.category_counts)
        card_y = 365

        cv2.putText(canvas, "MISSION TELEMETRY", (sidebar_x + 20, card_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (88, 166, 255), 2)
        cv2.line(canvas, (sidebar_x + 20, card_y + 8), (sidebar_x + 410, card_y + 8), (48, 54, 61), 1)

        # Stat Rows
        stat_rows = [
            ("Trash Collected:", f"{cleaner.collected_count} items", (126, 231, 135)),
            ("Estimated Payload:", f"{metrics['total_weight_kg']} kg  ({metrics['total_volume_l']} L)", (255, 255, 255)),
            ("Water Swept Area:", f"{metrics['area_covered_sqm']} m2 ({metrics['coverage_pct']}%)", (0, 215, 255)),
            ("Pond Boundary:", f"{geofence.width_m:.0f}m x {geofence.length_m:.0f}m ({metrics['total_area_sqm']} m2)", (200, 200, 200)),
            ("Distance Traveled:", f"{metrics['distance_traveled_m']} meters", (200, 200, 200)),
            ("Debris in View:", f"{len(verified_debris)} targets", (255, 165, 0))
        ]

        row_y = card_y + 32
        for lbl, val, val_col in stat_rows:
            cv2.putText(canvas, lbl, (sidebar_x + 20, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (139, 148, 158), 1)
            cv2.putText(canvas, val, (sidebar_x + 220, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.44, val_col, 2)
            row_y += 24

        # 3. Controls & Hotkey Guide
        cv2.line(canvas, (sidebar_x + 20, row_y + 5), (sidebar_x + 410, row_y + 5), (48, 54, 61), 1)
        row_y += 25
        cv2.putText(canvas, "OPERATOR HOTKEYS:", (sidebar_x + 20, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (88, 166, 255), 1)
        row_y += 20
        cv2.putText(canvas, "[A] Autonomous Roomba Mode    [M] Manual Standby", (sidebar_x + 20, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1)
        row_y += 18
        cv2.putText(canvas, "[W/A/S/D] Steering Override   [SPACE] Brake", (sidebar_x + 20, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1)
        row_y += 18
        cv2.putText(canvas, "[C] Toggle Paddle Collector   [Q] Quit & Export", (sidebar_x + 20, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1)

        # 4. Status Message Ribbon (Bottom of Left Pane)
        cv2.rectangle(canvas, (15, 665), (815, 700), (22, 27, 34), -1)
        cv2.putText(canvas, f">> {status_msg}", (25, 688),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.44, (230, 230, 230), 1)

        cv2.imshow(WINDOW_NAME, canvas)

        # Keyboard Interactivity
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:
            print("[INFO] Shutting down Ground Station...")
            break
        elif key == ord('a'): cleaner.set_mode("AUTO")
        elif key == ord('m'): cleaner.set_mode("MANUAL")
        elif key == ord('x'):
            cleaner.set_mode("KILL")
            print("[ALERT] EMERGENCY STOP ACTIVATED! ALL MOTORS KILLED.")
        elif key == ord('c'): send_boat_command('C')
        elif key == ord('p'):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            cap_file = f"captures/dashboard_{timestamp}.jpg"
            cv2.imwrite(cap_file, canvas)
            print(f"[SNAPSHOT] Saved: {cap_file}")

        # Direct Manual Steering (Immediate safety override)
        elif key in (ord('w'), ord('s'), ord('a'), ord('d'), 32):
            if cleaner.state != CleanerState.MANUAL_STANDBY:
                cleaner.set_mode("MANUAL")
            
            if key == ord('w'):   send_boat_command('F')
            elif key == ord('s'): send_boat_command('B')
            elif key == ord('a'): send_boat_command('L')
            elif key == ord('d'): send_boat_command('R')
            elif key == 32:       send_boat_command('S')

    # Export final summary report
    summary = logger.export_summary(geofence_mapper=geofence)
    print("\n" + "=" * 60)
    print("             UNIFIED MISSION SUMMARY REPORT")
    print("=" * 60)
    print(f"Mission Duration:        {summary['mission_duration_min']} mins")
    print(f"Total Trash Collected:   {summary['total_items_collected']} items")
    print(f"Estimated Payload Mass:  {summary['payload_estimates']['estimated_weight_kg']} kg")
    print(f"Estimated Volume:        {summary['payload_estimates']['estimated_volume_liters']} Liters")
    print(f"Water Surface Swept:     {summary['spatial_coverage']['water_area_swept_sqm']} m²")
    print(f"Geofence Coverage:       {summary['spatial_coverage']['coverage_percentage']} of {summary['spatial_coverage']['total_preset_pond_sqm']} m²")
    print(f"Distance Traveled:       {summary['spatial_coverage']['distance_traveled_m']} meters")
    print(f"Collection Rate:         {summary['collection_rate_per_min']} items/min")
    print(f"Composition Breakdown:   {summary['composition_breakdown']}")
    print(f"Mission Log:             trash_data/mission_log.csv")
    print(f"Summary Export:          trash_data/mission_summary.json")
    print("=" * 60)

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
