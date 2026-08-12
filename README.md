# ESPHome Weather Display Board

Inspired by the [Transit Tracker](https://transit-tracker.eastsideurbanism.org) project, this extends it's functionality by adding a display page showing important weather information for your travels that day.

![Example of the rain graph](images/rain_graph.jpg)
![Example of the future rain](images/future_rain.jpg)

## Requirements

- A built display board. See Transit Tracker's excellent [build guide](https://transit-tracker.eastsideurbanism.org/docs/build-guide)
- [ESPHome Device Builder](https://esphome.io/guides/getting_started_hassio/) environment. If you have docker setup, you can use the `start-esphome.sh` script to run the installer dashboard.
- [Home Assistant](https://www.home-assistant.io/) integration is now optional for controlling the device (page-switching, configuration) via the ESPHome API. **Weather is processed entirely on the device** — the firmware fetches the OpenWeatherMap One Call 3.0 API and the AirNow AQI endpoint directly from the ESP32, with no Home Assistant integration required for weather.
- Knowledge of building/installing ESPHome firmware.

## ESPHome Transit + Weatherboard Setup

Create a new firmware yaml with

```
packages:
  transit_weatherboard: github://mixtythepuppycat/esphome-weatherboard/firmware/transit-weatherboard.yaml@main

transit_tracker:
  See https://transit-tracker.eastsideurbanism.org/configurator for configuration values 
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
your separate AirNow API key for AQI which you can get at [docs.airnowapi.org](https://docs.airnowapi.org/). 
`owm_lat`/`owm_lon` are shared between the OWM and AirNow requests.

You can switch between the weather and transit information using the ESPHome web
dashboard's switches (or optionally, Home Assistant entities if you connect the
device via the ESPHome API).