"""
==============================================================================
Aqua-Sentry Prototype: Live Webcam & Autonomous Teleoperation Console
==============================================================================
Designed for Prototype Bench & Pool Testing:
  1. Video Source: USB Webcam (Plug-and-play directly into laptop).
  2. Communication: Direct USB Serial to Arduino (COM port) or Preview Mode.
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
from datetime import datetime

# ==========================================
# PROTOTYPE CONFIGURATION
# ==========================================
# Camera Index: 0 = Default / Built-in, 1 = External USB Webcam
CAMERA_INDEX = 0

# Arduino Serial Connection (Set to your COM port, e.g. "COM3", or None for preview)
SERIAL_PORT = "COM3"
BAUD_RATE   = 115200

# Window Settings
WINDOW_TITLE = "Aqua-Sentry Catamaran Prototype Console"

# ==========================================
# SERIAL HARDWARE BRIDGE
# ==========================================
ser = None
try:
    import serial
    import serial.tools.list_ports
    
    # Auto-detect Arduino if available
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
    """Sends a 1-character command ('F','B','L','R','S','A','M','C','X') to Arduino."""
    if ser and ser.is_open:
        try:
            ser.write(cmd_char.encode('utf-8'))
        except Exception:
            pass
    print(f">> COMMAND SENT: [{cmd_char}]")

# ==========================================
# TRASH DETECTION (HSV COLOR + CONTOURS)
# ==========================================
def find_floating_trash(frame):
    """
    Detects floating bottles, styrofoam, and plastics on water.
    Returns: list of (x, y, w, h, cx, cy, area) sorted by closest to boat first.
    """
    h, w, _ = frame.shape
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # Focus detection on the water ahead (ignore upper 30% horizon/room)
    roi_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.rectangle(roi_mask, (0, int(h * 0.30)), (w, h), 255, -1)

    # Detect bright white/clear plastics & styrofoam
    mask_white = cv2.inRange(hsv, np.array([0, 0, 150]), np.array([180, 55, 255]))

    # Detect bright colored debris (bottles, caps, colored plastics)
    mask_colored = cv2.inRange(hsv, np.array([10, 80, 100]), np.array([35, 255, 255]))

    mask = cv2.bitwise_or(mask_white, mask_colored)
    mask = cv2.bitwise_and(mask, roi_mask)

    # Clean noise
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    clean = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    clean = cv2.dilate(clean, kernel, iterations=2)

    contours, _ = cv2.findContours(clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    targets = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if 400 < area < 45000: # Filter out specks and huge walls
            x, y, cw, ch = cv2.boundingRect(cnt)
            cx = x + cw // 2
            cy = y + ch // 2
            targets.append((x, y, cw, ch, cx, cy, area))

    # Sort closest debris to catamaran first (bottom of screen)
    targets.sort(key=lambda t: t[5], reverse=True)
    return targets

# ==========================================
# MAIN PROTOTYPE APPLICATION
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

    # Set 720p resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_TITLE, 1024, 600)

    # Initialize data logging
    os.makedirs("trash_data/captures", exist_ok=True)
    csv_file = "trash_data/collected_trash.csv"
    if not os.path.exists(csv_file):
        with open(csv_file, "w", newline="") as f:
            csv.writer(f).writerow(["Timestamp", "Item_ID", "Status"])

    # State Variables
    mode = "MANUAL" # MANUAL, AUTO_SEARCH, AUTO_APPROACH, AUTO_INGEST
    collected_count = 0
    state_timer = time.time()
    last_steer_time = 0
    status_text = "Prototype ready. Use W/A/S/D to drive or press [A] for Auto Cleaning."

    print("\n[CONTROLS]:")
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
            print("[WARN] Dropped webcam frame.")
            time.sleep(0.05)
            continue

        h, w, _ = frame.shape
        center_x = w // 2
        now = time.time()

        # ----------------------------------------------------
        # 1. INTAKE CORRIDOR (Guides to Rear Trash Netting)
        # ----------------------------------------------------
        intake_left = int(w * 0.35)
        intake_right = int(w * 0.65)
        cv2.line(frame, (intake_left, int(h * 0.40)), (intake_left, h), (0, 255, 255), 2)
        cv2.line(frame, (intake_right, int(h * 0.40)), (intake_right, h), (0, 255, 255), 2)
        cv2.putText(frame, "REAR TRASH NET CORRIDOR", (intake_left + 15, h - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        # ----------------------------------------------------
        # 2. DETECT FLOATING TRASH
        # ----------------------------------------------------
        targets = find_floating_trash(frame)
        active_target = None

        if targets:
            active_target = targets[0] # Closest target
            for (tx, ty, tw, th, cx, cy, area) in targets:
                cv2.rectangle(frame, (tx, ty), (tx + tw, ty + th), (0, 255, 0), 2)
                cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)

            # Draw target vector to closest debris
            _, _, _, _, pcx, pcy, _ = active_target
            cv2.line(frame, (center_x, h - 30), (pcx, pcy), (0, 255, 0), 2)
            cv2.putText(frame, "TRASH TARGET", (active_target[0], max(active_target[1] - 8, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

        # ----------------------------------------------------
        # 3. PROTOTYPE AUTONOMOUS CLEANING LOGIC
        # ----------------------------------------------------
        if mode.startswith("AUTO"):
            if active_target:
                _, _, _, _, pcx, pcy, _ = active_target
                error_x = pcx - center_x
                deadband = int(w * 0.08)

                # Check if debris is right at the intake mouth (ready to scoop)
                if pcy > int(h * 0.78) and (intake_left - 30 <= pcx <= intake_right + 30):
                    if mode != "AUTO_INGEST":
                        mode = "AUTO_INGEST"
                        state_timer = now
                        send_command('C') # Ensure collector paddle is ON
                        send_command('F') # Push forward over the trash

                    status_text = "SCOOPING: Driving over trash into rear netting cover!"

                    # Drive over it for 2.0 seconds to deposit in rear net
                    if now - state_timer > 2.0:
                        collected_count += 1
                        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        with open(csv_file, "a", newline="") as f:
                            csv.writer(f).writerow([time_str, collected_count, "COLLECTED"])

                        # Save proof snapshot
                        snap_name = f"trash_data/captures/haul_{collected_count}.jpg"
                        cv2.imwrite(snap_name, frame)
                        print(f"[COLLECTION] Trash #{collected_count} scooped! Saved proof to {snap_name}")

                        mode = "AUTO_SEARCH"
                        status_text = f"Collected trash #{collected_count}! Looking for next target..."
                else:
                    # Steering to center the debris
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
                # No debris in sight: cruise forward slowly looking for trash
                mode = "AUTO_SEARCH"
                status_text = "Searching water surface for floating trash..."
                if now - last_steer_time > 0.6:
                    send_command('F')
                    last_steer_time = now

        # ----------------------------------------------------
        # 4. ON-SCREEN HUD OVERLAYS
        # ----------------------------------------------------
        # Top banner
        cv2.rectangle(frame, (0, 0), (w, 65), (20, 20, 20), -1)
        cv2.line(frame, (0, 65), (w, 65), (50, 50, 50), 1)

        # Mode color
        mode_color = (0, 255, 0) if mode.startswith("AUTO") else (88, 166, 255)
        if mode == "EMERGENCY_STOP": mode_color = (0, 0, 255)

        cv2.putText(frame, "AQUA-SENTRY PROTOTYPE", (15, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        cv2.putText(frame, f"MODE: {mode}", (15, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, mode_color, 2)
        cv2.putText(frame, f"COLLECTED: {collected_count}", (260, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        cv2.putText(frame, f"IN SIGHT: {len(targets)}", (440, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

        # Status Ribbon (Bottom)
        cv2.rectangle(frame, (0, h - 35), (w, h), (15, 15, 15), -1)
        cv2.putText(frame, f">> {status_text}", (15, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (220, 220, 220), 1)

        cv2.imshow(WINDOW_TITLE, frame)

        # ----------------------------------------------------
        # 5. KEYBOARD CONTROLS & SAFETY OVERRIDES
        # ----------------------------------------------------
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:
            print("[INFO] Exiting console...")
            send_command('S')
            break
        elif key == ord('a'):
            mode = "AUTO_SEARCH"
            send_command('A')
            send_command('C')
            print("[MODE] Switched to Autonomous Cleaning Mode.")
        elif key == ord('m'):
            mode = "MANUAL"
            send_command('M')
            send_command('S')
            status_text = "Manual mode active."
            print("[MODE] Switched to Manual Mode.")
        elif key == ord('x'): # EMERGENCY KILL SWITCH
            mode = "EMERGENCY_STOP"
            send_command('X')
            status_text = "EMERGENCY STOP ACTIVATED! ALL MOTORS STOPPED."
            print("[ALERT] EMERGENCY STOP SENT!")
        elif key == ord('c'):
            send_command('C')
        elif key == ord('p'):
            t_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            snap_path = f"trash_data/captures/manual_{t_str}.jpg"
            cv2.imwrite(snap_path, frame)
            print(f"[SNAPSHOT] Saved: {snap_path}")

        # Direct Manual Steering (Instantly interrupts auto mode!)
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
