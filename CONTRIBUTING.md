# Contributing to Aqua-Sentry 🤝

Thank you for your interest in contributing to **Aqua-Sentry**! We welcome contributions from embedded systems engineers, roboticists, marine conservationists, and software developers.

---

## 🛠 How to Contribute

### 1. Reporting Bugs
* Search existing [GitHub Issues](https://github.com/DhigveerrajuG/Aqua-Sentry/issues) before submitting a new report to avoid duplicates.
* When opening an issue, provide:
  * A clear, descriptive title.
  * Your operating system and hardware configuration (e.g. Windows 11, Arduino Uno, USB Webcam model).
  * Exact steps to reproduce the issue.
  * Serial monitor logs or Python console stack traces.

### 2. Suggesting Enhancements
* We welcome suggestions for mechanical improvements, computer vision filtering, or navigation algorithms!
* Open an issue labeled `enhancement` describing the proposed feature, why it is useful, and any relevant hardware specifications.

### 3. Pull Request (PR) Workflow
To contribute code or documentation changes:

1. **Fork the repository** to your personal GitHub account.
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/<your-username>/Aqua-Sentry.git
   cd Aqua-Sentry
   ```
3. **Create a new feature branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
4. **Make your modifications:**
   * Keep firmware changes non-blocking (`millis()` timing).
   * Ensure any new UI/Python dependencies are documented in `requirements.txt`.
5. **Test your changes:**
   * Verify Arduino sketch compilation in the Arduino IDE or CLI.
   * Run the Python console (`python monitor_stream.py`) to confirm zero frame drops or syntax errors.
6. **Commit your work** following the Conventional Commits format (see [RULESET.md](file:///d:/GITAM/Aqua-Sentry/RULESET.md)):
   ```bash
   git commit -m "feat: add adaptive contrast enhancement for turbid water vision"
   ```
7. **Push to your fork:**
   ```bash
   git push origin feature/your-feature-name
   ```
8. **Open a Pull Request** against the `main` branch of `DhigveerrajuG/Aqua-Sentry` using the PR template.

---

## 🧪 Testing Checklist Before Submitting a PR
- [ ] Code compiles cleanly without compiler warnings.
- [ ] Arduino pin assignments do not conflict with hardware timers (Timer 0 / Timer 1).
- [ ] Python scripts adhere to PEP 8 formatting.
- [ ] Updated `README.md` and wiring summaries if physical pin connections or controls changed.
- [ ] Verified that Emergency Kill Switch (`X` key) remains functional and unblocked.

---

## 📜 Code of Conduct
All contributors and maintainers are expected to uphold our [Code of Conduct](file:///d:/GITAM/Aqua-Sentry/CODE_OF_CONDUCT.md). Please report any unacceptable behavior to project maintainers.
