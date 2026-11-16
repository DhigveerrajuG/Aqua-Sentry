/**
 * ============================================================================
 * Project: Catamaran Water Surface Trash Collector (Aqua-Sentry Advanced FSM)
 * Platform: Arduino Uno / Nano / ESP32 (ATMega328P / Xtensa)
 * Target Hull: Twin PVC Pontoon with Differential Thrust
 * 
 * Advanced Upgrades:
 *   1. 3S LiPo Battery Voltage Monitor with Low-Voltage Cut-Off (LVCO @ 9.9V)
 *   2. Collector Anti-Jam Protection (Stall Current Auto-Reverse & Fault Mode)
 *   3. Ultrasonic Non-blocking Obstacle Avoidance
 *   4. Serial Command Interface & Manual Teleoperation Override with Watchdog
 * ============================================================================
 */

#include <Arduino.h>

// ==========================================
// PIN CONFIGURATION
// ==========================================

// Left Thruster Driver Pins (Channel A)
const uint8_t PIN_LEFT_ENA  = 9;    // PWM Speed Pin (Timer 1)
const uint8_t PIN_LEFT_IN1  = 8;    // Direction Pin 1
const uint8_t PIN_LEFT_IN2  = 7;    // Direction Pin 2

// Right Thruster Driver Pins (Channel B)
const uint8_t PIN_RIGHT_ENB = 10;   // PWM Speed Pin (Timer 1)
const uint8_t PIN_RIGHT_IN3 = 4;    // Direction Pin 3
const uint8_t PIN_RIGHT_IN4 = 2;    // Direction Pin 4

// Central Trash Collector Mechanism (Conveyor / Paddle Wheel)
const uint8_t PIN_COLL_PWM  = 6;    // PWM Speed Control (Timer 0)
const uint8_t PIN_COLL_IN1  = 12;   // Direction A (Forward intake)
const uint8_t PIN_COLL_IN2  = 11;   // Direction B (Reverse unjam)

// Waterproof Ultrasonic Sensor (JSN-SR04T)
const uint8_t PIN_US_TRIG   = 5;    // Ultrasonic Trigger
const uint8_t PIN_US_ECHO   = 3;    // Ultrasonic Echo

// Sensing & Diagnostic Pins
const uint8_t PIN_BATTERY_ADC = A0; // 3S LiPo Voltage Divider (10k / 4.7k)
const uint8_t PIN_CURRENT_ADC = A2; // ACS712 Current Sensor for Collector Motor
const uint8_t PIN_BUZZER_LED  = 13; // Warning buzzer / onboard status LED

// ==========================================
// SYSTEM TUNING & CALIBRATION PARAMETERS
// ==========================================

// Speeds (0 - 255)
const uint8_t SPEED_FORWARD_LEFT   = 180;
const uint8_t SPEED_FORWARD_RIGHT  = 180;
const uint8_t SPEED_REVERSE        = 160;
const uint8_t SPEED_TURN           = 190;
const uint8_t SPEED_COLLECTOR      = 191; // 75% Duty Cycle (0.75 * 255 = 191)
const uint8_t SPEED_UNJAM          = 240; // High torque for reverse unjam

// Battery Parameters (3S LiPo: 12.6V Full, 11.1V Nominal, 9.9V Cutoff)
// Voltage Divider: R1 = 10k, R2 = 4.7k -> Ratio = (10 + 4.7) / 4.7 = 3.1276
const float   VOLTAGE_DIVIDER_RATIO = 3.1276f;
const float   LIPO_WARN_VOLTAGE     = 10.5f; // Warning threshold (3.5V/cell)
const float   LIPO_CUTOFF_VOLTAGE   = 9.9f;  // Critical cutoff (3.3V/cell)

// Collector Jam Detection (ACS712 5A Sensitivity: 185mV/A, Vref = 2.5V)
const float   JAM_CURRENT_THRESHOLD_A = 2.4f; // Amperes considered as motor stall
const unsigned long JAM_DEBOUNCE_MS   = 400;  // Must exceed threshold for 400ms
const uint8_t MAX_UNJAM_RETRIES       = 3;    // Max auto-unjam attempts

// Obstacle Avoidance Thresholds
const float   OBSTACLE_DIST_CM     = 60.0f;
const float   SENSOR_MIN_VALID_CM  = 20.0f;
const float   SENSOR_MAX_VALID_CM  = 350.0f;

// Timing Constants (milliseconds)
const unsigned long DELAY_STARTUP_MS       = 3000;
const unsigned long INTERVAL_SENSOR_MS     = 60;
const unsigned long INTERVAL_TELEMETRY_MS  = 250;
const unsigned long INTERVAL_BATTERY_MS   = 500;
const unsigned long DURATION_REVERSE_MS    = 1500;
const unsigned long DURATION_TURN_MS       = 1500;
const unsigned long DURATION_UNJAM_REV_MS  = 1200; // Duration of reverse unjam pulse
const unsigned long WATCHDOG_TIMEOUT_MS    = 2000; // Manual control failsafe timeout

// ==========================================
// STATE DEFINITIONS
// ==========================================
enum NavMode {
  MODE_AUTONOMOUS,
  MODE_MANUAL_OVERRIDE
};

enum NavState {
  STATE_STANDBY,
  STATE_NAV_FORWARD,
  STATE_AVOID_STOP,
  STATE_AVOID_REVERSE,
  STATE_AVOID_TURN,
  STATE_LOW_BATTERY_LOCKOUT
};

enum CollectorState {
  COLL_IDLE,
  COLL_FORWARD,
  COLL_UNJAM_REVERSING,
  COLL_JAM_FAULT
};

// Global System Variables
NavMode        currentMode      = MODE_AUTONOMOUS;
NavState       currentState     = STATE_STANDBY;
CollectorState collState        = COLL_IDLE;

unsigned long stateTimer        = 0;
unsigned long collTimer         = 0;
unsigned long lastSensorTime    = 0;
unsigned long lastSerialTime    = 0;
unsigned long lastBatteryTime   = 0;
unsigned long lastCommandTime   = 0;

float currentDistanceCm         = 999.0f;
float batteryVoltage            = 12.6f;
float collectorCurrentA         = 0.0f;
uint8_t unjamRetryCount         = 0;
char manualCmd                  = 'S';

// ==========================================
// FUNCTION DECLARATIONS
// ==========================================
float readUltrasonic();
float readBatteryVoltage();
float readCollectorCurrent();
void  processSerialCommands();
void  runNavStateMachine();
void  runCollectorStateMachine();
void  moveForward(uint8_t left, uint8_t right);
void  moveReverse(uint8_t speed);
void  turnRight(uint8_t speed);
void  turnLeft(uint8_t speed);
void  stopThrusters();
void  setCollectorMotor(int speed); // positive = forward, negative = reverse, 0 = off
void  logDiagnostics();

// ==========================================
// ARDUINO SETUP
// ==========================================
void setup() {
  Serial.begin(115200);

  pinMode(PIN_LEFT_ENA, OUTPUT);
  pinMode(PIN_LEFT_IN1, OUTPUT);
  pinMode(PIN_LEFT_IN2, OUTPUT);

  pinMode(PIN_RIGHT_ENB, OUTPUT);
  pinMode(PIN_RIGHT_IN3, OUTPUT);
  pinMode(PIN_RIGHT_IN4, OUTPUT);

  pinMode(PIN_COLL_PWM, OUTPUT);
  pinMode(PIN_COLL_IN1, OUTPUT);
  pinMode(PIN_COLL_IN2, OUTPUT);

  pinMode(PIN_US_TRIG, OUTPUT);
  pinMode(PIN_US_ECHO, INPUT);
  digitalWrite(PIN_US_TRIG, LOW);

  pinMode(PIN_BUZZER_LED, OUTPUT);
  digitalWrite(PIN_BUZZER_LED, LOW);

  stopThrusters();
  setCollectorMotor(0);

  // Initial Battery Voltage check
  batteryVoltage = readBatteryVoltage();
  Serial.println(F("\n======================================================="));
  Serial.println(F("   Aqua-Sentry Autonomous Catamaran - Advanced System  "));
  Serial.println(F("======================================================="));
  Serial.print(F("[POWER] Initial Battery Voltage: "));
  Serial.print(batteryVoltage, 2);
  Serial.println(F(" V"));

  if (batteryVoltage < LIPO_CUTOFF_VOLTAGE && batteryVoltage > 5.0f) {
    Serial.println(F("[CRITICAL] Low battery at boot! Entering Lockout mode."));
    currentState = STATE_LOW_BATTERY_LOCKOUT;
  } else {
    Serial.println(F("[SAFETY] Arming delay (3.0s)... Keep clear of propellers."));
    stateTimer = millis();
    currentState = STATE_STANDBY;
  }

  lastCommandTime = millis();
}

// ==========================================
// MAIN CONTROL LOOP
// ==========================================
void loop() {
  unsigned long now = millis();

  // 1. Process Remote Failsafe & Manual Commands from ESP32-CAM / Laptop
  processSerialCommands();

  // 2. Battery Health & Voltage Monitoring
  if (now - lastBatteryTime >= INTERVAL_BATTERY_MS) {
    lastBatteryTime = now;
    batteryVoltage = readBatteryVoltage();

    if (batteryVoltage <= LIPO_CUTOFF_VOLTAGE && batteryVoltage > 6.0f) {
      if (currentState != STATE_LOW_BATTERY_LOCKOUT) {
        Serial.println(F("\n[CRITICAL ERROR] Battery below 9.9V! Auto-shutting down to save LiPo cells."));
        stopThrusters();
        setCollectorMotor(0);
        currentState = STATE_LOW_BATTERY_LOCKOUT;
      }
    } else if (batteryVoltage <= LIPO_WARN_VOLTAGE && batteryVoltage > 6.0f) {
      digitalWrite(PIN_BUZZER_LED, (now / 300) % 2); // Pulse LED/Buzzer warning
    } else {
      digitalWrite(PIN_BUZZER_LED, LOW);
    }
  }

  // 3. Periodic Ultrasonic Obstacle Sensing
  if (now - lastSensorTime >= INTERVAL_SENSOR_MS) {
    lastSensorTime = now;
    currentDistanceCm = readUltrasonic();
  }

  // 4. Current & Jam Detection for Collector Motor
  collectorCurrentA = readCollectorCurrent();
  runCollectorStateMachine();

  // 5. Navigation & FSM Execution
  runNavStateMachine();

  // 6. Diagnostics Telemetry Output
  if (now - lastSerialTime >= INTERVAL_TELEMETRY_MS) {
    lastSerialTime = now;
    logDiagnostics();
  }
}

// ==========================================
// BATTERY SENSING & CURRENT MONITORING
// ==========================================
float readBatteryVoltage() {
  int rawADC = analogRead(PIN_BATTERY_ADC);
  // Arduino Uno Vref = 5.0V, 10-bit ADC (1023 steps)
  float pinVoltage = (rawADC * 5.0f) / 1023.0f;
  float calculatedBat = pinVoltage * VOLTAGE_DIVIDER_RATIO;
  
  // Exponential Moving Average (EMA) to smooth out inductive motor spikes
  static float filteredBat = 12.4f;
  filteredBat = (0.85f * filteredBat) + (0.15f * calculatedBat);
  return filteredBat;
}

float readCollectorCurrent() {
  int rawADC = analogRead(PIN_CURRENT_ADC);
  float voltage = (rawADC * 5.0f) / 1023.0f;
  // ACS712-05B: Zero current = 2.5V, Sensitivity = 185mV/A
  float current = fabs((voltage - 2.5f) / 0.185f);
  
  static float filteredCurrent = 0.0f;
  filteredCurrent = (0.7f * filteredCurrent) + (0.3f * current);
  return filteredCurrent;
}

// ==========================================
// SERIAL COMMAND PROCESSOR & WATCHDOG
// ==========================================
void processSerialCommands() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    lastCommandTime = millis(); // Reset watchdog timer

    switch (c) {
      case 'M': // Switch to Manual Teleoperation Mode
        currentMode = MODE_MANUAL_OVERRIDE;
        stopThrusters();
        Serial.println(F("[MODE] Switched to MANUAL Teleoperation"));
        break;

      case 'A': // Switch to Autonomous Navigation Mode
        currentMode = MODE_AUTONOMOUS;
        Serial.println(F("[MODE] Switched to AUTONOMOUS Cruise"));
        break;

      case 'F': manualCmd = 'F'; break; // Forward
      case 'B': manualCmd = 'B'; break; // Reverse
      case 'L': manualCmd = 'L'; break; // Pivot Left
      case 'R': manualCmd = 'R'; break; // Pivot Right
      case 'S': manualCmd = 'S'; break; // Stop / Brake
      
      case 'C': // Toggle Collector
        if (collState == COLL_IDLE) collState = COLL_FORWARD;
        else collState = COLL_IDLE;
        break;

      case 'X': // Emergency Kill Switch
        stopThrusters();
        setCollectorMotor(0);
        currentMode = MODE_MANUAL_OVERRIDE;
        manualCmd = 'S';
        Serial.println(F("[ALERT] EMERGENCY STOP ACTIVATED"));
        break;
    }
  }

  // Failsafe Watchdog: If in manual mode and no command received for > 2.0s, stop motors
  if (currentMode == MODE_MANUAL_OVERRIDE && (millis() - lastCommandTime > WATCHDOG_TIMEOUT_MS)) {
    manualCmd = 'S';
  }
}

// ==========================================
// NAVIGATION & MOTION STATE MACHINE
// ==========================================
void runNavStateMachine() {
  if (currentState == STATE_LOW_BATTERY_LOCKOUT) {
    stopThrusters();
    setCollectorMotor(0);
    return;
  }

  unsigned long now = millis();

  // ---- MANUAL OVERRIDE MODE ----
  if (currentMode == MODE_MANUAL_OVERRIDE) {
    switch (manualCmd) {
      case 'F': moveForward(SPEED_FORWARD_LEFT, SPEED_FORWARD_RIGHT); break;
      case 'B': moveReverse(SPEED_REVERSE); break;
      case 'L': turnLeft(SPEED_TURN); break;
      case 'R': turnRight(SPEED_TURN); break;
      case 'S':
      default:  stopThrusters(); break;
    }
    return;
  }

  // ---- AUTONOMOUS CRUISE MODE ----
  switch (currentState) {
    case STATE_STANDBY:
      if (now - stateTimer >= DELAY_STARTUP_MS) {
        Serial.println(F("[SYSTEM] Armed. Starting Autonomous Cruise & Collection."));
        currentState = STATE_NAV_FORWARD;
        collState = COLL_FORWARD;
      }
      break;

    case STATE_NAV_FORWARD:
      moveForward(SPEED_FORWARD_LEFT, SPEED_FORWARD_RIGHT);

      // Trigger avoidance on obstacle within 60 cm
      if (currentDistanceCm <= OBSTACLE_DIST_CM && currentDistanceCm >= (SENSOR_MIN_VALID_CM - 5.0f)) {
        Serial.println(F("[OBSTACLE] Hazard detected ahead! Stopping."));
        stopThrusters();
        stateTimer = now;
        currentState = STATE_AVOID_STOP;
      }
      break;

    case STATE_AVOID_STOP:
      stopThrusters();
      if (now - stateTimer >= 150) { // Settle inertia
        stateTimer = now;
        currentState = STATE_AVOID_REVERSE;
      }
      break;

    case STATE_AVOID_REVERSE:
      moveReverse(SPEED_REVERSE);
      if (now - stateTimer >= DURATION_REVERSE_MS) {
        stopThrusters();
        stateTimer = now;
        currentState = STATE_AVOID_TURN;
      }
      break;

    case STATE_AVOID_TURN:
      turnRight(SPEED_TURN);
      if (now - stateTimer >= DURATION_TURN_MS) {
        stopThrusters();
        Serial.println(F("[OBSTACLE] Path clear. Resuming forward cruise."));
        currentState = STATE_NAV_FORWARD;
      }
      break;

    default:
      break;
  }
}

// ==========================================
// ANTI-JAM COLLECTOR STATE MACHINE
// ==========================================
void runCollectorStateMachine() {
  if (currentState == STATE_LOW_BATTERY_LOCKOUT) {
    setCollectorMotor(0);
    return;
  }

  unsigned long now = millis();
  static unsigned long jamStartTime = 0;

  switch (collState) {
    case COLL_IDLE:
      setCollectorMotor(0);
      unjamRetryCount = 0;
      break;

    case COLL_FORWARD:
      setCollectorMotor(SPEED_COLLECTOR);

      // Current Spike / Jam Check
      if (collectorCurrentA > JAM_CURRENT_THRESHOLD_A) {
        if (jamStartTime == 0) {
          jamStartTime = now;
        } else if (now - jamStartTime > JAM_DEBOUNCE_MS) {
          // Sustained high current = Motor Stall / Weed Jam
          Serial.println(F("[JAM DETECTED] High current on collector! Initiating reverse unjam."));
          collTimer = now;
          jamStartTime = 0;
          collState = COLL_UNJAM_REVERSING;
        }
      } else {
        jamStartTime = 0;
      }
      break;

    case COLL_UNJAM_REVERSING:
      setCollectorMotor(-SPEED_UNJAM); // Reverse full speed

      if (now - collTimer >= DURATION_UNJAM_REV_MS) {
        unjamRetryCount++;
        if (unjamRetryCount >= MAX_UNJAM_RETRIES) {
          Serial.println(F("[JAM FAULT] Paddle wheel failed to clear after 3 attempts. Disabling collector."));
          collState = COLL_JAM_FAULT;
        } else {
          Serial.print(F("[UNJAM] Reverse burst finished. Attempting forward intake (Retry "));
          Serial.print(unjamRetryCount);
          Serial.println(F("/3)"));
          collState = COLL_FORWARD;
        }
      }
      break;

    case COLL_JAM_FAULT:
      setCollectorMotor(0); // Protect motor & driver from burning
      break;
  }
}

// ==========================================
// MOTOR ACTUATION PRIMITIVES
// ==========================================
void moveForward(uint8_t left, uint8_t right) {
  digitalWrite(PIN_LEFT_IN1, HIGH);
  digitalWrite(PIN_LEFT_IN2, LOW);
  analogWrite(PIN_LEFT_ENA, left);

  digitalWrite(PIN_RIGHT_IN3, HIGH);
  digitalWrite(PIN_RIGHT_IN4, LOW);
  analogWrite(PIN_RIGHT_ENB, right);
}

void moveReverse(uint8_t speed) {
  digitalWrite(PIN_LEFT_IN1, LOW);
  digitalWrite(PIN_LEFT_IN2, HIGH);
  analogWrite(PIN_LEFT_ENA, speed);

  digitalWrite(PIN_RIGHT_IN3, LOW);
  digitalWrite(PIN_RIGHT_IN4, HIGH);
  analogWrite(PIN_RIGHT_ENB, speed);
}

void turnRight(uint8_t speed) {
  digitalWrite(PIN_LEFT_IN1, HIGH);
  digitalWrite(PIN_LEFT_IN2, LOW);
  analogWrite(PIN_LEFT_ENA, speed);

  digitalWrite(PIN_RIGHT_IN3, LOW);
  digitalWrite(PIN_RIGHT_IN4, LOW);
  analogWrite(PIN_RIGHT_ENB, 0);
}

void turnLeft(uint8_t speed) {
  digitalWrite(PIN_LEFT_IN1, LOW);
  digitalWrite(PIN_LEFT_IN2, LOW);
  analogWrite(PIN_LEFT_ENA, 0);

  digitalWrite(PIN_RIGHT_IN3, HIGH);
  digitalWrite(PIN_RIGHT_IN4, LOW);
  analogWrite(PIN_RIGHT_ENB, speed);
}

void stopThrusters() {
  digitalWrite(PIN_LEFT_IN1, LOW);
  digitalWrite(PIN_LEFT_IN2, LOW);
  analogWrite(PIN_LEFT_ENA, 0);

  digitalWrite(PIN_RIGHT_IN3, LOW);
  digitalWrite(PIN_RIGHT_IN4, LOW);
  analogWrite(PIN_RIGHT_ENB, 0);
}

void setCollectorMotor(int speed) {
  if (speed > 0) {
    // Forward rotation (intake)
    digitalWrite(PIN_COLL_IN1, HIGH);
    digitalWrite(PIN_COLL_IN2, LOW);
    analogWrite(PIN_COLL_PWM, speed);
  } else if (speed < 0) {
    // Reverse rotation (anti-jam ejection)
    digitalWrite(PIN_COLL_IN1, LOW);
    digitalWrite(PIN_COLL_IN2, HIGH);
    analogWrite(PIN_COLL_PWM, abs(speed));
  } else {
    // Brake / Stop
    digitalWrite(PIN_COLL_IN1, LOW);
    digitalWrite(PIN_COLL_IN2, LOW);
    analogWrite(PIN_COLL_PWM, 0);
  }
}

// ==========================================
// ULTRASONIC SENSOR SUBSYSTEM
// ==========================================
float readUltrasonic() {
  digitalWrite(PIN_US_TRIG, LOW);
  delayMicroseconds(4);
  digitalWrite(PIN_US_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_US_TRIG, LOW);

  unsigned long duration = pulseIn(PIN_US_ECHO, HIGH, 25000UL);
  if (duration == 0) return 400.0f;

  float dist = (duration * 0.0343f) / 2.0f;
  if (dist < SENSOR_MIN_VALID_CM && dist > 0.0f) return SENSOR_MIN_VALID_CM;
  return dist;
}

// ==========================================
// SERIAL TELEMETRY DIAGNOSTICS
// ==========================================
void logDiagnostics() {
  Serial.print(F("V_BAT:"));
  Serial.print(batteryVoltage, 2);
  Serial.print(F("V | I_COLL:"));
  Serial.print(collectorCurrentA, 2);
  Serial.print(F("A | DIST:"));
  if (currentDistanceCm >= SENSOR_MAX_VALID_CM) Serial.print(F("CLEAR"));
  else { Serial.print(currentDistanceCm, 0); Serial.print(F("cm")); }

  Serial.print(F(" | MODE:"));
  Serial.print(currentMode == MODE_AUTONOMOUS ? F("AUTO") : F("MANUAL"));

  Serial.print(F(" | STATE:"));
  switch (currentState) {
    case STATE_STANDBY:       Serial.print(F("ARMING")); break;
    case STATE_NAV_FORWARD:   Serial.print(F("CRUISE")); break;
    case STATE_AVOID_STOP:    Serial.print(F("BRAKE")); break;
    case STATE_AVOID_REVERSE: Serial.print(F("REVERSE")); break;
    case STATE_AVOID_TURN:    Serial.print(F("TURN_R")); break;
    case STATE_LOW_BATTERY_LOCKOUT: Serial.print(F("BAT_LOCKOUT")); break;
  }

  Serial.print(F(" | COLL:"));
  switch (collState) {
    case COLL_IDLE:             Serial.println(F("OFF")); break;
    case COLL_FORWARD:          Serial.println(F("RUN")); break;
    case COLL_UNJAM_REVERSING:  Serial.println(F("UNJAMMING")); break;
    case COLL_JAM_FAULT:        Serial.println(F("FAULT")); break;
  }
}
