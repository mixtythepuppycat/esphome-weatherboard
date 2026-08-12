# AGENTS.md — esphome-weatherboard

ESPHome firmware for a transit + weather LED matrix display board. This repo
extends the upstream [transit-tracker](https://github.com/EastsideUrbanism/transit-tracker)
firmware with an extra weather page. Source files are YAML; there is no CI, no
unit tests, and no lint/format step. Verification = compiling firmware in
ESPHome.

## Project layout

```
firmware/transit-weatherboard.yaml   # ESPHome YAML — the only source file
fonts/MaterialDesignIconsDesktop.ttf  # local icon font for weather glyphs
start-esphome.sh                      # Docker entrypoint for the ESPHome dashboard
```

## Build & verify

There is no lint/format step. Verification = compiling firmware in ESPHome.

To compile headlessly (CI or a local container without the dashboard):

```sh
# secrets.yaml (wifi_ssid, wifi_password, owm_api_key, owm_lat, owm_lon, airnow_api_key) must sit at the repo root.
docker run --rm -v /cache \
  -v "${PWD}:/config" -w /config \
  ghcr.io/esphome/esphome:2026.6.5 compile firmware/transit-weatherboard.yaml
```

- `start-esphome.sh` pins `ghcr.io/esphome/esphome:2026.6.5`. The upstream
  `transit-tracker@main` package declares `min_version: "2026.6.5"`, so anything
  older (the previous `2026.3.0` pin) refuses to load it. ESPHome YAML relies on
  directives that can break across releases — if you must bump, first verify
  compatibility with the directives used here (`!secret`, `!extend`, `!remove`,
  `packages:`, `${subst}`).
- **Network:** a real compile reaches `github.com` (the upstream package + fonts)
  **and** the toolchains' registries — `api.platformio.org` /
  `api.registry.platformio.org` (PlatformIO) and
  `components-file.espressif.com` (ESP-IDF component registry, for ArduinoJson).
- **Build cache:** PlatformIO materializes the toolchain via symlinks, so the
  cache must live on a filesystem that allows symlinks. Mount a persistent volume
  at `/cache` (as above) rather than relying on the bind-mounted `/config`, since
  a bind mount of `${PWD}` rejects symlinks with `EPERM`.

## Firmware conventions

The firmware is a thin overlay on the upstream transit-tracker package:

- `packages:` imports `github://EastsideUrbanism/transit-tracker/firmware/transit-tracker.yaml@main`.
  This requires **network access to GitHub** at build time.
- Several IDs are **not defined here** — they come from the upstream package and
  are consumed locally. Do not rename them:
  - `matrix` (the `hub75` display), `transit_schedule` (transit page)
  - `sntp_time`, `icon_font`, `color_red`, `color_blue`, `color_yellow`
- `id: !extend matrix` extends the upstream display definition rather than
  redefining it.
- `- id: !remove pixolletta` removes the upstream font so this repo can redefine
  it with a remote URL + custom glyph set.
- `!secret wifi_ssid` and `!secret wifi_password` resolve from `secrets.yaml`
  (not committed — see `firmware/.gitignore`). The OWM One Call URL is built
  inline from the `${owm_api_host}` substitution (API origin, e.g.
  `https://api.openweathermap.org`; in test mode re-route to a local emulator
  like `http://<lan-ip>:8080`), plus `!secret owm_api_key`, `!secret owm_lat`,
  and `!secret owm_lon`. AQI is fetched from the AirNow `ziplatlong` endpoint
  using a **separate** `${airnow_api_host}` substitution and `!secret airnow_api_key`
  (URL templated inline). `owm_lat`/`owm_lon` are shared between the OWM and
  AirNow requests. A test fixture set + emulated server live in `test/`
  (see `test/README.md`).

## Editing the weather page

- Weather icon glyphs (`\U000F0599`, etc.) are codepoints from
  `fonts/MaterialDesignIconsDesktop.ttf`. Add icons to the `icon_font` glyph list
  in `firmware/transit-weatherboard.yaml` so they embed in the build.
- Icons are selected by OWM weather `id` (which mirrors the HA OpenWeatherMap
  condition map) combined with the icon code's `d`/`n` suffix for day/night, via
  the glyph map in the `weather_page` lambda. `weather.id` values map 1:1 to the
  OpenWeatherMap condition codes; add a new branch and its matching glyph
  together.
- Fonts are loaded from **pinned upstream commits** via raw GitHub URLs. Changing
  a font file means updating the commit hash in the URL.
- **AQI (AirNow):** the device fetches the AirNow `ziplatlong` JSON on
  `${owm_poll_interval}` (same interval as OWM) using `own_lat`/`own_lon` and a
  separate `airnow_api_key`. The lambda takes the **max `nowcastAQI`** across the
  returned pollutants and publishes it to `sensor.aqi`. On the display, when
  `AQI >= aqi_mask_threshold` (default `51`, i.e. the first yellow tier) the
  top-left icon is replaced with the colored `\U000F1587` mask glyph
  (`face-mask-outline`); the color follows the EPA AQI bands
  (green ≤50, yellow ≤100, orange ≤150, red ≤200, purple ≤300, maroon 301+).
  Below the threshold the normal weather icon is shown. The exact AQI number is
  exposed via `sensor.aqi` (visible in Home Assistant); there is no room for the
  digits on-device alongside the mask. Add `"\U000F1587"` to the `icon_font`
  glyph list and the EPA-band colors to the `color:` block when enabling.

**Weather is processed entirely on-device**: the
firmware fetches the OpenWeatherMap One Call 3.0 API and the AirNow AQI endpoint
directly from the ESP32 using `http_request` (schedule governed by
`${owm_poll_interval}`).

The recommended ESPHome device YAML is:

    packages:
      transit_weatherboard: github://mixtythepuppycat/esphome-weatherboard/firmware/transit-weatherboard.yaml@main

    transit_tracker:
      font_id: pixolletta   # forwarded to the upstream package

and `secrets.yaml` must contain `wifi_ssid`, `wifi_password`, `owm_api_key`,
`owm_lat`, `owm_lon`, and `airnow_api_key`. In test mode, redirect the
`owm_api_host` and `airnow_api_host` substitutions (or point the API hosts at a
local emulator) — see `test/README.md`. Tune the fetch cadence with the
`owm_poll_interval` substitution.
