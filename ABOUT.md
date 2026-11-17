# About Aqua-Sentry 🌊

## 1. Problem Statement & Motivation
Every year, over **14 million tons of plastic** enter Earth's aquatic ecosystems, with rivers and urban canals acting as primary conduits transporting land-based waste directly into oceans. Floating plastics, styrofoam, beverage cans, and food packaging degrade aquatic habitats, poison marine fauna, block drainage culverts, and fragment into toxic microplastics.

Commercial marine waste-collection vessels (such as large industrial trash skimmers) often cost tens of thousands of dollars, demand diesel fuel, and require full-time marine crews—making them inaccessible for small municipal ponds, university campuses, park lakes, and community irrigation channels.

**Aqua-Sentry** was created to bridge this gap: an open-source, affordable, lightweight Autonomous Surface Vessel (ASV) designed for automated floating waste collection in calm inland waters.

---

## 2. WasteShark-Inspired Hydrodynamic Architecture
Traditional small-scale garbage boats rely on motorized paddle wheels, rotating rake conveyors, or Archimedes screws to lift garbage out of the water. In practice, these mechanical rollers present major failure points:
* Floating weeds, plastic bags, and nylon fishing lines constantly wrap around rotating shafts, stalling motors and burning motor drivers.
* Motorized rollers consume 40%–60% of total onboard battery energy.

Inspired by the industrial **WasteShark** catamaran design, Aqua-Sentry utilizes a **passive hydrodynamic flow-through collection system**:
1. **Twin-Hull Catamaran:** Twin parallel PVC pontoons create a clean central throat (intake mouth).
2. **Natural Hydrodynamic Trapping:** As the catamaran cruises forward under differential thruster propulsion, water flows freely through the central channel and escapes through the porous rear mesh.
3. **Passive Retention:** Floating waste enters the mouth, passes through the hulls, and remains trapped inside the rear collection basket purely by the craft's forward momentum.
4. **Zero Moving Collection Parts:** 100% of onboard battery energy is preserved for propulsion and navigation, and mechanical jam risk is eliminated entirely.

---

## 3. System Architecture & Workflows

```text
+-----------------------------------------------------------------------------------+
|                                  LAPTOP CONSOLE                                   |
|  - OpenCV Computer Vision: Floating Debris Detection                              |
|  - Quick HSV Calibration Sliders (Press T)                                        |
|  - Intake Guidance Overlay (Pontoon Alignment Corridor)                           |
|  - Autonomous Navigation Planner & Visual Servoing                                |
|  - Operator Teleoperation (W/A/S/D) & Instant Emergency Kill Switch [X]          |
+-----------------------------------------------------------------------------------+
                                         |
                       [USB Serial / Wireless Telemetry]
                                         v
+-----------------------------------------------------------------------------------+
|                            AQUA-SENTRY EMBEDDED CONTROLLER                        |
|                                    (Arduino Uno)                                  |
|                                                                                   |
|   +-----------------------+     +-----------------------+     +---------------+   |
|   | Differential Thruster |     | Waterproof Ultrasonic |     | 3S LiPo Safe  |   |
|   | Propulsion (L298N)    |     | Obstacle Avoid (60cm) |     | Cutoff (9.9V) |   |
|   +-----------------------+     +-----------------------+     +---------------+   |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                                 PHYSICAL CRAFT                                    |
|   [Left Pontoon] <======= Central Intake Channel =======> [Right Pontoon]         |
|   - Forward Water Inflow                                  - Rear Mesh Basket      |
+-----------------------------------------------------------------------------------+
```

---

## 4. Hardware Bill of Materials (BOM)

| Component | Specification | Purpose |
| :--- | :--- | :--- |
| **Pontoons** | 2x 3" or 4" PVC Pipes (75–90 cm length) + 4x End Caps | Water buoyancy & catamaran roll stability |
| **Deck Frame** | Acrylic sheet / Aluminium flat bar / PVC joints | Structural bridge maintaining 25–30 cm throat |
| **Propulsion** | 2x 12V Waterproof DC Thruster Motors with Propellers | Differential steering & forward cruise |
| **Motor Driver** | 1x L298N (or BTS7960) Dual H-Bridge Driver | Independent left/right motor speed & direction |
| **Microcontroller** | 1x Arduino Uno R3 / Nano (ATmega328P) | Real-time motion control, avoidance & safety |
| **Obstacle Sensor** | 1x JSN-SR04T Waterproof Ultrasonic Transceiver | Front deck obstacle collision prevention |
| **Camera Sensor** | 1x Standard USB Webcam (720p / 1080p) | Front-facing optical debris tracking |
| **Battery Pack** | 1x 12V 3S LiPo (2200–5000 mAh) or 12V SLA Battery | High-current propulsion power source |
| **Voltage Regulator**| 1x 12V-to-5V (3A) DC-DC Buck Converter / UBEC | Regulated logic power for Arduino & sensors |
| **Enclosure** | 1x IP65 / IP67 Waterproof Electrical Junction Box | Watertight protection for electronics |
| **Collection Basket**| 1x Porous Plastic Storage Basket / Mesh Laundry Net | Passive flow-through waste containment |

---

## 5. Key Innovations & Design Highlights
* **Zero-Lag Plug-and-Play Vision:** Utilizes a standard USB webcam connected directly to the laptop, bypassing the severe latency, low frame rate, and power brownout issues of micro-Wi-Fi cameras.
* **On-the-Fly Lighting Calibration:** A single keystroke (`T`) opens interactive HSV sliders and a live binary mask, allowing the craft to be calibrated for any pond, lighting condition, or waste type in under 10 seconds.
* **Fail-Safe Watchdog Architecture:** If communication between the laptop and the vessel is interrupted for more than 2 seconds while in manual mode, the Arduino automatically disengages all thrusters.
* **Non-Destructive LiPo Protection:** An analog voltage divider continuously monitors cell health, shutting down motors if voltage drops below $9.9\text{V}$ to protect the battery from swelling or thermal runaway.

---

## 6. Project Roadmap
- [x] Differential propulsion firmware & ultrasonic avoidance FSM.
- [x] 3S LiPo low-voltage safety cutoff.
- [x] USB Webcam vision tracking with central intake alignment corridor.
- [x] Live HSV color calibration trackbars with auto-saving JSON config.
- [x] Transition from active rollers to WasteShark passive flow-through mesh basket.
- [ ] Field-testing in natural open pond environments.
- [ ] Optional long-range 433 MHz LoRa telemetry bridge for extended outdoor missions.
- [ ] Integration of onboard GPS waypoint autonomous navigation for large lake surveys.
