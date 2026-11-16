/**
 * ============================================================================
 * Project: Catamaran Water Surface Trash Collector (Aqua-Sentry Prototype)
 * Platform: Arduino Uno / Nano / ESP32 (ATMega328P / Xtensa)
 * Target Hull: Twin PVC Pontoon with Differential Thrust
 * 
 * Architecture: Non-blocking Finite State Machine (FSM) using millis() timing.
 * Features:
 *   - 3-second arming delay for field safety.
 *   - Continuous obstacle scanning with moving-window sanity checks.
 *   - Differential thrust propulsion & autonomous obstacle avoidance.
 *   - Central paddle wheel / conveyor speed regulation.
 *   - Real-time Serial diagnostic telemetry.
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
const uint8_t PIN_COLL_DIR  = 12;   // Direction / Relay Enable

// Waterproof Ultrasonic Sensor (JSN-SR04T)
const uint8_t PIN_US_TRIG   = 5;    // Ultrasonic Trigger
const uint8_t PIN_US_ECHO   = 3;    // Ultrasonic Echo

// ==========================================
// SYSTEM TUNING & CALIBRATION PARAMETERS
// ==========================================

// Speeds (0 - 255)
const uint8_t SPEED_FORWARD_LEFT   = 180;  // 180/255 Forward speed
const uint8_t SPEED_FORWARD_RIGHT  = 180;  // 180/255 Forward speed
const uint8_t SPEED_REVERSE        = 160;  // Reverse clearance speed
const uint8_t SPEED_TURN           = 190;  // Differential turn thrust
const uint8_t SPEED_COLLECTOR      = 191;  // 75% Duty Cycle (0.75 * 255 = 191)

// Obstacle Avoidance Thresholds
const float   OBSTACLE_DIST_CM     = 60.0f; // Obstacle trigger distance (cm)
const float   SENSOR_MIN_VALID_CM  = 20.0f; // JSN-SR04T blind spot lower limit
const float   SENSOR_MAX_VALID_CM  = 350.0f;// Ultrasonic sanity ceiling limit

// Non-blocking Timing (milliseconds)
const unsigned long DELAY_STARTUP_MS     = 3000; // 3-second startup safety delay
const unsigned long INTERVAL_SENSOR_MS   = 60;   // Ultrasonic polling interval
const unsigned long INTERVAL_TELEMETRY_MS= 200;  // Serial monitor debug rate
const unsigned long DURATION_REVERSE_MS  = 1500; // Time spent reversing
const unsigned long DURATION_TURN_MS     = 1500; // Time spent turning right

// ==========================================
// STATE MACHINE DEFINITION
// ==========================================
enum RobotState {
  STATE_STANDBY,        // Initial safety hold after power-on
  STATE_NAV_FORWARD,    // Cruising forward & collecting trash
  STATE_AVOID_STOP,     // Emergency brake on obstacle detection
  STATE_AVOID_REVERSE,  // Backing away from hazard
  STATE_AVOID_TURN      // Differential turn to bypass obstacle
};

// Global State Variables
RobotState currentState = STATE_STANDBY;
unsigned long stateTimer      = 0;
unsigned long lastSensorTime  = 0;
unsigned long lastSerialTime  = 0;
float currentDistanceCm       = 999.0f;

// ==========================================
// HELPER FUNCTIONS & PROTOTYPES
// ==========================================
inline float safeMax(float a, float b) {
  return (a > b) ? a : b;
}

float readUltrasonic();
void  moveForward(uint8_t leftSpeed, uint8_t rightSpeed);
void  moveReverse(uint8_t speed);
void  turnRight(uint8_t speed);
void  stopThrusters();
void  runCollector(uint8_t speed);
void  avoidObstacleStateMachine();
void  logDiagnostics();

// ==========================================
// ARDUINO SETUP
// ==========================================
void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 1000); // Wait for serial console on USB-capable chips

  Serial.println(F("\n=================================================="));
  Serial.println(F("   Aqua-Sentry Autonomous Catamaran Controller   "));
  Serial.println(F("=================================================="));

  // Initialize Motor Control Pins
  pinMode(PIN_LEFT_ENA, OUTPUT);
  pinMode(PIN_LEFT_IN1, OUTPUT);
  pinMode(PIN_LEFT_IN2, OUTPUT);

  pinMode(PIN_RIGHT_ENB, OUTPUT);
  pinMode(PIN_RIGHT_IN3, OUTPUT);
  pinMode(PIN_RIGHT_IN4, OUTPUT);

  pinMode(PIN_COLL_PWM, OUTPUT);
  pinMode(PIN_COLL_DIR, OUTPUT);

  // Initialize Ultrasonic Sensor Pins
  pinMode(PIN_US_TRIG, OUTPUT);
  pinMode(PIN_US_ECHO, INPUT);
  digitalWrite(PIN_US_TRIG, LOW);

  // Ensure all actuators start safely in OFF state
  stopThrusters();
  runCollector(0);

  Serial.println(F("[SAFETY] 3-Second Arming Delay in progress... Keep clear of thrusters."));
  stateTimer = millis();
  currentState = STATE_STANDBY;
}

// ==========================================
// ARDUINO MAIN LOOP
// ==========================================
void loop() {
  unsigned long now = millis();

  // 1. Periodic non-blocking ultrasonic reading
  if (now - lastSensorTime >= INTERVAL_SENSOR_MS) {
    lastSensorTime = now;
    currentDistanceCm = readUltrasonic();
  }

  // 2. Obstacle Avoidance & Navigation State Machine
  avoidObstacleStateMachine();

  // 3. Periodic Serial Diagnostics
  if (now - lastSerialTime >= INTERVAL_TELEMETRY_MS) {
    lastSerialTime = now;
    logDiagnostics();
  }
}

// ==========================================
// ULTRASONIC SENSOR SUBSYSTEM
// ==========================================
/**
 * Triggers a 10µs pulse to the JSN-SR04T transducer and calculates distance.
 * Includes a timeout of 25ms to prevent blocking the main loop if an echo is lost.
 */
float readUltrasonic() {
  // Clear trigger line
  digitalWrite(PIN_US_TRIG, LOW);
  delayMicroseconds(4);

  // Send 10µs ultrasonic start pulse
  digitalWrite(PIN_US_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_US_TRIG, LOW);

  // Measure round-trip time (max 25000 µs ~= 430 cm max range)
  unsigned long duration = pulseIn(PIN_US_ECHO, HIGH, 25000UL);

  // pulseIn returned 0 implies timeout (out of range or hardware disconnected)
  if (duration == 0) {
    return safeMax(currentDistanceCm, 400.0f);
  }

  // Distance calculation: Speed of sound in air ~ 0.0343 cm/µs
  float calculatedDistance = (duration * 0.0343f) / 2.0f;

  // Filter out spurious echoes below the physical transducer blind zone (~20 cm)
  if (calculatedDistance < SENSOR_MIN_VALID_CM && calculatedDistance > 0.0f) {
    return SENSOR_MIN_VALID_CM; 
  }

  return calculatedDistance;
}

// ==========================================
// ROBOT MOTION CONTROL SUBSYSTEM
// ==========================================

/**
 * Commands both thrusters forward with specified PWM values.
 */
void moveForward(uint8_t leftSpeed, uint8_t rightSpeed) {
  // Left Thruster: Forward (IN1 = HIGH, IN2 = LOW)
  digitalWrite(PIN_LEFT_IN1, HIGH);
  digitalWrite(PIN_LEFT_IN2, LOW);
  analogWrite(PIN_LEFT_ENA, leftSpeed);

  // Right Thruster: Forward (IN3 = HIGH, IN4 = LOW)
  digitalWrite(PIN_RIGHT_IN3, HIGH);
  digitalWrite(PIN_RIGHT_IN4, LOW);
  analogWrite(PIN_RIGHT_ENB, rightSpeed);
}

/**
 * Reverses both thrusters simultaneously to back away from an obstacle.
 */
void moveReverse(uint8_t speed) {
  // Left Thruster: Reverse (IN1 = LOW, IN2 = HIGH)
  digitalWrite(PIN_LEFT_IN1, LOW);
  digitalWrite(PIN_LEFT_IN2, HIGH);
  analogWrite(PIN_LEFT_ENA, speed);

  // Right Thruster: Reverse (IN3 = LOW, IN4 = HIGH)
  digitalWrite(PIN_RIGHT_IN3, LOW);
  digitalWrite(PIN_RIGHT_IN4, HIGH);
  analogWrite(PIN_RIGHT_ENB, speed);
}

/**
 * Executes a right turn by powering only the left thruster (differential steering).
 */
void turnRight(uint8_t speed) {
  // Left Thruster: Forward drive
  digitalWrite(PIN_LEFT_IN1, HIGH);
  digitalWrite(PIN_LEFT_IN2, LOW);
  analogWrite(PIN_LEFT_ENA, speed);

  // Right Thruster: Idle/Brake
  digitalWrite(PIN_RIGHT_IN3, LOW);
  digitalWrite(PIN_RIGHT_IN4, LOW);
  analogWrite(PIN_RIGHT_ENB, 0);
}

/**
 * Immediately brakes/coasts both thrusters to zero RPM.
 */
void stopThrusters() {
  digitalWrite(PIN_LEFT_IN1, LOW);
  digitalWrite(PIN_LEFT_IN2, LOW);
  analogWrite(PIN_LEFT_ENA, 0);

  digitalWrite(PIN_RIGHT_IN3, LOW);
  digitalWrite(PIN_RIGHT_IN4, LOW);
  analogWrite(PIN_RIGHT_ENB, 0);
}

/**
 * Controls the central paddle wheel or trash conveyor mechanism.
 * @param speed: PWM level (0 to 255). 0 stops rotation.
 */
void runCollector(uint8_t speed) {
  if (speed > 0) {
    digitalWrite(PIN_COLL_DIR, HIGH); // Intake rotation direction
    analogWrite(PIN_COLL_PWM, speed);
  } else {
    digitalWrite(PIN_COLL_DIR, LOW);
    analogWrite(PIN_COLL_PWM, 0);
  }
}

// ==========================================
// STATE MACHINE & OBSTACLE AVOIDANCE
// ==========================================
void avoidObstacleStateMachine() {
  unsigned long now = millis();

  switch (currentState) {

    // 1. Initial 3-second startup safety delay
    case STATE_STANDBY:
      if (now - stateTimer >= DELAY_STARTUP_MS) {
        Serial.println(F("[SYSTEM] Armed. Starting navigation and trash collection."));
        currentState = STATE_NAV_FORWARD;
      }
      break;

    // 2. Normal operational cruise
    case STATE_NAV_FORWARD:
      // Keep conveyor actively running during forward collection
      runCollector(SPEED_COLLECTOR);
      moveForward(SPEED_FORWARD_LEFT, SPEED_FORWARD_RIGHT);

      // Check if distance reading falls within trigger boundary
      if (currentDistanceCm <= OBSTACLE_DIST_CM && currentDistanceCm >= (SENSOR_MIN_VALID_CM - 5.0f)) {
        Serial.println(F("[ALERT] Obstacle detected! Initiating evasive sequence."));
        stopThrusters();
        stateTimer = now;
        currentState = STATE_AVOID_STOP;
      }
      break;

    // 3. Inertia dampening stop (brief 150ms pause before reversing)
    case STATE_AVOID_STOP:
      stopThrusters();
      if (now - stateTimer >= 150) { 
        stateTimer = now;
        currentState = STATE_AVOID_REVERSE;
      }
      break;

    // 4. Reverse away from the obstacle for 1.5 seconds
    case STATE_AVOID_REVERSE:
      moveReverse(SPEED_REVERSE);
      if (now - stateTimer >= DURATION_REVERSE_MS) {
        stopThrusters();
        stateTimer = now;
        currentState = STATE_AVOID_TURN;
      }
      break;

    // 5. Differential pivot turn to the right for 1.5 seconds
    case STATE_AVOID_TURN:
      turnRight(SPEED_TURN);
      if (now - stateTimer >= DURATION_TURN_MS) {
        stopThrusters();
        Serial.println(F("[RECOVERY] Obstacle cleared. Resuming forward cruise."));
        currentState = STATE_NAV_FORWARD;
      }
      break;
  }
}

// ==========================================
// TELEMETRY / SERIAL DIAGNOSTICS
// ==========================================
void logDiagnostics() {
  Serial.print(F("Time: "));
  Serial.print(millis() / 1000.0f, 1);
  Serial.print(F("s | Dist: "));

  if (currentDistanceCm >= SENSOR_MAX_VALID_CM) {
    Serial.print(F("CLEAR (>350)"));
  } else {
    Serial.print(currentDistanceCm, 1);
    Serial.print(F(" cm"));
  }

  Serial.print(F(" | FSM: "));
  switch (currentState) {
    case STATE_STANDBY:       Serial.println(F("STANDBY (Arming)")); break;
    case STATE_NAV_FORWARD:   Serial.println(F("CRUISE (Forward + Collector 75%)")); break;
    case STATE_AVOID_STOP:    Serial.println(F("AVOID: BRAKING")); break;
    case STATE_AVOID_REVERSE: Serial.println(F("AVOID: REVERSING (1.5s)")); break;
    case STATE_AVOID_TURN:    Serial.println(F("AVOID: TURNING RIGHT (1.5s)")); break;
  }
}
