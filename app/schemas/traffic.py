from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime
from typing import Optional, List
import uuid


class TrafficFlowRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90, description="Latitude coordinate")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude coordinate")
    radius: int = Field(1000, ge=100, le=5000, description="Search radius in meters")


class TrafficFlowResponse(BaseModel):
    """Response model for traffic flow API endpoint"""
    road_segment_id: str
    start_latitude: float
    start_longitude: float
    end_latitude: float
    end_longitude: float
    current_speed_kmph: float  # Changed from int to float for precision
    free_flow_speed_kmph: float  # Changed from int to float for precision
    confidence_level: float
    congestion_level: str
    congestion_factor: float

    class Config:
        from_attributes = True


class TrafficFlowDBResponse(BaseModel):
    """Database model response with cache metadata"""
    cache_id: uuid.UUID
    road_segment_id: str
    start_latitude: Decimal
    start_longitude: Decimal
    current_speed_kmph: int
    free_flow_speed_kmph: int
    confidence_level: Decimal
    congestion_level: str
    travel_time_minutes: Optional[int]
    distance_km: Optional[Decimal]
    cached_at: datetime
    expires_at: Optional[datetime]

    class Config:
        from_attributes = True


class RouteTrafficRequest(BaseModel):
    waypoints: List[dict] = Field(..., description="List of waypoints with lat/lng")
    departure_time: Optional[datetime] = None


class RouteTrafficResponse(BaseModel):
    route: dict
    segments: List[TrafficFlowResponse]


class TrafficIncidentResponse(BaseModel):
    incident_id: uuid.UUID
    here_incident_id: str
    incident_type: str
    severity: str
    description: Optional[str]
    start_latitude: Decimal
    start_longitude: Decimal
    impact_on_traffic: Optional[int]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
