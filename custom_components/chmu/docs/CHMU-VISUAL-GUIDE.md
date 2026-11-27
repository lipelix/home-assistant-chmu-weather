# 🌤️ ČHMÚ Weather Integration - Visual Guide

## What You'll See After Installation

### 1. Integration Added
```
┌─────────────────────────────────────────────────────────┐
│ Settings > Devices & Services                           │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │  🌤️ ČHMÚ Weather                                  │  │
│  │  ─────────────────────────────────────────────   │  │
│  │  Praha-Libuš                                     │  │
│  │  6 entities • 0 devices                          │  │
│  │  ✓ Configured                                    │  │
│  └──────────────────────────────────────────────────┘  │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 2. Device Details
```
┌─────────────────────────────────────────────────────────┐
│ Praha-Libuš                                              │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ Entities (6)                                            │
│                                                          │
│ 🌡️  Temperature            10.5 °C                      │
│ 💧  Humidity               75 %                          │
│ 🎚️  Pressure               1013.2 hPa                   │
│ 🌧️  Precipitation          0.0 mm                       │
│ 💨  Wind Speed             2.3 m/s                      │
│ 🧭  Wind Direction         180 °                        │
│                                                          │
│ Device info                                             │
│ Manufacturer: ČHMÚ                                      │
│ Model: Weather Station                                  │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 3. Dashboard View
```
┌───────────────────────────────────────────────────────────────────┐
│ 🏠 Home                                                            │
└───────────────────────────────────────────────────────────────────┘

... (other sections) ...

┌───────────────────────────────────────────────────────────────────┐
│ 🌤️ Venkovní počasí ČHMÚ                                           │
├─────────────────────────────────┬─────────────────────────────────┤
│                                 │                                 │
│  Aktuální stav                  │  Průběh počasí (24h)           │
│  ───────────────               │  ────────────────────           │
│                                 │                                 │
│  🌡️  Teplota     10.5 °C       │   20°C ┌───╮                   │
│  💧  Vlhkost     75 %           │        │   │  ╭─╮              │
│  🎚️  Tlak        1013.2 hPa    │   15°C │   ╰──╯ │              │
│  🌧️  Srážky      0.0 mm         │        │       │              │
│  💨  Rychlost    2.3 m/s        │   10°C ╰───────╯              │
│      větru                      │                                 │
│  🧭  Směr větru  180 °          │    0°C └──┬──┬──┬──┬──┬──┬──┘ │
│                                 │       00 04 08 12 16 20 24     │
│                                 │                                 │
└─────────────────────────────────┴─────────────────────────────────┘
```

### 4. History Graph Detail
```
┌───────────────────────────────────────────────────────────────────┐
│ Průběh počasí (24h)                                                │
├───────────────────────────────────────────────────────────────────┤
│                                                                    │
│ Legend:                                                            │
│ ─── Venkovní teplota (°C)                                         │
│ ─── Venkovní vlhkost (%)                                          │
│ ─── Barometrický tlak (hPa)                                       │
│ ─── Srážky (mm)                                                   │
│                                                                    │
│  100 ┤                                                             │
│   90 ┤                                                             │
│   80 ┤        ╭───╮    Humidity                                   │
│   70 ┤    ╭───╯   ╰─╮                                             │
│   60 ┤ ╭──╯         ╰──╮                                          │
│   50 ┤ │                                                           │
│   40 ┤ │                                                           │
│   30 ┤ │                                                           │
│   20 ┤ │     ╭──╮      Temperature                                │
│   10 ┤ ╰─────╯  ╰───╮                                             │
│    0 ┤              ╰──                                            │
│      └──┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬──   │
│        00   02   04   06   08   10   12   14   16   18   20   22 │
│                          Nov 9, 2025                               │
│                                                                    │
└───────────────────────────────────────────────────────────────────┘
```

## Configuration Flow Screenshots

### Step 1: Add Integration
```
┌──────────────────────────────────┐
│  Add integration                 │
├──────────────────────────────────┤
│                                  │
│  [Search...]                     │
│  Type: ČHMÚ                      │
│                                  │
│  Results:                        │
│  ┌────────────────────────────┐ │
│  │ 🌤️ ČHMÚ Weather            │ │
│  │ Czech weather stations     │ │
│  └────────────────────────────┘ │
│                                  │
└──────────────────────────────────┘
```

### Step 2: Select Station
```
┌──────────────────────────────────┐
│  ČHMÚ Weather Station            │
├──────────────────────────────────┤
│                                  │
│  Vyberte meterologickou stanici  │
│  nejbližší k vaší poloze         │
│                                  │
│  Weather Station:                │
│  ┌────────────────────────────┐ │
│  │ Praha-Libuš (11406)     ▼ │ │
│  └────────────────────────────┘ │
│                                  │
│  Options shown:                  │
│  • Praha-Libuš                   │
│  • Praha-Ruzyně                  │
│  • Brno-Tuřany                   │
│  • Ostrava-Mošnov                │
│  • ...                           │
│                                  │
│        [Cancel]  [Submit]        │
│                                  │
└──────────────────────────────────┘
```

### Step 3: Success
```
┌──────────────────────────────────┐
│  Success!                        │
├──────────────────────────────────┤
│                                  │
│  ✓ Successfully configured       │
│    ČHMÚ Weather                  │
│                                  │
│  Praha-Libuš has been added      │
│  with 6 weather sensors.         │
│                                  │
│           [Finish]               │
│                                  │
└──────────────────────────────────┘
```

## Entity Naming Convention

All sensors follow this pattern:
```
sensor.{station_id}_{measurement}

Examples:
- sensor.11406_temperature       (Praha-Libuš Temperature)
- sensor.11406_humidity          (Praha-Libuš Humidity)
- sensor.11723_temperature       (Brno-Tuřany Temperature)
```

## Sensor States

### Temperature Sensor
```
State: 10.5
Unit: °C
Attributes:
  - device_class: temperature
  - state_class: measurement
  - friendly_name: "Praha-Libuš Temperature"
```

### Humidity Sensor
```
State: 75
Unit: %
Attributes:
  - device_class: humidity
  - state_class: measurement
  - friendly_name: "Praha-Libuš Humidity"
```

## Automation Examples

### Send Alert on Temperature Drop
```yaml
automation:
  - alias: "Cold Weather Alert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.11406_temperature
        below: 0
    action:
      - service: notify.notify
        data:
          title: "⚠️ Freezing Temperature"
          message: "Outside temperature is {{ states('sensor.11406_temperature') }}°C"
```

### Track Daily Rain
```yaml
automation:
  - alias: "Daily Rain Summary"
    trigger:
      - platform: time
        at: "21:00:00"
    action:
      - service: notify.notify
        data:
          title: "🌧️ Today's Rain"
          message: "Total precipitation: {{ states('sensor.11406_precipitation') }}mm"
```

## Lovelace Card Examples

### Gauge Card
```yaml
type: gauge
entity: sensor.11406_humidity
min: 0
max: 100
severity:
  green: 40
  yellow: 30
  red: 20
needle: true
```

### Weather Glance Card
```yaml
type: glance
entities:
  - entity: sensor.11406_temperature
    icon: mdi:thermometer
  - entity: sensor.11406_humidity
    icon: mdi:water-percent
  - entity: sensor.11406_pressure
    icon: mdi:gauge
  - entity: sensor.11406_wind_speed
    icon: mdi:weather-windy
title: Current Weather
show_name: true
show_state: true
```

## Data Visualization Options

### 1. History Graph (Included)
- Multi-line graph showing trends
- Configurable time range (24h default)
- Auto-refresh every 60 seconds

### 2. Mini Graph Card (Optional)
Install from HACS for enhanced graphs:
```yaml
type: custom:mini-graph-card
entities:
  - sensor.11406_temperature
  - sensor.11406_humidity
hours_to_show: 48
line_width: 2
animate: true
```

### 3. ApexCharts Card (Optional)
Install from HACS for advanced charts:
```yaml
type: custom:apexcharts-card
graph_span: 7d
series:
  - entity: sensor.11406_temperature
    name: Temperature
  - entity: sensor.11406_humidity
    name: Humidity
    yaxis_id: humidity
```

---

🎉 **Your Home Assistant now displays real Czech weather data!**
