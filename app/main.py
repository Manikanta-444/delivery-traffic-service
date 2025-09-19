from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
import os
from dotenv import load_dotenv

try:
    from app.routes import traffic
    from app.database import engine, Base
except ModuleNotFoundError:
    import sys
    import os as _os
    sys.path.append(_os.path.dirname(_os.path.dirname(__file__)))
    from app.routes import traffic
    from app.database import engine, Base

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Traffic Service",
    description="Microservice for traffic data integration with HERE Maps API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(traffic.router, prefix="/api/v1")

@app.get("/")
async def root():
    return {
        "message": "Traffic Service is running",
        "status": "healthy",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "traffic-service",
        "here_api_configured": bool(os.getenv("HERE_API_KEY"))
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=True)
