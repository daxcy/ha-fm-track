"""Constants for the FM-Track integration."""

from datetime import timedelta

DOMAIN = "fm_track"

CONF_BASE_URL = "base_url"
CONF_VEHICLES = "vehicles"
CONF_USE_STREAM = "use_stream"

DEFAULT_USE_STREAM = True
POLL_INTERVAL = timedelta(minutes=5)
STREAM_RETRY_MIN = 10
STREAM_RETRY_MAX = 300

EVENT_FM_TRACK = f"{DOMAIN}_event"
