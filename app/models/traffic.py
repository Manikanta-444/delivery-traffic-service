from sqlalchemy import Column, String, DateTime, Integer, Numeric, Index, Text
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime

from sqlalchemy.sql.sqltypes import Boolean

from app.database import Base

class TrafficCache(Base):
    __tablename__ = 'traffic_cache'
    __table_args__ = (
        Index('idx_road_segment', 'road_segment_id'),
        Index('idx_location', 'start_latitude', 'start_longitude'),
        Index('idx_expires_at', 'expires_at'),
        {'schema': 'delivery_traffic_service'}
    )

    cache_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    road_segment_id = Column(String(255), nullable=False)
    start_latitude = Column(Numeric(10, 8), nullable=False)
    start_longitude = Column(Numeric(11, 8), nullable=False)
    end_latitude = Column(Numeric(10, 8), nullable=False)
    end_longitude = Column(Numeric(11, 8), nullable=False)
    current_speed_kmph = Column(Integer)
    free_flow_speed_kmph = Column(Integer)
    confidence_level = Column(Numeric(3, 2))  # 0.0 to 1.0
    congestion_level = Column(String(20))  # LOW, MODERATE, HIGH, SEVERE
    travel_time_minutes = Column(Integer)
    distance_km = Column(Numeric(8, 3))
    cached_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)

class TrafficIncident(Base):
    __tablename__ = 'traffic_incidents'
    __table_args__ = (
        # {'schema': 'delivery_traffic_service'},
        Index('idx_here_incident', 'here_incident_id'),
        Index('idx_location_incident', 'start_latitude', 'start_longitude'),
        Index('idx_severity', 'severity'),
        {'schema': 'delivery_traffic_service'},
    )

    incident_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    here_incident_id = Column(String(255), unique=True, nullable=False)
    incident_type = Column(String(50), nullable=False)  # ACCIDENT, CONSTRUCTION, ROAD_CLOSURE
    severity = Column(String(20), nullable=False)  # LOW, MODERATE, HIGH, CRITICAL
    description = Column(Text)
    start_latitude = Column(Numeric(10, 8), nullable=False)
    start_longitude = Column(Numeric(11, 8), nullable=False)
    end_latitude = Column(Numeric(10, 8))
    end_longitude = Column(Numeric(11, 8))
    start_time = Column(DateTime)
    estimated_end_time = Column(DateTime)
    impact_on_traffic = Column(Integer)  # Delay in minutes
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ApiUsageLog(Base):
    __tablename__ = 'api_usage_logs'
    __table_args__ = (
        # {'schema': 'delivery_traffic_service'},
        Index('idx_endpoint_date', 'api_endpoint', 'created_at'),
        Index('idx_status_code', 'response_status_code'),
        {'schema': 'delivery_traffic_service'},
    )

    log_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    api_endpoint = Column(String(255), nullable=False)
    request_type = Column(String(10), nullable=False)
    response_status_code = Column(Integer)
    request_count = Column(Integer, default=1)
    response_time_ms = Column(Integer)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
