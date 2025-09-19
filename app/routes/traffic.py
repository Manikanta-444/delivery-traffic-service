import os
import traceback

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timedelta
import logging

from app.database import get_db
from app.models.traffic import TrafficCache, ApiUsageLog
from app.schemas.traffic import TrafficFlowResponse, RouteTrafficRequest, RouteTrafficResponse
from app.services.here_client import HereClient
from app.utils.cache_manager import CacheManager

router = APIRouter(prefix="/traffic", tags=["traffic"])
logger = logging.getLogger(__name__)

here_client = HereClient()
cache_manager = CacheManager()


@router.get("/flow", response_model=TrafficFlowResponse)
async def get_traffic_flow(
        lat: float = Query(..., ge=-90, le=90, description="Latitude"),
        lng: float = Query(..., ge=-180, le=180, description="Longitude"),
        radius: int = Query(1000, ge=100, le=5000, description="Radius in meters"),
        force_refresh: bool = Query(False, description="Force refresh from API"),
        background_tasks: BackgroundTasks = None,
        db: Session = Depends(get_db)
):
    """Get traffic flow data for a specific location"""

    try:
        # Generate cache key
        cache_key = cache_manager.generate_cache_key("traffic_flow", lat=lat, lng=lng, radius=radius)

        # Check Redis cache first (if not forcing refresh)
        if not force_refresh:
            cached_data = cache_manager.get(cache_key)
            if cached_data:
                logger.info(f"Cache hit for traffic flow: {lat}, {lng}")
                return TrafficFlowResponse(**cached_data)

        # Check database cache
        if not force_refresh:
            now = datetime.utcnow()
            db_cached = db.query(TrafficCache).filter(
                TrafficCache.start_latitude == lat,
                TrafficCache.start_longitude == lng,
                TrafficCache.expires_at > now
            ).first()

            if db_cached:
                logger.info(f"Database cache hit for traffic flow: {lat}, {lng}")
                # Store in Redis for faster access
                cache_data = {
                    "cache_id": str(db_cached.cache_id),
                    "road_segment_id": db_cached.road_segment_id,
                    "start_latitude": float(db_cached.start_latitude),
                    "start_longitude": float(db_cached.start_longitude),
                    "current_speed_kmph": db_cached.current_speed_kmph,
                    "free_flow_speed_kmph": db_cached.free_flow_speed_kmph,
                    "confidence_level": float(db_cached.confidence_level),
                    "congestion_level": db_cached.congestion_level,
                    "cached_at": db_cached.cached_at,
                    "expires_at": db_cached.expires_at
                }
                cache_manager.set(cache_key, cache_data, ttl_minutes=5)
                return TrafficFlowResponse(**cache_data)

        # Fetch from HERE API
        try:
            start_time = datetime.utcnow()
            print(f"radius: {radius}")
            here_data = here_client.get_traffic_flow(lat, lng, radius)
            print(f"here_data: {here_data}")
            response_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            # Determine congestion level
            speed = []
            free_flow = []
            confidence = []
            for location in here_data.get("results", []):
                location.get('currentFlow', {}).get('speed') and speed.append(location['currentFlow']['speed'])
                location.get('currentFlow', {}).get('freeFlow') and free_flow.append(location['currentFlow']['freeFlow'])
                location.get('currentFlow', {}).get('confidence') and confidence.append(location['currentFlow']['confidence'])
            current_speed = sum(speed) / len(speed) if speed else 0
            free_flow_speed = sum(free_flow) / len(free_flow) if free_flow else 0
            confidence_level = sum(confidence) / len(confidence) if confidence else 0
            print(f"current_speed: {current_speed}, free_flow_speed: {free_flow_speed}, confidence_level: {confidence_level}")
            congestion_level = here_client.determine_congestion_level(
                current_speed,
                free_flow_speed
            )
            print(f"congestion_level: {congestion_level}")

            # Create database record
            now = datetime.utcnow()
            expires_at = now + timedelta(minutes=int(os.getenv("CACHE_EXPIRY_MINUTES", 5)))

            traffic_cache = TrafficCache(
                road_segment_id=here_data["road_segment_id"],
                start_latitude=here_data["start_latitude"],
                start_longitude=here_data["start_longitude"],
                end_latitude=here_data["end_latitude"],
                end_longitude=here_data["end_longitude"],
                current_speed_kmph=here_data["current_speed_kmph"],
                free_flow_speed_kmph=here_data["free_flow_speed_kmph"],
                confidence_level=here_data["confidence_level"],
                congestion_level=congestion_level,
                cached_at=now,
                expires_at=expires_at
            )

            db.add(traffic_cache)
            db.commit()
            db.refresh(traffic_cache)

            # Log API usage
            if background_tasks:
                background_tasks.add_task(
                    log_api_usage,
                    "/traffic/flow",
                    "GET",
                    200,
                    response_time,
                    db
                )

            # Cache in Redis
            cache_data = {
                "cache_id": str(traffic_cache.cache_id),
                "road_segment_id": traffic_cache.road_segment_id,
                "start_latitude": float(traffic_cache.start_latitude),
                "start_longitude": float(traffic_cache.start_longitude),
                "current_speed_kmph": traffic_cache.current_speed_kmph,
                "free_flow_speed_kmph": traffic_cache.free_flow_speed_kmph,
                "confidence_level": float(traffic_cache.confidence_level),
                "congestion_level": traffic_cache.congestion_level,
                "cached_at": traffic_cache.cached_at,
                "expires_at": traffic_cache.expires_at
            }
            cache_manager.set(cache_key, cache_data, ttl_minutes=5)

            logger.info(f"Traffic flow data fetched and cached for: {lat}, {lng}")
            return TrafficFlowResponse(**cache_data)

        except Exception as e:
            logger.error(f"Error fetching traffic flow data: {e}")

            # Log API error
            if background_tasks:
                background_tasks.add_task(
                    log_api_usage,
                    "/traffic/flow",
                    "GET",
                    500,
                    0,
                    db,
                    error_message=str(e)
                )

            # If upstream returned rate limit, propagate a clear 429
            try:
                import requests
                from tenacity import RetryError
                # unwrap RetryError if present
                underlying = e
                if isinstance(e, RetryError) and e.last_attempt and e.last_attempt.exception():
                    underlying = e.last_attempt.exception()

                if isinstance(underlying, requests.exceptions.HTTPError) and getattr(underlying, 'response', None) is not None and underlying.response.status_code == 429:
                    raise HTTPException(status_code=429, detail="Rate limit reached for HERE API. Please retry after some time.")
            except Exception:
                pass

            raise HTTPException(status_code=500, detail=f"Failed to fetch traffic data: {str(e)}")
    except Exception:
        logger.error(f"Unexpected error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/route", response_model=RouteTrafficResponse)
async def get_route_with_traffic(
        request: RouteTrafficRequest,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db)
):
    """Get route with traffic information for multiple waypoints"""

    if len(request.waypoints) < 2:
        raise HTTPException(status_code=400, detail="At least 2 waypoints required")

    try:
        # Get route from HERE API
        route_data = here_client.get_route_with_traffic(
            request.waypoints,
            request.departure_time
        )

        # Get traffic data for each segment
        route_segments = []
        total_delay = 0

        for i in range(len(request.waypoints) - 1):
            start_wp = request.waypoints[i]

            # Get traffic flow for this segment
            segment_traffic = here_client.get_traffic_flow(
                start_wp["lat"],
                start_wp["lng"]
            )

            congestion_level = here_client.determine_congestion_level(
                segment_traffic["current_speed_kmph"],
                segment_traffic["free_flow_speed_kmph"]
            )

            segment_traffic["congestion_level"] = congestion_level
            route_segments.append(TrafficFlowResponse(**segment_traffic))

            # Calculate delay
            if congestion_level in ["HIGH", "SEVERE"]:
                delay_factor = {"HIGH": 1.5, "SEVERE": 2.0}[congestion_level]
                segment_delay = int(10 * (delay_factor - 1))  # 10 min base time
                total_delay += segment_delay

        response = RouteTrafficResponse(
            total_distance_km=route_data["total_distance_km"],
            total_time_minutes=route_data["total_time_minutes"],
            traffic_delay_minutes=max(route_data["traffic_delay_minutes"], total_delay),
            congestion_summary={
                "low": sum(1 for seg in route_segments if seg.congestion_level == "LOW"),
                "moderate": sum(1 for seg in route_segments if seg.congestion_level == "MODERATE"),
                "high": sum(1 for seg in route_segments if seg.congestion_level == "HIGH"),
                "severe": sum(1 for seg in route_segments if seg.congestion_level == "SEVERE")
            },
            route_segments=route_segments
        )

        return response

    except Exception as e:
        logger.error(f"Error getting route with traffic: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get route data: {str(e)}")


@router.delete("/cache")
async def clear_cache(
        older_than_minutes: int = Query(60, description="Clear cache older than X minutes"),
        db: Session = Depends(get_db)
):
    """Clear expired cache entries"""

    cutoff_time = datetime.utcnow() - timedelta(minutes=older_than_minutes)

    # Clear database cache
    deleted_count = db.query(TrafficCache).filter(
        TrafficCache.cached_at < cutoff_time
    ).delete()

    db.commit()

    logger.info(f"Cleared {deleted_count} expired cache entries")
    return {"message": f"Cleared {deleted_count} expired cache entries"}


def log_api_usage(endpoint: str, method: str, status_code: int, response_time: int,
                  db: Session, error_message: str = None):
    """Background task to log API usage"""
    try:
        log_entry = ApiUsageLog(
            api_endpoint=endpoint,
            request_type=method,
            response_status_code=status_code,
            response_time_ms=response_time,
            error_message=error_message
        )
        db.add(log_entry)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log API usage: {e}")
