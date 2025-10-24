from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
import traceback
from app.services.here_client import HereClient
from app.utils.cache_manager import CacheManager
from app.schemas.traffic import TrafficFlowResponse, RouteTrafficRequest, RouteTrafficResponse
from app.utils.logger import logger, log_exception

router = APIRouter(prefix="/traffic", tags=["traffic"])
here_client = HereClient()
cache_manager = CacheManager()

# --- GET Traffic Flow (HERE API v7) ---
@router.get("/flow", response_model=TrafficFlowResponse)
async def get_traffic_flow(
    lat: float = Query(..., ge=-90, le=90, description="Latitude"),
    lng: float = Query(..., ge=-180, le=180, description="Longitude"),
    radius: int = Query(1000, ge=100, le=5000, description="Radius in meters"),
    force_refresh: bool = Query(False, description="Force refresh from HERE API"),
):
    """
    Get real-time traffic flow for a given (lat, lng) using HERE API v7.
    """
    try:
        logger.info(f"📊 Traffic flow request - lat:{lat}, lng:{lng}, radius:{radius}m")
        
        cache_key = cache_manager.generate_cache_key("traffic_flow", lat=lat, lng=lng, radius=radius)
        # Try cache unless forced
        if not force_refresh:
            cached = cache_manager.get(cache_key)
            if cached:
                logger.info(f"✅ Cache hit for flow:{lat},{lng}")
                return TrafficFlowResponse(**cached)

        data = here_client.get_traffic_flow(lat, lng, radius)
        cache_manager.set(cache_key, data, ttl_minutes=5)
        logger.info(f"✅ Traffic flow data fetched and cached for {lat},{lng}")
        return TrafficFlowResponse(**data)
    except HTTPException:
        raise
    except Exception as e:
        log_exception(logger, f"❌ Error fetching traffic flow for {lat},{lng}", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch traffic flow: {str(e)}")

# --- GET Traffic Incidents (HERE API v7) ---
@router.get("/incidents")
async def get_traffic_incidents(
    lat: float = Query(..., ge=-90, le=90, description="Latitude"),
    lng: float = Query(..., ge=-180, le=180, description="Longitude"),
    radius: int = Query(5000, ge=100, le=10000, description="Radius in meters"),
):
    """
    Get current traffic incidents using HERE API v7.
    
    Returns a list of incidents (may be empty if no incidents or API unavailable for region).
    """
    try:
        logger.info(f"🚨 Traffic incidents request - lat:{lat}, lng:{lng}, radius:{radius}m")
        
        data = here_client.get_traffic_incidents(lat, lng, radius)
        
        logger.info(f"✅ Fetched {len(data) if isinstance(data, list) else 0} incidents for {lat},{lng}")
        
        # Return structured response
        return {
            "success": True,
            "location": {"lat": lat, "lng": lng, "radius": radius},
            "incident_count": len(data) if isinstance(data, list) else 0,
            "incidents": data if isinstance(data, list) else []
        }
    except Exception as e:
        log_exception(logger, f"⚠️ Error fetching incidents for {lat},{lng}", e)
        # Return empty incidents instead of failing completely
        return {
            "success": False,
            "location": {"lat": lat, "lng": lng, "radius": radius},
            "incident_count": 0,
            "incidents": [],
            "error": str(e),
            "message": "Unable to fetch incidents. This may be due to API limitations or region availability."
        }

# --- POST Route with Traffic (HERE Routing API v8) ---
@router.post("/route", response_model=RouteTrafficResponse)
async def get_route_with_traffic(
    request: RouteTrafficRequest,
):
    """
    Get optimal route with real-time traffic using HERE API v8.
    At least 2 waypoints required.
    """
    try:
        logger.info(f"🗺️ Route with traffic request - {len(request.waypoints)} waypoints")
        
        if len(request.waypoints) < 2:
            logger.warning(f"⚠️ Invalid request: Only {len(request.waypoints)} waypoint(s) provided")
            raise HTTPException(status_code=400, detail="At least 2 waypoints required")

        # Routing API v8 call
        waypoints = request.waypoints
        route_data = here_client.get_route_with_traffic(
            waypoints=waypoints,
            departure_time=request.departure_time
        )
        
        # Collect segment traffic (optional, per segment)
        route_segments = []
        for wp_start, wp_end in zip(waypoints, waypoints[1:]):
            segment_data = here_client.get_traffic_flow(wp_start["lat"], wp_start["lng"])
            route_segments.append(segment_data)
        
        logger.info(f"✅ Route calculated with {len(route_segments)} segments")
        return RouteTrafficResponse(route=route_data, segments=route_segments)
    except HTTPException:
        raise
    except Exception as e:
        log_exception(logger, "❌ Error getting route with traffic", e)
        raise HTTPException(status_code=500, detail=f"Failed to calculate route: {str(e)}")

# --- GET Cache Stats ---
@router.get("/cache-stats")
async def get_cache_stats():
    """
    Get cache statistics and performance metrics.
    """
    try:
        logger.info(f"📊 Cache stats request")
        
        stats = cache_manager.get_stats()
        
        logger.info(f"✅ Cache stats retrieved")
        return stats
    except Exception as e:
        log_exception(logger, "❌ Error getting cache stats", e)
        raise HTTPException(status_code=500, detail=f"Failed to get cache stats: {str(e)}")

# --- DELETE Cache (Maintenance) ---
@router.delete("/cache")
async def clear_cache(
    older_than_minutes: int = Query(60, ge=1, le=1440, description="Clear cache older than X minutes")
):
    """
    Clear expired cache entries (normally maintenance/admin only).
    """
    try:
        logger.info(f"🗑️ Clearing cache entries older than {older_than_minutes} minutes")
        
        count = cache_manager.clear_expired(minutes=older_than_minutes)
        
        logger.info(f"✅ Cleared {count} expired cache entries")
        return {"message": f"Cleared {count} expired cache entries", "count": count}
    except Exception as e:
        log_exception(logger, "❌ Error clearing cache", e)
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")

