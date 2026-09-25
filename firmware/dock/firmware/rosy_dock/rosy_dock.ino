// Rosy charging dock — ESP32 reference firmware.
//
// The rule that matters most is the first one: the output is never energised
// without a detected load. Bare DC contacts on a floor at pet and toddler
// height are a short-circuit and foreign-object hazard, and that hazard — not
// the current reporting — is why this controller exists at all.
//
// Contract: ../../README.md (ROSY-DOCK-001), ADR D-28.
// The robot polls; this device never initiates a connection.

#include <Arduino.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>

// --- pins -------------------------------------------------------------------

static const int PIN_OUTPUT_ENABLE = 25;  // drives the contact relay / FET
static const int PIN_CURRENT_SENSE = 34;  // ADC, current shunt amplifier
static const int PIN_VOLTAGE_SENSE = 35;  // ADC, output voltage divider
static const int PIN_LOAD_SENSE = 32;     // ADC, probe current through contacts

// --- thresholds -------------------------------------------------------------

// A pack presents a load; open contacts do not. Probing is done at a current
// far below anything that could matter if the "load" turns out to be a coin.
static const float LOAD_PROBE_THRESHOLD_V = 0.25f;
static const float CHARGING_CURRENT_A = 0.05f;   // above this, current is flowing
static const float OVER_CURRENT_A = 3.0f;        // fault: fold back immediately
static const float OVER_VOLTAGE_V = 8.7f;        // fault: 2S full is 8.4 V

static const uint32_t LOAD_DEBOUNCE_MS = 300;    // no chatter on a bouncing pad
static const uint32_t SAMPLE_INTERVAL_MS = 50;

// --- state ------------------------------------------------------------------

WebServer server(80);
Preferences prefs;

static bool outputEnabled = false;
static bool loadDetected = false;
static float currentA = 0.0f;
static float outputVoltageV = 0.0f;
static String faults = "";
static String dockId = "dock_1";

static uint32_t loadSince = 0;
static uint32_t lastSample = 0;

// --- output control ---------------------------------------------------------

// The single place the contacts are switched. Everything else calls this.
static void setOutput(bool on) {
  outputEnabled = on;
  digitalWrite(PIN_OUTPUT_ENABLE, on ? HIGH : LOW);
}

static void raiseFault(const char *name) {
  // A fault always de-energises. There is no fault worth staying live for.
  setOutput(false);
  if (faults.length() > 0) {
    faults += ",";
  }
  faults += name;
}

// --- sensing ----------------------------------------------------------------

static float readVolts(int pin, float scale) {
  return (analogRead(pin) / 4095.0f) * 3.3f * scale;
}

static void sampleSensors() {
  currentA = readVolts(PIN_CURRENT_SENSE, 1.0f) / 0.4f;   // shunt amp gain
  outputVoltageV = readVolts(PIN_VOLTAGE_SENSE, 4.0f);    // 1:4 divider

  const float probe = readVolts(PIN_LOAD_SENSE, 1.0f);
  const bool present = probe > LOAD_PROBE_THRESHOLD_V;

  const uint32_t now = millis();
  if (!present) {
    loadDetected = false;
    loadSince = 0;
    return;
  }
  if (loadSince == 0) {
    loadSince = now;
  }
  // Debounced, so a pad brushing past on the way in does not energise the dock.
  loadDetected = (now - loadSince) >= LOAD_DEBOUNCE_MS;
}

static void reconcileOutput() {
  if (currentA > OVER_CURRENT_A) {
    raiseFault("overcurrent");
    return;
  }
  if (outputVoltageV > OVER_VOLTAGE_V) {
    raiseFault("overvoltage");
    return;
  }
  if (faults.length() > 0) {
    setOutput(false);       // faults latch until the load is removed
    if (!loadDetected) {
      faults = "";
    }
    return;
  }
  // Rule 1 and rule 2, in one line: energised exactly while a load is present.
  setOutput(loadDetected);
}

// --- HTTP -------------------------------------------------------------------

static String faultsJson() {
  if (faults.length() == 0) {
    return "[]";
  }
  String out = "[";
  int start = 0;
  while (true) {
    const int comma = faults.indexOf(',', start);
    const String item = comma < 0 ? faults.substring(start)
                                  : faults.substring(start, comma);
    out += "\"" + item + "\"";
    if (comma < 0) break;
    out += ",";
    start = comma + 1;
  }
  return out + "]";
}

static void handleStatus() {
  // load_present and charging are separate questions. Contacts can be engaged
  // with no current flowing — oxidation, a full pack, a latched protection
  // board — and the robot recovers from that differently than from no contact.
  const bool charging = outputEnabled && currentA > CHARGING_CURRENT_A;

  String body = "{";
  body += "\"dock_id\":\"" + dockId + "\",";
  body += "\"firmware\":\"1.0.0\",";
  body += "\"output_enabled\":" + String(outputEnabled ? "true" : "false") + ",";
  body += "\"load_present\":" + String(loadDetected ? "true" : "false") + ",";
  body += "\"charging\":" + String(charging ? "true" : "false") + ",";
  body += "\"current_a\":" + String(currentA, 3) + ",";
  body += "\"output_voltage_v\":" + String(outputVoltageV, 3) + ",";
  body += "\"faults\":" + faultsJson();
  body += "}";

  server.send(200, "application/json", body);
}

// --- lifecycle --------------------------------------------------------------

void setup() {
  pinMode(PIN_OUTPUT_ENABLE, OUTPUT);
  setOutput(false);         // rule 2: de-energised on boot, before anything else

  Serial.begin(115200);

  // Credentials are provisioned at setup and live in NVS. Nothing is compiled
  // in — test_dock_contract.py fails the build if it finds a credential here.
  prefs.begin("rosy-dock", true);
  const String ssid = prefs.getString("ssid", "");
  const String secret = prefs.getString("secret", "");
  dockId = prefs.getString("dock_id", "dock_1");
  prefs.end();

  if (ssid.length() > 0) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid.c_str(), secret.c_str());
  }

  server.on("/status", HTTP_GET, handleStatus);
  server.begin();
}

void loop() {
  server.handleClient();

  const uint32_t now = millis();
  if (now - lastSample >= SAMPLE_INTERVAL_MS) {
    lastSample = now;
    sampleSensors();
    reconcileOutput();
  }
}
