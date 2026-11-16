/**
 * ============================================================================
 * Project: Aqua-Sentry Catamaran Autonomous Waste Collector
 * Platform: Arduino Uno / Nano (ATMega328P)
 * Mechanism: Passive Flow-Through Rear Mesh Collection (WasteShark Principle)
 * 
 * Hardware:
 *   - Propulsion: Twin DC thrusters with differential steering (L298N driver)
 *   - Collection: Passive central hull channel leading to rear mesh basket
 *                 (No rollers or moving parts needed - forward motion traps trash!)
 *   - Obstacle Avoidance: Front waterproof ultrasonic sensor (JSN-SR04T)
 *   - Battery Safety: 3S LiPo voltage divider monitor (A0) with auto-cutoff (9.9V)
 *   - Control: Serial teleoperation & emergency kill switch (F, B, L, R, S, A, M, X)
 * ============================================================================
 */

#include <Arduino.h>

// ==========================================
// PIN CONFIGURATION
// ==========================================

// Left Thruster Driver Pins (Channel A)
const uint8_t PIN_LEFT_ENA  = 9;    // PWM Speed (Timer 1)
const uint8_t PIN_LEFT_IN1  = 8;    // Direction 1
const uint8_t PIN_LEFT_IN2  = 7;    // Direction 2

// Right Thruster Driver Pins (Channel B)
const uint8_t PIN_RIGHT_ENB = 10;   // PWM Speed (Timer 1)
const uint8_t PIN_RIGHT_IN3 = 4;    // Direction 1
const uint8_t PIN_RIGHT_IN4 = 2;    // Direction 2

// Front Waterproof Ultrasonic Sensor (JSN-SR04T)
const uint8_t PIN_US_TRIG   = 5;    // Trigger
const uint8_t PIN_US_ECHO   = 3;    // Echo

// Sensing & Diagnostic Pins
const uint8_t PIN_BATTERY_ADC = A0; // 3S LiPo Voltage Divider (10k / 4.7k)
const uint8_t PIN_BUZZER_LED  = 13; // Onboard status indicator / buzzer

// ==========================================
// TUNING PARAMETERS
// ==========================================

// Speed settings (0 - 255)
const uint8_t SPEED_FORWARD_LEFT   = 180;
const uint8_t SPEED_FORWARD_RIGHT  = 180;
const uint8_t SPEED_REVERSE        = 160;
const uint8_t SPEED_TURN           = 190;

// Battery Safety (3S LiPo: 12.6V Full, 9.9V Cutoff = 3.3V/cell)
// Divider ratio: R1=10k, R2=4.7k -> (10 + 4.7) / 4.7 = 3.1276
const float   VOLTAGE_DIVIDER_RATIO = 3.1276f;
const float   LIPO_WARN_VOLTAGE     = 10.5f;
const float   LIPO_CUTOFF_VOLTAGE   = 9.9f;

// Obstacle Avoidance Thresholds
const float   OBSTACLE_DIST_CM     = 60.0f;
const float   SENSOR_MIN_VALID_CM  = 20.0f; // JSN-SR04T dead band
const float   SENSOR_MAX_VALID_CM  = 350.0f;

// Non-blocking Timings (milliseconds)
const unsigned long DELAY_STARTUP_MS     = 3000;
const unsigned long INTERVAL_SENSOR_MS   = 60;
const unsigned long INTERVAL_BATTERY_MS  = 500;
const unsigned long INTERVAL_TELEMETRY_MS= 250;
const unsigned long DURATION_REVERSE_MS  = 1500;
const unsigned long DURATION_TURN_MS     = 1500;
const unsigned long WATCHDOG_TIMEOUT_MS  = 2000;

// ==========================================
// STATE MACHINE DEFINITION
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

// Global Variables
NavMode       currentMode      = MODE_MANUAL_OVERRIDE;
NavState      currentState     = STATE_STANDBY;

unsigned long stateTimer       = 0;
unsigned long lastSensorTime   = 0;
unsigned long lastBatteryTime  = 0;
unsigned long lastSerialTime   = 0;
unsigned long lastCommandTime  = 0;

float currentDistanceCm        = 999.0f;
float batteryVoltage           = 12.4f;
char  manualCmd                = 'S';

// ==========================================
// FUNCTION PROTOTYPES
// ==========================================
float readUltrasonic();
float readBatteryVoltage();
void  processSerialCommands();
void  runNavStateMachine();
void  moveForward(uint8_t left, uint8_t right);
void  moveReverse(uint8_t speed);
void  turnRight(uint8_t speed);
void  turnLeft(uint8_t speed);
void  stopThrusters();
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

  pinMode(PIN_US_TRIG, OUTPUT);
  pinMode(PIN_US_ECHO, INPUT);
  digitalWrite(PIN_US_TRIG, LOW);

  pinMode(PIN_BUZZER_LED, OUTPUT);
  digitalWrite(PIN_BUZZER_LED, LOW);

  stopThrusters();

  batteryVoltage = readBatteryVoltage();
  Serial.println(F("\n=================================================="));
  Serial.println(F("   Aqua-Sentry WasteShark-Style Catamaran Bot     "));
  Serial.println(F("   Mechanism: Passive Flow-Through Rear Mesh      "));
  Serial.println(F("=================================================="));
  Serial.print(F("[POWER] Battery Voltage: "));
  Serial.print(batteryVoltage, 2);
  Serial.println(F(" V"));

  if (batteryVoltage < LIPO_CUTOFF_VOLTAGE && batteryVoltage > 6.0f) {
    Serial.println(F("[CRITICAL] Low battery! Lockout active to save cells."));
    currentState = STATE_LOW_BATTERY_LOCKOUT;
  } else {
    Serial.println(F("[SAFETY] Arming delay (3.0s)... Keep hands clear."));
    stateTimer = millis();
    currentState = STATE_STANDBY;
  }

  lastCommandTime = millis();
}

// ==========================================
// MAIN LOOP
// ==========================================
void loop() {
  unsigned long now = millis();

  // 1. Process Laptop / Teleoperation Serial Commands
  processSerialCommands();

  // 2. Battery Health & Low-Voltage Cutoff
  if (now - lastBatteryTime >= INTERVAL_BATTERY_MS) {
    lastBatteryTime = now;
    batteryVoltage = readBatteryVoltage();

    if (batteryVoltage <= LIPO_CUTOFF_VOLTAGE && batteryVoltage > 6.0f) {
      if (currentState != STATE_LOW_BATTERY_LOCKOUT) {
        Serial.println(F("\n[CRITICAL] Battery < 9.9V! Motors killed to protect LiPo."));
        stopThrusters();
        currentState = STATE_LOW_BATTERY_LOCKOUT;
      }
    } else if (batteryVoltage <= LIPO_WARN_VOLTAGE && batteryVoltage > 6.0f) {
      digitalWrite(PIN_BUZZER_LED, (now / 300) % 2);
    } else {
      digitalWrite(PIN_BUZZER_LED, LOW);
    }
  }

  // 3. Front Ultrasonic Obstacle Scanning
  if (now - lastSensorTime >= INTERVAL_SENSOR_MS) {
    lastSensorTime = now;
    currentDistanceCm = readUltrasonic();
  }

  // 4. Motion State Machine
  runNavStateMachine();

  // 5. Periodic Telemetry Stream
  if (now - lastSerialTime >= INTERVAL_TELEMETRY_MS) {
    lastSerialTime = now;
    logDiagnostics();
  }
}

// ==========================================
// SENSORS
// ==========================================
float readBatteryVoltage() {
  int rawADC = analogRead(PIN_BATTERY_ADC);
  float pinVoltage = (rawADC * 5.0f) / 1023.0f;
  float calculatedBat = pinVoltage * VOLTAGE_DIVIDER_RATIO;
  
  static float filteredBat = 12.4f;
  filteredBat = (0.85f * filteredBat) + (0.15f * calculatedBat);
  return filteredBat;
}

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
// SERIAL COMMAND PROCESSOR
// ==========================================
void processSerialCommands() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    lastCommandTime = millis();

    switch (c) {
      case 'M': currentMode = MODE_MANUAL_OVERRIDE; stopThrusters(); break;
      case 'A': currentMode = MODE_AUTONOMOUS; break;
      case 'F': manualCmd = 'F'; break;
      case 'B': manualCmd = 'B'; break;
      case 'L': manualCmd = 'L'; break;
      case 'R': manualCmd = 'R'; break;
      case 'S': manualCmd = 'S'; break;
      case 'X': // Emergency Kill Switch
        stopThrusters();
        currentMode = MODE_MANUAL_OVERRIDE;
        manualCmd = 'S';
        Serial.println(F("[ALERT] EMERGENCY STOP ACTIVATED"));
        break;
    }
  }

  // Watchdog timeout in manual mode: stop if laptop disconnects for > 2 seconds
  if (currentMode == MODE_MANUAL_OVERRIDE && (millis() - lastCommandTime > WATCHDOG_TIMEOUT_MS)) {
    manualCmd = 'S';
  }
}

// ==========================================
// NAVIGATION STATE MACHINE
// ==========================================
void runNavStateMachine() {
  if (currentState == STATE_LOW_BATTERY_LOCKOUT) {
    stopThrusters();
    return;
  }

  unsigned long now = millis();

  // Manual Override Mode
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

  // Autonomous Cruise Mode
  switch (currentState) {
    case STATE_STANDBY:
      if (now - stateTimer >= DELAY_STARTUP_MS) {
        Serial.println(F("[SYSTEM] Armed. Starting forward cruise."));
        currentState = STATE_NAV_FORWARD;
      }
      break;

    case STATE_NAV_FORWARD:
      moveForward(SPEED_FORWARD_LEFT, SPEED_FORWARD_RIGHT);

      // Obstacle detection
      if (currentDistanceCm <= OBSTACLE_DIST_CM && currentDistanceCm >= (SENSOR_MIN_VALID_CM - 5.0f)) {
        Serial.println(F("[OBSTACLE] Obstacle detected! Braking."));
        stopThrusters();
        stateTimer = now;
        currentState = STATE_AVOID_STOP;
      }
      break;

    case STATE_AVOID_STOP:
      stopThrusters();
      if (now - stateTimer >= 150) {
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
        Serial.println(F("[RECOVERY] Obstacle cleared. Resuming forward cruise."));
        currentState = STATE_NAV_FORWARD;
      }
      break;

    default:
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

// ==========================================
// TELEMETRY
// ==========================================
void logDiagnostics() {
  Serial.print(F("BAT:"));
  Serial.print(batteryVoltage, 2);
  Serial.print(F("V | DIST:"));
  if (currentDistanceCm >= SENSOR_MAX_VALID_CM) Serial.print(F("CLEAR"));
  else { Serial.print(currentDistanceCm, 0); Serial.print(F("cm")); }

  Serial.print(F(" | MODE:"));
  Serial.print(currentMode == MODE_AUTONOMOUS ? F("AUTO") : F("MANUAL"));

  Serial.print(F(" | STATE:"));
  switch (currentState) {
    case STATE_STANDBY:             Serial.println(F("ARMING")); break;
    case STATE_NAV_FORWARD:         Serial.println(F("CRUISING")); break;
    case STATE_AVOID_STOP:          Serial.println(F("BRAKING")); break;
    case STATE_AVOID_REVERSE:       Serial.println(F("REVERSING")); break;
    case STATE_AVOID_TURN:          Serial.println(F("TURNING")); break;
    case STATE_LOW_BATTERY_LOCKOUT: Serial.println(F("BAT_LOCKOUT")); break;
  }
}
