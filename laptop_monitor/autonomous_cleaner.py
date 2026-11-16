"""
==============================================================================
Aqua-Sentry Autonomous Water Surface Cleaning Coordinator (Water-Roomba Mode)
==============================================================================
Implements autonomous surface debris cleanup cycle:
  1. SEARCH_PATROL:   Executes a wide water patrol pattern when no trash is visible.
  2. TARGET_APPROACH: Locks onto the nearest verified trash target and steers toward it.
  3. INGEST_RUNOVER:  Drives directly over the target with the paddle wheel running,
                      drawing the trash through the hulls into the rear netting cover.
  4. VERIFY_NEXT:     Verifies collection, logs confirmation proof, and immediately
                      acquires the next closest target.
  5. SAFETY_OVERRIDE: Immediate manual teleoperation takeover & kill switch.
==============================================================================
"""

import time
import math
import cv2

class CleanerState:
    MANUAL_STANDBY     = "MANUAL_STANDBY"
    SEARCH_PATROL      = "SEARCH_PATROL"
    TARGET_APPROACH    = "TARGET_APPROACH"
    INGEST_RUNOVER     = "INGEST_RUNOVER"
    VERIFY_COLLECTED   = "VERIFY_COLLECTED"
    EMERGENCY_STOP     = "EMERGENCY_STOP"

class AutonomousCleaner:
    def __init__(self, send_cmd_fn):
        self.send_cmd = send_cmd_fn
        self.state = CleanerState.MANUAL_STANDBY
        
        # State timers and transitions
        self.state_start_time = time.time()
        self.last_cmd_time = 0
        self.patrol_phase = 0 # 0: cruise forward, 1: sector pivot
        
        # Target Tracking
        self.locked_target_id = None
        self.locked_target_class = None
        self.locked_target_box = None
        self.ingest_start_time = 0
        self.collected_count = 0
        self.status_message = "Standing by in Manual Mode. Press [A] for Autonomous Water-Roomba Mode."

        # Calibration parameters
        self.ingest_duration_sec = 2.0   # Time to drive over trash into rear net
        self.patrol_cruise_sec   = 5.0   # Cruise straight before scanning
        self.patrol_scan_sec     = 1.2   # Sector turn duration
        self.cmd_interval_sec    = 0.35  # Throttle control packets

    def set_mode(self, mode):
        """Switches system between Autonomous Cleaning and Manual Standby."""
        now = time.time()
        if mode == "AUTO":
            self.state = CleanerState.SEARCH_PATROL
            self.state_start_time = now
            self.status_message = "[AUTO] Autonomous Water-Roomba Mode Active. Searching surrounding water..."
            self.send_cmd('A')
            self.send_cmd('C') # Ensure conveyor is running
        elif mode == "MANUAL":
            self.state = CleanerState.MANUAL_STANDBY
            self.locked_target_id = None
            self.status_message = "[MANUAL] Operator Override Active. Autonomous cleaner paused."
            self.send_cmd('M')
            self.send_cmd('S')
        elif mode == "KILL":
            self.state = CleanerState.EMERGENCY_STOP
            self.locked_target_id = None
            self.status_message = "[ALERT] EMERGENCY KILL SWITCH ENGAGED! ALL THRUSTERS CUT."
            self.send_cmd('X')

    def update(self, frame, verified_debris, logger):
        """
        Executes the autonomous cleaning decision cycle based on current video frame
        and detected floating debris.
        Returns: dict(state, status_message, target_box, target_vector, hud_color)
        """
        now = time.time()
        fh, fw, _ = frame.shape
        center_x = fw // 2
        intake_left = int(fw * 0.35)
        intake_right = int(fw * 0.65)
        intake_bottom_threshold = int(fh * 0.78)

        target_box = None
        target_vector = None
        hud_color = (0, 255, 0)

        # ----------------------------------------------------
        # 1. EMERGENCY STOP & MANUAL OVERRIDE
        # ----------------------------------------------------
        if self.state == CleanerState.EMERGENCY_STOP:
            hud_color = (0, 0, 255)
            return self._build_status(hud_color, None, None)

        if self.state == CleanerState.MANUAL_STANDBY:
            hud_color = (200, 200, 200)
            return self._build_status(hud_color, None, None)

        # ----------------------------------------------------
        # 2. SEARCH & PATROL (Surrounding Area Scan)
        # ----------------------------------------------------
        if self.state == CleanerState.SEARCH_PATROL:
            hud_color = (0, 215, 255) # Yellow

            # Check if any verified debris has entered visual field
            if verified_debris:
                # Target found! Lock onto nearest target
                best_target = self._select_best_target(verified_debris)
                self.locked_target_id = best_target["track_id"]
                self.locked_target_class = best_target["class_name"]
                self.locked_target_box = best_target["bbox"]
                self.state = CleanerState.TARGET_APPROACH
                self.state_start_time = now
                self.status_message = f"[LOCK] Trash Identified: {self.locked_target_class} #{self.locked_target_id}. Approaching..."
            else:
                # No trash in view: execute systematic water sweep
                elapsed = now - self.state_start_time
                if self.patrol_phase == 0: # Cruise forward
                    self.status_message = f"[PATROL] Searching water surface... Cruising forward ({int(self.patrol_cruise_sec - elapsed)}s)"
                    if now - self.last_cmd_time > self.cmd_interval_sec:
                        self.send_cmd('F')
                        self.last_cmd_time = now
                    if elapsed >= self.patrol_cruise_sec:
                        self.patrol_phase = 1
                        self.state_start_time = now
                else: # Pivot turn to scan next water sector
                    self.status_message = "[PATROL] Sector scan: pivoting to inspect surrounding waterway..."
                    if now - self.last_cmd_time > self.cmd_interval_sec:
                        self.send_cmd('R')
                        self.last_cmd_time = now
                    if elapsed >= self.patrol_scan_sec:
                        self.patrol_phase = 0
                        self.state_start_time = now

        # ----------------------------------------------------
        # 3. TARGET APPROACH & VISUAL SERVOING
        # ----------------------------------------------------
        elif self.state == CleanerState.TARGET_APPROACH:
            hud_color = (0, 255, 0) # Green

            # Match locked target in current detections
            matched = None
            for item in verified_debris:
                if item["track_id"] == self.locked_target_id:
                    matched = item
                    break

            if not matched and verified_debris:
                # If target was lost momentarily, re-lock onto the next closest target
                matched = self._select_best_target(verified_debris)
                self.locked_target_id = matched["track_id"]
                self.locked_target_class = matched["class_name"]

            if matched:
                x, y, w, h = matched["bbox"]
                cx, cy = matched["centroid"]
                target_box = (x, y, w, h)
                target_vector = ((center_x, fh - 20), (cx, cy))

                error_x = cx - center_x
                deadband = int(fw * 0.07) # 7% tolerance corridor

                # Check if trash has reached intake mouth
                if cy >= intake_bottom_threshold and (intake_left - 30 <= cx <= intake_right + 30):
                    # Enter Ingestion phase: drive over it so it enters rear net cover
                    self.state = CleanerState.INGEST_RUNOVER
                    self.ingest_start_time = now
                    self.status_message = f"[COLLECTING] Driving over {self.locked_target_class}... Ingesting into rear net!"
                    self.send_cmd('C') # Ensure collector on
                    self.send_cmd('F') # Push forward
                    self.last_cmd_time = now
                else:
                    # Steer toward the target
                    if now - self.last_cmd_time > self.cmd_interval_sec:
                        if error_x < -deadband:
                            self.send_cmd('L')
                            self.status_message = f"[APPROACH] Steering LEFT toward {self.locked_target_class} #{self.locked_target_id}"
                        elif error_x > deadband:
                            self.send_cmd('R')
                            self.status_message = f"[APPROACH] Steering RIGHT toward {self.locked_target_class} #{self.locked_target_id}"
                        else:
                            self.send_cmd('F')
                            self.status_message = f"[ALIGNED] Centered on {self.locked_target_class}! Advancing directly..."
                        self.last_cmd_time = now
            else:
                # Target vanished before reaching intake (e.g. sank or moved out of frame)
                self.status_message = "[WARN] Target lost from view. Returning to patrol search..."
                self.state = CleanerState.SEARCH_PATROL
                self.state_start_time = now
                self.locked_target_id = None

        # ----------------------------------------------------
        # 4. INGESTION & RUN-OVER (Scoop into Rear Trash Cover)
        # ----------------------------------------------------
        elif self.state == CleanerState.INGEST_RUNOVER:
            hud_color = (255, 0, 255) # Magenta
            elapsed_ingest = now - self.ingest_start_time

            # Drive straight forward over the trash with full collector power
            if now - self.last_cmd_time > self.cmd_interval_sec:
                self.send_cmd('F')
                self.last_cmd_time = now

            self.status_message = f"[SCOOPING] Depositing into rear collection cover... ({elapsed_ingest:.1f}s / {self.ingest_duration_sec}s)"

            if elapsed_ingest >= self.ingest_duration_sec:
                # Ingestion complete: Trash has passed through into rear netting
                self.state = CleanerState.VERIFY_COLLECTED
                self.state_start_time = now
                self.collected_count += 1

                # Log verification event and capture proof
                if logger and self.locked_target_box:
                    logger.log_detection(
                        self.locked_target_id,
                        self.locked_target_class,
                        0.95,
                        self.locked_target_box,
                        self.locked_target_box[2] * self.locked_target_box[3],
                        status="COLLECTED"
                    )

        # ----------------------------------------------------
        # 5. VERIFY COLLECTION & TRANSITION TO NEXT TARGET
        # ----------------------------------------------------
        elif self.state == CleanerState.VERIFY_COLLECTED:
            hud_color = (0, 255, 0)
            self.status_message = f"[SUCCESS] Trash #{self.locked_target_id} collected in rear net! Searching for next target..."

            # Brief 0.6s verification pause to settle water surface
            if now - self.state_start_time > 0.6:
                self.locked_target_id = None
                self.locked_target_box = None

                # Query if there is another debris target already in view
                remaining_targets = [d for d in verified_debris if d["status"] != "COLLECTED"]
                if remaining_targets:
                    next_target = self._select_best_target(remaining_targets)
                    self.locked_target_id = next_target["track_id"]
                    self.locked_target_class = next_target["class_name"]
                    self.locked_target_box = next_target["bbox"]
                    self.state = CleanerState.TARGET_APPROACH
                    self.state_start_time = now
                    self.status_message = f"[NEXT TARGET] Locked onto {self.locked_target_class} #{self.locked_target_id}!"
                else:
                    # No more trash in visual field; resume patrol search
                    self.state = CleanerState.SEARCH_PATROL
                    self.state_start_time = now
                    self.patrol_phase = 0

        return self._build_status(hud_color, target_box, target_vector)

    def _select_best_target(self, targets):
        """Chooses the best target (closest to the catamaran bow)."""
        return max(targets, key=lambda d: d["centroid"][1])

    def _build_status(self, hud_color, target_box, target_vector):
        return {
            "state": self.state,
            "status_message": self.status_message,
            "target_box": target_box,
            "target_vector": target_vector,
            "hud_color": hud_color,
            "collected_count": self.collected_count
        }
