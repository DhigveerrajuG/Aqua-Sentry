# Security Policy 🛡️

## 1. Supported Versions

Security updates and critical firmware fixes are applied to the following branches:

| Version | Supported |
| :--- | :--- |
| `main` | :white_check_mark: Active |
| Feature Branches | :x: Development only |

---

## 2. Reporting a Vulnerability

If you discover a security vulnerability, software flaw that causes actuator runaways, or safety risk in Aqua-Sentry, please report it responsibly:

1. **Do not create a public GitHub issue.**
2. Send an email or private message to the repository maintainer (`DhigveerrajuG`) detailing:
   * A description of the vulnerability.
   * Steps or script required to reproduce the behavior.
   * Affected hardware or software components.
3. You will receive an acknowledgment within **48 hours**. We will coordinate a fix before disclosing the issue publicly.

---

## 3. Physical & Electrical Safety Guidelines

Because Aqua-Sentry combines high-capacity lithium batteries, dual high-current DC thrusters, and aquatic operation, hardware safety is of paramount importance:

### High-Voltage & High-Current Safety:
* **Inline Fuse:** A **10A–15A fuse** must be installed immediately after the positive battery terminal. Never bypass this fuse during field tests.
* **Propeller Hazard:** DC thruster propellers can cause severe lacerations. Never test thrusters on a bench without confirming all team members are clear of spinning blades.
* **LiPo Thermal Runaway:** Always charge and store lithium-polymer batteries in dedicated fireproof LiPo bags. If a battery is dropped in water or punctured, immediately disconnect it and submerge it in salt water for safe discharge.

### Fail-Safe Watchdog:
* The onboard firmware implements an automated **2.0-second communications watchdog**. If the vessel loses serial communication with the ground station while in manual mode, all thrusters automatically disengage to prevent runaway collisions.
