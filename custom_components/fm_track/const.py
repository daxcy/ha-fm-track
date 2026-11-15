"""Constants for the FM-Track integration."""

from datetime import timedelta

DOMAIN = "fm_track"

CONF_BASE_URL = "base_url"
CONF_VEHICLES = "vehicles"
CONF_USE_STREAM = "use_stream"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_TRIPS = "trips"
CONF_PLATFORM_EVENTS = "platform_events"

DEFAULT_USE_STREAM = True
DEFAULT_SCAN_INTERVAL = 5  # minutes
DEFAULT_TRIPS = True
DEFAULT_PLATFORM_EVENTS = True

TRIP_HISTORY = timedelta(days=7)
RECORD_FALLBACK_WINDOW = timedelta(hours=6)
BACKFILL_WINDOW = timedelta(days=7)
BACKFILL_MAX_PAGES = 3
GEOZONE_REFRESH = timedelta(hours=6)
STREAM_RETRY_MIN = 10
STREAM_RETRY_MAX = 300

EVENT_FM_TRACK = f"{DOMAIN}_event"

# Event types (bus event "fm_track_event" and the per-vehicle event entity)
EVENT_IGNITION_ON = "ignition_on"
EVENT_IGNITION_OFF = "ignition_off"
EVENT_TRIP_ENDED = "trip_ended"
EVENT_PLATFORM = "platform_event"
EVENT_TYPES = [EVENT_IGNITION_ON, EVENT_IGNITION_OFF, EVENT_TRIP_ENDED, EVENT_PLATFORM]

# Optional API features that may not be part of the customer's plan.
FEATURE_RECORDS = "records"
FEATURE_TRIPS = "trips"
FEATURE_EVENTS = "events"
FEATURE_GEOZONES = "geozones"
FEATURE_STREAM = "stream"
