"""
==============================================================================
Aqua-Sentry Prototype: Live Webcam & Autonomous Teleoperation Console
==============================================================================
Designed for Prototype Bench & Pool Testing:
  1. Video Source: USB Webcam (Plug-and-play directly into laptop).
  2. Quick Color Calibration Trackbars:
     - Press [T] to open live HSV sliders to calibrate detection for your test debris.
     - Live Mask preview (White = Detected Trash, Black = Ignored Water).
     - Automatically saves your calibrated values to hsv_config.json!
  3. Visual Guidance: Intake corridor lines showing where trash enters the rear net.
  4. Autonomous Cycle: Detects debris -> Steers to it -> Drives over it -> Targets next!
  5. Operator Safety: Instant W/A/S/D manual takeover + [X] Emergency Kill Switch.
==============================================================================
"""

import cv2
import numpy as np
import time
import os
import csv
import json
from datetime import datetime

# ==========================================
# PROTOTYPE CONFIGURATION
# ==========================================
CAMERA_INDEX = 0      # 0 = Built-in / First Webcam, 1 = External USB Webcam
SERIAL_PORT  = "COM3" # Arduino COM port (e.g. "COM3" on Windows, or None)
BAUD_RATE    = 115200
WINDOW_TITLE = "Aqua-Sentry Catamaran Prototype Console"
CONFIG_FILE  = "hsv_config.json"

# ==========================================
# HSV COLOR CALIBRATION DEFAULTS
# ==========================================
# Default values optimized for bright floating plastics / white styrofoam
hsv_params = {
    "h_min": 0,   "h_max": 180,
    "s_min": 0,   "s_max": 65,
    "v_min": 140, "v_max": 255
}

def load_hsv_config():
    global hsv_params
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                hsv_params.update(saved)
                print(f"[CONFIG] Loaded saved HSV parameters from {CONFIG_FILE}")
        except Exception:
            pass

def save_hsv_config():
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(hsv_params, f, indent=4)
        print(f"[CONFIG] Saved HSV calibration to {CONFIG_FILE}")
    except Exception as e:
        print(f"[WARN] Could not save config: {e}")

load_hsv_config()

# ==========================================
# TRACKBAR CALLBACKS
# ==========================================
trackbars_created = False
TRACKBAR_WINDOW = "Trash Color Calibration [Sliders]"

def on_trackbar(_):
    global hsv_params
    if trackbars_created:
        hsv_params["h_min"] = cv2.getTrackbarPos("H Min", TRACKBAR_WINDOW)
        hsv_params["h_max"] = cv2.getTrackbarPos("H Max", TRACKBAR_WINDOW)
        hsv_params["s_min"] = cv2.getTrackbarPos("S Min", TRACKBAR_WINDOW)
        hsv_params["s_max"] = cv2.getTrackbarPos("S Max", TRACKBAR_WINDOW)
        hsv_params["v_min"] = cv2.getTrackbarPos("V Min", TRACKBAR_WINDOW)
        hsv_params["v_max"] = cv2.getTrackbarPos("V Max", TRACKBAR_WINDOW)

def setup_trackbars():
    global trackbars_created
    cv2.namedWindow(TRACKBAR_WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(TRACKBAR_WINDOW, 420, 280)
    cv2.createTrackbar("H Min", TRACKBAR_WINDOW, hsv_params["h_min"], 180, on_trackbar)
    cv2.createTrackbar("H Max", TRACKBAR_WINDOW, hsv_params["h_max"], 180, on_trackbar)
    cv2.createTrackbar("S Min", TRACKBAR_WINDOW, hsv_params["s_min"], 255, on_trackbar)
    cv2.createTrackbar("S Max", TRACKBAR_WINDOW, hsv_params["s_max"], 255, on_trackbar)
    cv2.createTrackbar("V Min", TRACKBAR_WINDOW, hsv_params["v_min"], 255, on_trackbar)
    cv2.createTrackbar("V Max", TRACKBAR_WINDOW, hsv_params["v_max"], 255, on_trackbar)
    trackbars_created = True

# ==========================================
# SERIAL HARDWARE BRIDGE
# ==========================================
ser = None
try:
    import serial
    import serial.tools.list_ports
    
    available_ports = [p.device for p in serial.tools.list_ports.comports()]
    target_port = SERIAL_PORT if SERIAL_PORT in available_ports else (available_ports[0] if available_ports else None)
    
    if target_port:
        ser = serial.Serial(target_port, BAUD_RATE, timeout=0.1)
        print(f"[SERIAL] Connected to Arduino on {target_port} at {BAUD_RATE} baud.")
    else:
        print("[SERIAL] No Arduino detected. Running in PREVIEW / SIMULATION mode.")
except Exception as e:
    print(f"[SERIAL] Running without hardware serial ({e}).")

def send_command(cmd_char):
    """Sends a 1-character command to Arduino."""
    if ser and ser.is_open:
        try:
            ser.write(cmd_char.encode('utf-8'))
        except Exception:
            pass
    print(f">> COMMAND SENT: [{cmd_char}]")

# ==========================================
# TRASH DETECTION USING CALIBRATED HSV
# ==========================================
def find_floating_trash(frame):
    """
    Applies calibrated HSV thresholding and morphology.
    Returns: (targets, clean_mask)
    targets: list of (x, y, w, h, cx, cy, area) sorted closest to boat first.
    """
    h, w, _ = frame.shape
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # Focus detection on water surface (ignore upper 30% horizon/ceiling)
    roi_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.rectangle(roi_mask, (0, int(h * 0.30)), (w, h), 255, -1)

    lower_bound = np.array([hsv_params["h_min"], hsv_params["s_min"], hsv_params["v_min"]])
    upper_bound = np.array([hsv_params["h_max"], hsv_params["s_max"], hsv_params["v_max"]])

    mask = cv2.inRange(hsv, lower_bound, upper_bound)
    mask = cv2.bitwise_and(mask, roi_mask)

    # Clean up small ripples and glints
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    clean = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    clean = cv2.dilate(clean, kernel, iterations=2)

    contours, _ = cv2.findContours(clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    targets = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if 400 < area < 45000: # Ignore tiny specks and whole-screen noise
            x, y, cw, ch = cv2.boundingRect(cnt)
            cx = x + cw // 2
            cy = y + ch // 2
            targets.append((x, y, cw, ch, cx, cy, area))

    targets.sort(key=lambda t: t[5], reverse=True)
    return targets, clean

# ==========================================
# MAIN APPLICATION
# ==========================================
def main():
    print("=" * 65)
    print("  Aqua-Sentry Prototype Mission Console (Webcam Edition)")
    print("=" * 65)
    print(f"Connecting to Webcam (Index {CAMERA_INDEX})...")

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"[WARN] Camera index {CAMERA_INDEX} failed. Trying index 1 (External USB Webcam)...")
        cap = cv2.VideoCapture(1)
        if not cap.isOpened():
            print("[FATAL] No webcam found! Please ensure your USB webcam is plugged in.")
            return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_TITLE, 1024, 600)

    os.makedirs("trash_data/captures", exist_ok=True)
    csv_file = "trash_data/collected_trash.csv"
    if not os.path.exists(csv_file):
        with open(csv_file, "w", newline="") as f:
            csv.writer(f).writerow(["Timestamp", "Item_ID", "Status"])

    # State Variables
    mode = "MANUAL"
    calibration_mode = False
    collected_count = 0
    state_timer = time.time()
    last_steer_time = 0
    status_text = "Prototype ready. Use W/A/S/D to drive or press [A] for Auto Cleaning."

    print("\n[CONTROLS]:")
    print("  T       : Toggle Quick Color Calibration Trackbars")
    print("  W/A/S/D : Manual Differential Steering")
    print("  SPACE   : Brake / Stop")
    print("  X       : EMERGENCY KILL SWITCH (Stops All Motors)")
    print("  A       : Start Autonomous Water Cleaning Cycle")
    print("  M       : Switch to Manual Standby")
    print("  C       : Toggle Trash Collector Motor")
    print("  P       : Take Snapshot")
    print("  Q       : Exit Console\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue

        h, w, _ = frame.shape
        center_x = w // 2
        now = time.time()

        # ----------------------------------------------------
        # 1. INTAKE CORRIDOR (Guides to Rear Netting)
        # ----------------------------------------------------
        intake_left = int(w * 0.35)
        intake_right = int(w * 0.65)
        cv2.line(frame, (intake_left, int(h * 0.40)), (intake_left, h), (0, 255, 255), 2)
        cv2.line(frame, (intake_right, int(h * 0.40)), (intake_right, h), (0, 255, 255), 2)
        cv2.putText(frame, "REAR TRASH NET CORRIDOR", (intake_left + 15, h - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        # ----------------------------------------------------
        # 2. DETECT TRASH & GET THRESHOLD MASK
        # ----------------------------------------------------
        targets, mask_clean = find_floating_trash(frame)
        active_target = None

        if targets:
            active_target = targets[0]
            for (tx, ty, tw, th, cx, cy, area) in targets:
                cv2.rectangle(frame, (tx, ty), (tx + tw, ty + th), (0, 255, 0), 2)
                cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)

            # Target Lock Vector
            _, _, _, _, pcx, pcy, _ = active_target
            cv2.line(frame, (center_x, h - 30), (pcx, pcy), (0, 255, 0), 2)
            cv2.putText(frame, "TRASH TARGET", (active_target[0], max(active_target[1] - 8, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

        # ----------------------------------------------------
        # 3. COLOR CALIBRATION PREVIEW INSET
        # ----------------------------------------------------
        if calibration_mode:
            # Show live threshold mask as small Picture-in-Picture in top-right
            mask_bgr = cv2.cvtColor(mask_clean, cv2.COLOR_GRAY2BGR)
            pip_w, pip_h = int(w * 0.25), int(h * 0.25)
            pip_mask = cv2.resize(mask_bgr, (pip_w, pip_h))
            frame[75:75+pip_h, w - pip_w - 15:w - 15] = pip_mask
            cv2.rectangle(frame, (w - pip_w - 15, 75), (w - 15, 75 + pip_h), (0, 255, 255), 2)
            cv2.putText(frame, "CALIBRATION MASK", (w - pip_w - 10, 95),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)

        # ----------------------------------------------------
        # 4. AUTONOMOUS CLEANING LOGIC
        # ----------------------------------------------------
        if mode.startswith("AUTO"):
            if active_target:
                _, _, _, _, pcx, pcy, _ = active_target
                error_x = pcx - center_x
                deadband = int(w * 0.08)

                if pcy > int(h * 0.78) and (intake_left - 30 <= pcx <= intake_right + 30):
                    if mode != "AUTO_INGEST":
                        mode = "AUTO_INGEST"
                        state_timer = now
                        send_command('C')
                        send_command('F')

                    status_text = "SCOOPING: Driving over trash into rear netting cover!"

                    if now - state_timer > 2.0:
                        collected_count += 1
                        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        with open(csv_file, "a", newline="") as f:
                            csv.writer(f).writerow([time_str, collected_count, "COLLECTED"])

                        snap_name = f"trash_data/captures/haul_{collected_count}.jpg"
                        cv2.imwrite(snap_name, frame)
                        print(f"[COLLECTION] Trash #{collected_count} scooped! Saved proof to {snap_name}")

                        mode = "AUTO_SEARCH"
                        status_text = f"Collected trash #{collected_count}! Looking for next target..."
                else:
                    mode = "AUTO_APPROACH"
                    if now - last_steer_time > 0.4:
                        if error_x < -deadband:
                            send_command('L')
                            status_text = "Steering LEFT toward floating debris..."
                        elif error_x > deadband:
                            send_command('R')
                            status_text = "Steering RIGHT toward floating debris..."
                        else:
                            send_command('F')
                            status_text = "Aligned! Driving forward to collect..."
                        last_steer_time = now
            else:
                mode = "AUTO_SEARCH"
                status_text = "Searching water surface for floating trash..."
                if now - last_steer_time > 0.6:
                    send_command('F')
                    last_steer_time = now

        # ----------------------------------------------------
        # 5. ON-SCREEN HUD OVERLAYS
        # ----------------------------------------------------
        cv2.rectangle(frame, (0, 0), (w, 65), (20, 20, 20), -1)
        cv2.line(frame, (0, 65), (w, 65), (50, 50, 50), 1)

        mode_color = (0, 255, 0) if mode.startswith("AUTO") else (88, 166, 255)
        if mode == "EMERGENCY_STOP": mode_color = (0, 0, 255)

        cv2.putText(frame, "AQUA-SENTRY PROTOTYPE", (15, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        cv2.putText(frame, f"MODE: {mode}", (15, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, mode_color, 2)
        cv2.putText(frame, f"COLLECTED: {collected_count}", (260, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        cv2.putText(frame, f"IN SIGHT: {len(targets)}", (440, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

        calib_status = "[CALIBRATION: ON - Press T to Close]" if calibration_mode else "[T: Color Calibrate]"
        calib_color = (0, 215, 255) if calibration_mode else (120, 120, 120)
        cv2.putText(frame, calib_status, (600, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.50, calib_color, 1)

        # Status Ribbon (Bottom)
        cv2.rectangle(frame, (0, h - 35), (w, h), (15, 15, 15), -1)
        cv2.putText(frame, f">> {status_text}", (15, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (220, 220, 220), 1)

        cv2.imshow(WINDOW_TITLE, frame)

        # ----------------------------------------------------
        # 6. KEYBOARD CONTROLS
        # ----------------------------------------------------
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:
            print("[INFO] Exiting console...")
            send_command('S')
            save_hsv_config()
            break
        elif key == ord('t'): # Toggle Calibration Trackbars
            calibration_mode = not calibration_mode
            if calibration_mode:
                setup_trackbars()
                status_text = "Calibration Mode ON: Adjust sliders so trash is white and water is black. Press [T] to save."
            else:
                try:
                    cv2.destroyWindow(TRACKBAR_WINDOW)
                except Exception:
                    pass
                save_hsv_config()
                status_text = "Calibration Saved! Sliders closed."
        elif key == ord('a'):
            mode = "AUTO_SEARCH"
            send_command('A')
            send_command('C')
        elif key == ord('m'):
            mode = "MANUAL"
            send_command('M')
            send_command('S')
            status_text = "Manual mode active."
        elif key == ord('x'): # EMERGENCY KILL SWITCH
            mode = "EMERGENCY_STOP"
            send_command('X')
            status_text = "EMERGENCY STOP ACTIVATED! ALL MOTORS STOPPED."
        elif key == ord('c'):
            send_command('C')
        elif key == ord('p'):
            t_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            snap_path = f"trash_data/captures/manual_{t_str}.jpg"
            cv2.imwrite(snap_path, frame)
            print(f"[SNAPSHOT] Saved: {snap_path}")

        # Direct Manual Steering
        elif key in (ord('w'), ord('s'), ord('a'), ord('d'), 32):
            if mode != "MANUAL":
                mode = "MANUAL"
                send_command('M')
            
            if key == ord('w'):   send_command('F'); status_text = "Manual: Forward"
            elif key == ord('s'): send_command('B'); status_text = "Manual: Reverse"
            elif key == ord('a'): send_command('L'); status_text = "Manual: Steer Left"
            elif key == ord('d'): send_command('R'); status_text = "Manual: Steer Right"
            elif key == 32:       send_command('S'); status_text = "Manual: Brake / Stopped"

    cap.release()
    cv2.destroyAllWindows()
    if ser and ser.is_open:
        ser.close()

if __name__ == "__main__":
    main()
