"""
==============================================================================
Aqua-Sentry Geofence Boundary & Water Area Coverage Mapper
==============================================================================
Functionality:
  1. Preset Virtual Boundary (Geofence):
     - Keeps the catamaran strictly inside a predefined water perimeter (e.g. 25m x 20m pond).
     - Auto-detects perimeter proximity and commands turn-backs to prevent stranding on banks.
  2. Dead Reckoning Odometry & Area Coverage Tracker:
     - Discretizes the water surface into a spatial grid (0.5m x 0.5m cells).
     - Calculates total square meters (m²) swept based on boat swath width (0.6m).
     - Computes real-time water coverage percentage (%).
  3. Trash Weight & Volume Estimation:
     - Converts item counts and categories into estimated kilograms (kg) and Liters (L).
  4. Real-Time 2D Top-Down Mini-Map:
     - Renders a live visual map with geofence borders, covered cells, boat trajectory,
       and collection coordinate markers for the operator console.
==============================================================================
"""

import math
import time
import numpy as np
import cv2

# Approximate mass and volume coefficients per waste class
WASTE_METRICS = {
    "Plastic Bottle": {"mass_kg": 0.030, "volume_l": 0.60},
    "Drink Can":      {"mass_kg": 0.015, "volume_l": 0.33},
    "Styrofoam":      {"mass_kg": 0.012, "volume_l": 0.85},
    "Plastic Bag":    {"mass_kg": 0.010, "volume_l": 0.25},
    "Plastic Debris": {"mass_kg": 0.020, "volume_l": 0.40}
}

class GeofenceMapper:
    def __init__(self, pond_width_m=20.0, pond_length_m=25.0, boat_swath_m=0.6):
        # Geofence dimensions (meters)
        self.width_m = pond_width_m
        self.length_m = pond_length_m
        self.swath_m = boat_swath_m
        self.safety_margin_m = 1.8  # Distance from perimeter that triggers turn-back

        # Catamaran Kinematic Calibration
        self.speed_fwd_mps = 0.55   # Forward speed at PWM 180 (~0.55 m/s)
        self.turn_rate_deg = 45.0   # Turn rate (~45 deg/sec)

        # Pose: start at center-bottom of preset boundary
        self.x = pond_width_m / 2.0
        self.y = 2.5
        self.heading_deg = 90.0     # 90 deg = Facing North / Forward into pond

        # Spatial Coverage Grid (0.5m resolution)
        self.cell_size_m = 0.5
        self.grid_cols = int(pond_width_m / self.cell_size_m)
        self.grid_rows = int(pond_length_m / self.cell_size_m)
        self.coverage_grid = np.zeros((self.grid_rows, self.grid_cols), dtype=np.uint8)

        # Telemetry & History
        self.last_update_time = time.time()
        self.path_history = []
        self.collection_points = []
        self.distance_traveled_m = 0.0

        # Mark initial swath cell
        self._mark_swept_cells(self.x, self.y)

    def update_odometry(self, current_action):
        """
        Updates boat pose (x, y, heading) based on active drive action:
        action in ['F', 'B', 'L', 'R', 'S']
        """
        now = time.time()
        dt = min(now - self.last_update_time, 0.5)
        self.last_update_time = now

        if current_action == 'F':
            rad = math.radians(self.heading_deg)
            dx = self.speed_fwd_mps * math.cos(rad) * dt
            dy = self.speed_fwd_mps * math.sin(rad) * dt
            self.x += dx
            self.y += dy
            dist = math.hypot(dx, dy)
            self.distance_traveled_m += dist
            self._mark_swept_cells(self.x, self.y)

        elif current_action == 'B':
            rad = math.radians(self.heading_deg)
            self.x -= (self.speed_fwd_mps * 0.7) * math.cos(rad) * dt
            self.y -= (self.speed_fwd_mps * 0.7) * math.sin(rad) * dt

        elif current_action == 'L':
            self.heading_deg = (self.heading_deg + self.turn_rate_deg * dt) % 360.0

        elif current_action == 'R':
            self.heading_deg = (self.heading_deg - self.turn_rate_deg * dt) % 360.0

        # Record path breadcrumbs every 0.3s
        if not self.path_history or math.hypot(self.x - self.path_history[-1][0], self.y - self.path_history[-1][1]) > 0.4:
            self.path_history.append((self.x, self.y))

    def check_boundary_safety(self):
        """
        Checks if the catamaran is approaching the preset virtual water boundary.
        Returns:
          is_near_boundary: bool
          recommended_turn: 'L', 'R', or None
          distance_to_edge: float
        """
        # Distances to 4 perimeter edges
        d_left   = self.x
        d_right  = self.width_m - self.x
        d_bottom = self.y
        d_top    = self.length_m - self.y

        min_dist = min(d_left, d_right, d_bottom, d_top)

        if min_dist <= self.safety_margin_m:
            # Boat is near boundary! Calculate angle pointing toward pond center
            center_x = self.width_m / 2.0
            center_y = self.length_m / 2.0
            target_heading = math.degrees(math.atan2(center_y - self.y, center_x - self.x)) % 360.0

            angle_diff = (target_heading - self.heading_deg + 180.0) % 360.0 - 180.0
            turn_cmd = 'L' if angle_diff > 0 else 'R'
            return True, turn_cmd, min_dist

        return False, None, min_dist

    def record_collection_point(self, item_class):
        """Records the coordinate where a piece of debris was scooped."""
        self.collection_points.append((self.x, self.y, item_class))

    def _mark_swept_cells(self, x, y):
        """Marks spatial cells covered by the boat's 0.6m pontoon beam width."""
        col = int(x / self.cell_size_m)
        row = int(y / self.cell_size_m)

        # Mark swath footprint (catamaran width)
        radius_cells = max(1, int((self.swath_m / 2.0) / self.cell_size_m))
        for r in range(max(0, row - radius_cells), min(self.grid_rows, row + radius_cells + 1)):
            for c in range(max(0, col - radius_cells), min(self.grid_cols, col + radius_cells + 1)):
                self.coverage_grid[r, c] = 1

    def get_metrics(self, category_counts):
        """Returns computed area coverage, total mass (kg), and volume (L)."""
        covered_cells = np.sum(self.coverage_grid == 1)
        area_covered_sqm = covered_cells * (self.cell_size_m ** 2)
        total_pond_area_sqm = self.width_m * self.length_m
        coverage_pct = (area_covered_sqm / max(total_pond_area_sqm, 1.0)) * 100.0

        # Trash weight & volume aggregation
        total_weight_kg = 0.0
        total_volume_l = 0.0

        for c_name, count in category_counts.items():
            metrics = WASTE_METRICS.get(c_name, {"mass_kg": 0.02, "volume_l": 0.4})
            total_weight_kg += metrics["mass_kg"] * count
            total_volume_l += metrics["volume_l"] * count

        return {
            "area_covered_sqm": round(area_covered_sqm, 1),
            "total_area_sqm": round(total_pond_area_sqm, 1),
            "coverage_pct": round(coverage_pct, 1),
            "distance_traveled_m": round(self.distance_traveled_m, 1),
            "total_weight_kg": round(total_weight_kg, 2),
            "total_volume_l": round(total_volume_l, 1)
        }

    def render_minimap(self, map_size=200):
        """
        Generates an attractive top-down 2D radar/mini-map showing:
          - Preset Boundary Box
          - Cleaned/Swept Water Cells (Light Blue)
          - Catamaran Track History (Dark Blue)
          - Active Catamaran Position & Heading Arrow (Red/Yellow)
          - Collected Trash Markers (Gold Stars/Dots)
        """
        map_img = np.full((map_size, map_size, 3), 20, dtype=np.uint8) # Dark background

        # Scale factors
        scale_x = (map_size - 20) / float(self.width_m)
        scale_y = (map_size - 20) / float(self.length_m)

        def to_map(px, py):
            mx = int(10 + px * scale_x)
            my = int(map_size - 10 - py * scale_y) # Invert Y for top-down display
            return max(0, min(map_size - 1, mx)), max(0, min(map_size - 1, my))

        # 1. Draw Covered Area Cells
        for r in range(self.grid_rows):
            for c in range(self.grid_cols):
                if self.coverage_grid[r, c] == 1:
                    cx = c * self.cell_size_m
                    cy = r * self.cell_size_m
                    mx1, my1 = to_map(cx, cy)
                    mx2, my2 = to_map(cx + self.cell_size_m, cy + self.cell_size_m)
                    cv2.rectangle(map_img, (mx1, my2), (mx2, my1), (60, 45, 20), -1)

        # 2. Draw Preset Geofence Perimeter
        p_bl = to_map(0, 0)
        p_tr = to_map(self.width_m, self.length_m)
        cv2.rectangle(map_img, p_bl, p_tr, (0, 255, 0), 2) # Green boundary perimeter

        # 3. Draw Path Trajectory
        if len(self.path_history) > 1:
            for i in range(1, len(self.path_history)):
                pt1 = to_map(self.path_history[i-1][0], self.path_history[i-1][1])
                pt2 = to_map(self.path_history[i][0], self.path_history[i][1])
                cv2.line(map_img, pt1, pt2, (180, 120, 40), 1)

        # 4. Draw Collection Points
        for (cx, cy, _) in self.collection_points:
            m_pt = to_map(cx, cy)
            cv2.circle(map_img, m_pt, 3, (0, 215, 255), -1)

        # 5. Draw Catamaran Boat & Heading Arrow
        bx, by = to_map(self.x, self.y)
        cv2.circle(map_img, (bx, by), 5, (0, 0, 255), -1) # Red hull center

        # Heading vector line
        rad = math.radians(self.heading_deg)
        hx = int(bx + 12 * math.cos(rad))
        hy = int(by - 12 * math.sin(rad))
        cv2.line(map_img, (bx, by), (hx, hy), (0, 255, 255), 2)

        # Border overlay
        cv2.rectangle(map_img, (0, 0), (map_size - 1, map_size - 1), (80, 80, 80), 1)
        cv2.putText(map_img, "GEOFENCE RADAR", (8, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 0), 1)
        return map_img
