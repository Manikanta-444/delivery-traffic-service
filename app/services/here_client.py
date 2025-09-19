import time

import requests
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
import logging

logger = logging.getLogger(__name__)


class HereClient:
    def __init__(self):
        self.api_key = os.getenv("HERE_API_KEY")
        self.base_url = "https://data.traffic.hereapi.com/v7"
        self.routing_url = "https://router.hereapi.com/v8"

        if not self.api_key:
            raise ValueError("HERE_API_KEY environment variable is required")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(lambda e: not HereClient._is_rate_limit_error(e))
    )
    def get_traffic_flow(self, lat, lng, radius=1000):
        """Use HERE Traffic API v7 - the current supported version"""
        try:
            url = f"{self.base_url}/flow"

            params = {
                "apikey": self.api_key,
                "in": f"circle:{lat},{lng};r={radius}",  # New parameter format
                "locationReferencing": "shape",
                "units": "metric"
            }

            headers = {
                'Accept': 'application/json',
                'User-Agent': 'DeliveryRouteOptimizer/1.0'
            }

            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"HERE API traffic flow request failed: {e}")
            raise

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        try:
            import requests  # local import to avoid global namespace issues
            from tenacity import RetryError
            if isinstance(exc, requests.exceptions.HTTPError) and getattr(exc, 'response', None) is not None:
                return exc.response.status_code == 429
            if isinstance(exc, RetryError) and exc.last_attempt and exc.last_attempt.exception():
                inner = exc.last_attempt.exception()
                if isinstance(inner, requests.exceptions.HTTPError) and getattr(inner, 'response', None) is not None:
                    return inner.response.status_code == 429
        except Exception:
            return False
        return False

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_traffic_incidents(self, bbox: str) -> List[Dict]:
        """Get traffic incidents from HERE Maps API"""
        url = f"{self.base_url}/incidents.json"
        params = {
            "apiKey": self.api_key,
            "bbox": bbox,  # Format: "north,west;south,east"
            "responseattributes": "all"
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            logger.info(f"HERE API incidents request successful for bbox {bbox}")
            return self._parse_incidents_response(data)

        except requests.exceptions.RequestException as e:
            logger.error(f"HERE API incidents request failed: {e}")
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_route_with_traffic(self, waypoints: List[Dict], departure_time: Optional[datetime] = None) -> Dict:
        """Get route with traffic information"""
        url = f"{self.routing_url}/routes"

        # Format waypoints for HERE API
        origin = f"{waypoints[0]['lat']},{waypoints[0]['lng']}"
        destination = f"{waypoints[-1]['lat']},{waypoints[-1]['lng']}"

        params = {
            "apiKey": self.api_key,
            "origin": origin,
            "destination": destination,
            "transportMode": "car",
            "return": "summary,polyline,travelSummary",
            "departureTime": departure_time.isoformat() if departure_time else "now"
        }

        # Add intermediate waypoints if any
        if len(waypoints) > 2:
            via_points = [f"{wp['lat']},{wp['lng']}" for wp in waypoints[1:-1]]
            params["via"] = ";".join(via_points)

        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            logger.info(f"HERE API routing request successful")
            return self._parse_route_response(data)

        except requests.exceptions.RequestException as e:
            logger.error(f"HERE API routing request failed: {e}")
            raise

    @staticmethod
    def _parse_traffic_flow_response(data: Dict, lat: float, lng: float) -> Dict:
        """Parse HERE traffic flow response"""
        try:
            # Extract first flow item (closest to requested location)
            if "FLOW_ITEMS" in data and len(data["FLOW_ITEMS"]) > 0:
                flow_item = data["FLOW_ITEMS"][0]

                return {
                    "road_segment_id": flow_item.get("LI", f"unknown_{lat}_{lng}"),
                    "current_speed_kmph": int(flow_item.get("SU", 50)),
                    "free_flow_speed_kmph": int(flow_item.get("FF", 60)),
                    "congestion_factor": flow_item.get("CF", 1.0),
                    "confidence_level": flow_item.get("CN", 0.7),
                    "start_latitude": lat,
                    "start_longitude": lng,
                    "end_latitude": lat,  # Simplified for point traffic
                    "end_longitude": lng
                }
            else:
                # Return default values if no traffic data available
                return {
                    "road_segment_id": f"default_{lat}_{lng}",
                    "current_speed_kmph": 50,
                    "free_flow_speed_kmph": 60,
                    "congestion_factor": 1.0,
                    "confidence_level": 0.5,
                    "start_latitude": lat,
                    "start_longitude": lng,
                    "end_latitude": lat,
                    "end_longitude": lng
                }
        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Error parsing traffic flow response: {e}")
            raise

    @staticmethod
    def _parse_incidents_response(data: Dict) -> List[Dict]:
        """Parse HERE incidents response"""
        incidents = []
        try:
            if "INCIDENTS" in data:
                for incident in data["INCIDENTS"]:
                    incidents.append({
                        "here_incident_id": incident.get("INCIDENT_ID", ""),
                        "incident_type": incident.get("INCIDENT_TYPE", "UNKNOWN"),
                        "severity": incident.get("CRITICALITY", "LOW"),
                        "description": incident.get("SUMMARY", ""),
                        "start_latitude": float(
                            incident.get("LOCATION", {}).get("GEOLOC", {}).get("ORIGIN", {}).get("LATITUDE", 0)),
                        "start_longitude": float(
                            incident.get("LOCATION", {}).get("GEOLOC", {}).get("ORIGIN", {}).get("LONGITUDE", 0)),
                        "impact_on_traffic": incident.get("LENGTH", 0)
                    })
        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Error parsing incidents response: {e}")

        return incidents

    @staticmethod
    def _parse_route_response(data: Dict) -> Dict:
        """Parse HERE routing response"""
        try:
            sections = data.get("routes", [])[0].get("sections", [])
            length_m = 0
            duration_s = 0
            traffic_delay_s = 0
            polyline = ""
            if sections:
                for sec in sections:
                    summ = sec.get("summary", {})
                    length_m += int(summ.get("length", 0))
                    duration_s += int(summ.get("duration", 0))
                    traffic_delay_s += int(summ.get("trafficDelay", 0))
                polyline = sections[0].get("polyline", "")

            return {
                "total_distance_km": length_m / 1000,
                "total_time_minutes": duration_s // 60,
                "traffic_delay_minutes": traffic_delay_s // 60,
                "polyline": polyline,
                "departure_time": None,
                "arrival_time": None
            }
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Error parsing route response: {e}")
            raise

    @staticmethod
    def determine_congestion_level(current_speed: int, free_flow_speed: int) -> str:
        """Determine congestion level based on speed comparison"""
        if free_flow_speed == 0:
            return "UNKNOWN"

        speed_ratio = current_speed / free_flow_speed

        if speed_ratio >= 0.8:
            return "LOW"
        elif speed_ratio >= 0.6:
            return "MODERATE"
        elif speed_ratio >= 0.4:
            return "HIGH"
        else:
            return "SEVERE"
