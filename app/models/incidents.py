from sqlalchemy import Column, String, DateTime, Float, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
import uuid
from datetime import datetime

Base = declarative_base()

class TrafficIncident(Base):
    __tablename__ = "traffic_incidents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    here_incident_id = Column(String, unique=True, nullable=False)
    type = Column(String)
    criticality = Column(String)
    description = Column(String)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    impact_on_traffic = Column(Float)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    geo_location = Column(JSON)  # Save raw geo object from HERE API, or adapt

    def __repr__(self):
        return f"<TrafficIncident(here_incident_id={self.here_incident_id}, type={self.type}, criticality={self.criticality})>"
