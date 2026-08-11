#!/usr/bin/env python3
"""Emulated OpenWeatherMap One Call 3.0 + AirNow `ziplatlong` server.

Run with:  pip install flask   # then
           python3 emulated_server.py [--host 0.0.0.0] [--port 8080]

Serves:
  GET  /                                   control UI
  GET  /state                              current in-memory state
  GET  /scenarios.json                     preset definitions
  GET  /last                               info about the most recent firmware fetch
  POST /state                              set one or more knobs (JSON body)
  GET  /data/3.0/onecall?...               OWM One Call 3.0 body assembled from state
  GET  /aq/observation/current/ziplatlong?...  AirNow array assembled from state

The firmware (firmware/transit-weatherboard.yaml) fetches these at
`${owm_poll_interval}`. Point `owm_base_url` / `airnow_base_url` in your
firmware/secrets.yaml (test copy) at this server's LAN address.

All JSON is regenerated on each request from the current in-memory state, so a
knob change takes effect on the next firmware poll. Timestamps are anchored to
real wall-clock time so the firmware's today-summary timing math stays honest.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
SCENARIOS_PATH = os.path.join(HERE, "scenarios.json")

# OWM weather-condition ids that the firmware's today-summary treats as "rain".
# Mirrors the `rain_state` boolean in firmware/weather_logic.h parse_owm().
RAIN_STATE_IDS = set()
for lo, hi in [(200, 202), (230, 232), (502, 504), (300, 313)]:
    RAIN_STATE_IDS.update(range(lo, hi + 1))
for single in (500, 501, 511, 520, 521, 522, 314, 615, 616, 906):
    RAIN_STATE_IDS.add(single)

# Subset that the firmware flags as "storm".
STORM_IDS = set()
for lo, hi in [(200, 202), (230, 232), (502, 504)]:
    STORM_IDS.update(range(lo, hi + 1))
for single in (522, 314, 906):
    STORM_IDS.add(single)

# Short OWM icon prefix per leading weather id (only the final d/n char is read
# by the firmware, but we emit a plausible 3-char code anyway).
ICON_PREFIX = {
    800: "01", 801: "02", 802: "03", 803: "04", 804: "04",
    701: "50", 721: "50", 741: "50", 782: "50", 783: "50",
    906: "12", 905: "50", 951: "01", 957: "01", 958: "01", 959: "01",
    960: "01", 961: "01", 962: "01",
}

DEFAULT_STATE = {
    "weather_id": 800,
    "icon_code": "d",          # 'd' or 'n'
    "current_temp": 70.1,
    "today_high": 76.0,
    "today_low": 56.2,
    "uvi": 0.0,
    "aqi": 30,
    "rain_intensity": 0.0,     # mm/h, 0..5
    "rain_shape": "dry",       # dry | steady_this_hour | starts_in_10 | ending_in_10
    "tz_offset": -25200,       # seconds (Seattle PDT)
}

app = Flask(__name__)
_state_lock = threading.Lock()
state = dict(DEFAULT_STATE)
_last_fetch = {"ts": 0.0, "path": None, "state_snapshot": None}

SCENARIOS = json.load(open(SCENARIOS_PATH))
# Strip the human "_comment" key if present.
SCENARIOS.pop("_comment", None)


# --------------------------------------------------------------------------- #
# State helpers
# --------------------------------------------------------------------------- #
def _coerce(s):
    """Normalise a partial state update coming from the UI / presets."""
    out = dict(s)
    try:
        out["weather_id"] = int(out.get("weather_id", 800))
    except (TypeError, ValueError):
        out["weather_id"] = 800
    try:
        out["aqi"] = int(out.get("aqi", 30))
    except (TypeError, ValueError):
        out["aqi"] = 30
    try:
        out["uvi"] = float(out.get("uvi", 0.0))
    except (TypeError, ValueError):
        out["uvi"] = 0.0
    try:
        out["current_temp"] = float(out.get("current_temp", 70.0))
    except (TypeError, ValueError):
        out["current_temp"] = 70.0
    try:
        out["today_high"] = float(out.get("today_high", 76.0))
    except (TypeError, ValueError):
        out["today_high"] = 76.0
    try:
        out["today_low"] = float(out.get("today_low", 56.0))
    except (TypeError, ValueError):
        out["today_low"] = 56.0
    try:
        out["rain_intensity"] = max(0.0, min(5.0, float(out.get("rain_intensity", 0.0))))
    except (TypeError, ValueError):
        out["rain_intensity"] = 0.0
    try:
        out["tz_offset"] = int(out.get("tz_offset", -25200))
    except (TypeError, ValueError):
        out["tz_offset"] = -25200
    icon_code = str(out.get("icon_code", "d"))
    if not icon_code:
        icon_code = "d"
    out["icon_code"] = "n" if icon_code.lower().startswith("n") else "d"
    shape = str(out.get("rain_shape", "dry"))
    if shape not in ("dry", "steady_this_hour", "starts_in_10", "ending_in_10"):
        out["rain_shape"] = "dry"
    else:
        out["rain_shape"] = shape
    # Keep today_high >= today_low + current in a sane range (cosmetic only).
    if out["today_low"] > out["today_high"]:
        out["today_low"], out["today_high"] = out["today_high"], out["today_low"]
    return out


def icon_for(weather_id, dn):
    prefix = ICON_PREFIX.get(weather_id, "04")
    return prefix + ("n" if dn == "n" else "d")


def aqi_category(aqi):
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy for Sensitive Groups"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "Very Unhealthy"
    return "Hazardous"


def tz_short_name(tz_offset):
    """Best-effort short tz name; only used in cosmetic dateObserved fields."""
    secs = tz_offset
    sign = "+" if secs >= 0 else "−"
    secs = abs(secs)
    hh = secs // 3600
    mm = (secs % 3600) // 60
    return f"Etc/GMT{sign}{hh}" if mm == 0 else f"UTC{sign}{hh}:{mm:02d}"


# --------------------------------------------------------------------------- #
# JSON builders — faithful to what firmware/weather_logic.h expects
# --------------------------------------------------------------------------- #
def build_owm():
    with _state_lock:
        s = dict(state)
    now = int(time.time())
    tz = s["tz_offset"]
    now_local = now + tz
    today_start = (now_local // 86400) * 86400
    today_end = today_start + 86399
    wid = s["weather_id"]
    icon = icon_for(wid, s["icon_code"])
    is_rain = wid in RAIN_STATE_IDS

    # current
    current = {
        "dt": now,
        "sunrise": today_start - tz + 3600,
        "sunset": today_start - tz + 68400,
        "temp": round(s["current_temp"], 2),
        "feels_like": round(s["current_temp"] - 0.4, 2),
        "pressure": 1017,
        "humidity": 60,
        "dew_point": 55.0,
        "uvi": round(s["uvi"], 2),
        "clouds": 5,
        "visibility": 10000,
        "wind_speed": 1.5,
        "wind_deg": 96,
        "wind_gust": 5.0,
        "weather": [{"id": wid, "main": "Test", "description": "test sky", "icon": icon}],
    }

    # minutely: 60 one-minute entries. The firmware batches these 5-at-a-time
    # and derives the next-hour description + 60 bar graph values from them.
    intensity = s["rain_intensity"]
    shape = s["rain_shape"]
    minutely = []
    for i in range(60):
        dt = now + i * 60
        p = 0.0
        if shape == "steady_this_hour":
            p = intensity
        elif shape == "starts_in_10" and i >= 10:
            p = intensity
        elif shape == "ending_in_10" and i < 50:
            p = intensity
        minutely.append({"dt": dt, "precipitation": round(p, 3)})

    # hourly: span the rest of today (local). Inject rain into the current +
    # near hours so the firmware's today-summary can say "Rain today …".
    hourly = []
    h = 0
    while True:
        dt = now + h * 3600
        if (dt + tz) > today_end + 86400 * 0.25:  # stop a bit into tomorrow
            break
        entry = {
            "dt": dt,
            "temp": round(s["current_temp"] + (1.0 if h == 0 else -1.0) * h, 2),
            "feels_like": round(s["current_temp"] - 0.4, 2),
            "pressure": 1017,
            "humidity": 60,
            "dew_point": 55.0,
            "uvi": round(max(0.0, s["uvi"] - h * 0.4), 2),
            "clouds": 5,
            "visibility": 10000,
            "wind_speed": 1.5,
            "wind_deg": 96,
            "wind_gust": 5.0,
            "weather": [{"id": wid, "main": "Test", "description": "test sky", "icon": icon}],
            "pop": 0.0,
        }
        # The firmware's rain_threshold defaults to 0.0 in test secrets.
        if intensity > 0.0 and is_rain and h < 4:
            entry["rain"] = {"1h": round(intensity * 2.5, 1)}
            entry["pop"] = 0.9
        hourly.append(entry)
        h += 1
        if h > 48:
            break

    # daily[0] — the firmware reads temp.max/min and pop.
    daily0 = {
        "dt": today_start - tz,
        "sunrise": today_start - tz + 3600,
        "sunset": today_start - tz + 68400,
        "moon_phase": 0.5,
        "summary": "Emulated day",
        "temp": {
            "day": s["current_temp"] + 2.0,
            "min": s["today_low"],
            "max": s["today_high"],
            "night": s["today_low"] + 1.0,
            "eve": s["current_temp"],
            "morn": s["today_low"],
        },
        "feels_like": {
            "day": s["current_temp"] + 1.6,
            "night": s["today_low"] + 0.6,
            "eve": s["current_temp"] - 0.4,
            "morn": s["today_low"] - 0.4,
        },
        "pressure": 1018,
        "humidity": 58,
        "dew_point": 54.0,
        "wind_speed": 7.1,
        "wind_deg": 25,
        "wind_gust": 15.6,
        "weather": [{"id": wid, "main": "Test", "description": "emulated", "icon": icon}],
        "clouds": 40,
        "pop": s["rain_intensity"] / 5.0 if intensity > 0 else 0.0,
        "uvi": round(s["uvi"], 2),
    }

    return {
        "lat": s["tz_offset"] * 0.0001,  # cosmetic; ignored by firmware
        "lon": 0.0,
        "timezone": tz_short_name(tz),
        "timezone_offset": tz,
        "current": current,
        "minutely": minutely,
        "hourly": hourly,
        "daily": [daily0],
    }


def build_airnow():
    with _state_lock:
        s = dict(state)
    now = int(time.time())
    tz = s["tz_offset"]
    local = datetime.fromtimestamp(now + tz, tz=timezone.utc)
    aqi = max(0, min(500, int(s["aqi"])))
    return [{
        "dateObserved": local.strftime("%Y-%m-%d"),
        "hourObserved": local.strftime("%H:00"),
        "localTimeZone": tz_short_name(tz),
        "reportingAreaName": "Emulator Region",
        "siteID": "0",
        "siteName": "Emulator",
        "parameterName": "PM2.5",
        "nowcastAQI": aqi,
        "aqiCategoryName": aqi_category(aqi),
        "reportingAgency": "Weatherboard Test Emulator",
        "lookupBehavior": "Emulated",
        "consideredMonitors": "All",
        "lookupBoundary": "N/A",
    }]


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/state", methods=["GET"])
def get_state():
    with _state_lock:
        return jsonify(dict(state))


@app.route("/state", methods=["POST"])
def set_state():
    global state
    body = request.get_json(silent=True) or {}
    with _state_lock:
        merged = dict(state)
        merged.update(body)
        state = _coerce(merged)
    return jsonify(dict(state))


@app.route("/scenarios.json")
def scenarios():
    return jsonify(SCENARIOS)


@app.route("/last")
def last_fetch():
    with _state_lock:
        snap = dict(state)
    return jsonify(_last_fetch if _last_fetch["state_snapshot"] is None else {
        "ts": _last_fetch["ts"],
        "path": _last_fetch["path"],
        "age_s": round(time.time() - _last_fetch["ts"], 1),
        "snapshot": snap,
    })


@app.route("/data/3.0/onecall")
@app.route("/data/3.0/onecall/")
def owm_onecall():
    _record_fetch("/data/3.0/onecall")
    return jsonify(build_owm())


@app.route("/aq/observation/current/ziplatlong")
@app.route("/aq/observation/current/ziplatlong/")
def airnow_ziplatlong():
    _record_fetch("/aq/observation/current/ziplatlong")
    return jsonify(build_airnow())


def _record_fetch(path):
    global _last_fetch
    with _state_lock:
        _last_fetch = {
            "ts": time.time(),
            "path": path,
            "state_snapshot": dict(state),
        }


# --------------------------------------------------------------------------- #
# HTML UI (materialised to disk on first launch so Flask can serve it)
# --------------------------------------------------------------------------- #
def _write_index(path):
    html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Weatherboard Emulator</title>
<style>
  body { font: 14px/1.5 -apple-system, Segoe UI, Roboto, sans-serif; margin: 18px; color: #1a1a1a; }
  h1 { font-size: 18px; margin: 0 0 8px; }
  fieldset { border: 1px solid #d0d0d0; border-radius: 6px; padding: 10px 12px; margin-bottom: 12px; }
  legend { font-weight: 600; padding: 0 6px; }
  label { display: inline-block; width: 130px; font-size: 12px; color: #555; }
  select, input { font: 13px monospace; }
  .row { margin: 4px 0; }
  .preset { font-weight: 600; }
  #lastfetch { font-size: 12px; color: #666; }
  #live { background: #f5f5f5; border-radius: 6px; padding: 8px 10px; font-size: 12px; white-space: pre; }
</style>
</head>
<body>
  <h1>Weatherboard Emulator</h1>
  <p>Drive the ESP32 weather page. Changes take effect on the next firmware poll.</p>
  <div id="lastfetch"></div>
  <div id="live"></div>

  <fieldset>
    <legend class="preset">Preset</legend>
    <select id="preset" style="width:100%">
      <option value="">— pick a preset —</option>
    </select>
  </fieldset>

  <fieldset>
    <legend>Weather glyph</legend>
    <div class="row"><label>Condition </label>
      <select id="weather_id">
        <option value="800">800 Clear</option>
        <option value="801">801 Few clouds</option>
        <option value="802">802 Scattered</option>
        <option value="803">803 Broken</option>
        <option value="804">804 Overcast</option>
        <option value="701">701 Mist</option>
        <option value="741">741 Fog</option>
        <option value="500">500 Light rain</option>
        <option value="501">501 Rain</option>
        <option value="502">502 Heavy rain</option>
        <option value="520">520 Shower rain</option>
        <option value="521">521 Shower rain</option>
        <option value="211">211 Thunderstorm</option>
        <option value="201">201 Thunderstorm w/ rain</option>
        <option value="601">601 Snow</option>
        <option value="615">615 Sleet</option>
        <option value="616">616 Sleet</option>
        <option value="511">511 Freezing rain</option>
        <option value="906">906 Hail</option>
        <option value="905">905 Wind</option>
        <option value="782">782 Tornado</option>
        <option value="951">951 Tornado</option>
        <option value="958">958 Strong wind</option>
      </select>
    </div>
    <div class="row"><label>Day/Night </label>
      <select id="icon_code"><option value="d">day (d)</option><option value="n">night (n)</option></select>
    </div>
  </fieldset>

  <fieldset>
    <legend>Temperatures &amp; UV</legend>
    <div class="row"><label>Current temp (°F) </label><input type="number" step="0.1" id="current_temp" style="width:70px"></div>
    <div class="row"><label>Today high (°F) </label><input type="number" step="0.1" id="today_high" style="width:70px"></div>
    <div class="row"><label>Today low (°F) </label><input type="number" step="0.1" id="today_low" style="width:70px"></div>
    <div class="row"><label>UV index </label><input type="number" step="0.1" id="uvi" style="width:70px"></div>
  </fieldset>

  <fieldset>
    <legend>Rain (minutely graph + today summary)</legend>
    <div class="row"><label>Intensity (0–5) </label><input type="range" id="rain_intensity" min="0" max="5" step="0.5" value="0" style="vertical-align:middle"> <span id="ri_val">0</span></div>
    <div class="row"><label>Shape </label>
      <select id="rain_shape">
        <option value="dry">dry</option>
        <option value="steady_this_hour">steady (Rain this hour)</option>
        <option value="starts_in_10">starts in 10 min (Rain in 10)</option>
        <option value="ending_in_10">ending in 50 (Ending in 50)</option>
      </select>
    </div>
  </fieldset>

  <fieldset>
    <legend>AQI (AirNow / mask glyph)</legend>
    <div class="row"><label>nowcastAQI </label><input type="number" id="aqi" style="width:70px" value="30">
      <span id="aqi_cat"></span></div>
    <p style="font-size:12px;color:#666;margin:4px 0">Mask replaces the weather glyph when AQI ≥ 51; band colors:
      0–50 green, ≤100 yellow, ≤150 orange, ≤200 red, ≤300 purple, 301+ maroon.</p>
  </fieldset>

  <fieldset>
    <legend>Timing</legend>
    <div class="row"><label>tz offset (s) </label><input type="number" id="tz_offset" style="width:90px" value="-25200">
      <span style="font-size:12px;color:#666">e.g. -25200 = PDT</span></div>
  </fieldset>

<script>
const AQI_BANDS = [
  {max: 0, label: ''},
  {max: 50, label: 'Good', color: 'green'},
  {max: 100, label: 'Moderate', color: 'yellow'},
  {max: 150, label: 'Unhealthy for Sensitive Groups', color: 'orange'},
  {max: 200, label: 'Unhealthy', color: 'red'},
  {max: 300, label: 'Very Unhealthy', color: 'purple'},
  {max: 9999, label: 'Hazardous', color: 'maroon'},
];
function aqiCat(v){for(const b of AQI_BANDS){if(v<=b.max)return b.label||''}return 'Hazardous'}
function aqiColor(v){for(const b of AQI_BANDS){if(v<=b.max)return b.color||''}return 'maroon'}

const INPUTS = ['weather_id','icon_code','current_temp','today_high','today_low','uvi',
                'rain_intensity','rain_shape','aqi','tz_offset'];

function readState(){
  const s = {};
  for (const k of INPUTS) {
    const el = document.getElementById(k);
    let v = el.value;
    if (el.type === 'number') {
      const n = parseFloat(v); s[k] = isNaN(n) ? (k==='aqi'||k==='weather_id'||k==='tz_offset' ? 0 : 0) : n;
      if (k==='aqi'||k==='weather_id'||k==='tz_offset') s[k]=Math.round(s[k]);
    } else if (el.type === 'range') {
      s[k] = parseFloat(v);
    } else {
      s[k] = v;
    }
  }
  return s;
}
function writeState(s){
  for (const k of INPUTS) {
    const el = document.getElementById(k);
    if (el.type === 'range') { el.value = s[k]; }
    else { el.value = s[k]; }
  }
  document.getElementById('ri_val').textContent = document.getElementById('rain_intensity').value;
  document.getElementById('aqi_cat').textContent = aqiCat(Math.round(s.aqi));
  document.getElementById('aqi_cat').style.color = aqiColor(Math.round(s.aqi));
}
function push(){
  const s = readState();
  fetch('/state', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(s)})
    .then(r => r.json()).then(s => { writeState(s); refresh(); });
}

window.SCENARIOS = {};
function loadScenarios(){
  fetch('/scenarios.json').then(r=>r.json()).then(s => {
    window.SCENARIOS = s;
    const sel = document.getElementById('preset');
    sel.innerHTML = '<option value="">— pick a preset —</option>';
    for (const k of Object.keys(s)) sel.add(new Option(k, k));
  });
}
document.getElementById('preset').addEventListener('change', () => {
  const v = document.getElementById('preset').value;
  if (!v) return;
  writeState(window.SCENARIOS[v]);
  push();
});

let _t;
for (const k of INPUTS){
  const el = document.getElementById(k);
  el.addEventListener('input', () => {
    if (k==='rain_intensity') document.getElementById('ri_val').textContent = el.value;
    if (k==='aqi') {
      const a = Math.round(parseFloat(el.value)||0);
      document.getElementById('aqi_cat').textContent = aqiCat(a);
      document.getElementById('aqi_cat').style.color = aqiColor(a);
    }
    clearTimeout(_t);
    _t = setTimeout(push, 250);
  });
}

function refresh(){
  fetch('/last').then(r=>r.json()).then(d => {
    const ago = d.ts ? Math.round((Date.now()/1000 - d.ts)) : null;
    document.getElementById('lastfetch').innerHTML =
      '<b>Last firmware fetch:</b> ' + (d.path ? d.path : 'none yet') +
      (ago !== null ? ' — ' + ago + 's ago' : '');
    const s = d.snapshot || {};
    document.getElementById('live').textContent =
      'icon: '+iconFor(s.weather_id, s.icon_code)+'  temp: '+s.current_temp+'°  H/L: '+s.today_high+'/'+s.today_low+
      '  UV: '+s.uvi+'  AQI: '+s.aqi+'  rain: '+s.rain_intensity+'('+s.rain_shape+')';
  });
}
function iconFor(id, dn){
  const m={800:'01',801:'02',802:'03',803:'04',804:'04',701:'50',721:'50',741:'50',782:'50',783:'50',906:'12',905:'50',951:'01',957:'01',958:'01',959:'01',960:'01',961:'01',962:'01'};
  return (m[id]||'04') + (dn==='n'?'n':'d');
}

loadScenarios();
fetch('/state').then(r=>r.json()).then(writeState);
setInterval(refresh, 2000);
</script>
</body>
</html>
"""
    with open(path, "w") as f:
        f.write(html)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Emulated OWM + AirNow server for weatherboard testing")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    # Serve the inline UI from a small static dir so / works without extra config.
    static_dir = os.path.join(HERE, "static")
    os.makedirs(static_dir, exist_ok=True)
    index_html = os.path.join(static_dir, "index.html")
    if not os.path.exists(index_html):
        _write_index(index_html)

    app.static_folder = static_dir
    app.static_url_path = ""
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)
