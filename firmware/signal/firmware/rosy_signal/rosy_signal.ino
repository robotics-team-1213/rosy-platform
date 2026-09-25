// Rosy traffic signal controller — ESP32 reference firmware.
//
// The rule above every other rule: a signal nobody can trust must say so.
// On boot, on loss of the supervisor, or on reboot, every lamp shows FLASH
// RED — the universal "this signal is out of service" pattern — until a
// fresh authenticated command arrives. The device never resurrects an old
// command on its own: no lamp state is stored in NVS, on purpose.
//
// Contract: ../../README.md (ROSY-SIGNAL-001).
// The supervisor (Fleet console) polls and commands; this device never
// initiates a connection.

#include <Arduino.h>
#include <ArduinoJson.h>  // ArduinoJson 6.x
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>

// --- pins -------------------------------------------------------------------

// Relay channels are driven active-HIGH: a channel closes its contact while
// its pin is HIGH. Module inputs must be biased (see README "Electrical") so
// a floating ESP32 pin during boot cannot close a contact.
static const int PIN_LAMP_RED    = 25;
static const int PIN_LAMP_YELLOW = 26;
static const int PIN_LAMP_GREEN  = 27;
static const int PIN_SPARE_A     = 16;  // reserved: arrow / pedestrian module
static const int PIN_SPARE_B     = 17;  // reserved

// --- timing -----------------------------------------------------------------

static const uint32_t HEARTBEAT_TIMEOUT_MS = 10000;  // 5 missed 2 s polls
static const uint32_t FLASH_INTERVAL_MS    = 500;
static const uint32_t TICK_MS              = 20;

// Cycle defaults; a command may override per device.
static const uint32_t DEFAULT_GREEN_MS   = 5000;
static const uint32_t DEFAULT_YELLOW_MS  = 2000;
static const uint32_t DEFAULT_RED_MS     = 5000;
static const uint32_t MAX_CYCLE_TOTAL_MS = 3600000;  // 1 h sanity cap

// --- state ------------------------------------------------------------------

enum Mode { FAILSAFE, MANUAL, CYCLE, HOLD, ALL_RED, FLASH_RED };

// Explicit prototypes: the .ino auto-prototyper hoists declarations above the
// enum and fails to compile. Keep this list in sync with the definitions.
static const char *modeName(Mode m);
static void writeLamps(bool r, bool y, bool g);
static void addFault(const char *name);
static void enterFailsafe(const char *reason);
static void stepCycle(uint32_t now);
static void applyOutputs(uint32_t now);
static bool requestAuthenticated();
static String faultsJson();
static void sendStatus(uint32_t now);
static void jsonError(int code, const char *name);
static void handleStatus();
static void handleCommand();
static void provisionViaSerial();

WebServer server(80);
Preferences prefs;

static Mode mode = FAILSAFE;  // boot state: fail-safe, before anything else
static bool lampRed = false, lampYellow = false, lampGreen = false;   // commanded
static bool appliedRed = false, appliedYellow = false, appliedGreen = false;

static uint32_t lastSeq = 0;
static uint32_t lastContactMs = 0;  // last token-valid request
static String faults = "";
static String signalId = "signal_1";
static String authToken = "";

static uint32_t cycleGreenMs = DEFAULT_GREEN_MS;
static uint32_t cycleYellowMs = DEFAULT_YELLOW_MS;
static uint32_t cycleRedMs = DEFAULT_RED_MS;
static int cyclePhase = 0;  // 0 green, 1 yellow, 2 red
static uint32_t phaseStartMs = 0;

static const char *modeName(Mode m) {
  switch (m) {
    case FAILSAFE: return "failsafe";
    case MANUAL: return "manual";
    case CYCLE: return "cycle";
    case HOLD: return "hold";
    case ALL_RED: return "all_red";
    case FLASH_RED: return "flash_red";
  }
  return "failsafe";
}

// --- lamp output ------------------------------------------------------------

// The single place lamp pins are switched. Everything else calls this.
static void writeLamps(bool r, bool y, bool g) {
  if (r == appliedRed && y == appliedYellow && g == appliedGreen) return;
  appliedRed = r;
  appliedYellow = y;
  appliedGreen = g;
  digitalWrite(PIN_LAMP_RED, r ? HIGH : LOW);
  digitalWrite(PIN_LAMP_YELLOW, y ? HIGH : LOW);
  digitalWrite(PIN_LAMP_GREEN, g ? HIGH : LOW);
}

static void addFault(const char *name) {
  if (faults.length() > 0) {
    faults += ",";
  }
  faults += name;
}

static void enterFailsafe(const char *reason) {
  // Flash red is deliberately distinct from ALL_RED: steady all-red is a
  // commanded, healthy stop phase; flashing means "controller fault — treat
  // as all-way stop".
  mode = FAILSAFE;
  addFault(reason);
}

// --- cycle ------------------------------------------------------------------

static void stepCycle(uint32_t now) {
  const uint32_t durations[3] = {cycleGreenMs, cycleYellowMs, cycleRedMs};
  uint32_t elapsed = now - phaseStartMs;
  while (elapsed >= durations[cyclePhase]) {
    elapsed -= durations[cyclePhase];
    cyclePhase = (cyclePhase + 1) % 3;
    phaseStartMs = now - elapsed;
  }
}

// --- mode application -------------------------------------------------------

static void applyOutputs(uint32_t now) {
  bool r = false, y = false, g = false;

  switch (mode) {
    case FAILSAFE:
    case FLASH_RED:
      // Flashing all-red: red and green together is the one display that
      // lies, so the fail-safe pattern lights red alone, blinking.
      r = ((now / FLASH_INTERVAL_MS) % 2) == 0;
      break;
    case ALL_RED:
      r = true;
      break;
    case MANUAL:
    case HOLD:
      r = lampRed;
      y = lampYellow;
      g = lampGreen;
      break;
    case CYCLE:
      stepCycle(now);
      g = (cyclePhase == 0);
      y = (cyclePhase == 1);
      r = (cyclePhase == 2);
      break;
  }
  writeLamps(r, y, g);
}

// --- auth -------------------------------------------------------------------

static const char *HEADER_KEYS[] = {"X-Rosy-Token"};

static bool requestAuthenticated() {
  // Fail closed: an unprovisioned device (no token) serves read-only status
  // and accepts no command — it can never leave the fail-safe state.
  if (authToken.length() == 0) {
    return false;
  }
  return server.header("X-Rosy-Token").equals(authToken);
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
    const String item =
        comma < 0 ? faults.substring(start) : faults.substring(start, comma);
    out += "\"" + item + "\"";
    if (comma < 0) break;
    out += ",";
    start = comma + 1;
  }
  return out + "]";
}

static void sendStatus(uint32_t now) {
  String body = "{";
  body += "\"signal_id\":\"" + signalId + "\",";
  body += "\"firmware\":\"1.0.0\",";
  body += "\"mode\":\"" + String(modeName(mode)) + "\",";
  body += "\"seq\":" + String(lastSeq) + ",";
  body += "\"lamps\":{\"red\":" + String(appliedRed ? "true" : "false") + ",";
  body += "\"yellow\":" + String(appliedYellow ? "true" : "false") + ",";
  body += "\"green\":" + String(appliedGreen ? "true" : "false") + "},";
  body += "\"secs_since_contact\":" + String((now - lastContactMs) / 1000) + ",";
  body += "\"faults\":" + faultsJson();
  body += "}";
  server.send(200, "application/json", body);
}

static void jsonError(int code, const char *name) {
  server.send(code, "application/json", String("{\"error\":\"") + name + "\"}");
}

static void handleStatus() {
  // Any authenticated request, poll or command, counts as the heartbeat. An
  // unauthenticated GET is for debugging; it must not keep a signal out of
  // fail-safe merely by existing.
  if (requestAuthenticated()) {
    lastContactMs = millis();
  }
  sendStatus(millis());
}

static void handleCommand() {
  const uint32_t now = millis();
  if (!requestAuthenticated()) {
    jsonError(403, "unauthorized");
    return;
  }

  DynamicJsonDocument doc(768);
  const DeserializationError err = deserializeJson(doc, server.arg("plain"));
  if (err || doc.isNull()) {
    jsonError(400, "bad_json");
    return;
  }

  const uint32_t seq = doc["seq"] | 0u;
  if (seq == 0 || seq <= lastSeq) {
    server.send(409, "application/json",
                String("{\"error\":\"stale_seq\",\"last_seq\":") + lastSeq +
                    "}");
    return;
  }

  const char *modeStr = doc["mode"] | "";
  Mode next = FAILSAFE;
  if (strcmp(modeStr, "manual") == 0) {
    next = MANUAL;
  } else if (strcmp(modeStr, "cycle") == 0) {
    next = CYCLE;
  } else if (strcmp(modeStr, "hold") == 0) {
    next = HOLD;
  } else if (strcmp(modeStr, "all_red") == 0) {
    next = ALL_RED;
  } else if (strcmp(modeStr, "flash_red") == 0) {
    next = FLASH_RED;
  } else {
    jsonError(400, "bad_mode");
    return;
  }

  if (next == MANUAL) {
    JsonObject lamps = doc["lamps"];
    if (lamps.isNull()) {
      jsonError(400, "bad_lamps");
      return;
    }
    const bool r = lamps["red"] | false;
    const bool y = lamps["yellow"] | false;
    const bool g = lamps["green"] | false;
    if (r && g) {  // conflict guard: the impossible display is refused
      jsonError(400, "conflict");
      return;
    }
    lampRed = r;
    lampYellow = y;
    lampGreen = g;
  } else if (next == CYCLE) {
    JsonObject cyc = doc["cycle"];
    cycleGreenMs = cyc["green_ms"] | DEFAULT_GREEN_MS;
    cycleYellowMs = cyc["yellow_ms"] | DEFAULT_YELLOW_MS;
    cycleRedMs = cyc["red_ms"] | DEFAULT_RED_MS;
    const uint32_t total = cycleGreenMs + cycleYellowMs + cycleRedMs;
    if (cycleGreenMs == 0 || cycleYellowMs == 0 || cycleRedMs == 0 ||
        total > MAX_CYCLE_TOTAL_MS) {
      jsonError(400, "bad_cycle");
      return;
    }
    cyclePhase = 0;
    phaseStartMs = now;
  } else if (next == HOLD) {
    // Freeze whatever is lit right now.
    lampRed = appliedRed;
    lampYellow = appliedYellow;
    lampGreen = appliedGreen;
  }

  lastSeq = seq;
  faults = "";  // a fresh command from a live supervisor heals
  mode = next;
  lastContactMs = now;
  sendStatus(now);
}

// --- provisioning -----------------------------------------------------------

// Secrets live only in NVS and are provisioned once over serial, when NVS is
// empty. Nothing is compiled in — test_signal_contract.py fails the build if
// a credential appears in any source under signal/.
static void provisionViaSerial() {
  Serial.println("[rosy-signal] NVS empty — provision now, end with 'done':");
  Serial.println("  wifi <ssid> <key>");
  Serial.println("  token <value>");
  Serial.println("  id <signal_id>");
  String ssid = "", key = "", token = "", id = "";
  const uint32_t deadline = millis() + 120000;
  while (millis() < deadline) {
    if (!Serial.available()) {
      delay(20);
      continue;
    }
    String line = Serial.readStringUntil('\n');
    line.trim();
    const int sep = line.indexOf(' ');
    if (sep <= 0) {
      if (line == "done") break;
      continue;
    }
    const String verb = line.substring(0, sep);
    const String rest = line.substring(sep + 1);
    if (verb == "wifi") {
      const int wifiSep = rest.indexOf(' ');
      if (wifiSep > 0) {
        ssid = rest.substring(0, wifiSep);
        key = rest.substring(wifiSep + 1);
      }
    } else if (verb == "token") {
      token = rest;
    } else if (verb == "id") {
      id = rest;
    }
  }
  prefs.begin("rosy-signal", false);
  if (ssid.length() > 0) prefs.putString("ssid", ssid);
  if (key.length() > 0) prefs.putString("key", key);
  if (token.length() > 0) prefs.putString("token", token);
  if (id.length() > 0) prefs.putString("id", id);
  prefs.end();
  Serial.println("[rosy-signal] saved — restarting");
  delay(300);
  ESP.restart();
}

// --- lifecycle --------------------------------------------------------------

void setup() {
  // Fail-safe first: pins low before anything else can run.
  pinMode(PIN_LAMP_RED, OUTPUT);
  pinMode(PIN_LAMP_YELLOW, OUTPUT);
  pinMode(PIN_LAMP_GREEN, OUTPUT);
  pinMode(PIN_SPARE_A, OUTPUT);
  pinMode(PIN_SPARE_B, OUTPUT);
  writeLamps(false, false, false);
  digitalWrite(PIN_SPARE_A, LOW);
  digitalWrite(PIN_SPARE_B, LOW);

  Serial.begin(115200);

  prefs.begin("rosy-signal", true);
  const String ssid = prefs.getString("ssid", "");
  const String key = prefs.getString("key", "");
  authToken = prefs.getString("token", "");
  signalId = prefs.getString("id", "signal_1");
  prefs.end();

  if (ssid.length() == 0) {
    provisionViaSerial();
  }

  if (ssid.length() > 0) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid.c_str(), key.c_str());
  }

  server.collectHeaders(HEADER_KEYS, 1);
  server.on("/status", HTTP_GET, handleStatus);
  server.on("/command", HTTP_POST, handleCommand);
  server.begin();
}

void loop() {
  server.handleClient();

  static uint32_t lastTick = 0;
  const uint32_t now = millis();
  if (now - lastTick < TICK_MS) {
    return;
  }
  lastTick = now;

  // Silence is a fault: if the token-valid supervisor stops speaking, the
  // signal must not keep displaying its last instruction.
  if (mode != FAILSAFE && now - lastContactMs > HEARTBEAT_TIMEOUT_MS) {
    enterFailsafe("supervisor_lost");
  }
  applyOutputs(now);
}
