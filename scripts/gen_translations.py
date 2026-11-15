"""Generate strings.json and translations/{en,nl}.json.

Run from the repository root:  python3 scripts/gen_translations.py
Each entry is (English, Dutch).
"""

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "fm_track"

CONFIG = {
    "step": {
        "user": {
            "title": ("FM-Track", "FM-Track"),
            "description": (
                "Enter the API key from your FM-Track platform. Only change the base URL if your provider uses its own domain.",
                "Vul de API-sleutel van je FM-Track-platform in. Wijzig de basis-URL alleen als je provider een eigen domein gebruikt.",
            ),
            "data": {"api_key": ("API key", "API-sleutel"), "base_url": ("Base URL", "Basis-URL")},
        },
        "vehicles": {
            "title": ("Vehicles", "Voertuigen"),
            "description": ("Choose which vehicles and assets to add.", "Kies welke voertuigen en assets je wilt toevoegen."),
            "data": {"vehicles": ("Vehicles", "Voertuigen")},
        },
        "reauth_confirm": {
            "title": ("Re-enter API key", "API-sleutel opnieuw invoeren"),
            "description": ("The API key is no longer accepted.", "De API-sleutel wordt niet meer geaccepteerd."),
            "data": {"api_key": ("API key", "API-sleutel")},
        },
    },
    "error": {
        "invalid_auth": ("The API key was rejected.", "De API-sleutel is geweigerd."),
        "cannot_connect": ("Could not reach the FM-Track API.", "Kan de FM-Track-API niet bereiken."),
        "no_vehicles": ("No vehicles found for this API key.", "Geen voertuigen gevonden voor deze API-sleutel."),
    },
    "abort": {
        "already_configured": ("This API key is already configured.", "Deze API-sleutel is al ingesteld."),
        "reauth_successful": ("API key updated.", "API-sleutel bijgewerkt."),
    },
}

OPTIONS = {
    "step": {
        "init": {
            "title": ("FM-Track options", "FM-Track-opties"),
            "data": {
                "scan_interval": ("Poll interval", "Poll-interval"),
                "use_stream": ("Live stream (real-time updates)", "Live stream (realtime updates)"),
                "trips": ("Trips (last trip, distance today)", "Ritten (laatste rit, km vandaag)"),
                "platform_events": ("Platform events (alarms from FM-Track)", "Platform-events (meldingen uit FM-Track)"),
            },
            "data_description": {
                "scan_interval": (
                    "How often to poll positions, full records and trips. The live stream delivers changes in between.",
                    "Hoe vaak posities, volledige records en ritten worden opgehaald. De live stream levert wijzigingen tussendoor.",
                ),
            },
        }
    }
}

BINARY_SENSOR = {
    "ignition": ("Ignition", "Contact"),
    "moving": ("Moving", "Rijdt"),
    "external_power": ("External power", "Externe voeding"),
    "charging": ("Charging", "Laden"),
    "lock": ("Door lock", "Deurslot"),
    "driver_door": ("Driver door", "Bestuurdersdeur"),
    "passenger_door": ("Passenger door", "Passagiersdeur"),
    "rear_left_door": ("Rear left door", "Achterdeur links"),
    "rear_right_door": ("Rear right door", "Achterdeur rechts"),
    "trunk": ("Trunk", "Kofferbak"),
    "hood": ("Hood", "Motorkap"),
    "window_front_left": ("Front left window", "Raam linksvoor"),
    "window_front_right": ("Front right window", "Raam rechtsvoor"),
    "window_rear_left": ("Rear left window", "Raam linksachter"),
    "window_rear_right": ("Rear right window", "Raam rechtsachter"),
    "sunroof": ("Sunroof", "Schuifdak"),
    "parking_brake": ("Parking brake", "Handrem"),
    "cruise_control": ("Cruise control", "Cruisecontrol"),
    "brake_pedal": ("Brake pedal", "Rempedaal"),
    "clutch_pedal": ("Clutch pedal", "Koppelingspedaal"),
    "panic": ("Panic button", "Paniekknop"),
    "rollover": ("Rollover", "Kanteling"),
    "jamming": ("GSM jamming", "GSM-stoorzender"),
    "gprs": ("Mobile data", "Mobiele data"),
    "gnss_antenna": ("GPS antenna", "GPS-antenne"),
    "digital_input_n": ("Digital input {index}", "Digitale ingang {index}"),
    "ot_digital_input_n": ("OT digital input {index}", "OT digitale ingang {index}"),
    "output_n": ("Output {index}", "Uitgang {index}"),
    "tire_problem": ("Tyre {index} problem", "Band {index} probleem"),
    "live_stream": ("Live stream", "Live stream"),
}

TRIP_TYPE_STATES = {
    "unknown": ("Unknown", "Onbekend"),
    "none": ("None", "Geen"),
    "private": ("Private", "Privé"),
    "business": ("Business", "Zakelijk"),
    "work": ("Commute", "Woon-werk"),
}

SENSOR = {
    "speed": ("Speed", "Snelheid"),
    "heading": ("Heading", "Richting"),
    "altitude": ("Altitude", "Hoogte"),
    "satellites": ("Satellites", "Satellieten"),
    "hdop": ("GPS precision (HDOP)", "GPS-precisie (HDOP)"),
    "last_update": ("Last update", "Laatste update"),
    "geozone": ("Geozone", "Geozone"),
    "trip_type": ("Trip type", "Ritsoort"),
    "odometer": ("Odometer", "Kilometerstand"),
    "ev_battery": ("Battery", "Accu"),
    "ev_range": ("Range", "Actieradius"),
    "electric_motor_temperature": ("Electric motor temperature", "Temperatuur elektromotor"),
    "dxp_battery": ("Traction battery", "Tractieaccu"),
    "dxp_battery_voltage": ("Traction battery voltage", "Spanning tractieaccu"),
    "dxp_battery_temperature": ("Traction battery temperature", "Temperatuur tractieaccu"),
    "supply_voltage": ("Supply voltage", "Voedingsspanning"),
    "tracker_battery": ("Tracker battery", "Batterij tracker"),
    "tracker_battery_voltage": ("Tracker battery voltage", "Spanning batterij tracker"),
    "tracker_battery_current": ("Tracker battery current", "Laadstroom batterij tracker"),
    "fuel_level": ("Fuel level", "Brandstof"),
    "fuel_level_percent": ("Fuel level (%)", "Brandstof (%)"),
    "fuel_used": ("Total fuel used", "Totaal brandstofverbruik"),
    "fuel_rate": ("Fuel rate", "Actueel verbruik"),
    "fuel_economy": ("Fuel economy", "Zuinigheid"),
    "rpm": ("Engine speed", "Toerental"),
    "coolant_temperature": ("Coolant temperature", "Koelvloeistoftemperatuur"),
    "engine_hours": ("Engine hours", "Motoruren"),
    "engine_load": ("Engine load", "Motorbelasting"),
    "accelerator_pedal": ("Accelerator pedal", "Gaspedaal"),
    "obd_dtc_count": ("Fault codes", "Foutcodes"),
    "distance_with_mil": ("Distance with check-engine light", "Afstand met storingslampje"),
    "ambient_temperature": ("Outside temperature", "Buitentemperatuur"),
    "service_distance": ("Distance to service", "Afstand tot onderhoud"),
    "service_hours": ("Hours to service", "Uren tot onderhoud"),
    "weight": ("Weight", "Gewicht"),
    "gsm_signal": ("GSM signal", "GSM-signaal"),
    "modem_temperature": ("Modem temperature", "Modemtemperatuur"),
    "device_temperature": ("Tracker temperature", "Temperatuur tracker"),
    "driver_id": ("Driver ID", "Bestuurder-ID"),
    "last_trip_distance": ("Last trip distance", "Laatste rit afstand"),
    "last_trip_duration": ("Last trip duration", "Laatste rit duur"),
    "last_trip_start": ("Last trip start", "Laatste rit start"),
    "last_trip_end": ("Last trip end", "Laatste rit einde"),
    "last_trip_start_address": ("Last trip origin", "Laatste rit vertrekadres"),
    "last_trip_end_address": ("Last trip destination", "Laatste rit bestemming"),
    "last_trip_fuel": ("Last trip fuel", "Laatste rit brandstof"),
    "distance_today": ("Distance today", "Afstand vandaag"),
    "trips_today": ("Trips today", "Ritten vandaag"),
    "temperature": ("Temperature", "Temperatuur"),
    "temperature_n": ("Temperature sensor {index}", "Temperatuursensor {index}"),
    "bt_temperature_n": ("Bluetooth temperature {index}", "Bluetooth-temperatuur {index}"),
    "ot_temperature_n": ("OT temperature {index}", "OT-temperatuur {index}"),
    "tk_temperature_n": ("Thermo King temperature {index}", "Thermo King-temperatuur {index}"),
    "humidity_n": ("Humidity {index}", "Luchtvochtigheid {index}"),
    "axle_weight_n": ("Axle {index} weight", "Asgewicht {index}"),
    "analog_input_n": ("Analog input {index}", "Analoge ingang {index}"),
    "frequency_input_n": ("Frequency input {index}", "Frequentie-ingang {index}"),
    "custom_input_n": ("Custom input {index}", "Eigen invoer {index}"),
    "tire_pressure": ("Tyre {index} pressure", "Band {index} druk"),
    "tire_temperature": ("Tyre {index} temperature", "Band {index} temperatuur"),
}

EVENT_TYPES = {
    "ignition_on": ("Ignition on", "Contact aan"),
    "ignition_off": ("Ignition off", "Contact uit"),
    "trip_ended": ("Trip ended", "Rit beëindigd"),
    "platform_event": ("Platform event", "Platform-melding"),
}


def pick(tree, lang: int):
    if isinstance(tree, tuple):
        return tree[lang]
    return {k: pick(v, lang) for k, v in tree.items()}


def build(lang: int) -> dict:
    entity = {
        "binary_sensor": {k: {"name": v[lang]} for k, v in BINARY_SENSOR.items()},
        "sensor": {k: {"name": v[lang]} for k, v in SENSOR.items()},
        "event": {
            "vehicle_event": {
                "name": ("Event", "Gebeurtenis")[lang],
                "state_attributes": {
                    "event_type": {"state": {k: v[lang] for k, v in EVENT_TYPES.items()}}
                },
            }
        },
    }
    entity["sensor"]["trip_type"]["state"] = {k: v[lang] for k, v in TRIP_TYPE_STATES.items()}
    entity["sensor"]["geozone"]["state"] = {"none": ("Outside geozones", "Buiten geozones")[lang]}
    return {"config": pick(CONFIG, lang), "options": pick(OPTIONS, lang), "entity": entity}


def write(path: pathlib.Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    write(ROOT / "strings.json", build(0))
    write(ROOT / "translations" / "en.json", build(0))
    write(ROOT / "translations" / "nl.json", build(1))
    print("translations written")
