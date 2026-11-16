"""
==============================================================================
Aqua-Sentry Autonomous Cleaning Console with Geofence & Area Mapping
==============================================================================
Features:
  1. Live Video Stream with Intake Corridor & Real-time Telemetry.
  2. Autonomous Cleaning Loop (Water-Roomba Mode):
     - SEARCH_PATROL: Systematically sweeps the designated water zone.
     - TARGET_APPROACH: Locks onto nearest debris and maneuvers toward it.
     - INGEST_RUNOVER: Runs over the trash with the paddle wheel, sweeping it
       into the rear netting cover.
     - VERIFY_COLLECTED: Verifies collection and acquires the next target.
  3. Preset Virtual Water Boundary (Geofence Guard):
     - Prevents the catamaran from running aground or leaving the pond/lake zone.
     - Auto-rebounds inward when approaching the perimeter buffer (1.8m).
  4. Real-time Area Coverage & Payload Mapping:
     - 2D Top-Down Mini-Map HUD showing swept cells, boat position, and debris.
     - Live metrics: Area swept (m²), % covered, estimated weight (kg), and volume (L).
  5. Operator Controls & Safety Failsafes:
     - Touch ANY key (W/A/S/D/SPACE) to instantly interrupt autonomous mode.
     - [X] One-Touch EMERGENCY KILL SWITCH.
==============================================================================
"""

import cv2
import time
import os
import urllib.request
from datetime import datetime

from trash_classifier import TrashClassifier
from trash_logger import TrashLogger
from geofence_mapper import GeofenceMapper
from autonomous_cleaner import AutonomousCleaner, CleanerState

# Network Configuration
BASE_URL = "http://192.168.4.1"
STREAM_URL = f"{BASE_URL}:81/stream"
CONTROL_URL = f"{BASE_URL}/control?cmd="
WINDOW_NAME = "Aqua-Sentry Mission Console (Geofence & Area Coverage)"

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
    print("  Aqua-Sentry Autonomous Cleaning Console with Geofence & Area Mapping")
    print("=" * 75)
    print("Connecting to live video stream at:", STREAM_URL)
    print("Operating Modes:")
    print("  [A] Autonomous Cleaning (Scan -> Scoop into Rear Net -> Next Target)")
    print("  [M] Manual Standby Mode")
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
    cv2.resizeWindow(WINDOW_NAME, 1020, 680)

    # Initialize Modules (Default: 20m x 25m water zone)
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
        # 2. AUTONOMOUS CLEANING & GEOFENCE CYCLE
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
        # 3. SPATIAL COVERAGE & PAYLOAD METRICS
        # ----------------------------------------------------
        metrics = geofence.get_metrics(logger.category_counts)

        # ----------------------------------------------------
        # 4. ON-SCREEN HUD OVERLAYS
        # ----------------------------------------------------
        hud_bg = frame[0:95, 0:w].copy()
        cv2.rectangle(frame, (0, 0), (w, 95), (12, 12, 12), -1)
        cv2.addWeighted(hud_bg, 0.35, frame[0:95, 0:w], 0.65, 0, frame[0:95, 0:w])

        # Row 1: System Title & FPS
        cv2.putText(frame, "AQUA-SENTRY MISSION CONSOLE", (15, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (88, 166, 255), 2)
        cv2.putText(frame, f"FPS: {fps:.1f}", (15, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

        # Row 2: State & Core Metrics
        cv2.putText(frame, f"STATE: {cleaner.state}", (110, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, hud_color, 2)
        cv2.putText(frame, f"HAUL: {cleaner.collected_count} items ({metrics['total_weight_kg']} kg | {metrics['total_volume_l']} L)", 
                    (330, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

        # Row 3: Status Message & Area Swept
        cv2.putText(frame, status_msg, (15, 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.46, (230, 230, 230), 1)
        cv2.putText(frame, f"AREA: {metrics['area_covered_sqm']} m2 ({metrics['coverage_pct']}%)", 
                    (15, 92), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (120, 220, 120), 1)

        # ----------------------------------------------------
        # 5. RENDER 2D GEOFENCE RADAR MINI-MAP (TOP-RIGHT CORNER)
        # ----------------------------------------------------
        map_size = 175
        minimap = geofence.render_minimap(map_size=map_size)
        if w > map_size + 20 and h > map_size + 110:
            frame[105:105+map_size, w - map_size - 15:w - 15] = minimap

        cv2.imshow(WINDOW_NAME, frame)

        # ----------------------------------------------------
        # 6. KEYBOARD INTERRUPTS & SAFETY FAILSAFES
        # ----------------------------------------------------
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:
            print("[INFO] Shutting down console...")
            break
        elif key == ord('a'): # Autonomous Mode
            cleaner.set_mode("AUTO")
        elif key == ord('m'): # Manual Standby
            cleaner.set_mode("MANUAL")
        elif key == ord('x'): # EMERGENCY KILL SWITCH
            cleaner.set_mode("KILL")
            print("[ALERT] EMERGENCY STOP ACTIVATED! ALL MOTORS KILLED.")
        elif key == ord('c'): # Toggle Collector Motor
            send_boat_command('C')
        elif key == ord('p'): # Screenshot
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            cap_file = f"captures/cleanup_{timestamp}.jpg"
            cv2.imwrite(cap_file, frame)
            print(f"[SNAPSHOT] Saved: {cap_file}")

        # Direct Manual Steering (Instantly interrupts auto mode!)
        elif key in (ord('w'), ord('s'), ord('a'), ord('d'), 32):
            if cleaner.state != CleanerState.MANUAL_STANDBY:
                cleaner.set_mode("MANUAL")
            
            if key == ord('w'):   send_boat_command('F')
            elif key == ord('s'): send_boat_command('B')
            elif key == ord('a'): send_boat_command('L')
            elif key == ord('d'): send_boat_command('R')
            elif key == 32:       send_boat_command('S')

    # Export Mission Summary upon exit
    summary = logger.export_summary(geofence_mapper=geofence)
    print("\n" + "=" * 60)
    print("                MISSION SUMMARY REPORT")
    print("=" * 60)
    print(f"Mission Duration:        {summary['mission_duration_min']} mins")
    print(f"Total Trash Collected:   {summary['total_items_collected']} items")
    print(f"Estimated Payload Mass:  {summary['payload_estimates']['estimated_weight_kg']} kg")
    print(f"Estimated Volume:        {summary['payload_estimates']['estimated_volume_liters']} Liters")
    print(f"Water Surface Swept:     {summary['spatial_coverage']['water_area_swept_sqm']} m²")
    print(f"Geofence Coverage:       {summary['spatial_coverage']['coverage_percentage']} of {summary['spatial_coverage']['total_preset_pond_sqm']} m²")
    print(f"Total Distance Traveled: {summary['spatial_coverage']['distance_traveled_m']} meters")
    print(f"Collection Rate:         {summary['collection_rate_per_min']} items/min")
    print(f"Composition Breakdown:   {summary['composition_breakdown']}")
    print(f"Mission Log:             trash_data/mission_log.csv")
    print(f"Summary Export:          trash_data/mission_summary.json")
    print("=" * 60)

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
