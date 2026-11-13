#include <Wire.h>

// ==================================================
// MONROE CONTROLLER FIRMWARE (thin I/O layer)
// ==================================================
// The treatment sequence (evacuate -> plasma -> vent -> count cycles)
// runs in the Python GUI. This sketch only:
//   1. streams sensor and output state to the PC, and
//   2. applies commands sent by the PC.
//
// Serial: 115200 baud, one command per line (case-insensitive)
//
// SOLENOID ON | SOLENOID OFF -> Solenoid valve relay on D2
// PUMP ON | PUMP OFF         -> Vacuum pump on D7
// BRIDGE ON | BRIDGE OFF     -> Half-bridge power on D8
// VALVE <0-100> or <0-100>   -> Proportional valve opening via GP8302
// FREQ <0-40000>             -> Gate signal on D9 in Hz, 50% duty (Timer1)
//                               0 = gate stopped, D9 held LOW
// ALL OFF                    -> Bridge, gate, pump, solenoid off, valve 0%
// STREAM <ms>                -> DATA line period (0 = off, default 200 ms)
// WATCHDOG <s>               -> ALL OFF if no command received for <s>
//                               seconds (0 = disabled, default 5 s)
// PING                       -> Does nothing; keeps the watchdog fed
// STATUS                     -> Send one DATA line now
//
// DATA line (sent every STREAM ms):
// DATA MS=12345 SOL=0 PUMP=1 BRIDGE=0 VALVE=0.0 FREQ=20000 AFREQ=20000.0
//
// Chamber pressure is NOT read here: the Omega PXM409-USBH transmitter
// plugs into the PC by USB and the GUI reads it directly.

// ==================================================
// GP8302 CONFIGURATION
// ==================================================

const uint8_t DAC_ADDR = 0x58;
const uint8_t CURRENT_REG = 0x02;

const float MAX_VOLTAGE = 10.0;     // V
const float MAX_CURRENT = 25.0;     // mA
const float LOAD_RESISTOR = 460.0;  // Ohms

// ==================================================
// PINS
// ==================================================

const uint8_t SOLENOID_VALVE_PIN = 2; // D2 - Relay controlling solenoid valve
const uint8_t VACUUM_PUMP_PIN = 7;    // D7
const uint8_t HALF_BRIDGE_PIN = 8;    // D8
const uint8_t PWM_PIN = 9;            // D9 - Timer1 OC1A (Uno/Nano)

// ==================================================
// STATE
// ==================================================

const uint32_t MAX_GATE_FREQ = 40000; // Hz

float openingPercent = 0.0;
bool solenoidState = false;
bool pumpState = false;
bool bridgeState = false;
uint32_t gateFrequency = 0;   // Hz, requested
float actualFrequency = 0.0;  // Hz, produced by Timer1

unsigned long streamPeriodMs = 200;
unsigned long lastStreamMs = 0;

unsigned long watchdogMs = 5000;
unsigned long lastCommandMs = 0;
bool watchdogTripped = false;

// ==================================================
// TIMER1 GATE PWM (D9, 50% duty)
// ==================================================

const uint16_t PRESCALERS[] = {1, 8, 64, 256, 1024};
const uint8_t PRESCALER_BITS[] = {
  _BV(CS10),
  _BV(CS11),
  _BV(CS11) | _BV(CS10),
  _BV(CS12),
  _BV(CS12) | _BV(CS10)
};

void gateStop()
{
  TCCR1A = 0;
  TCCR1B = 0;
  digitalWrite(PWM_PIN, LOW);
  actualFrequency = 0.0;
}

void setGateFrequency(long hz)
{
  if (hz < 0 || hz > (long)MAX_GATE_FREQ)
  {
    Serial.println("ERROR: Frequency must be 0 to 40000 Hz.");
    return;
  }

  gateFrequency = (uint32_t)hz;

  if (gateFrequency == 0)
  {
    gateStop();
    Serial.println("Gate: OFF");
    return;
  }

  // Smallest prescaler whose TOP fits in 16 bits
  for (uint8_t i = 0; i < 5; i++)
  {
    uint32_t top =
        (uint32_t)((F_CPU / (float)PRESCALERS[i] / gateFrequency) + 0.5) - 1;

    if (top <= 65535UL && top >= 1)
    {
      TCCR1B = 0;                         // stop timer while reconfiguring
      ICR1 = (uint16_t)top;
      OCR1A = (uint16_t)((top + 1) / 2);  // 50% duty
      if (TCNT1 > top) TCNT1 = 0;

      // Fast PWM mode 14 (TOP = ICR1), non-inverting on OC1A (D9)
      TCCR1A = _BV(COM1A1) | _BV(WGM11);
      TCCR1B = _BV(WGM13) | _BV(WGM12) | PRESCALER_BITS[i];

      actualFrequency = F_CPU / (float)PRESCALERS[i] / (top + 1);

      Serial.print("Gate frequency: ");
      Serial.print(actualFrequency, 1);
      Serial.println(" Hz");
      return;
    }
  }

  gateStop();
  Serial.println("ERROR: Frequency too low.");
}

// ==================================================
// GP8302 / PROPORTIONAL VALVE
// ==================================================

bool setVoltage(float voltage)
{
  voltage = constrain(voltage, 0.0, MAX_VOLTAGE);

  float current_mA = (voltage / LOAD_RESISTOR) * 1000.0;
  uint16_t dacValue = (uint16_t)((current_mA / MAX_CURRENT) * 4095.0);

  uint8_t lowByte = (dacValue << 4) & 0xF0;
  uint8_t highByte = (dacValue >> 4) & 0xFF;

  Wire.beginTransmission(DAC_ADDR);
  Wire.write(CURRENT_REG);
  Wire.write(lowByte);
  Wire.write(highByte);

  uint8_t error = Wire.endTransmission();

  if (error != 0)
  {
    Serial.print("ERROR: DAC communication error ");
    Serial.println(error);
    return false;
  }

  return true;
}

void setValveOpening(float percentage)
{
  if (percentage < 0.0 || percentage > 100.0)
  {
    Serial.println("ERROR: Valve must be 0 to 100%.");
    return;
  }

  if (setVoltage(MAX_VOLTAGE * (percentage / 100.0)))
  {
    openingPercent = percentage;
    Serial.print("Valve: ");
    Serial.print(openingPercent, 1);
    Serial.println("%");
  }
}

// ==================================================
// DIGITAL OUTPUTS
// ==================================================

void setSolenoidValve(bool state)
{
  // HIGH energises relay: COM1 -> NO1 supplies 12 V to the valve.
  digitalWrite(SOLENOID_VALVE_PIN, state ? HIGH : LOW);
  solenoidState = state;
  Serial.print("Solenoid: ");
  Serial.println(state ? "ON" : "OFF");
}

void setVacuumPump(bool state)
{
  digitalWrite(VACUUM_PUMP_PIN, state ? HIGH : LOW);
  pumpState = state;
  Serial.print("Pump: ");
  Serial.println(state ? "ON" : "OFF");
}

void setHalfBridge(bool state)
{
  digitalWrite(HALF_BRIDGE_PIN, state ? HIGH : LOW);
  bridgeState = state;
  Serial.print("Bridge: ");
  Serial.println(state ? "ON" : "OFF");
}

void allOff()
{
  setHalfBridge(false);   // power off before stopping the gate
  setGateFrequency(0);
  setVacuumPump(false);
  setValveOpening(0.0);
  setSolenoidValve(false);
}

// ==================================================
// DATA STREAM
// ==================================================

void sendData()
{
  Serial.print("DATA MS=");
  Serial.print(millis());
  Serial.print(" SOL=");
  Serial.print(solenoidState ? 1 : 0);
  Serial.print(" PUMP=");
  Serial.print(pumpState ? 1 : 0);
  Serial.print(" BRIDGE=");
  Serial.print(bridgeState ? 1 : 0);
  Serial.print(" VALVE=");
  Serial.print(openingPercent, 1);
  Serial.print(" FREQ=");
  Serial.print(gateFrequency);
  Serial.print(" AFREQ=");
  Serial.println(actualFrequency, 1);
}

// ==================================================
// COMMAND HANDLING
// ==================================================

bool isNumber(const String &s, bool allowDecimal)
{
  if (s.length() == 0) return false;

  bool dot = false;
  for (unsigned int i = 0; i < s.length(); i++)
  {
    char c = s.charAt(i);
    if (c == '.' && allowDecimal && !dot) dot = true;
    else if (c < '0' || c > '9') return false;
  }
  return true;
}

// Returns the argument after "<KEYWORD> ", or "" if the prefix doesn't match
String argAfter(const String &input, const char *keyword)
{
  String prefix = String(keyword) + " ";
  if (!input.startsWith(prefix)) return "";
  String arg = input.substring(prefix.length());
  arg.trim();
  return arg;
}

void handleCommand(String input)
{
  input.trim();
  input.toUpperCase();
  if (input.length() == 0) return;

  if (input == "PING") return;
  if (input == "STATUS") { sendData(); return; }

  if (input == "SOLENOID ON")  { setSolenoidValve(true);  return; }
  if (input == "SOLENOID OFF") { setSolenoidValve(false); return; }
  if (input == "PUMP ON")      { setVacuumPump(true);     return; }
  if (input == "PUMP OFF")     { setVacuumPump(false);    return; }
  if (input == "BRIDGE ON")    { setHalfBridge(true);     return; }
  if (input == "BRIDGE OFF")   { setHalfBridge(false);    return; }
  if (input == "ALL OFF")      { allOff();                return; }

  String arg;

  if ((arg = argAfter(input, "FREQ")).length())
  {
    if (isNumber(arg, false)) setGateFrequency(arg.toInt());
    else Serial.println("ERROR: Usage FREQ 0-40000");
    return;
  }

  if ((arg = argAfter(input, "STREAM")).length())
  {
    if (isNumber(arg, false)) streamPeriodMs = arg.toInt();
    else Serial.println("ERROR: Usage STREAM <ms>");
    return;
  }

  if ((arg = argAfter(input, "WATCHDOG")).length())
  {
    if (isNumber(arg, false)) watchdogMs = arg.toInt() * 1000UL;
    else Serial.println("ERROR: Usage WATCHDOG <seconds>");
    return;
  }

  if ((arg = argAfter(input, "VALVE")).length())
  {
    input = arg;
  }

  if (isNumber(input, true))
  {
    setValveOpening(input.toFloat());
    return;
  }

  Serial.println("ERROR: Invalid command.");
}

// ==================================================
// SETUP
// ==================================================

void setup()
{
  Serial.begin(115200);
  Serial.setTimeout(100);

  Wire.begin();
  Wire.setClock(100000);

  pinMode(SOLENOID_VALVE_PIN, OUTPUT);
  pinMode(VACUUM_PUMP_PIN, OUTPUT);
  pinMode(HALF_BRIDGE_PIN, OUTPUT);
  pinMode(PWM_PIN, OUTPUT);

  digitalWrite(SOLENOID_VALVE_PIN, LOW);
  digitalWrite(VACUUM_PUMP_PIN, LOW);
  digitalWrite(HALF_BRIDGE_PIN, LOW);
  gateStop();

  delay(1000);

  Serial.println();
  Serial.println("Monroe Controller (thin firmware)");

  Wire.beginTransmission(DAC_ADDR);
  if (Wire.endTransmission() != 0)
  {
    Serial.println("ERROR: GP8302 not detected.");
    while (true)
    {
      delay(1000);
    }
  }
  Serial.println("GP8302 detected at 0x58.");

  setValveOpening(0.0);
  setSolenoidValve(false);

  lastCommandMs = millis();
  Serial.println("READY");
}

// ==================================================
// MAIN LOOP
// ==================================================

void loop()
{
  if (Serial.available() > 0)
  {
    String line = Serial.readStringUntil('\n');
    lastCommandMs = millis();
    watchdogTripped = false;
    handleCommand(line);
  }

  // Safety: if the PC stops talking, shut everything off once
  if (watchdogMs > 0 && !watchdogTripped &&
      millis() - lastCommandMs >= watchdogMs)
  {
    watchdogTripped = true;
    if (bridgeState || pumpState || solenoidState || gateFrequency || openingPercent > 0)
    {
      Serial.println("WATCHDOG: no commands from PC, ALL OFF");
      allOff();
    }
  }

  if (streamPeriodMs > 0 && millis() - lastStreamMs >= streamPeriodMs)
  {
    lastStreamMs = millis();
    sendData();
  }
}
