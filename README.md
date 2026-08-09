# ESPHome Weather Display Board

Inspired by the [Transit Tracker](https://transit-tracker.eastsideurbanism.org) project, this extends it's functionality by adding a display page showing important weather information for your travels that day.

![Example of the rain graph](images/rain_graph.jpg)
![Example of the future rain](images/future_rain.jpg)

## Requirements
- A built display board. See Transit Tracker's excellent [build guide](https://transit-tracker.eastsideurbanism.org/docs/build-guide)
- [ESPHome Device Builder](https://esphome.io/guides/getting_started_hassio/) environment. If you have docker setup, you can use the `start-esphome.sh` script to run the installer dashboard.
- [Home Assistant](https://www.home-assistant.io/) for transit data + API/OTA. The weather page now fetches OpenWeatherMap directly on the device, so the **OpenWeatherMap HA integration is optional/deprecated**.
- Knowledge of building/installing ESPHome firmware, Home Assistant blueprint importing, and Home Assistant configuration yamls.

## Home Assistant Setup (transit + OTA)

Home Assistant is required for **transit data and OTA uploads** (via the upstream
transit-tracker package's `api:`/`ota:`), but it is **not** required for
**weather**: the firmware fetches the OpenWeatherMap One Call 3.0 API directly
from the ESP32 using the `owm_url` secret.

> **Deprecated:** the [OpenWeatherMap HA integration](https://www.home-assistant.io/integrations/openweathermap)
> and the [ha/openweatherblueprint.yaml](ha/openweatherblueprint.yaml) + input
> helper files are no longer consumed by the firmware for weather; they are kept
> only for backward compatibility. New installs should skip steps 1–3 below and
> use the on-device fetch.
>
> 1. (deprecated) Add [ha/input_number.yaml](ha/input_number.yaml) and [ha/input_text.yaml](ha/input_text.yaml) to your Home Assistant's `configuration.yaml` and reload YAML.
> 2. (deprecated) Import [ha/openweatherblueprint.yaml](ha/openweatherblueprint.yaml) (requires OpenWeatherMap One Call API 3.0).
> 3. (deprecated) Confirm `next_hour_rain_description` / `today_high_temp` appear under Helpers.

## ESPHome Transit + Weatherboard Setup
Create a new firmware yaml with

```
packages:
 transit_weatherboard: github://mixtythepuppycat/esphome-weatherboard/firmware/transit-weatherboard.yaml@main

transit_tracker:
 # See https://transit-tracker.eastsideurbanism.org/configurator for configuration values 
```

Additionally add the following to your `secrets.yaml`:

```
wifi_ssid: <YOUR_WIFI_SSID>
wifi_password: <YOUR_WIFI_PASSWORD>
owm_url: "https://api.openweathermap.org/data/3.0/onecall?lat=<LAT>&lon=<LON>&exclude=alerts&units=metric&appid=<YOUR_OWM_API_KEY>"
```

`owm_url` is the full OpenWeatherMap **One Call API 3.0** endpoint (free tier
covers ~288 calls/day at the default 5-minute poll). Fetch an appid at
[openweathermap.org](https://openweathermap.org/api/).

You can then switch between the weather and transit information using switches in Home Assistant.

## ESPHome Weatherboard Standalone Setup
If you want to use this standalone, look at the Weatherboard section in
[transit-weatherboard.yaml](firmware/transit-weatherboard.yaml). It fetches
weather directly via an `interval` HTTP GET to `!secret owm_url`, so your
`secrets.yaml` must provide `wifi_ssid`, `wifi_password`, and `owm_url`, and the
`weather_page` must be added as a display page on your `matrix`.
