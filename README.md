# ESPHome Weather Display Board

Inspired by the [Transit Tracker](https://transit-tracker.eastsideurbanism.org) project, this extends it's functionality by adding a display page showing important weather information for your travels that day.

![Example of the rain graph](images/rain_graph.jpg)
![Example of the future rain](images/future_rain.jpg)

## Requirements

- A built display board. See Transit Tracker's excellent [build guide](https://transit-tracker.eastsideurbanism.org/docs/build-guide)
- [ESPHome Device Builder](https://esphome.io/guides/getting_started_hassio/) environment. If you have docker setup, you can use the `start-esphome.sh` script to run the installer dashboard.
- [Home Assistant](https://www.home-assistant.io/) for transit data + OTA uploads only. **Weather is processed entirely on the device** — the firmware fetches the OpenWeatherMap One Call 3.0 API and the AirNow AQI endpoint directly from the ESP32, with no Home Assistant integration required for weather.
- Knowledge of building/installing ESPHome firmware.

## Home Assistant Setup (transit + OTA)

Home Assistant is required only for **transit data and OTA uploads** (via the
upstream transit-tracker package's `api:`/`ota:`). **Weather is processed
entirely on-device**: the firmware fetches the OpenWeatherMap One Call 3.0 API
and the AirNow AQI endpoint directly from the ESP32 using `http_request`
(schedule governed by `${owm_poll_interval}`). No Home Assistant weather
integration or helper entities are needed.

## ESPHome Transit + Weatherboard Setup

Create a new firmware yaml with

```
packages:
  transit_weatherboard: github://mixtythepuppycat/esphome-weatherboard/firmware/transit-weatherboard.yaml@main

transit_tracker:
  font_id: pixolletta   # forwarded to the upstream package
```

Additionally add the following to your `secrets.yaml`:

```
wifi_ssid: <YOUR_WIFI_SSID>
wifi_password: <YOUR_WIFI_PASSWORD>
owm_api_key: <YOUR_OPENWEATHERMAP_API_KEY>
owm_lat: <YOUR_LATITUDE>
owm_lon: <YOUR_LONGITUDE>
airnow_api_key: <YOUR_AIRNOW_API_KEY>
```

`owm_api_key` is your OpenWeatherMap One Call 3.0 key (free tier covers ~1000
calls/day at the default 3-minute poll). Fetch an appid at
[openweathermap.org](https://openweathermap.org/api/). `airnow_api_key` is
your separate AirNow API key for AQI. `owm_lat`/`owm_lon` are shared between
the OWM and AirNow requests.

You can then switch between the weather and transit information using switches in Home Assistant.

## ESPHome Weatherboard Standalone Setup

If you want to use this standalone, look at the Weatherboard section in
[transit-weatherboard.yaml](firmware/transit-weatherboard.yaml). It fetches
weather directly via an `interval` HTTP GET to the OWM One Call 3.0 endpoint
(built inline from `owm_api_host`, `owm_api_key`, `owm_lat`, and `owm_lon`), so
your `secrets.yaml` must provide `wifi_ssid`, `wifi_password`, `owm_api_key`,
`owm_lat`, `owm_lon`, and `airnow_api_key`, and the `weather_page` must be added
as a display page on your `matrix`.
