# AGENTS.md — esphome-weatherboard

ESPHome firmware for a transit + weather LED matrix display board. This repo
extends the upstream [transit-tracker](https://github.com/EastsideUrbanism/transit-tracker)
firmware with an extra weather page. Source files are YAML; there is no CI, no
unit tests, and no lint/format step. Verification = compiling firmware in
ESPHome.

## Project layout

```
firmware/transit-weatherboard.yaml   # ESPHome YAML — the only source file
ha/                                   # Home Assistant helper + blueprint YAML
  input_number.yaml                   # helpers: today_high_temp, today_low_temp, today_rain_chance
  input_text.yaml                    # helpers: next_hour_rain_description, rain_values, today_precipitation_description
  openweatherblueprint.yaml           # Blueprint that populates the helpers from OpenWeatherMap
fonts/MaterialDesignIconsDesktop.ttf  # local icon font for weather glyphs
start-esphome.sh                      # Docker entrypoint for the ESPHome dashboard
```

## Build & verify

There is no lint/format step. Verification = compiling firmware in ESPHome.

To compile headlessly (CI or a local container without the dashboard):

```sh
# secrets.yaml (wifi_ssid, wifi_password, owm_url) must sit at the repo root.
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
- `!secret wifi_ssid`, `!secret wifi_password`, and `!secret owm_url` are
  resolved from `secrets.yaml` (not committed — see `firmware/.gitignore`).
  `owm_url` is the full OpenWeatherMap One Call 3.0 endpoint, e.g.:
  `https://api.openweathermap.org/data/3.0/onecall?lat=<LAT>&lon=<LON>&exclude=alerts&units=metric&appid=<KEY>`

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

## Home Assistant setup

Weather is fetched **on-device** from the OpenWeatherMap One Call 3.0 API (see
`!secret owm_url` + the `interval` HTTP fetch in the firmware), so the OpenWeatherMap
*HA integration* and the `ha/openweatherblueprint.yaml` input helpers are
**deprecated** for weather. Home Assistant is still used for **transit + OTA**
via the upstream transit-tracker package (`api:`/`ota:`).

The deprecated legacy steps (retained for existing installs) were:

1. Add `ha/input_number.yaml` and `ha/input_text.yaml` to your
   `configuration.yaml` (or an included file), then **reload YAML**. These
   helpers must exist before the blueprint runs.
2. Import `ha/openweatherblueprint.yaml` into Home Assistant. It requires
   `homeassistant: min_version: "2026.2.3"` and the OpenWeatherMap integration in
   One Call API 3.0 mode.

The recommended ESPHome device YAML is:

    packages:
      transit_weatherboard: github://mixtythepuppycat/esphome-weatherboard/firmware/transit-weatherboard.yaml@main

    transit_tracker:
      font_id: pixolletta   # forwarded to the upstream package

and `secrets.yaml` must contain `wifi_ssid`, `wifi_password`, and `owm_url`.

The (deprecated) blueprint polled OpenWeatherMap on a time pattern and wrote rain
values, descriptions, and high/low temps into the input helpers, which the ESPHome
firmware used to read via `homeassistant:` text/number sensor entities. The
current firmware no longer reads those helpers; tune the fetch cadence with the
`owm_poll_interval` substitution instead.
