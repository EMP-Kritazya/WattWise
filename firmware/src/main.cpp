// WattWise ESP32 hub (docs/design/CONVEX_AND_ESP32.md, CONTRACTS.md §1 Command / CommandAck / Reading, §6 Convex).
//
// Two bench loads (small DC fans or LED strips) on two MOSFET channels stand in for two kitchen devices. The board talks
// to Convex only, over the convex-esp32 client (one TLS WebSocket):
//   commands:forDevice({hub_id})  subscribed  → execute each Command on its channel → commands:ack(...)
//   devices:map()                 subscribed  → which device_id and scale each channel is (rows with this HUB_ID)
//   devices:report({reading})     every 2 s per mapped channel, from its INA219
//   hubs:heartbeat({hub_id})      every 5 s
// Fail safe: no successful Convex contact for 30 s → every channel back to normal (on, 100 %).
//
// The board computes no kitchen number: a Reading carries the INA219's watts and the contract's own conversion
// (power_kw = raw_w × scale / 1000, scale from device_map). The engine does everything else.

#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <time.h>

#include <Adafruit_INA219.h>
#include <ArduinoJson.h>
#include <Convex.h>

#include "secrets.h"  // WIFI_SSID, WIFI_PASS, CONVEX_URL (copy include/secrets.example.h)

#ifndef HUB_ID
#define HUB_ID "esp32_1"
#endif
#ifndef SIM_SPEED
#define SIM_SPEED 120
#endif
#ifndef MIN_DUTY_PCT
#define MIN_DUTY_PCT 20
#endif

// ESP32-S3 DevKitC-1 pins (override with -D). Each INA219 sits alone on its own I2C bus, so both keep the default
// address 0x40 and no address pad has to be soldered.
#ifndef CH0_PWM_PIN
#define CH0_PWM_PIN 4
#endif
#ifndef CH1_PWM_PIN
#define CH1_PWM_PIN 5
#endif
#ifndef I2C0_SDA
#define I2C0_SDA 8
#endif
#ifndef I2C0_SCL
#define I2C0_SCL 9
#endif
#ifndef I2C1_SDA
#define I2C1_SDA 17
#endif
#ifndef I2C1_SCL
#define I2C1_SCL 18
#endif

static const uint32_t PWM_FREQ_HZ = 25000;  // above hearing; fine for fans and LED strips behind a logic-level MOSFET
static const uint8_t PWM_BITS = 10;
static const uint32_t READING_EVERY_MS = 2000;
static const uint32_t HEARTBEAT_EVERY_MS = 5000;
static const uint32_t FAILSAFE_AFTER_MS = 30000;
static const uint32_t ACK_RESEND_MS = 5000;  // an acked command still listed after this → ack again (never re-execute)
static const int N_CHANNELS = 2;
static const int N_HANDLED = 32;

// ------------------------------------------------------------------------------------------------ channels

struct Channel {
  uint8_t pin;
  TwoWire *bus;
  uint8_t sda, scl;
  Adafruit_INA219 ina{0x40};
  bool sensor_ok = false;
  // device_map row for (HUB_ID, channel)
  bool mapped = false;
  String device_id;
  double scale = 1;
  // Physical state. Normal = on at 100 %.
  bool on = true;
  int pct = 100;
  bool held = false;          // `delay`: off until hold_until_ms, then back to normal
  uint32_t hold_until_ms = 0;
};

static Channel channels[N_CHANNELS] = {
    {CH0_PWM_PIN, &Wire, I2C0_SDA, I2C0_SCL},
    {CH1_PWM_PIN, &Wire1, I2C1_SDA, I2C1_SCL},
};

static void drive(Channel &ch) {
  const uint32_t max_duty = (1u << PWM_BITS) - 1;
  uint32_t duty = (ch.on && !ch.held) ? (max_duty * (uint32_t)ch.pct + 50) / 100 : 0;
  ledcWrite(ch.pin, duty);
}

static void to_normal(Channel &ch) {
  ch.on = true;
  ch.pct = 100;
  ch.held = false;
  drive(ch);
}

static Channel *channel_for(const char *device_id) {
  for (auto &ch : channels)
    if (ch.mapped && ch.device_id == device_id) return &ch;
  return nullptr;
}

// ------------------------------------------------------------------------------------------------ Convex contact

static volatile uint32_t last_contact_ms = 0;  // written from the socket task (mutation callbacks) and loop()
static bool failsafe = false;
static bool map_ready = false;
static int q_commands = -1, q_map = -1;

static void contact() { last_contact_ms = millis(); }

static void on_result(bool ok, JsonVariantConst) {
  if (ok) contact();  // runs on the socket task: keep it this short
}

static void mutate(const char *udf, const JsonDocument &args) {
  int id = convexMutation(udf, args, ConvexResultFn(on_result));
  if (id < 0) Serial.printf("%s not sent: %s\n", udf, convexStatusStr((ConvexStatus)id));
}

// ------------------------------------------------------------------------------------------------ commands

struct Ack {
  bool ok;
  bool has_value;
  double applied_value;
  const char *reason;  // null | out_of_range | job_running | already_off | unknown_device
};

// Commands this board executed and acked, kept while commands:forDevice still lists them (the ack has not reached
// Convex yet) so a command is executed once. Ids restart with every kitchen build, so an id is forgotten as soon as
// it leaves the list; a new command reusing it later is new.
struct Handled {
  bool used = false;
  bool listed = false;
  char command_id[32];
  Ack ack;
  uint32_t sent_ms;
};
static Handled handled[N_HANDLED];

static void send_ack(Handled &h) {
  JsonDocument a;
  a["command_id"] = h.command_id;
  a["ok"] = h.ack.ok;
  if (h.ack.has_value) a["applied_value"] = h.ack.applied_value;
  else a["applied_value"] = nullptr;
  if (h.ack.reason) a["reason"] = h.ack.reason;
  else a["reason"] = nullptr;
  mutate("commands:ack", a);
  h.sent_ms = millis();
}

// value passes through as applied_value unless a physical limit clamps it (CONTRACTS.md §1 CommandAck).
static Ack applied(JsonVariantConst value) {
  if (value.isNull()) return {true, false, 0, nullptr};
  return {true, true, value.as<double>(), nullptr};
}

static Ack execute(JsonObjectConst cmd) {
  const char *device_id = cmd["device_id"] | "";
  const char *action = cmd["action"] | "";
  JsonVariantConst value = cmd["value"];
  Channel *chp = channel_for(device_id);
  if (chp == nullptr || strcmp(cmd["lane"] | "", "with") != 0) return {false, false, 0, "unknown_device"};
  Channel &ch = *chp;
  bool running = ch.on && !ch.held;

  if (strcmp(action, "off") == 0) {
    if (!running) return {false, false, 0, "already_off"};
    ch.on = false;
    ch.held = false;
    drive(ch);
    return applied(value);
  }
  if (strcmp(action, "on") == 0) {
    ch.on = true;
    ch.held = false;
    drive(ch);
    return applied(value);
  }
  if (strcmp(action, "restore") == 0) {
    to_normal(ch);
    return applied(value);
  }
  if (strcmp(action, "start") == 0) {
    if (running) return {false, false, 0, "job_running"};
    ch.on = true;
    ch.held = false;
    drive(ch);
    return applied(value);
  }
  if (strcmp(action, "reduce") == 0) {
    double asked = value.isNull() ? 100 : value.as<double>();
    int pct = (int)lround(asked);
    if (pct < MIN_DUTY_PCT) pct = MIN_DUTY_PCT;
    if (pct > 100) pct = 100;
    ch.on = true;  // flexible: reduced, never stopped
    ch.held = false;
    ch.pct = pct;
    drive(ch);
    return {true, true, (double)pct, (double)pct == asked ? nullptr : "out_of_range"};
  }
  if (strcmp(action, "delay") == 0) {
    // The bench load mirrors power, not job phases: a delay holds it off for `value` sim minutes, in real time at
    // SIM_SPEED, then it returns to normal. It replaces any hold already running.
    double minutes = value.isNull() ? 0 : value.as<double>();
    const char *reason = nullptr;
    if (minutes < 0) {
      minutes = 0;
      reason = "out_of_range";
    }
    ch.held = true;
    ch.hold_until_ms = millis() + (uint32_t)(minutes * 60000.0 / SIM_SPEED);
    drive(ch);
    return {true, true, minutes, reason};
  }
  return {false, false, 0, "unknown_device"};  // an action this hub cannot perform (no other reason exists in §1)
}

static Handled *find_handled(const char *id) {
  for (auto &h : handled)
    if (h.used && strcmp(h.command_id, id) == 0) return &h;
  return nullptr;
}

static Handled *alloc_handled() {
  for (auto &h : handled)
    if (!h.used) return &h;
  return nullptr;
}

static void on_commands(JsonArrayConst list) {
  for (auto &h : handled) h.listed = false;
  for (JsonObjectConst cmd : list) {  // oldest first
    const char *id = cmd["command_id"] | "";
    if (*id == '\0') continue;
    Handled *h = find_handled(id);
    if (h != nullptr) {
      h->listed = true;
      continue;
    }
    if (!map_ready) continue;  // which channel is which is not known yet; the next update brings it back
    h = alloc_handled();
    if (h == nullptr) {
      Serial.printf("command %s waits: %d commands still unacked\n", id, N_HANDLED);
      continue;
    }
    h->used = true;
    h->listed = true;
    strlcpy(h->command_id, id, sizeof h->command_id);
    h->ack = execute(cmd);
    Serial.printf("command %s %s %s → ok=%d reason=%s\n", id, (const char *)(cmd["action"] | "?"),
                  (const char *)(cmd["device_id"] | "?"), h->ack.ok, h->ack.reason ? h->ack.reason : "null");
    send_ack(*h);
  }
  for (auto &h : handled)
    if (h.used && !h.listed) h.used = false;
}

static void resend_stale_acks() {
  uint32_t now = millis();
  for (auto &h : handled)
    if (h.used && h.listed && now - h.sent_ms > ACK_RESEND_MS) send_ack(h);
}

// ------------------------------------------------------------------------------------------------ device map

static void on_map(JsonArrayConst rows) {
  bool seen[N_CHANNELS] = {false, false};
  for (JsonObjectConst row : rows) {
    if (strcmp(row["hub_id"] | "", HUB_ID) != 0) continue;
    int c = row["channel"] | -1;
    if (c < 0 || c >= N_CHANNELS) continue;
    Channel &ch = channels[c];
    String device_id = row["device_id"] | "";
    if (!ch.mapped || ch.device_id != device_id) Serial.printf("channel %d = %s\n", c, device_id.c_str());
    ch.mapped = true;
    ch.device_id = device_id;
    ch.scale = row["scale"] | 1.0;
    seen[c] = true;
  }
  for (int c = 0; c < N_CHANNELS; c++) {
    if (!seen[c] && channels[c].mapped) {
      Serial.printf("channel %d unmapped\n", c);
      channels[c].mapped = false;
      to_normal(channels[c]);
    }
  }
  map_ready = true;
}

// ------------------------------------------------------------------------------------------------ readings

static bool utc_now(char *out, size_t cap) {
  time_t t = time(nullptr);
  if (t < 1700000000) return false;  // SNTP not synced yet: no honest timestamp, so no Reading
  struct tm tm;
  gmtime_r(&t, &tm);
  strftime(out, cap, "%Y-%m-%dT%H:%M:%SZ", &tm);
  return true;
}

static void report_readings() {
  char ts[24];
  if (!utc_now(ts, sizeof ts)) return;
  for (int c = 0; c < N_CHANNELS; c++) {
    Channel &ch = channels[c];
    if (!ch.mapped || !ch.sensor_ok) continue;
    double raw_w = ch.ina.getPower_mW() / 1000.0;
    if (raw_w < 0) raw_w = 0;  // shunt noise around an idle load
    raw_w = round(raw_w * 1000.0) / 1000.0;  // the INA219 resolves ~mW
    JsonDocument a;
    JsonObject r = a["reading"].to<JsonObject>();
    r["hub_id"] = HUB_ID;
    r["channel"] = c;
    r["device_id"] = ch.device_id;
    r["ts"] = ts;
    r["raw_w"] = raw_w;
    r["scale"] = ch.scale;
    r["power_kw"] = raw_w * ch.scale / 1000.0;  // CONTRACTS.md §1 Reading
    mutate("devices:report", a);
  }
}

// ------------------------------------------------------------------------------------------------ setup / loop

static void subscribe() {
  JsonDocument args;
  args["hub_id"] = HUB_ID;
  q_commands = convexSubscribe("commands:forDevice", args);
  q_map = convexSubscribe("devices:map");
  Serial.printf("subscribed commands:forDevice=%d devices:map=%d\n", q_commands, q_map);
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\nWattWise hub %s\n", HUB_ID);

  for (int c = 0; c < N_CHANNELS; c++) {  // loads start normal, before any network
    Channel &ch = channels[c];
    ledcAttach(ch.pin, PWM_FREQ_HZ, PWM_BITS);
    to_normal(ch);
    ch.bus->begin(ch.sda, ch.scl);
    ch.sensor_ok = ch.ina.begin(ch.bus);
    if (ch.sensor_ok) ch.ina.setCalibration_32V_1A();  // 5–12 V bench loads, < 1 A
    Serial.printf("channel %d: pwm gpio %d, INA219 %s\n", c, ch.pin, ch.sensor_ok ? "found" : "MISSING (no readings)");
  }

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("wifi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.printf(" %s\n", WiFi.localIP().toString().c_str());

  configTime(0, 0, "pool.ntp.org", "time.google.com");  // UTC inside
  char ts[24];
  for (int i = 0; i < 50 && !utc_now(ts, sizeof ts); i++) delay(200);
  Serial.printf("time %s\n", utc_now(ts, sizeof ts) ? ts : "not synced yet (readings wait for it)");

  if (!convexBegin(CONVEX_URL)) {
    Serial.printf("convexBegin failed: %s (retrying in loop)\n", convexLastError());
  } else {
    subscribe();
  }
  last_contact_ms = millis();  // the 30 s fail-safe window starts now
}

void loop() {
  static uint32_t last_reading = 0, last_heartbeat = 0, last_resend = 0, last_begin_try = 0;
  static bool was_connected = false;
  uint32_t now = millis();

  if (q_commands < 0 && now - last_begin_try > 5000) {  // convexBegin failed in setup (e.g. low heap, no network)
    last_begin_try = now;
    if (convexBegin(CONVEX_URL)) subscribe();
  }

  bool connected = convexConnected();
  if (connected != was_connected) {
    Serial.printf("convex %s\n", connected ? "connected" : "disconnected");
    was_connected = connected;
  }

  if (q_map >= 0 && convexQueryChanged(q_map)) {
    JsonDocument doc;
    if (convexQueryValue(q_map, doc)) {
      contact();
      on_map(doc.as<JsonArrayConst>());
    }
  }
  if (q_commands >= 0 && convexQueryChanged(q_commands)) {
    JsonDocument doc;
    if (convexQueryValue(q_commands, doc)) {
      contact();
      on_commands(doc.as<JsonArrayConst>());
    }
  }

  for (auto &ch : channels) {  // a delay hold ran out → normal
    if (ch.held && (int32_t)(now - ch.hold_until_ms) >= 0) {
      Serial.printf("%s hold over\n", ch.device_id.c_str());
      to_normal(ch);
    }
  }

  if (connected && now - last_heartbeat >= HEARTBEAT_EVERY_MS) {
    last_heartbeat = now;
    JsonDocument a;
    a["hub_id"] = HUB_ID;
    mutate("hubs:heartbeat", a);
  }
  if (connected && now - last_reading >= READING_EVERY_MS) {
    last_reading = now;
    report_readings();
  }
  if (connected && now - last_resend >= 1000) {
    last_resend = now;
    resend_stale_acks();
  }

  // Fail safe: 30 s without a successful Convex round trip → every load back to normal operation.
  bool lost = now - last_contact_ms > FAILSAFE_AFTER_MS;
  if (lost && !failsafe) {
    failsafe = true;
    Serial.println("FAIL SAFE: no Convex contact for 30 s, every channel back to normal");
    for (auto &ch : channels) to_normal(ch);
  } else if (!lost && failsafe) {
    failsafe = false;
    Serial.println("Convex contact back; commands are executed again");
  }

  delay(10);
}
