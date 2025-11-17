"""Config flow for ČHMÚ Weather integration."""
import logging
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .api import get_stations_with_coords
from .const import CONF_STATION_ID, CONF_STATION_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


def calculate_distance(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Calculate distance between two coordinates using Haversine formula.
    
    Returns distance in kilometers.
    """
    from math import radians, sin, cos, sqrt, atan2
    
    # Earth radius in kilometers
    R = 6371.0
    
    lat1_rad = radians(lat1)
    lon1_rad = radians(lon1)
    lat2_rad = radians(lat2)
    lon2_rad = radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    
    distance = R * c
    return distance


def find_nearest_station(
    home_lat: float,
    home_lon: float,
    stations: Dict[str, Dict[str, Any]]
) -> Optional[str]:
    """Find the nearest station to home coordinates.
    
    Returns station ID of the nearest station.
    """
    if not stations:
        return None
    
    nearest_id = None
    nearest_distance = float('inf')
    
    for station_id, info in stations.items():
        distance = calculate_distance(
            home_lat,
            home_lon,
            info['latitude'],
            info['longitude']
        )
        if distance < nearest_distance:
            nearest_distance = distance
            nearest_id = station_id
    
    _LOGGER.debug(
        f"Nearest station: {nearest_id} at {nearest_distance:.1f} km"
    )
    
    return nearest_id


class ChmuConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ČHMÚ Weather."""
    
    VERSION = 1
    
    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}
        
        if user_input is not None:
            station_id = user_input[CONF_STATION_ID]
            
            # Fetch stations to get the name
            stations_with_coords = await self.hass.async_add_executor_job(
                get_stations_with_coords
            )
            station_info = stations_with_coords.get(station_id, {})
            station_name = station_info.get("name", f"Station {station_id}")
            
            # Check if already configured
            await self.async_set_unique_id(station_id)
            self._abort_if_unique_id_configured()
            
            return self.async_create_entry(
                title=f"{station_name} ({station_id})",
                data={
                    CONF_STATION_ID: station_id,
                    CONF_STATION_NAME: station_name,
                }
            )
        
        # Fetch available stations with coordinates
        try:
            stations_with_coords = await self.hass.async_add_executor_job(
                get_stations_with_coords
            )
            if not stations_with_coords:
                errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Failed to fetch stations")
            errors["base"] = "cannot_connect"
            stations_with_coords = {}
        
        # Get Home Assistant location to suggest nearest station
        home_lat = self.hass.config.latitude
        home_lon = self.hass.config.longitude
        
        suggested_station = None
        if home_lat and home_lon and stations_with_coords:
            suggested_station = find_nearest_station(
                home_lat,
                home_lon,
                stations_with_coords
            )
        
        # Build select options sorted by name
        select_options = [
            selector.SelectOptionDict(
                value=station_id,
                label=info['name'],
            )
            for station_id, info in sorted(
                stations_with_coords.items(),
                key=lambda x: x[1]["name"]
            )
        ]
        
        # Build schema with suggested default if available
        if suggested_station:
            data_schema = vol.Schema({
                vol.Required(
                    CONF_STATION_ID,
                    default=suggested_station
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=select_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        sort=False,
                    )
                )
            })
        else:
            data_schema = vol.Schema({
                vol.Required(CONF_STATION_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=select_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        sort=False,
                    )
                )
            })
        
        # Prepare description with nearest station info
        description_placeholders = {
            "stations_count": str(len(stations_with_coords)),
        }
        
        if suggested_station and suggested_station in stations_with_coords:
            station_info = stations_with_coords[suggested_station]
            distance = calculate_distance(
                home_lat,
                home_lon,
                station_info['latitude'],
                station_info['longitude']
            )
            description_placeholders["nearest_station"] = station_info['name']
            description_placeholders["distance"] = f"{distance:.1f}"
        else:
            description_placeholders["nearest_station"] = "N/A"
            description_placeholders["distance"] = "N/A"
        
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )
