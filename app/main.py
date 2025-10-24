from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

try:
    from app.routes import traffic
    from app.database import engine, Base
    from app.utils.logger import logger
except ModuleNotFoundError:
    import sys
    import os as _os
    sys.path.append(_os.path.dirname(_os.path.dirname(__file__)))
    from app.routes import traffic
    from app.database import engine, Base
    from app.utils.logger import logger

# Load environment variables
load_dotenv()

logger.info("🚀 Starting Traffic Service...")

# Create tables
try:
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables created successfully")
except Exception as e:
    logger.error(f"❌ Failed to create database tables: {str(e)}")
    raise

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

@app.on_event("startup")
async def startup_event():
    logger.info("✅ Traffic Service started successfully")
    logger.info(f"📍 Service URL: http://0.0.0.0:8002")
    logger.info(f"📚 API Docs: http://localhost:8002/docs")
    logger.info(f"🗺️ HERE API configured: {bool(os.getenv('HERE_API_KEY'))}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Traffic Service shutting down...")

@app.get("/")
async def root():
    logger.debug("Root endpoint called")
    return {
        "message": "Traffic Service is running",
        "status": "healthy",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    logger.debug("Health check endpoint called")
    try:
        here_api_configured = bool(os.getenv("HERE_API_KEY"))
        return {
            "status": "healthy",
            "service": "traffic-service",
            "here_api_configured": here_api_configured
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "service": "traffic-service",
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=True)
