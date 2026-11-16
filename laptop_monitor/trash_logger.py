"""
==============================================================================
Aqua-Sentry Mission Data Logger & Active Learning Harvester
==============================================================================
Manages:
  1. Real-time CSV logging of all detected and collected trash events.
  2. Aggregated mission analytics (counts, waste breakdown, collection rate).
  3. Spatial Area Coverage & Payload Metrics (m², % covered, kg collected, Liters).
  4. Active dataset collection: saves cropped images with YOLO annotation labels.
==============================================================================
"""

import os
import csv
import json
import time
from datetime import datetime
import cv2

class TrashLogger:
    def __init__(self, data_dir="trash_data"):
        self.data_dir = data_dir
        self.images_dir = os.path.join(data_dir, "dataset", "images")
        self.labels_dir = os.path.join(data_dir, "dataset", "labels")
        self.log_file = os.path.join(data_dir, "mission_log.csv")
        self.summary_file = os.path.join(data_dir, "mission_summary.json")

        os.makedirs(self.images_dir, exist_ok=True)
        os.makedirs(self.labels_dir, exist_ok=True)

        self.start_time = time.time()
        self.total_detected = 0
        self.total_collected = 0
        self.category_counts = {}
        self.collected_ids = set()

        self._init_csv()

    def _init_csv(self):
        """Initializes the CSV log file with standard metadata headers."""
        if not os.path.exists(self.log_file):
            with open(self.log_file, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Timestamp", "Track_ID", "Class_Name", "Confidence",
                    "BBox_X", "BBox_Y", "BBox_W", "BBox_H",
                    "Estimated_Area_Px", "Status"
                ])

    def log_detection(self, track_id, class_name, confidence, bbox, area, status="TRACKING"):
        """Logs a single detection or collection event into the mission log."""
        x, y, w, h = bbox
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if status == "COLLECTED" and track_id not in self.collected_ids:
            self.collected_ids.add(track_id)
            self.total_collected += 1
            self.category_counts[class_name] = self.category_counts.get(class_name, 0) + 1

        with open(self.log_file, mode='a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                now_str, track_id, class_name, f"{confidence:.2f}",
                x, y, w, h, area, status
            ])

    def harvest_dataset_sample(self, frame, bbox, class_id, class_name):
        """Saves a cropped image and YOLO-formatted bounding box label (.txt)."""
        x, y, w, h = bbox
        fh, fw, _ = frame.shape

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        base_name = f"debris_{class_name}_{timestamp}"

        img_path = os.path.join(self.images_dir, f"{base_name}.jpg")
        cv2.imwrite(img_path, frame)

        xc = (x + w / 2.0) / fw
        yc = (y + h / 2.0) / fh
        nw = w / float(fw)
        nh = h / float(fh)

        label_path = os.path.join(self.labels_dir, f"{base_name}.txt")
        with open(label_path, "w") as f:
            f.write(f"{class_id} {xc:.6f} {yc:.6f} {nw:.6f} {nh:.6f}\n")

    def export_summary(self, geofence_mapper=None):
        """Generates a mission summary JSON report including spatial coverage & weight."""
        elapsed_min = max((time.time() - self.start_time) / 60.0, 0.01)
        collection_rate = self.total_collected / elapsed_min

        spatial_metrics = {}
        if geofence_mapper:
            spatial_metrics = geofence_mapper.get_metrics(self.category_counts)

        summary = {
            "mission_start": datetime.fromtimestamp(self.start_time).strftime("%Y-%m-%d %H:%M:%S"),
            "mission_duration_min": round(elapsed_min, 2),
            "total_items_collected": self.total_collected,
            "collection_rate_per_min": round(collection_rate, 2),
            "composition_breakdown": self.category_counts,
            "spatial_coverage": {
                "water_area_swept_sqm": spatial_metrics.get("area_covered_sqm", 0.0),
                "total_preset_pond_sqm": spatial_metrics.get("total_area_sqm", 0.0),
                "coverage_percentage": f"{spatial_metrics.get('coverage_pct', 0.0)}%",
                "distance_traveled_m": spatial_metrics.get("distance_traveled_m", 0.0)
            },
            "payload_estimates": {
                "estimated_weight_kg": spatial_metrics.get("total_weight_kg", 0.0),
                "estimated_volume_liters": spatial_metrics.get("total_volume_l", 0.0)
            }
        }

        with open(self.summary_file, "w") as f:
            json.dump(summary, f, indent=4)
        return summary
