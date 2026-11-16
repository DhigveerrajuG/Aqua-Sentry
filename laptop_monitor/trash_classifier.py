"""
==============================================================================
Aqua-Sentry Real-Time Trash Classifier & Reflection Rejection Engine
==============================================================================
Combines:
  1. Temporal Persistence Tracking (Anti-Glint / Anti-Reflection):
     Filters out specular water flashes, ripples, and foam that flicker and
     disappear in 1-2 frames. True debris must persist for >= 3 frames.
  2. Multi-Class Classification:
     - YOLOv8 Neural Network integration (if ultralytics installed).
     - Built-in Robust Multi-Feature Geometric & Color Classifier (Fallback).
  3. Geometric Validation:
     Rejects wave crests (abnormal aspect ratios) and shoreline boundaries.
==============================================================================
"""

import cv2
import numpy as np
import math

class TrackedObject:
    def __init__(self, track_id, bbox, class_name, confidence):
        self.track_id = track_id
        self.bbox = bbox # (x, y, w, h)
        self.class_name = class_name
        self.confidence = confidence
        self.centroid = (bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2)
        self.hits = 1       # Consecutive detections
        self.lost_frames = 0 # Frames since last match
        self.status = "CANDIDATE" # CANDIDATE -> VERIFIED -> COLLECTED

class TrashClassifier:
    def __init__(self, use_yolo=False, yolo_weights="yolov8n.pt"):
        self.use_yolo = use_yolo
        self.yolo_model = None
        self.next_track_id = 1
        self.active_tracks = []
        
        # Configuration parameters
        self.min_persistence_frames = 3 # Anti-Glint: Must be seen for 3 frames
        self.max_lost_frames = 4        # Tolerate up to 4 dropped frames
        self.max_match_dist = 65.0      # Maximum Euclidean pixel distance between frames

        if self.use_yolo:
            try:
                from ultralytics import YOLO
                self.yolo_model = YOLO(yolo_weights)
                print(f"[AI] Loaded YOLOv8 weights from {yolo_weights}")
            except Exception as e:
                print(f"[AI WARN] Could not load YOLO ({e}). Using Built-in Robust Classifier.")
                self.use_yolo = False

    def process_frame(self, frame):
        """
        Processes a video frame and returns a list of verified debris objects:
        Each entry: dict(track_id, bbox, class_name, confidence, centroid, status)
        """
        raw_candidates = []

        if self.use_yolo and self.yolo_model is not None:
            raw_candidates = self._detect_yolo(frame)
        else:
            raw_candidates = self._detect_geometric_color(frame)

        # Update temporal persistence tracking (Anti-Glint filter)
        verified_debris = self._update_tracks(raw_candidates, frame.shape)
        return verified_debris

    def _detect_geometric_color(self, frame):
        """
        Multi-feature color and morphological segmentation with geometric filters.
        """
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        h, w, _ = frame.shape

        # Region of Interest: Only water surface (lower 65% of frame)
        roi_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.rectangle(roi_mask, (0, int(h * 0.35)), (w, h), 255, -1)

        # Color Band 1: Styrofoam & White Plastics (High Value, Low Saturation)
        mask_white = cv2.inRange(hsv, np.array([0, 0, 160]), np.array([180, 50, 255]))

        # Color Band 2: Bright Colored Plastics (Bottles, caps, floats)
        mask_bright = cv2.inRange(hsv, np.array([10, 90, 110]), np.array([38, 255, 255]))

        # Color Band 3: Darker plastics / Cans / Metallic
        mask_metal = cv2.inRange(hsv, np.array([85, 40, 60]), np.array([135, 255, 220]))

        combined = cv2.bitwise_or(mask_white, mask_bright)
        combined = cv2.bitwise_or(combined, mask_metal)
        combined = cv2.bitwise_and(combined, roi_mask)

        # Morphological clean up
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        clean = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel, iterations=1)
        clean = cv2.dilate(clean, kernel, iterations=2)

        contours, _ = cv2.findContours(clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []

        for cnt in contours:
            area = cv2.contourArea(cnt)
            # Rejection 1: Size limits (reject tiny noise flakes and massive land boundaries)
            if area < 350 or area > 45000:
                continue

            x, y, cw, ch = cv2.boundingRect(cnt)
            aspect_ratio = float(cw) / float(ch)

            # Rejection 2: Water wave crests / horizontal reflections (elongated streaks)
            if aspect_ratio > 4.2 or aspect_ratio < 0.2:
                continue

            # Crop region to analyze color & texture features
            crop_hsv = hsv[y:y+ch, x:x+cw]
            mean_sat = np.mean(crop_hsv[:, :, 1])
            mean_val = np.mean(crop_hsv[:, :, 2])

            # Debris Classification
            class_name = "Plastic Debris"
            confidence = 0.72

            if mean_val > 195 and mean_sat < 40:
                class_name = "Styrofoam"
                confidence = 0.88
            elif 1.6 <= aspect_ratio <= 3.6 and mean_val > 140:
                class_name = "Plastic Bottle"
                confidence = 0.84
            elif 0.8 <= aspect_ratio <= 1.5 and mean_sat > 70:
                class_name = "Drink Can"
                confidence = 0.79
            elif area > 3500 and mean_sat > 30:
                class_name = "Plastic Bag"
                confidence = 0.76

            candidates.append({
                "bbox": (x, y, cw, ch),
                "class_name": class_name,
                "confidence": confidence,
                "centroid": (x + cw // 2, y + ch // 2),
                "area": area
            })

        return candidates

    def _detect_yolo(self, frame):
        """Runs YOLO inference and maps detections to marine trash classes."""
        results = self.yolo_model(frame, verbose=False)[0]
        candidates = []

        for box in results.boxes:
            conf = float(box.conf[0])
            if conf < 0.45:
                continue

            cls_id = int(box.cls[0])
            cls_name = self.yolo_model.names.get(cls_id, "Trash")
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            x, y, w, h = int(x1), int(y1), int(x2 - x1), int(y2 - y1)

            candidates.append({
                "bbox": (x, y, w, h),
                "class_name": cls_name,
                "confidence": conf,
                "centroid": (x + w // 2, y + h // 2),
                "area": w * h
            })

        return candidates

    def _update_tracks(self, detections, frame_shape):
        """
        Anti-Glint Temporal Persistence Filter:
        Associates candidates across frames. Items must survive >= min_persistence_frames
        to be promoted from CANDIDATE (possible water reflection) to VERIFIED.
        """
        fh, fw = frame_shape[:2]
        intake_y_threshold = int(fh * 0.85)

        # Match detections to existing tracks using Euclidean distance
        matched_tracks = set()
        matched_detections = set()

        for t_idx, track in enumerate(self.active_tracks):
            best_dist = 9999.0
            best_d_idx = -1

            for d_idx, det in enumerate(detections):
                if d_idx in matched_detections:
                    continue

                dx = track.centroid[0] - det["centroid"][0]
                dy = track.centroid[1] - det["centroid"][1]
                dist = math.hypot(dx, dy)

                if dist < self.max_match_dist and dist < best_dist:
                    best_dist = dist
                    best_d_idx = d_idx

            if best_d_idx != -1:
                det = detections[best_d_idx]
                track.bbox = det["bbox"]
                track.centroid = det["centroid"]
                track.class_name = det["class_name"]
                track.confidence = det["confidence"]
                track.hits += 1
                track.lost_frames = 0

                # Promote to verified if seen across consecutive frames
                if track.hits >= self.min_persistence_frames:
                    track.status = "VERIFIED"

                # Check if object reached collection intake
                if track.centroid[1] >= intake_y_threshold:
                    track.status = "COLLECTED"

                matched_tracks.add(t_idx)
                matched_detections.add(best_d_idx)
            else:
                track.lost_frames += 1

        # Create new candidate tracks for unmatched detections
        for d_idx, det in enumerate(detections):
            if d_idx not in matched_detections:
                new_track = TrackedObject(
                    track_id=self.next_track_id,
                    bbox=det["bbox"],
                    class_name=det["class_name"],
                    confidence=det["confidence"]
                )
                self.next_track_id += 1
                self.active_tracks.append(new_track)

        # Prune dead tracks (lost for too many frames or collected)
        surviving_tracks = []
        verified_results = []

        for track in self.active_tracks:
            if track.lost_frames <= self.max_lost_frames and track.status != "COLLECTED":
                surviving_tracks.append(track)
            
            # Only return verified debris (filters out 1-frame water reflections/sun glints)
            if track.status in ("VERIFIED", "COLLECTED"):
                verified_results.append({
                    "track_id": track.track_id,
                    "bbox": track.bbox,
                    "class_name": track.class_name,
                    "confidence": track.confidence,
                    "centroid": track.centroid,
                    "status": track.status,
                    "area": track.bbox[2] * track.bbox[3]
                })

        self.active_tracks = surviving_tracks
        return verified_results
