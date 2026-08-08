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

There is no compile/lint/test cycle — run ESPHome and hit **Install**:

```sh
./start-esphome.sh    # opens the ESPHome dashboard on http://localhost:6052
```

`start-esphome.sh` pins `ghcr.io/esphome/esphome:2026.3.0`. ESPHome YAML relies on
features that break across releases, so **do not bump the version tag** unless
you've checked compatibility with the directives used here (`!secret`,
`!extend`, `!remove`, `packages:`).

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
- `!secret wifi_ssid` / `!secret wifi_password` are resolved from
  `secrets.yaml` (not in this repo). It must contain both keys.

## Editing the weather page

- Weather icon glyphs (`\U000F0599`, etc.) are codepoints from
  `fonts/MaterialDesignIconsDesktop.ttf`. Add icons to the `icon_font` glyph list
  in `firmware/transit-weatherboard.yaml` so they embed in the build.
- The `weather_state` strings (`sunny`, `partlycloudy`, `rainy`, ...) must match
  the condition strings emitted by the HA `weather.openweathermap` entity. If
  you add a weather icon, add the matching icon to `ha/openweatherblueprint.yaml`
  glyph logic and the `icon_font` glyphs list together.
- Fonts are loaded from **pinned upstream commits** via raw GitHub URLs. Changing
  a font file means updating the commit hash in the URL.

## Home Assistant setup (required order)

1. Add `ha/input_number.yaml` and `ha/input_text.yaml` contents to your
   `configuration.yaml` (or an included file), then **reload YAML**. These
   helpers must exist before the blueprint runs.
2. Import `ha/openweatherblueprint.yaml` into Home Assistant. It requires
   `homeassistant: min_version: "2026.2.3"` and the OpenWeatherMap integration in
   One Call API 3.0 mode.
3. In your ESPHome device YAML, include this repo as a package:
   ```yaml
   packages:
     transit_weatherboard: github://mixtythepuppycat/esphome-weatherboard/firmware/transit-weatherboard.yaml@main
   ```
4. Add `wifi_ssid` / `wifi_password` to your `secrets.yaml`.

The blueprint polls OpenWeatherMap on a time pattern (default `/5` minutes) and
writes rain values, descriptions, and high/low temps into the input helpers,
which the ESPHome firmware reads via `homeassistant:` text/number sensor
entities. See the blueprint's `polling_frequency`, `threshold_rate`, and
`graph_multi` inputs to tune frequency and rain sensitivity.
