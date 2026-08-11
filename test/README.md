# Weatherboard Emulator

A standalone Flask server that emulates the OpenWeatherMap One Call 3.0 and
AirNow `ziplatlong` APIs so you can visually verify every weather-board display
mode against the real firmware — without touching the live APIs.

## What it does

`emulated_server.py` keeps an in-memory "weather state" and, on each request
from the ESP32, assembles a valid OWM One Call 3.0 body and an AirNow array
from that state. A single-page web UI (`/`) lets you pick a preset or tweak any
value (weather id, day/night, current temp, today H/L, UV, AQI, rain intensity,
rain shape, tz offset). Changes take effect on the next firmware poll.

## Prerequisites

- Python 3.8+
- `pip install flask`

## Quick start

```sh
# 1. Configure test secrets (gitignored — never commit it)
cp firmware/secrets.yaml.test.example firmware/secrets.yaml
# Edit firmware/secrets.yaml:
#   wifi_ssid / wifi_password         your Wi-Fi
#   owm_base_url / airnow_base_url    http://<your-lan-ip>:8080
#                                     (NOT 127.0.0.1 — that is the device itself)

# 2. Compile + flash the firmware (same image/flags as production)
docker run --rm -v /cache -v "${PWD}:/config" -w /config \
  ghcr.io/esphome/esphome:2026.6.5 run firmware/transit-weatherboard.yaml \
  --upload-port /dev/ttyUSB0        # or whatever your device port is

# 3. Run the emulator on the same LAN
python3 test/emulated_server.py --port 8080

# 4. Drive the display
#    Open http://<your-lan-ip>:8080 in a browser.
```

> For faster visual feedback, temporarily lower `owm_poll_interval` in
> `firmware/transit-weatherboard.yaml` (e.g. `15s`) while testing. Revert to the
> default `2min` for real use. On production secrets the `*_base_url` values stay
> the real API origins; only `firmware/secrets.yaml` is swapped for test.

## Route map

| Method | Path (matched by suffix) | Returns |
|---|---|---|
| GET | `/` | control UI |
| GET | `/state` | current in-memory state |
| POST | `/state` | JSON body merges into state (partial merge OK) |
| GET | `/scenarios.json` | preset definitions |
| GET | `/last` | timestamp + snapshot of the most recent firmware fetch |
| GET | `/data/3.0/onecall` | assembled OWM One Call 3.0 JSON |
| GET | `/aq/observation/current/ziplatlong` | assembled AirNow array |

The OWM and AirNow routes ignore query strings; they match by path suffix so the
firmware can keep its real `lat`/`lon`/`appid`/`format` parameters.

## Presets

Weather glyphs (aqi = 30, so the icon is visible):

| Preset | weather id | icon | today-desc | top-left glyph |
|---|---|---|---|---|
| Clear day | 800 | 01d | No rain today | sunny |
| Clear night | 800 | 01n | No rain today | clear-night |
| Partly cloudy | 801 | 02d | No rain today | partly-cloudy |
| Overcast | 803 | 04d | No rain today | cloudy |
| Light rain | 500 | 10d | Rain today this hour | rainy |
| Heavy rain | 502 | 10d | Storm today this hour | pouring |
| Storm | 201 | 11d | Storm today this hour | lightning-rainy |
| Snow | 601 | 13d | No rain today | snowy |
| Snowy-rainy | 511 | 12d | No rain today | snowy-rainy |
| Hail | 906 | 12d | No rain today | hail |
| Windy | 905 | 50d | No rain today | windy |
| High UV | 800 | 01d | UV 11 | sunny |

AQI mask bands (weather id 800, dry — isolates the mask color in the top-left):

| Preset | aqi | result |
|---|---|---|
| AQI good (green) | 30 | no mask — weather glyph stays (confirms ≤ 50 threshold) |
| AQI moderate (yellow) | 75 | yellow mask |
| AQI orange | 145 | orange mask |
| AQI red | 180 | red mask |
| AQI purple | 250 | purple mask |
| AQI maroon (hazardous) | 350 | maroon mask |

Mask thresholds (in the firmware `weather_page` lambda): green ≤ 50, yellow ≤
100, orange ≤ 150, red ≤ 200, purple ≤ 300, maroon 301+. The mask replaces the
weather glyph when `aqi ≥ 51`.

## Knobs

- **Rain shape** drives the minutely bar graph and the next-hour description:
  `dry` → "No rain", `steady_this_hour` → "Rain this hour", `starts_in_10` →
  "Rain in 10", `ending_in_10` → "Ending in 50". Bars are anchored to real
  wall-clock time, so they advance as the device polls.
- **Today-desc** is driven by the hourly block: if the weather id is a
  rain-state (see `parse_owm` in `firmware/weather_logic.h`) and
  `rain_intensity > 0`, hourly rain is injected so the firmware prints
  "Rain today …" / "Storm today …". For non-rain presets (or AQI presets) it
  stays "No rain today" or "UV N".
- **TZ offset** defaults to `-25200` (Seattle PDT) so the today-summary window
  is correct; change it to match your location's offset if needed.

## Notes

- The emulator does **not** authenticate; the firmware's `appid` / `API_KEY`
  query params are ignored.
- The firmware only polls once SNTP time is valid (`sntp_time` on the device).
  In test mode the device gets real time from your NTP server, so no mock time
  service is required.
- A preset with `aqi ≥ 51` will show the colored mask *instead of* the weather
  glyph in the top-left — that is the real firmware behaviour, not a server
  limitation. The AQI-band presets keep the weather clear (id 800) so only the
  mask color is visible; the weather-glyph presets keep `aqi = 30`.
