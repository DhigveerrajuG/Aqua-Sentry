"""
==============================================================================
Aqua-Sentry Live Deck Monitor (Laptop Client)
==============================================================================
Connects to the Aqua-Sentry catamaran camera stream over local Wi-Fi.
Features:
  - Live HUD overlay with central trash collection targeting corridor.
  - Real-time FPS monitor.
  - Single-key snapshot capture ('s' key) saved to /captures folder.
  - Auto-reconnect handling if signal momentarily dips.

Usage:
  1. Connect your laptop Wi-Fi to "AquaSentry-Vision" (Password: aquasentry123).
  2. Run: python monitor_stream.py
  3. Controls:
     - Press 's' to save a snapshot with timestamp.
     - Press 'q' or 'ESC' to exit.
==============================================================================
"""

import cv2
import time
import os
from datetime import datetime

# Stream configuration (Default ESP32-CAM AP IP)
STREAM_URL = "http://192.168.4.1:81/stream"
WINDOW_NAME = "Aqua-Sentry Remote Deck Monitor"

def main():
    print("=" * 60)
    print("  Aqua-Sentry Catamaran Video Telemetry Client")
    print("=" * 60)
    print(f"Connecting to live video stream at: {STREAM_URL}")
    print("Make sure your laptop is connected to Wi-Fi: AquaSentry-Vision")
    print("Controls: [s] Save Snapshot | [q] Exit\n")

    # Create capture output folder
    os.makedirs("captures", exist_ok=True)

    # Initialize video capture
    cap = cv2.VideoCapture(STREAM_URL)

    if not cap.isOpened():
        print(f"[ERROR] Could not open video stream at {STREAM_URL}")
        print("Tip: If running outside, ensure your laptop Wi-Fi is connected to 'AquaSentry-Vision'")
        print("Trying fallback URL: http://192.168.4.1/stream ...")
        cap = cv2.VideoCapture("http://192.168.4.1/stream")
        if not cap.isOpened():
            print("[FATAL] Unable to connect. Please check ESP32-CAM power and Wi-Fi connection.")
            return

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 800, 600)

    prev_time = time.time()
    fps = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[WARN] Dropped frame or connection interrupted. Reconnecting...")
            time.sleep(0.5)
            cap.release()
            cap = cv2.VideoCapture(STREAM_URL)
            continue

        # Calculate FPS
        current_time = time.time()
        fps = 0.9 * fps + 0.1 * (1.0 / max(current_time - prev_time, 0.0001))
        prev_time = current_time

        h, w, _ = frame.shape

        # ==========================================
        # HUD OVERLAYS (Central Intake Guide)
        # ==========================================
        # Central collection intake alignment corridor (guide lines for floating trash)
        intake_left = int(w * 0.35)
        intake_right = int(w * 0.65)
        
        # Guide corridor
        cv2.line(frame, (intake_left, int(h * 0.4)), (intake_left, h), (0, 255, 255), 2)
        cv2.line(frame, (intake_right, int(h * 0.4)), (intake_right, h), (0, 255, 255), 2)
        
        # Center crosshair
        center_x = w // 2
        center_y = int(h * 0.55)
        cv2.drawMarker(frame, (center_x, center_y), (0, 255, 0), cv2.MARKER_CROSS, 20, 2)

        # Status HUD Text
        cv2.putText(frame, "AQUA-SENTRY [DECK CAM]", (15, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(frame, f"FPS: {fps:.1f}", (15, 60), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(frame, "INTAKE CORRIDOR", (intake_left + 10, h - 20), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        cv2.imshow(WINDOW_NAME, frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:  # 'q' or ESC
            print("[INFO] Quitting stream viewer.")
            break
        elif key == ord('s'):  # Save screenshot
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"captures/debris_{timestamp}.jpg"
            cv2.imwrite(filename, frame)
            print(f"[SAVED] Snapshot recorded to: {filename}")

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
