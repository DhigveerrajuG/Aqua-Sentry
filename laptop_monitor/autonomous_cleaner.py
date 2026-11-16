"""
==============================================================================
Aqua-Sentry Autonomous Water Surface Cleaning Coordinator (Water-Roomba Mode)
==============================================================================
Lifecycle:
  1. GEOFENCE_GUARD:  Monitors preset pond boundaries and rebounds inward if near perimeter.
  2. SEARCH_PATROL:   Performs systematic area sweeping when surrounding water is clear.
  3. TARGET_APPROACH: Locks onto closest verified debris and closes distance.
  4. INGEST_RUNOVER:  Drives over debris with paddle spinning to deposit it into rear net.
  5. VERIFY_NEXT:     Confirms collection into rear cover, records coordinates, and
                      locks onto the next closest target.
  6. SAFETY_OVERRIDE: Immediate human teleoperation takeover & one-touch kill switch.
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
    BOUNDARY_REBOUND   = "BOUNDARY_REBOUND"
    EMERGENCY_STOP     = "EMERGENCY_STOP"

class AutonomousCleaner:
    def __init__(self, send_cmd_fn, geofence_mapper=None):
        self.send_cmd = send_cmd_fn
        self.mapper = geofence_mapper
        self.state = CleanerState.MANUAL_STANDBY
        
        # State timers and transitions
        self.state_start_time = time.time()
        self.last_cmd_time = 0
        self.current_action = 'S'
        self.patrol_phase = 0
        
        # Target Tracking
        self.locked_target_id = None
        self.locked_target_class = None
        self.locked_target_box = None
        self.ingest_start_time = 0
        self.collected_count = 0
        self.status_message = "Standing by in Manual Mode. Press [A] for Autonomous Water-Roomba Mode."

        # Calibration parameters
        self.ingest_duration_sec = 2.0
        self.patrol_cruise_sec   = 5.0
        self.patrol_scan_sec     = 1.2
        self.cmd_interval_sec    = 0.35
        self.boundary_turn_sec   = 1.8

    def set_mode(self, mode):
        """Switches system between Autonomous Cleaning and Manual Standby."""
        now = time.time()
        if mode == "AUTO":
            self.state = CleanerState.SEARCH_PATROL
            self.state_start_time = now
            self.status_message = "[AUTO] Autonomous Cleaning Active. Patrolling within preset boundary..."
            self._send_action('A')
            self._send_action('C') # Ensure collector paddle is spinning
        elif mode == "MANUAL":
            self.state = CleanerState.MANUAL_STANDBY
            self.locked_target_id = None
            self.status_message = "[MANUAL] Operator Override Active. Autonomous cleaner paused."
            self._send_action('M')
            self._send_action('S')
        elif mode == "KILL":
            self.state = CleanerState.EMERGENCY_STOP
            self.locked_target_id = None
            self.status_message = "[ALERT] EMERGENCY KILL SWITCH ENGAGED! ALL THRUSTERS CUT."
            self._send_action('X')

    def _send_action(self, cmd):
        self.current_action = cmd
        self.send_cmd(cmd)

    def update(self, frame, verified_debris, logger):
        """
        Executes autonomous cleaning cycle while enforcing preset geofence perimeter.
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

        # Update Dead Reckoning & Area Coverage Map
        if self.mapper:
            self.mapper.update_odometry(self.current_action)

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
        # 2. PRESET GEOFENCE PERIMETER SAFETY CHECK
        # ----------------------------------------------------
        if self.mapper and self.state != CleanerState.INGEST_RUNOVER:
            is_near_bound, turn_cmd, dist_edge = self.mapper.check_boundary_safety()
            if is_near_bound and self.state != CleanerState.BOUNDARY_REBOUND:
                self.state = CleanerState.BOUNDARY_REBOUND
                self.state_start_time = now
                self.boundary_turn_cmd = turn_cmd if turn_cmd else 'R'
                self.status_message = f"[GEOFENCE] Near perimeter ({dist_edge:.1f}m)! Rebounding inward toward pond center."

        # Handle Perimeter Rebound Turn
        if self.state == CleanerState.BOUNDARY_REBOUND:
            hud_color = (0, 140, 255) # Orange warning
            elapsed_turn = now - self.state_start_time

            if now - self.last_cmd_time > self.cmd_interval_sec:
                self._send_action(self.boundary_turn_cmd)
                self.last_cmd_time = now

            if elapsed_turn >= self.boundary_turn_sec:
                # Rebound complete: boat is safely facing inward
                self.state = CleanerState.SEARCH_PATROL
                self.state_start_time = now
                self.status_message = "[GEOFENCE] Safely cleared perimeter. Resuming autonomous area patrol."

            return self._build_status(hud_color, None, None)

        # ----------------------------------------------------
        # 3. SEARCH & PATROL (Surrounding Area Scan)
        # ----------------------------------------------------
        if self.state == CleanerState.SEARCH_PATROL:
            hud_color = (0, 215, 255) # Yellow

            if verified_debris:
                best_target = self._select_best_target(verified_debris)
                self.locked_target_id = best_target["track_id"]
                self.locked_target_class = best_target["class_name"]
                self.locked_target_box = best_target["bbox"]
                self.state = CleanerState.TARGET_APPROACH
                self.state_start_time = now
                self.status_message = f"[LOCK] Trash Identified: {self.locked_target_class} #{self.locked_target_id}. Approaching..."
            else:
                elapsed = now - self.state_start_time
                if self.patrol_phase == 0:
                    self.status_message = f"[PATROL] Sweeping water surface... Forward ({int(self.patrol_cruise_sec - elapsed)}s)"
                    if now - self.last_cmd_time > self.cmd_interval_sec:
                        self._send_action('F')
                        self.last_cmd_time = now
                    if elapsed >= self.patrol_cruise_sec:
                        self.patrol_phase = 1
                        self.state_start_time = now
                else:
                    self.status_message = "[PATROL] Sector scan: pivoting to inspect surrounding waterway..."
                    if now - self.last_cmd_time > self.cmd_interval_sec:
                        self._send_action('R')
                        self.last_cmd_time = now
                    if elapsed >= self.patrol_scan_sec:
                        self.patrol_phase = 0
                        self.state_start_time = now

        # ----------------------------------------------------
        # 4. TARGET APPROACH & VISUAL SERVOING
        # ----------------------------------------------------
        elif self.state == CleanerState.TARGET_APPROACH:
            hud_color = (0, 255, 0) # Green

            matched = None
            for item in verified_debris:
                if item["track_id"] == self.locked_target_id:
                    matched = item
                    break

            if not matched and verified_debris:
                matched = self._select_best_target(verified_debris)
                self.locked_target_id = matched["track_id"]
                self.locked_target_class = matched["class_name"]

            if matched:
                x, y, w, h = matched["bbox"]
                cx, cy = matched["centroid"]
                target_box = (x, y, w, h)
                target_vector = ((center_x, fh - 20), (cx, cy))

                error_x = cx - center_x
                deadband = int(fw * 0.07)

                # Check if trash has reached intake mouth
                if cy >= intake_bottom_threshold and (intake_left - 30 <= cx <= intake_right + 30):
                    self.state = CleanerState.INGEST_RUNOVER
                    self.ingest_start_time = now
                    self.status_message = f"[COLLECTING] Driving over {self.locked_target_class}... Ingesting into rear net!"
                    self._send_action('C')
                    self._send_action('F')
                    self.last_cmd_time = now
                else:
                    if now - self.last_cmd_time > self.cmd_interval_sec:
                        if error_x < -deadband:
                            self._send_action('L')
                            self.status_message = f"[APPROACH] Steering LEFT toward {self.locked_target_class} #{self.locked_target_id}"
                        elif error_x > deadband:
                            self._send_action('R')
                            self.status_message = f"[APPROACH] Steering RIGHT toward {self.locked_target_class} #{self.locked_target_id}"
                        else:
                            self._send_action('F')
                            self.status_message = f"[ALIGNED] Centered on {self.locked_target_class}! Advancing directly..."
                        self.last_cmd_time = now
            else:
                self.status_message = "[WARN] Target lost from view. Returning to patrol search..."
                self.state = CleanerState.SEARCH_PATROL
                self.state_start_time = now
                self.locked_target_id = None

        # ----------------------------------------------------
        # 5. INGESTION & RUN-OVER (Scoop into Rear Net Cover)
        # ----------------------------------------------------
        elif self.state == CleanerState.INGEST_RUNOVER:
            hud_color = (255, 0, 255) # Magenta
            elapsed_ingest = now - self.ingest_start_time

            if now - self.last_cmd_time > self.cmd_interval_sec:
                self._send_action('F')
                self.last_cmd_time = now

            self.status_message = f"[SCOOPING] Depositing into rear collection cover... ({elapsed_ingest:.1f}s / {self.ingest_duration_sec}s)"

            if elapsed_ingest >= self.ingest_duration_sec:
                self.state = CleanerState.VERIFY_COLLECTED
                self.state_start_time = now
                self.collected_count += 1

                # Record coordinate on spatial map
                if self.mapper:
                    self.mapper.record_collection_point(self.locked_target_class)

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
        # 6. VERIFY COLLECTION & NEXT TARGET TRANSITION
        # ----------------------------------------------------
        elif self.state == CleanerState.VERIFY_COLLECTED:
            hud_color = (0, 255, 0)
            self.status_message = f"[SUCCESS] Trash #{self.locked_target_id} in rear net! Acquiring next target..."

            if now - self.state_start_time > 0.6:
                self.locked_target_id = None
                self.locked_target_box = None

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
                    self.state = CleanerState.SEARCH_PATROL
                    self.state_start_time = now
                    self.patrol_phase = 0

        return self._build_status(hud_color, target_box, target_vector)

    def _select_best_target(self, targets):
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
