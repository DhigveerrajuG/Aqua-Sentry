# Repository Ruleset & Engineering Standards 📜

This document outlines the engineering protocols, code conventions, branch governance, and physical marine safety rules governing the **Aqua-Sentry** repository.

---

## 1. Branch Governance & PR Workflow

### Core Branch Rule: Protected `main`
* **Direct pushes to `main` are strictly forbidden.** All code changes, documentation updates, and bug fixes must arrive via a Pull Request (PR) from a descriptive feature or fix branch.
* Branch Naming Convention:
  * `feature/<feature-name>` (e.g., `feature/mesh-intake-calibration`)
  * `fix/<bug-description>` (e.g., `fix/ultrasonic-deadzone-filtering`)
  * `docs/<topic>` (e.g., `docs/wiring-schematic-update`)
  * `refactor/<subsystem>` (e.g., `refactor/serial-bridge-timeout`)

### PR Review & Merge Criteria
Before any PR can be merged into `main`:
1. All newly added features must be tested on both simulated and/or physical hardware.
2. Code must compile without warnings or deprecation errors.
3. Documentation (`README.md`, pin tables, or configuration notes) must be kept up to date with any hardware or software changes.

---

## 2. Commit Message Standards (Conventional Commits)

Commit messages must follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```text
<type>(<scope>): <short description in present tense>

[optional body explaining the reasoning behind the change]
```

### Allowed Types:
* **`feat`**: A new user-facing feature or firmware capability.
* **`fix`**: A bug fix or hardware edge-case mitigation.
* **`docs`**: Documentation changes only (`README.md`, `ABOUT.md`, code comments).
* **`refactor`**: Code restructuring that neither adds a feature nor fixes a bug.
* **`perf`**: A code change that improves performance (e.g. OpenCV frame rate optimizations).
* **`test`**: Adding or modifying unit tests, simulation test cases, or benchtop validation.
* **`chore`**: Maintenance tasks, library dependency updates, or `.gitignore` modifications.

---

## 3. Firmware & Software Coding Standards

### Embedded C++ (Arduino Firmware):
* **Non-Blocking Architecture:** Never use blocking `delay()` calls within loop functions or state machines. All intervals and timers must use `millis()` non-blocking timestamp comparisons.
* **Pin & Constant Management:** All GPIO pins, timing limits, and calibration constants must be declared at the top of the file as `const uint8_t` or `constexpr`. Never scatter magic numbers throughout motor control logic.
* **Motor Safety Defaults:** Actuator pins must be initialized to a safe `OFF` / neutral state immediately during `setup()`.
* **Robust Telemetry:** All debug output via `Serial.print()` must use the flash-string macro `F("...")` to conserve internal SRAM on ATmega328P microcontrollers.

### Python Ground Station (`laptop_monitor/`):
* **PEP 8 Compliance:** Follow standard Python formatting conventions (4-space indentation, clear variable naming).
* **Defensive Hardware Connections:** Camera capture (`cv2.VideoCapture`) and Serial ports (`serial.Serial`) must handle disconnects and reconnection attempts gracefully without terminating the program unexpectedly.
* **Non-Blocking Key Handlers:** Keyboard event polling (`cv2.waitKey(1)`) must not introduce frame stutter or block the main video loop.

---

## 4. Physical Marine & Field Safety Rules

Operating electrical machinery in aquatic environments presents unique safety hazards. All team members and contributors must adhere to the following safety rules:

### A. Pre-Deployment Bench Test Protocol
Every vessel must complete a "dry bench test" before touching water:
1. Propellers must be tested with hands and tools completely clear.
2. The software Emergency Kill Switch (`X` key) must be verified to immediately cut thruster power.
3. The ultrasonic obstacle avoidance sequence must be verified by hand before water testing.

### B. LiPo Battery Safety Rules
1. Never discharge a 3S LiPo battery below **9.9V (3.3V per cell)**. The firmware's Low-Voltage Cut-Off (LVCO) must never be bypassed.
2. Always inspect LiPo packs for physical puffing, denting, or swelling before connecting to the boat.
3. Always store and charge LiPo batteries in a fireproof LiPo-safe bag or metal container.
4. An inline marine fuse (10A–15A) must always be present on the main positive battery lead.

### C. Water Ingress & Flotation Rules
1. Both PVC pontoons must be tested for airtightness before mounting electronics.
2. The electronics enclosure (IP65 box) must be checked for positive seal with all cable glands tightly compressed.
3. When testing with tethered USB cables, a foam flotation collar must be attached to the cable to prevent it from sinking into the propellers.
