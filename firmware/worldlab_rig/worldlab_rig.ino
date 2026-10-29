// WorldLab rig firmware (Arduino Uno / Nano, ATmega328P)
//
// Hardware
//   2x DS18B20 on one OneWire bus, pin 2, 4.7k pull-up to 5V
//      sensor 0: bonded to the heatsink (object), sensor 1: in free air (ambient)
//      bus index 0 is used as the object and index 1 as ambient; if yours read the
//      wrong way round, swap the two getAddress() indices in setup()
//   4-pin PWM PC fan: PWM wire on pin 9 (25 kHz, Timer1), 12 V supply, common ground
//   Heater: 10 W power resistor (e.g. 3.3 ohm 25 W on 5.7 V, or 15 ohm on 12 V)
//           switched by a logic-level N-MOSFET, gate on pin 7 (with 100 ohm + 100k pull-down)
//   Optional INA219 on I2C measuring the fan's 12 V line (define USE_INA219)
//
// Safety, independent of the host
//   - object above TRIP_C: heater off, fan 100%, latched until the host sends R
//   - no command from the host for WATCHDOG_MS: heater off, fan 100%
//   - heater is refused while a sensor reads invalid
//
// Serial 115200: see worldlab/rig/serial_rig.py for the protocol.

#include <OneWire.h>
#include <DallasTemperature.h>
// #define USE_INA219
#ifdef USE_INA219
#include <Adafruit_INA219.h>
Adafruit_INA219 ina219;
#endif

const uint8_t ONEWIRE_PIN = 2;
const uint8_t FAN_PWM_PIN = 9;     // OC1A
const uint8_t HEATER_PIN = 7;
const float TRIP_C = 80.0;
const unsigned long WATCHDOG_MS = 10000;
const unsigned long PERIOD_MS = 1000;

OneWire oneWire(ONEWIRE_PIN);
DallasTemperature sensors(&oneWire);
DeviceAddress objAddr, ambAddr;

uint8_t fanPct = 0;
bool heaterOn = false;
bool tripped = false;
bool watchdogSafe = false;
unsigned long lastCmd = 0, lastSample = 0;
String line;

void fanInit() {
  // 25 kHz phase-correct PWM on pin 9: TOP = 320 at 16 MHz, no prescaler
  pinMode(FAN_PWM_PIN, OUTPUT);
  TCCR1A = _BV(COM1A1) | _BV(WGM11);
  TCCR1B = _BV(WGM13) | _BV(CS10);
  ICR1 = 320;
  OCR1A = 0;
}

void applyOutputs() {
  bool safe = tripped || watchdogSafe;
  uint8_t pct = safe ? 100 : fanPct;
  OCR1A = (uint16_t)((uint32_t)pct * 320 / 100);
  digitalWrite(HEATER_PIN, (heaterOn && !safe) ? HIGH : LOW);
}

void setup() {
  Serial.begin(115200);
  pinMode(HEATER_PIN, OUTPUT);
  digitalWrite(HEATER_PIN, LOW);
  fanInit();
  sensors.begin();
  sensors.setResolution(12);
  if (sensors.getDeviceCount() < 2) {
    Serial.println("E,need two DS18B20 sensors");
  }
  sensors.getAddress(objAddr, 0);
  sensors.getAddress(ambAddr, 1);
#ifdef USE_INA219
  ina219.begin();
#endif
  sensors.setWaitForConversion(false);
  sensors.requestTemperatures();
  lastCmd = millis();
  applyOutputs();
  Serial.println("I,worldlab rig ready");
}

void handle(const String& cmd) {
  lastCmd = millis();
  watchdogSafe = false;
  char c = cmd.length() ? cmd.charAt(0) : ' ';
  int v = cmd.length() > 2 ? cmd.substring(2).toInt() : 0;
  if (c == 'F') { fanPct = constrain(v, 0, 100); Serial.print("OK,F,"); Serial.println(fanPct); }
  else if (c == 'H') { heaterOn = (v == 1); Serial.print("OK,H,"); Serial.println(heaterOn ? 1 : 0); }
  else if (c == 'P') { /* heartbeat */ }
  else if (c == 'S') { heaterOn = false; fanPct = 100; Serial.println("OK,S"); }
  else if (c == 'R') { tripped = false; Serial.println("OK,R"); }
  applyOutputs();
}

void loop() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n') { line.trim(); if (line.length()) handle(line); line = ""; }
    else if (line.length() < 32) line += ch;
  }
  if (millis() - lastCmd > WATCHDOG_MS && !watchdogSafe) {
    watchdogSafe = true;
    applyOutputs();
    Serial.println("W,watchdog: host silent, safe state");
  }
  if (millis() - lastSample >= PERIOD_MS) {
    lastSample = millis();
    float tObj = sensors.getTempC(objAddr);
    float tAmb = sensors.getTempC(ambAddr);
    sensors.requestTemperatures();
    bool valid = tObj > -50 && tObj < 125 && tAmb > -50 && tAmb < 125;
    if (!valid) heaterOn = false;
    if (valid && tObj >= TRIP_C) tripped = true;
    applyOutputs();
    long mw = -1;
#ifdef USE_INA219
    mw = (long)(ina219.getPower_mW());
#endif
    Serial.print("D,"); Serial.print(millis()); Serial.print(',');
    Serial.print(tObj, 4); Serial.print(','); Serial.print(tAmb, 4); Serial.print(',');
    Serial.print((tripped || watchdogSafe) ? 100 : fanPct); Serial.print(',');
    Serial.print((heaterOn && !tripped && !watchdogSafe) ? 1 : 0); Serial.print(',');
    Serial.print(mw); Serial.print(',');
    Serial.println(tripped ? "TRIP" : (watchdogSafe ? "WDOG" : (valid ? "OK" : "SENSOR")));
  }
}
