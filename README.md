# ESPHome Weather Display Board

Inspired by the [Transit Tracker](https://transit-tracker.eastsideurbanism.org) project, this extends it's functionality by adding a display page showing important weather information for your travels that day.

![Example of the rain graph](images/rain_graph.jpg)
![Example of the future rain](images/future_rain.jpg)

## Requirements
- A built display board. See Transit Tracker's excellent [build guide](https://transit-tracker.eastsideurbanism.org/docs/build-guide)
- [ESPHome Device Builder](https://esphome.io/guides/getting_started_hassio/) environment. If you have docker setup, you can use the `start-esphome.sh` script to run the installer dashboard.
- [Home Assistant](https://www.home-assistant.io/) setup with the [OpenWeatherMap integration](https://www.home-assistant.io/integrations/openweathermap) in One Call API 3.0 mode.
- Knowledge of building/installing ESPHome firmware, Home Assistant blueprint importing, and Home Assistant configuration yamls.

## Home Assistant Setup
Due to current limitations in Home Assistant, there's a few steps you must take.
First add [ha/input_number.yaml](ha/input_number.yaml) and [ha/input_text.yaml](ha/input_text.yaml) to your Home Assistant's `configuration.yaml` and reload your yamls. These will add the intermediary helpers used by the Blueprint and the ESPHome firmware.
Next import the [ha/openweatherblueprint.yaml](ha/openweatherblueprint.yaml) Blueprint into Home Assistant.
If everything is setup correctly, you should see a few entries under the Helpers tab such as `next_hour_rain_description` and `today_high_temp` which will be populated with current values.

## ESPHome Transit + Weatherboard Setup
Create a new firmware yaml with

```
packages:
 transit_weatherboard: github://mixtythepuppycat/esphome-weatherboard/firmware/transit-weatherboard.yaml@main

transit_tracker:
 # See https://transit-tracker.eastsideurbanism.org/configurator for configuration values 
```

Additionally add the following wifi configuration information to your `secrets.yaml`

```
wifi_ssid: <YOUR_WIFI_SSID>
wifi_password: <YOUR_WIFI_PASSWORD>
```

You can then switch between the weather and transit information using switches in Home Assistant.

## ESPHome Weatherboard Standalone Setup
If you want to use this standalone, look at the Weatherboard section in [transit-weatherboard.yaml](firmware/transit-weatherboard.yaml) for what to add to your project.
