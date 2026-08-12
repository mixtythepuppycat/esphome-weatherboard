#pragma once

#include <string>
#include <vector>
#include <cmath>
#include <cstdio>
#include <ctime>
#include <sstream>

// Forward declarations of ESPHome / ArduinoJson types used internally.
// These are already in scope in the generated firmware translation unit
// (esphome.h is included before this header by ESPHome's includes: mechanism).
// We use `auto` for return types to avoid naming them in the public API.

// ---------------------------------------------------------------------------
// Configuration passed from the YAML substitutions.
// ---------------------------------------------------------------------------
struct OwmConfig {
  float rain_threshold;   // mm/h — batch average <= this is treated as dry
  float graph_scale;      // multiplier applied to each graph bar height
  float uv_threshold;     // UV index above which "UV N" is shown on a dry day
};

// ---------------------------------------------------------------------------
// All data parsed from a single OWM One Call API response.
// ---------------------------------------------------------------------------
struct OwmData {
  long tz = 0;
  float current_temp   = NAN;
  float current_uvi    = NAN;
  int   weather_id     = 0;
  std::string icon_code;
  float today_high     = NAN;
  float today_low      = NAN;
  float today_pop      = 0.0f;   // probability of precipitation (0–1)
  std::vector<int> rain_bars;
  std::string rain_csv;         // serialised rain_bars for the template sensor
  std::string next_hour_desc;
  std::string today_desc;
};

// ---------------------------------------------------------------------------
// Parse an OWM One Call 4.0 JSON response. The 3.0 single-endpoint API was
// split into 4 separate endpoints, so parsing is split into 4 functions that
// each consume one endpoint's `data[]` array. All share the same top-level
// `timezone_offset` field.
// Returns true on success; logs and returns false on parse error.
// ---------------------------------------------------------------------------
inline bool parse_owm_current(const std::string& body, OwmData& data) {
  auto doc = esphome::json::parse_json(body);
  if (doc.isNull() || doc.overflowed()) {
    ESP_LOGE("owm", "Current weather JSON parse failed (len=%u)", (unsigned) body.length());
    return false;
  }
  JsonArray data_arr = doc["data"].as<JsonArray>();
  if (data_arr.size() == 0) {
    ESP_LOGW("owm", "Current weather: empty data array in response");
    return false;
  }
  data.tz = (long) doc["timezone_offset"];
  data.current_temp = (float) data_arr[0]["temp"];
  data.current_uvi  = (float)(data_arr[0]["uvi"] | 0.0);
  data.weather_id   = (int)  data_arr[0]["weather"][0]["id"];
  data.icon_code    =         data_arr[0]["weather"][0]["icon"].as<std::string>();
  return true;
}

// --- 1-min timeline: 5-minute batches, threshold on the batch average ---
inline bool parse_owm_minute(const std::string& body, OwmData& data, const OwmConfig& cfg) {
  auto doc = esphome::json::parse_json(body);
  if (doc.isNull() || doc.overflowed()) {
    ESP_LOGE("owm", "1-min timeline JSON parse failed (len=%u)", (unsigned) body.length());
    return false;
  }
  data.tz = (long) doc["timezone_offset"];

  auto minutely = doc["data"].as<JsonArray>();
  size_t n = minutely.size();
  for (size_t b = 0; b < n; b += 5) {
    float sum = 0.0f;
    size_t cnt = 0;
    for (size_t j = b; j < n && j < b + 5; ++j) {
      sum += (float)(minutely[j]["precipitation"] | 0.0);
      ++cnt;
    }
    float avg = (cnt > 0) ? (sum / (float) cnt) : 0.0f;
    bool  wet = avg > cfg.rain_threshold;
    for (size_t j = b; j < n && j < b + 5; ++j) {
      float p = (float)(minutely[j]["precipitation"] | 0.0);
      int   bar = wet ? (int) ceil((double) p * (double) cfg.graph_scale) : 0;
      if (bar < 0) bar = 0;
      data.rain_bars.push_back(bar);
      if (data.rain_bars.size() >= 60) break;
    }
    if (data.rain_bars.size() >= 60) break;
  }

  // serialise bars to CSV for the template sensor
  std::string csv;
  for (size_t i = 0; i < data.rain_bars.size(); ++i) {
    if (i) csv += ",";
    csv += std::to_string(data.rain_bars[i]);
  }
  data.rain_csv = csv;

  // --- next-hour description (N = minutes, accurate) ---
  int nz = 0, first_zero = -1, first_rain = -1;
  for (size_t i = 0; i < data.rain_bars.size(); ++i) {
    if (data.rain_bars[i] > 0) {
      ++nz;
      if (first_rain < 0) first_rain = (int) i;
    } else if (first_zero < 0) {
      first_zero = (int) i;
    }
  }
  if (nz == 0) {
    data.next_hour_desc = "No rain";
  } else if (nz == (int) data.rain_bars.size()) {
    data.next_hour_desc = "Rain this hour";
  } else if (first_rain == 0) {
    data.next_hour_desc = "Ending in " + std::to_string(first_zero);
  } else {
    data.next_hour_desc = "Rain in " + std::to_string(first_rain);
  }

  return true;
}

// --- 1-hour timeline: today-summary timing, rain/storm detection, UV fallback ---
// now_ts    — current unix timestamp (from sntp_time) so today-summary timing
//             is grounded even when the SNTP guard has already passed.
// current_uvi — most recent current UV (from owm_current_uv); may be NAN on
//               the very first forecast cycle, in which case the UV fallback
//               is gracefully skipped (NAN > threshold is false).
inline bool parse_owm_hourly(const std::string& body, OwmData& data,
                             const OwmConfig& cfg, long now_ts, float current_uvi) {
  auto doc = esphome::json::parse_json(body);
  if (doc.isNull() || doc.overflowed()) {
    ESP_LOGE("owm", "1-hour timeline JSON parse failed (len=%u)", (unsigned) body.length());
    return false;
  }
  data.tz = (long) doc["timezone_offset"];

  // --- today summary (hourly timing preserved) ---
  // rain_states & storm mirror HA's OpenWeatherMap condition map.
  long now_local  = now_ts + data.tz;
  long today_start = (now_local / 86400) * 86400;
  long today_end   = today_start + 86400 - 1;
  data.today_desc = "No rain today";
  auto hourly = doc["data"].as<JsonArray>();
  for (auto h : hourly) {
    long dt = (long) h["dt"];
    long local_dt = dt + data.tz;
    if (local_dt > today_end) break;
    float rv = (float)(h["rain"]["1h"] | 0.0);
    int   hid = (int) h["weather"][0]["id"];
    bool rain_state =
      ((hid >= 200 && hid <= 202) || (hid >= 230 && hid <= 232) ||   // lightning-rainy
       (hid >= 502 && hid <= 504) || hid == 314 || hid == 522 ||       // pouring
       (hid >= 300 && hid <= 313) || hid == 500 || hid == 501 ||       // rainy
       hid == 520 || hid == 521 ||
       hid == 511 || hid == 615 || hid == 616 ||                       // snowy-rainy
       hid == 906);                                                    // hail
    if (rv > cfg.rain_threshold && rain_state) {
      bool storm =
        ((hid >= 200 && hid <= 202) || (hid >= 230 && hid <= 232) ||
         hid == 906 || (hid >= 502 && hid <= 504) || hid == 522 || hid == 314);
      std::string cat  = storm ? "Storm" : "Rain";
      std::string when;
      if (local_dt <= now_local) {
        when = "this hour";
      } else {
        long hl = (local_dt % 86400) / 3600;
        char buf[16];
        snprintf(buf, sizeof(buf), "at %02ld:00", hl);
        when = std::string(buf);
      }
      data.today_desc = cat + " today " + when;
      break;
    }
  }
  if (current_uvi > cfg.uv_threshold && data.today_desc == "No rain today") {
    char ub[16];
    snprintf(ub, sizeof(ub), "UV %.0f", (double) current_uvi);
    data.today_desc = std::string(ub);
  }

  return true;
}

// --- 1-day timeline: today high/low + POP ---
inline bool parse_owm_daily(const std::string& body, OwmData& data) {
  auto doc = esphome::json::parse_json(body);
  if (doc.isNull() || doc.overflowed()) {
    ESP_LOGE("owm", "1-day timeline JSON parse failed (len=%u)", (unsigned) body.length());
    return false;
  }
  JsonArray data_arr = doc["data"].as<JsonArray>();
  if (data_arr.size() == 0) {
    ESP_LOGW("owm", "1-day timeline: empty data array in response");
    return false;
  }
  data.tz = (long) doc["timezone_offset"];
  data.today_high  = (float) data_arr[0]["temp"]["max"];
  data.today_low   = (float) data_arr[0]["temp"]["min"];
  data.today_pop   = (float)(data_arr[0]["pop"] | 0.0);
  return true;
}

// ---------------------------------------------------------------------------
// Parse an AirNow ziplatlong JSON response body.
// Returns max nowcastAQI across pollutants (>0 on success, 0 if no data).
// ---------------------------------------------------------------------------
inline int parse_aqi(const std::string& body) {
  auto doc = esphome::json::parse_json(body);
  if (doc.isNull() || doc.overflowed()) {
    ESP_LOGE("aqi", "AirNow JSON parse failed (len=%u)", (unsigned) body.length());
    return 0;
  }
  auto arr = doc.as<JsonArray>();
  int best_aqi = 0;
  bool found = false;
  for (auto obs : arr) {
    int a = (int) obs["nowcastAQI"];
    if (!found || a > best_aqi) {
      best_aqi = a;
      found = true;
    }
  }
  if (!found) {
    ESP_LOGW("aqi", "AirNow returned no usable observations");
  }
  return found ? best_aqi : 0;
}

// ---------------------------------------------------------------------------
// Map an OWM weather condition ID + icon code to an MDI glyph codepoint.
// Returns a pointer to a string literal (static storage duration).
// ---------------------------------------------------------------------------
inline const char* glyph_for_weather_id(int wid, const std::string& icon_code) {
  bool is_night = !icon_code.empty() && icon_code[icon_code.size() - 1] == 'n';
  if (wid == 800) {
    return is_night ? "\U000F0594" : "\U000F0599";                // clear-night / sunny
  } else if (wid == 801 || wid == 802) {
    return is_night ? "\U000F0F31" : "\U000F0595";                // night-partly-cloudy / partly-cloudy
  } else if (wid == 803 || wid == 804) {
    return "\U000F0590";                                           // cloudy
  } else if (wid == 701 || wid == 721 || wid == 741) {
    return "\U000F0591";                                           // fog
  } else if (wid == 906) {
    return "\U000F0592";                                           // hail
  } else if ((wid >= 200 && wid <= 202) || (wid >= 230 && wid <= 232)) {
    return "\U000F067E";                                           // lightning-rainy
  } else if (wid == 210 || wid == 211 || wid == 212 || wid == 221) {
    return "\U000F0593";                                           // lightning
  } else if (wid == 502 || wid == 503 || wid == 504 || wid == 314 || wid == 522) {
    return "\U000F0596";                                           // pouring
  } else if (wid == 300 || wid == 301 || wid == 302 || wid == 310 || wid == 311 || wid == 312 || wid == 313 || wid == 500 || wid == 501 || wid == 520 || wid == 521) {
    return "\U000F0597";                                           // rainy
  } else if (wid >= 600 && wid <= 622) {
    return "\U000F0598";                                           // snowy
  } else if (wid == 511 || wid == 615 || wid == 616) {
    return "\U000F0F35";                                           // snowy-rainy
  } else if (wid == 905 || (wid >= 951 && wid <= 957)) {
    return "\U000F059D";                                           // windy
  } else if (wid >= 958 && wid <= 961) {
    return "\U000F059E";                                           // windy-variant
  } else {
    return "\U000F0F2F";                                           // exceptional
  }
}

// ---------------------------------------------------------------------------
// Parse a comma-separated list of rain bar heights for the graph renderer.
// ---------------------------------------------------------------------------
inline std::vector<int> parse_rain_csv(const std::string& csv) {
  std::vector<int> bars;
  if (csv.empty()) return bars;
  std::istringstream ss(csv);
  std::string item;
  while (std::getline(ss, item, ',')) {
    if (!item.empty()) {
      bars.push_back(std::stoi(item));
    }
  }
  return bars;
}
