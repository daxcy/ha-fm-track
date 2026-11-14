# FM-Track for Home Assistant

Unofficial Home Assistant integration for vehicles on the **FM-Track fleet management platform**
(`api.fm-track.com`, used with Ruptela GPS trackers). Not affiliated with or endorsed by Ruptela or FM-Track.

## Features

- `device_tracker` per vehicle (GPS position, speed, heading, altitude, satellites)
- Live updates via the *Object Coordinates Streaming API v2* (server-sent events), with polling of the
  *Object Last Coordinate API v2* every 5 minutes as a fallback
- Sensors and binary sensors that are created only when your vehicle actually reports the value:
  ignition, moving, odometer, fuel, EV battery/range/charging, RPM, temperatures, door lock, doors,
  trunk, hood, GSM signal, jamming, trip type
- Event `fm_track_event` with `type: ignition_on` / `ignition_off` for automations
- Configurable base URL for white-label instances of the platform
- English and Dutch translations

## Requirements

An API key for your FM-Track account. Depending on your provider you can generate one yourself or
request it from their support. The integration uses:

- `GET /objects-last-coordinate?version=2`
- `GET /object-coordinates-stream?version=2`

## Installation (HACS)

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/daxcy/ha-fm-track` as type *Integration*.
2. Install **FM-Track** and restart Home Assistant.
3. *Settings → Devices & services → Add integration → FM-Track*, enter your API key and pick vehicles.

## Privacy

The API key is stored in the Home Assistant config entry. It is sent as a query parameter (as required
by the API), so the integration never logs request URLs or raw HTTP errors.

## Status

Early development (0.x). The stream payload format is handled leniently until verified against live data.
