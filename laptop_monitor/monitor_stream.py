"""
==============================================================================
Aqua-Sentry Live Teleoperation & AI Trash Tracking Monitor (Laptop Client)
==============================================================================
Features:
  1. Live Video Stream with HUD & Intake Corridor.
  2. Teleoperation Keyboard Override:
     - [W] Forward | [S] Reverse | [A] Left | [D] Right | [SPACE] Brake
     - [M] Switch to Manual Mode | [K] Switch to Auto Mode
     - [C] Toggle Trash Collector | [X] Emergency Kill Switch
  3. AI Trash Hunting / Visual Servoing (Press [T] to toggle):
     - Uses HSV color & contour segmentation to isolate floating debris.
     - Calculates lateral error relative to the central intake channel.
     - Automatically transmits directional trim commands to center the trash!
  4. Snapshot capture [P] saved to /captures.
==============================================================================
"""

import cv2
import numpy as np
import time
import os
import urllib.request
from datetime import datetime

# Network Configuration
BASE_URL = "http://192.168.4.1"
STREAM_URL = f"{BASE_URL}:81/stream"
CONTROL_URL = f"{BASE_URL}/control?cmd="
WINDOW_NAME = "Aqua-Sentry Teleoperation & AI Hunting Console"

def send_boat_command(cmd_char):
    """Sends non-blocking HTTP control commands to the catamaran."""
    try:
        url = f"{CONTROL_URL}{cmd_char}"
        req = urllib.request.Request(url, headers={'User-Agent': 'AquaSentryClient'})
        # Short timeout to avoid blocking video rendering loop
        urllib.request.urlopen(req, timeout=0.15)
    except Exception:
        pass # Ignore transient network drops during high-speed streaming

def detect_floating_debris(frame):
    """
    Identifies floating surface debris using adaptive color & morphological segmentation.
    Returns: list of (x, y, w, h, centroid_x, centroid_y, area) sorted by proximity.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    h, w, _ = frame.shape

    # Focus detection primarily on the water surface (middle & lower half of frame)
    roi_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.rectangle(roi_mask, (0, int(h * 0.35)), (w, h), 255, -1)

    # Multi-band mask for typical water surface trash (white styrofoam, plastics, bright cans)
    # Range 1: High-brightness/white plastic & styrofoam
    lower_white = np.array([0, 0, 160])
    upper_white = np.array([180, 55, 255])
    mask_white = cv2.inRange(hsv, lower_white, upper_white)

    # Range 2: Bright colored plastics (red/orange/yellow floats)
    lower_bright = np.array([10, 100, 120])
    upper_bright = np.array([35, 255, 255])
    mask_bright = cv2.inRange(hsv, lower_bright, upper_bright)

    # Combine masks and apply ROI
    combined_mask = cv2.bitwise_or(mask_white, mask_bright)
    combined_mask = cv2.bitwise_and(combined_mask, roi_mask)

    # Noise removal with morphological operations
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    clean_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel, iterations=1)
    clean_mask = cv2.dilate(clean_mask, kernel, iterations=2)

    contours, _ = cv2.findContours(clean_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if 400 < area < 40000: # Filter out tiny noise and massive bank reflections
            x, y, cw, ch = cv2.boundingRect(cnt)
            cx = x + cw // 2
            cy = y + ch // 2
            candidates.append((x, y, cw, ch, cx, cy, area))

    # Sort candidates by Y coordinate (closest to the boat at bottom of frame first)
    candidates.sort(key=lambda c: c[5], reverse=True)
    return candidates

def main():
    print("=" * 65)
    print("  Aqua-Sentry Teleoperation & AI Vision Console")
    print("=" * 65)
    print("Connecting to live stream at:", STREAM_URL)
    print("Keyboard Controls:")
    print("  [W] Forward  | [S] Reverse  | [A] Left  | [D] Right  | [SPACE] Brake")
    print("  [M] Manual Mode | [K] Auto Mode | [C] Toggle Collector | [X] E-STOP")
    print("  [T] Toggle AI Trash Hunting | [P] Save Snapshot | [Q] Exit\n")

    os.makedirs("captures", exist_ok=True)
    cap = cv2.VideoCapture(STREAM_URL)

    if not cap.isOpened():
        print(f"[WARN] Port 81 failed, trying fallback port 80...")
        cap = cv2.VideoCapture(f"{BASE_URL}/stream")
        if not cap.isOpened():
            print("[FATAL] Unable to connect. Ensure your laptop is connected to 'AquaSentry-Vision'")
            return

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 960, 640)

    ai_hunting_enabled = False
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

        # FPS calculation
        now = time.time()
        fps = 0.9 * fps + 0.1 * (1.0 / max(now - prev_time, 0.0001))
        prev_time = now

        h, w, _ = frame.shape
        center_x = w // 2

        # Intake target corridor boundaries (35% to 65% width)
        intake_left = int(w * 0.35)
        intake_right = int(w * 0.65)

        # Draw intake guide lines
        cv2.line(frame, (intake_left, int(h * 0.45)), (intake_left, h), (0, 255, 255), 2)
        cv2.line(frame, (intake_right, int(h * 0.45)), (intake_right, h), (0, 255, 255), 2)

        # Detect floating debris targets
        targets = detect_floating_debris(frame)
        active_target = None

        if targets:
            active_target = targets[0] # Focus on closest debris
            for (tx, ty, tw, th, cx, cy, area) in targets:
                # Green box for targets, thicker for primary lock
                is_primary = (active_target[0] == tx and active_target[1] == ty)
                box_color = (0, 255, 0) if is_primary else (200, 200, 200)
                cv2.rectangle(frame, (tx, ty), (tx + tw, ty + th), box_color, 2 if is_primary else 1)
                cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)

            # Target Lock Vector to primary target
            ptx, pty, ptw, pth, pcx, pcy, _ = active_target
            cv2.line(frame, (center_x, h - 20), (pcx, pcy), (0, 255, 0), 2)
            cv2.putText(frame, "TARGET LOCK", (ptx, max(pty - 8, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            # AI Visual Servoing Navigation Logic
            if ai_hunting_enabled and (now - last_ai_steering_time > 0.4):
                error_x = pcx - center_x
                deadband = int(w * 0.08) # 8% tolerance deadband

                if error_x < -deadband:
                    # Debris is on the LEFT -> Pulse Left Thruster
                    send_boat_command('L')
                    cv2.putText(frame, "<< STEER LEFT", (intake_left - 130, h - 50),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
                elif error_x > deadband:
                    # Debris is on the RIGHT -> Pulse Right Thruster
                    send_boat_command('R')
                    cv2.putText(frame, "STEER RIGHT >>", (intake_right + 10, h - 50),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
                else:
                    # Aligned inside intake corridor -> Drive Forward!
                    send_boat_command('F')
                    cv2.putText(frame, "== ON TARGET (CRUISE) ==", (center_x - 110, h - 50),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                last_ai_steering_time = now

        # On-screen Telemetry HUD
        hud_bg = frame[0:75, 0:w].copy()
        cv2.rectangle(frame, (0, 0), (w, 75), (20, 20, 20), -1)
        cv2.addWeighted(hud_bg, 0.4, frame[0:75, 0:w], 0.6, 0, frame[0:75, 0:w])

        cv2.putText(frame, "AQUA-SENTRY TELEOP CONSOLE", (15, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (88, 166, 255), 2)
        cv2.putText(frame, f"FPS: {fps:.1f}", (15, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        ai_status_color = (0, 255, 0) if ai_hunting_enabled else (120, 120, 120)
        cv2.putText(frame, f"AI HUNTING [T]: {'ACTIVE' if ai_hunting_enabled else 'OFF'}", 
                    (160, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, ai_status_color, 2)
        cv2.putText(frame, f"MODE: {current_mode_label}", (380, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        cv2.imshow(WINDOW_NAME, frame)

        # Keyboard Event Handler
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:
            break
        elif key == ord('w'):
            send_boat_command('F')
        elif key == ord('s'):
            send_boat_command('B')
        elif key == ord('a'):
            send_boat_command('L')
        elif key == ord('d'):
            send_boat_command('R')
        elif key == 32: # SPACEBAR: Brake
            send_boat_command('S')
        elif key == ord('x'): # EMERGENCY KILL
            send_boat_command('X')
            print("[ALERT] EMERGENCY STOP SENT!")
        elif key == ord('m'): # Manual Mode
            send_boat_command('M')
            current_mode_label = "MANUAL"
        elif key == ord('k'): # Auto Mode
            send_boat_command('A')
            current_mode_label = "AUTONOMOUS"
        elif key == ord('c'): # Toggle Collector
            send_boat_command('C')
        elif key == ord('t'): # Toggle AI Trash Hunting
            ai_hunting_enabled = not ai_hunting_enabled
            if ai_hunting_enabled:
                send_boat_command('M') # Visual servoing runs in manual trim mode
                current_mode_label = "AI_HUNTING"
            print(f"[AI] Trash Tracking: {'ENABLED' if ai_hunting_enabled else 'DISABLED'}")
        elif key == ord('p'): # Screenshot
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = f"captures/debris_{timestamp}.jpg"
            cv2.imwrite(fname, frame)
            print(f"[SAVED] {fname}")

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
