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
        # NEW: Traffic API v7 endpoint
        self.base_url = "https://data.traffic.hereapi.com/v7"
        # HERE Routing API v8 endpoint
        self.routing_url = "https://router.hereapi.com/v8"

    def get_traffic_flow(self, lat, lng, radius=1000):
        """Use HERE Traffic API v7 - the current supported version"""
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
        data = response.json()
        return self._parse_traffic_flow_response(data, lat, lng)

    def get_traffic_incidents(self, lat, lng, radius=5000):
        """Get traffic incidents using HERE Traffic API v7"""
        # HERE Traffic API v7 - Incidents endpoint
        url = "https://data.traffic.hereapi.com/v7/incidents"

        params = {
            "apiKey": self.api_key,  # Note: Capital K for incidents endpoint
            "locationReferencing": "shape",
            "in": f"circle:{lat},{lng};r={radius}"
        }

        headers = {
            'Accept': 'application/json',
            'User-Agent': 'DeliveryRouteOptimizer/1.0'
        }

        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            return self._parse_incidents_response(data)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                logger.warning(f"HERE Incidents API returned 400. Returning empty list. Location: {lat},{lng}")
                return []
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
    def get_route_with_traffic(self, waypoints: List[Dict], departure_time: Optional[datetime] = None) -> Dict:
        """Get route with traffic information - handles multiple waypoints by fetching segments"""
        url = f"{self.routing_url}/routes"

        # For multiple waypoints, fetch route for each segment and combine
        all_polylines = []
        total_length_m = 0
        total_duration_s = 0
        total_traffic_delay_s = 0

        logger.info(f"Fetching route for {len(waypoints)} waypoints ({len(waypoints)-1} segments)")

        for i in range(len(waypoints) - 1):
            origin = f"{waypoints[i]['lat']},{waypoints[i]['lng']}"
            destination = f"{waypoints[i+1]['lat']},{waypoints[i+1]['lng']}"

            params = {
                "apiKey": self.api_key,
                "origin": origin,
                "destination": destination,
                "transportMode": "car",
                "return": "summary,polyline,travelSummary",
                "departureTime": departure_time.isoformat() if departure_time else "now"
            }

            try:
                logger.info(f"Segment {i+1}/{len(waypoints)-1}: {origin} -> {destination}")
                
                response = requests.get(url, params=params, timeout=15)
                
                if response.status_code != 200:
                    logger.error(f"HERE API Error for segment {i+1}: {response.text}")
                    response.raise_for_status()

                data = response.json()
                
                # Extract data from this segment
                if "routes" in data and len(data["routes"]) > 0:
                    sections = data["routes"][0].get("sections", [])
                    if sections:
                        for sec in sections:
                            summ = sec.get("summary", {})
                            total_length_m += int(summ.get("length", 0))
                            total_duration_s += int(summ.get("duration", 0))
                            total_traffic_delay_s += int(summ.get("trafficDelay", 0))
                            
                            # Collect polyline from this section
                            section_polyline = sec.get("polyline", "")
                            if section_polyline:
                                all_polylines.append(section_polyline)
                
                logger.info(f"✅ Segment {i+1} fetched successfully")

            except requests.exceptions.RequestException as e:
                logger.error(f"Segment {i+1} failed: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"Response: {e.response.text}")
                raise

        logger.info(f"✅ All {len(waypoints)-1} segments fetched successfully")
        logger.info(f"Total polylines: {len(all_polylines)}")

        return {
            "total_distance_km": total_length_m / 1000,
            "total_time_minutes": total_duration_s // 60,
            "traffic_delay_minutes": total_traffic_delay_s // 60,
            "polyline": "",  # Empty since we have multiple sections
            "sections": all_polylines,  # Return all section polylines
            "departure_time": None,
            "arrival_time": None
        }

    @staticmethod
    def _parse_traffic_flow_response(data: Dict, lat: float, lng: float) -> Dict:
        """Parse HERE traffic flow response v7 format"""
        try:
            # Extract first result from v7 API (closest to requested location)
            if "results" in data and len(data["results"]) > 0:
                result = data["results"][0]
                current_flow = result.get("currentFlow", {})
                
                # Extract speed values
                current_speed = current_flow.get("speed", current_flow.get("speedUncapped", 50))
                free_flow_speed = current_flow.get("freeFlow", 60)
                jam_factor = current_flow.get("jamFactor", 0)
                confidence = current_flow.get("confidence", 0.7)
                
                # Calculate congestion factor from jam factor (0 = free flow, 10 = complete jam)
                congestion_factor = 1.0 + (jam_factor / 10.0)
                
                # Determine congestion level from speeds
                congestion_level = HereClient.determine_congestion_level(int(current_speed), int(free_flow_speed))

                return {
                    "road_segment_id": result.get("location", {}).get("linkId", f"unknown_{lat}_{lng}"),
                    "current_speed_kmph": round(float(current_speed), 2),  # Preserve precision
                    "free_flow_speed_kmph": round(float(free_flow_speed), 2),  # Preserve precision
                    "congestion_factor": round(congestion_factor, 2),
                    "congestion_level": congestion_level,
                    "confidence_level": round(confidence, 2),
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
                    "congestion_level": "LOW",
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
        """Parse HERE incidents response v7 format"""
        incidents = []
        try:
            # v7 API uses 'results' key instead of 'INCIDENTS'
            if "results" in data:
                for incident in data["results"]:
                    # Extract location coordinates
                    location = incident.get("location", {})
                    geometry = location.get("geometry", {})
                    coordinates = geometry.get("coordinates", [])
                    
                    # Get lat/lng from coordinates array [lng, lat]
                    lng = coordinates[0] if len(coordinates) > 0 else 0
                    lat = coordinates[1] if len(coordinates) > 1 else 0
                    
                    incidents.append({
                        "here_incident_id": incident.get("incidentDetails", {}).get("id", ""),
                        "incident_type": incident.get("incidentDetails", {}).get("type", "UNKNOWN"),
                        "severity": incident.get("incidentDetails", {}).get("criticality", "LOW"),
                        "description": incident.get("incidentDetails", {}).get("description", {}).get("value", ""),
                        "start_latitude": float(lat),
                        "start_longitude": float(lng),
                        "impact_on_traffic": incident.get("incidentDetails", {}).get("impactOnTraffic", 0)
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
            all_polylines = []
            
            if sections:
                for sec in sections:
                    summ = sec.get("summary", {})
                    length_m += int(summ.get("length", 0))
                    duration_s += int(summ.get("duration", 0))
                    traffic_delay_s += int(summ.get("trafficDelay", 0))
                    
                    # Collect polylines from all sections
                    section_polyline = sec.get("polyline", "")
                    if section_polyline:
                        all_polylines.append(section_polyline)
                
            # Combine all polylines (or use first one if only one section)
            polyline = all_polylines[0] if len(all_polylines) == 1 else ""
            
            return {
                "total_distance_km": length_m / 1000,
                "total_time_minutes": duration_s // 60,
                "traffic_delay_minutes": traffic_delay_s // 60,
                "polyline": polyline,
                "sections": all_polylines,  # Return all section polylines
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
