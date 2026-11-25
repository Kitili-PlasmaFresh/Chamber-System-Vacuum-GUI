#include <SPI.h>
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
// COOLANT ON | COOLANT OFF   -> Coolant pump relay on D2
// PUMP ON | PUMP OFF         -> Vacuum pump on D7
// BRIDGE ON | BRIDGE OFF     -> Half-bridge power on D8
// VALVE <0-100> or <0-100>   -> Proportional valve opening via GP8302
// FREQ <0-40000>             -> Gate signal on D9 in Hz, 50% duty (Timer1)
//                               0 = gate stopped, D9 held LOW
// ALL OFF                    -> Bridge, gate, vacuum pump, coolant pump off,
//                               valve 0%
// STREAM <ms>                -> DATA line period (0 = off, default 200 ms)
// WATCHDOG <s>               -> ALL OFF if no command received for <s>
//                               seconds (0 = disabled, default 5 s)
// PING                       -> Does nothing; keeps the watchdog fed
// STATUS                     -> Send one DATA line now
//
// DATA line (sent every STREAM ms):
// DATA MS=12345 COOLANT=0 PUMP=1 BRIDGE=0 VALVE=0.0 FREQ=20000 AFREQ=20000.0
//      FLOWOK=1 FLOW=12.345 FTEMP=23.10
//      HUMOK=1 HUM=45.12 HTEMP=22.85
//      TC1OK=1 TC1=85.25 TC2OK=1 TC2=84.75 TC3OK=0 TC3F=1
// FLOW (slm) and FTEMP (deg C) come from the Sensirion SFM4300-50-P on the
// I2C bus; they are only sent when FLOWOK=1.
// HUM (%RH) and HTEMP (deg C) come from the Sensylink CHT832X humidity
// sensor; they are only sent when HUMOK=1 and update once per second.
//
// I2C bus (Uno R3 SDA/SCL header pins, same lines as A4/A5):
//   GP8302 DAC        0x58
//   SFM4300-50-P      0x2A
//   CHT832X           0x44 (0x45/0x46/0x47 for B/C/D address variants)
//
// Chamber Temp Sensors 1-3: MAX31855 thermocouple converters on hardware SPI
//   MISO D12, SCK D13, chip selects D3 / D4 / D5. TCn (deg C) is sent when
//   TCnOK=1; otherwise TCnF is a fault bitfield:
//   1 = open circuit, 2 = short to GND, 4 = short to VCC, 8 = no response
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
// SFM4300-50-P FLOW SENSOR CONFIGURATION
// ==================================================

const uint8_t FLOW_ADDR = 0x2A;

// Continuous-measurement command selects the gas calibration.
//   0x3603 O2   0x3608 Air   0x3615 N2O   0x361E CO2
const uint16_t FLOW_CMD_START = 0x3608;   // Air
const uint16_t FLOW_CMD_STOP = 0x3FF9;
const uint16_t FLOW_CMD_READ_SCALE = 0x3661;

const float FLOW_TEMP_SCALE = 200.0;      // raw / 200 = deg C
const unsigned long FLOW_RETRY_MS = 2000; // retry init if sensor missing

// ==================================================
// CHT832X HUMIDITY SENSOR CONFIGURATION
// ==================================================

// 7-bit address set by part number: A=0x44, B=0x45, C=0x46, D=0x47
// (datasheet lists 8-bit write addresses 0x88/0x8A/0x8C/0x8E)
const uint8_t HUM_ADDR = 0x44;

const uint16_t HUM_CMD_ONESHOT = 0x2400;  // T + RH, no clock stretching
const uint16_t HUM_CMD_BREAK = 0x3093;    // stop any periodic mode
const uint16_t HUM_CMD_SOFT_RESET = 0x30A2;
const uint16_t HUM_CMD_MANUFACTURER_ID = 0x3781;
const uint16_t HUM_MANUFACTURER_ID = 0x5959;

const unsigned long HUM_PERIOD_MS = 1000;   // datasheet: <= 1 measurement/s
const unsigned long HUM_CONVERT_MS = 20;    // wait after one-shot trigger
const unsigned long HUM_RETRY_MS = 2000;

// ==================================================
// MAX31855 CHAMBER TEMPERATURE SENSORS
// ==================================================

const uint8_t TC_COUNT = 3;
const uint8_t TC_CS_PINS[TC_COUNT] = {3, 4, 5};  // Chamber Temp Sensor 1, 2, 3
const unsigned long TC_PERIOD_MS = 250;           // conversion takes <= 100 ms
const SPISettings TC_SPI(4000000, MSBFIRST, SPI_MODE0);  // MAX31855: <= 5 MHz

const uint8_t TC_FAULT_NO_RESPONSE = 8;

// ==================================================
// PINS
// ==================================================

const uint8_t COOLANT_PUMP_PIN = 2;   // D2 - Relay controlling coolant pump
const uint8_t VACUUM_PUMP_PIN = 7;    // D7
const uint8_t HALF_BRIDGE_PIN = 8;    // D8
const uint8_t PWM_PIN = 9;            // D9 - Timer1 OC1A (Uno/Nano)

// ==================================================
// STATE
// ==================================================

const uint32_t MAX_GATE_FREQ = 40000; // Hz

float openingPercent = 0.0;
bool coolantState = false;
bool pumpState = false;
bool bridgeState = false;
uint32_t gateFrequency = 0;   // Hz, requested
float actualFrequency = 0.0;  // Hz, produced by Timer1

unsigned long streamPeriodMs = 200;
unsigned long lastStreamMs = 0;

unsigned long watchdogMs = 5000;
unsigned long lastCommandMs = 0;
bool watchdogTripped = false;

bool flowReady = false;        // sensor initialised and measuring
bool flowValid = false;        // last read succeeded
int16_t flowScale = 1;         // read from sensor at init
int16_t flowOffset = 0;
float flowSlm = 0.0;
float flowTempC = 0.0;
unsigned long lastFlowInitMs = 0;

bool humReady = false;         // sensor detected
bool humValid = false;         // last read succeeded
bool humPending = false;       // one-shot triggered, waiting for result
float humRh = 0.0;
float humTempC = 0.0;
unsigned long humTriggerMs = 0;
unsigned long lastHumMs = 0;

float tcTempC[TC_COUNT] = {0.0, 0.0, 0.0};
uint8_t tcFault[TC_COUNT] = {TC_FAULT_NO_RESPONSE, TC_FAULT_NO_RESPONSE,
                             TC_FAULT_NO_RESPONSE};   // 0 = reading valid
unsigned long lastTcMs = 0;

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
    Serial.println(F("ERROR: Frequency must be 0 to 40000 Hz."));
    return;
  }

  gateFrequency = (uint32_t)hz;

  if (gateFrequency == 0)
  {
    gateStop();
    Serial.println(F("Gate: OFF"));
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

      Serial.print(F("Gate frequency: "));
      Serial.print(actualFrequency, 1);
      Serial.println(F(" Hz"));
      return;
    }
  }

  gateStop();
  Serial.println(F("ERROR: Frequency too low."));
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
    Serial.print(F("ERROR: DAC communication error "));
    Serial.println(error);
    return false;
  }

  return true;
}

void setValveOpening(float percentage)
{
  if (percentage < 0.0 || percentage > 100.0)
  {
    Serial.println(F("ERROR: Valve must be 0 to 100%."));
    return;
  }

  if (setVoltage(MAX_VOLTAGE * (percentage / 100.0)))
  {
    openingPercent = percentage;
    Serial.print(F("Valve: "));
    Serial.print(openingPercent, 1);
    Serial.println(F("%"));
  }
}

// ==================================================
// SFM4300-50-P FLOW SENSOR (I2C)
// ==================================================

// Sensirion CRC-8: polynomial 0x31, init 0xFF
uint8_t sensirionCrc(uint8_t msb, uint8_t lsb)
{
  uint8_t crc = 0xFF;
  uint8_t data[2] = {msb, lsb};
  for (uint8_t i = 0; i < 2; i++)
  {
    crc ^= data[i];
    for (uint8_t b = 0; b < 8; b++)
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x31) : (uint8_t)(crc << 1);
  }
  return crc;
}

bool i2cWriteCommand(uint8_t addr, uint16_t cmd)
{
  Wire.beginTransmission(addr);
  Wire.write((uint8_t)(cmd >> 8));
  Wire.write((uint8_t)(cmd & 0xFF));
  return Wire.endTransmission() == 0;
}

bool flowWriteCommandArg(uint16_t cmd, uint16_t arg)
{
  uint8_t msb = arg >> 8, lsb = arg & 0xFF;
  Wire.beginTransmission(FLOW_ADDR);
  Wire.write((uint8_t)(cmd >> 8));
  Wire.write((uint8_t)(cmd & 0xFF));
  Wire.write(msb);
  Wire.write(lsb);
  Wire.write(sensirionCrc(msb, lsb));
  return Wire.endTransmission() == 0;
}

// Reads `count` CRC-protected 16-bit words (Sensirion-style framing,
// shared by the SFM4300 and CHT832X)
bool i2cReadWords(uint8_t addr, uint16_t *words, uint8_t count)
{
  uint8_t len = count * 3;
  if (Wire.requestFrom(addr, len) != len) return false;

  for (uint8_t i = 0; i < count; i++)
  {
    uint8_t msb = Wire.read();
    uint8_t lsb = Wire.read();
    uint8_t crc = Wire.read();
    if (sensirionCrc(msb, lsb) != crc) return false;
    words[i] = ((uint16_t)msb << 8) | lsb;
  }
  return true;
}

bool flowInit()
{
  flowReady = false;
  flowValid = false;

  // Stop any measurement left running (e.g. after an Arduino reset)
  i2cWriteCommand(FLOW_ADDR, FLOW_CMD_STOP);
  delay(1);

  // Scale factor and offset for the selected gas: flow = (raw - offset) / scale
  uint16_t w[3];
  if (!flowWriteCommandArg(FLOW_CMD_READ_SCALE, FLOW_CMD_START)) return false;
  delay(1);
  if (!i2cReadWords(FLOW_ADDR, w, 3)) return false;

  flowScale = (int16_t)w[0];
  flowOffset = (int16_t)w[1];
  if (flowScale == 0) return false;

  if (!i2cWriteCommand(FLOW_ADDR, FLOW_CMD_START)) return false;
  delay(15);  // first measurement ready ~12 ms after start

  flowReady = true;
  Serial.print(F("SFM4300 detected at 0x2A (scale "));
  Serial.print(flowScale);
  Serial.print(F(", offset "));
  Serial.print(flowOffset);
  Serial.println(F(")."));
  return true;
}

void readFlow()
{
  if (!flowReady)
  {
    if (millis() - lastFlowInitMs >= FLOW_RETRY_MS)
    {
      lastFlowInitMs = millis();
      flowInit();
    }
    return;
  }

  // Flow, temperature, status word
  uint16_t w[3];
  if (!i2cReadWords(FLOW_ADDR, w, 3))
  {
    if (flowValid) Serial.println(F("ERROR: SFM4300 read failed."));
    flowValid = false;
    flowReady = false;            // re-initialise on next retry
    lastFlowInitMs = millis();
    return;
  }

  flowSlm = ((int16_t)w[0] - flowOffset) / (float)flowScale;
  flowTempC = (int16_t)w[1] / FLOW_TEMP_SCALE;
  flowValid = true;
}

// ==================================================
// CHT832X HUMIDITY SENSOR (I2C)
// ==================================================

bool humInit()
{
  humReady = false;
  humValid = false;
  humPending = false;

  i2cWriteCommand(HUM_ADDR, HUM_CMD_BREAK);
  delay(1);
  if (!i2cWriteCommand(HUM_ADDR, HUM_CMD_SOFT_RESET)) return false;
  delay(5);  // soft reset time <= 1 ms, power-up <= 3 ms

  uint16_t id;
  if (!i2cWriteCommand(HUM_ADDR, HUM_CMD_MANUFACTURER_ID)) return false;
  if (!i2cReadWords(HUM_ADDR, &id, 1)) return false;
  if (id != HUM_MANUFACTURER_ID)
  {
    Serial.print(F("ERROR: Unexpected device at humidity address, ID 0x"));
    Serial.println(id, HEX);
    return false;
  }

  humReady = true;
  Serial.print(F("CHT832X detected at 0x"));
  Serial.print(HUM_ADDR, HEX);
  Serial.println(F("."));
  return true;
}

void humFail()
{
  if (humValid) Serial.println(F("ERROR: CHT832X read failed."));
  humValid = false;
  humReady = false;
  humPending = false;
  lastHumMs = millis();
}

// Non-blocking: trigger a one-shot, collect it HUM_CONVERT_MS later
void serviceHumidity()
{
  unsigned long now = millis();

  if (!humReady)
  {
    if (now - lastHumMs >= HUM_RETRY_MS)
    {
      lastHumMs = now;
      humInit();
    }
    return;
  }

  if (humPending)
  {
    if (now - humTriggerMs < HUM_CONVERT_MS) return;
    humPending = false;

    uint16_t w[2];  // temperature, humidity
    if (!i2cReadWords(HUM_ADDR, w, 2)) { humFail(); return; }

    humTempC = -45.0 + 175.0 * (w[0] / 65535.0);
    humRh = 100.0 * (w[1] / 65535.0);
    humValid = true;
    return;
  }

  if (now - lastHumMs >= HUM_PERIOD_MS)
  {
    lastHumMs = now;
    if (!i2cWriteCommand(HUM_ADDR, HUM_CMD_ONESHOT)) { humFail(); return; }
    humTriggerMs = now;
    humPending = true;
  }
}

// ==================================================
// MAX31855 THERMOCOUPLES (SPI)
// ==================================================

// 32-bit frame: D31-D18 thermocouple temp (signed, 0.25 C), D16 fault,
// D15-D4 cold-junction temp, D2 short to VCC, D1 short to GND, D0 open circuit
uint32_t tcReadFrame(uint8_t csPin)
{
  SPI.beginTransaction(TC_SPI);
  digitalWrite(csPin, LOW);
  uint32_t v = 0;
  for (uint8_t i = 0; i < 4; i++)
    v = (v << 8) | SPI.transfer(0x00);
  digitalWrite(csPin, HIGH);
  SPI.endTransaction();
  return v;
}

void readThermocouples()
{
  for (uint8_t i = 0; i < TC_COUNT; i++)
  {
    uint32_t v = tcReadFrame(TC_CS_PINS[i]);

    if (v == 0x00000000UL || v == 0xFFFFFFFFUL)
    {
      tcFault[i] = TC_FAULT_NO_RESPONSE;    // MISO stuck: chip absent/unpowered
    }
    else if (v & 0x00010000UL)
    {
      tcFault[i] = (uint8_t)(v & 0x07);     // OC / SCG / SCV bits
    }
    else
    {
      int16_t raw = (int16_t)((v >> 18) & 0x3FFF);
      if (raw & 0x2000) raw |= (int16_t)0xC000;   // sign-extend 14 bits
      tcTempC[i] = raw * 0.25;
      tcFault[i] = 0;
    }
  }
}

void serviceThermocouples()
{
  if (millis() - lastTcMs >= TC_PERIOD_MS)
  {
    lastTcMs = millis();
    readThermocouples();
  }
}

// ==================================================
// DIGITAL OUTPUTS
// ==================================================

void setCoolantPump(bool state)
{
  // HIGH energises relay: COM1 -> NO1 supplies 12 V to the coolant pump.
  digitalWrite(COOLANT_PUMP_PIN, state ? HIGH : LOW);
  coolantState = state;
  Serial.print(F("Coolant pump: "));
  Serial.println(state ? "ON" : "OFF");
}

void setVacuumPump(bool state)
{
  digitalWrite(VACUUM_PUMP_PIN, state ? HIGH : LOW);
  pumpState = state;
  Serial.print(F("Vacuum pump: "));
  Serial.println(state ? "ON" : "OFF");
}

void setHalfBridge(bool state)
{
  digitalWrite(HALF_BRIDGE_PIN, state ? HIGH : LOW);
  bridgeState = state;
  Serial.print(F("Bridge: "));
  Serial.println(state ? "ON" : "OFF");
}

void allOff()
{
  setHalfBridge(false);   // power off before stopping the gate
  setGateFrequency(0);
  setVacuumPump(false);
  setValveOpening(0.0);
  setCoolantPump(false);
}

// ==================================================
// DATA STREAM
// ==================================================

void sendData()
{
  Serial.print(F("DATA MS="));
  Serial.print(millis());
  Serial.print(F(" COOLANT="));
  Serial.print(coolantState ? 1 : 0);
  Serial.print(F(" PUMP="));
  Serial.print(pumpState ? 1 : 0);
  Serial.print(F(" BRIDGE="));
  Serial.print(bridgeState ? 1 : 0);
  Serial.print(F(" VALVE="));
  Serial.print(openingPercent, 1);
  Serial.print(F(" FREQ="));
  Serial.print(gateFrequency);
  Serial.print(F(" AFREQ="));
  Serial.print(actualFrequency, 1);
  Serial.print(F(" FLOWOK="));
  Serial.print(flowValid ? 1 : 0);
  if (flowValid)
  {
    Serial.print(F(" FLOW="));
    Serial.print(flowSlm, 3);
    Serial.print(F(" FTEMP="));
    Serial.print(flowTempC, 2);
  }
  Serial.print(F(" HUMOK="));
  Serial.print(humValid ? 1 : 0);
  if (humValid)
  {
    Serial.print(F(" HUM="));
    Serial.print(humRh, 2);
    Serial.print(F(" HTEMP="));
    Serial.print(humTempC, 2);
  }
  for (uint8_t i = 0; i < TC_COUNT; i++)
  {
    Serial.print(F(" TC"));
    Serial.print(i + 1);
    if (tcFault[i]) Serial.print(F("OK=0 TC"));
    else Serial.print(F("OK=1 TC"));
    Serial.print(i + 1);
    if (tcFault[i])
    {
      Serial.print(F("F="));
      Serial.print(tcFault[i]);
    }
    else
    {
      Serial.print(F("="));
      Serial.print(tcTempC[i], 2);
    }
  }
  Serial.println();
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
  if (input == "STATUS") { readFlow(); sendData(); return; }

  if (input == "COOLANT ON")   { setCoolantPump(true);    return; }
  if (input == "COOLANT OFF")  { setCoolantPump(false);   return; }
  if (input == "PUMP ON")      { setVacuumPump(true);     return; }
  if (input == "PUMP OFF")     { setVacuumPump(false);    return; }
  if (input == "BRIDGE ON")    { setHalfBridge(true);     return; }
  if (input == "BRIDGE OFF")   { setHalfBridge(false);    return; }
  if (input == "ALL OFF")      { allOff();                return; }

  String arg;

  if ((arg = argAfter(input, "FREQ")).length())
  {
    if (isNumber(arg, false)) setGateFrequency(arg.toInt());
    else Serial.println(F("ERROR: Usage FREQ 0-40000"));
    return;
  }

  if ((arg = argAfter(input, "STREAM")).length())
  {
    if (isNumber(arg, false)) streamPeriodMs = arg.toInt();
    else Serial.println(F("ERROR: Usage STREAM <ms>"));
    return;
  }

  if ((arg = argAfter(input, "WATCHDOG")).length())
  {
    if (isNumber(arg, false)) watchdogMs = arg.toInt() * 1000UL;
    else Serial.println(F("ERROR: Usage WATCHDOG <seconds>"));
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

  Serial.println(F("ERROR: Invalid command."));
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

  // MAX31855 chip selects idle HIGH before the SPI bus starts
  for (uint8_t i = 0; i < TC_COUNT; i++)
  {
    pinMode(TC_CS_PINS[i], OUTPUT);
    digitalWrite(TC_CS_PINS[i], HIGH);
  }
  SPI.begin();   // D13 SCK, D12 MISO (D11 MOSI / D10 SS driven but unused)

  pinMode(COOLANT_PUMP_PIN, OUTPUT);
  pinMode(VACUUM_PUMP_PIN, OUTPUT);
  pinMode(HALF_BRIDGE_PIN, OUTPUT);
  pinMode(PWM_PIN, OUTPUT);

  digitalWrite(COOLANT_PUMP_PIN, LOW);
  digitalWrite(VACUUM_PUMP_PIN, LOW);
  digitalWrite(HALF_BRIDGE_PIN, LOW);
  gateStop();

  delay(1000);

  Serial.println();
  Serial.println(F("Monroe Controller (thin firmware)"));

  Wire.beginTransmission(DAC_ADDR);
  if (Wire.endTransmission() != 0)
  {
    Serial.println(F("ERROR: GP8302 not detected."));
    while (true)
    {
      delay(1000);
    }
  }
  Serial.println(F("GP8302 detected at 0x58."));

  // Flow sensor is optional: keep running without it and retry in loop()
  lastFlowInitMs = millis();
  if (!flowInit())
    Serial.println(F("ERROR: SFM4300 not detected at 0x2A, will retry."));

  // Humidity sensor is optional too
  lastHumMs = millis();
  if (!humInit())
    Serial.println(F("ERROR: CHT832X not detected, will retry."));

  setValveOpening(0.0);
  setCoolantPump(false);

  lastCommandMs = millis();
  Serial.println(F("READY"));
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
    if (bridgeState || pumpState || coolantState || gateFrequency || openingPercent > 0)
    {
      Serial.println(F("WATCHDOG: no commands from PC, ALL OFF"));
      allOff();
    }
  }

  serviceHumidity();
  serviceThermocouples();

  if (streamPeriodMs > 0 && millis() - lastStreamMs >= streamPeriodMs)
  {
    lastStreamMs = millis();
    readFlow();
    sendData();
  }
}
