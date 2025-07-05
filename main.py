# main.py (Updated with extracted error handling and modularized)
from dotenv import load_dotenv
load_dotenv()  

from fastapi import FastAPI, Request, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, Optional, Union
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo
from payload_logger import payload_logger

import hmac
import hashlib
import time
import asyncpg
import httpx
import os
import logging
from functools import lru_cache
import asyncio
import logging.config

# Import from our other modules
from database import (
    get_clinic_by_dialed_number,
    log_voice_booking,
    get_location_by_name
)
from cliniko import ClinikoAPI
from models import (
    ClinicData,
    LocationResolverRequest,
    ConfirmLocationRequest
)
from utils import (
    normalize_phone, mask_phone
)

# === Add new imports for caching and location resolution ===
from cache_manager import CacheManager, IncrementalCacheSync
from location_resolver import LocationResolver
from tools.timezone_utils import get_clinic_timezone
from tools.shared_dependencies import set_db_pool, set_cache_manager

# Import tool routers
from tools.location_router import router as location_resolver_router, router as confirm_location_router
from tools.availability_router import router as find_next_available_router, router as availability_checker_router
from tools.booking_router import router as appointment_handler_router, router as cancel_appointment_router
from tools.practitioner_router import router as get_practitioner_services_router, router as get_practitioner_info_router, router as get_location_practitioners_router, router as get_available_practitioners_router

# Import timezone utils
from tools.timezone_utils import convert_utc_to_local, format_time_for_voice

app = FastAPI()

# Define logging configuration
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        },
        'detailed': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'INFO',
            'formatter': 'standard',
            'stream': 'ext://sys.stdout'
        },
        'debug_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'level': 'DEBUG',
            'formatter': 'detailed',
            'filename': 'debug.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 3
        }
    },
    'loggers': {
        # Root logger
        '': {
            'level': 'INFO',
            'handlers': ['console']
        },
        # Detailed booking flow logging - only to file
        'tools.booking_router.flow': {
            'level': 'DEBUG',
            'handlers': ['debug_file'],
            'propagate': False
        },
        # Reduce Cliniko API logging
        'cliniko': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': False
        },
        # Cache manager - reduce verbosity
        'cache_manager': {
            'level': 'WARNING',
            'handlers': ['console'],
            'propagate': False
        },
        # HTTP request logging
        'httpx': {
            'level': 'WARNING',
            'handlers': ['console'],
            'propagate': False
        }
    }
}

# Apply configuration based on environment
if os.getenv('ENVIRONMENT') == 'development':
    # In development, show more details
    LOGGING_CONFIG['handlers']['console']['level'] = 'DEBUG'
    LOGGING_CONFIG['loggers']['']['level'] = 'DEBUG'
else:
    # In production, only show important messages
    LOGGING_CONFIG['handlers']['console']['level'] = 'INFO'
    LOGGING_CONFIG['loggers']['httpx']['level'] = 'ERROR'

# Apply the configuration
logging.config.dictConfig(LOGGING_CONFIG)

logger = logging.getLogger(__name__)

# === Configuration ===
class Settings:
    """Application settings from environment variables"""
    def __init__(self):
        supabase_db_url = os.environ.get("DATABASE_URL")
        if False:
            self.database_url = supabase_db_url
        else:
            self.database_url = os.environ.get("DATABASE_URL", "postgresql://user:pass@localhost/voice_booking")
            
        self.supabase_url = os.environ.get("SUPABASE_URL", "https://xdnjnrrnehximkxteidq.supabase.co")
        self.supabase_key = os.environ.get("SUPABASE_KEY")
        self.api_key = os.environ.get("API_KEY", "development-key")
        self.environment = os.environ.get("ENVIRONMENT", "development")
        self.default_timezone = os.environ.get("DEFAULT_TIMEZONE", "Australia/Sydney")
        
@lru_cache()
def get_settings():
    return Settings()

# === Database Connection Pool ===
class Database:
    pool: asyncpg.Pool = None
    cache: CacheManager = None  # Add cache manager

db = Database()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    settings = get_settings()
    logger.info(f"Starting Voice Booking System in {settings.environment} mode")
    
    try:
        db.pool = await asyncpg.create_pool(
            settings.database_url, 
            min_size=5,
            max_size=20,
            command_timeout=10,
            server_settings={
                'jit': 'off'
            }
        )
        logger.info("Database connected successfully")
        
        # Initialize cache manager
        db.cache = CacheManager(db.pool)
        logger.info("Cache manager initialized")
        
        # Set up dependencies for tools modules
        set_db_pool(db.pool)
        set_cache_manager(db.cache)
        
        # Start background incremental sync task
        async def incremental_sync_loop():
            """Background task for incremental cache sync"""
            sync = IncrementalCacheSync(db.cache, db.pool)
            
            while True:
                try:
                    # Wait 5 minutes between syncs
                    await asyncio.sleep(300)  # 5 minutes
                    
                    # Get all active clinics
                    async with db.pool.acquire() as conn:
                        clinics = await conn.fetch("""
                            SELECT clinic_id, cliniko_api_key, cliniko_shard, contact_email
                            FROM clinics
                            WHERE is_active = true
                        """)
                    
                    for clinic in clinics:
                        try:
                            from cliniko import ClinikoAPI
                            
                            # Create Cliniko API instance
                            cliniko = ClinikoAPI(
                                clinic['cliniko_api_key'],
                                clinic['cliniko_shard'],
                                clinic.get('contact_email', 'support@example.com')
                            )
                            
                            # Run incremental sync
                            stats = await sync.sync_appointments_incremental(
                                clinic['clinic_id'],
                                cliniko
                            )
                            
                            logger.info(f"Background sync for {clinic['clinic_id']}: {stats}")
                            
                        except Exception as e:
                            logger.error(f"Background sync failed for clinic {clinic['clinic_id']}: {e}")
                    
                except Exception as e:
                    logger.error(f"Incremental sync loop error: {e}")
                    # Wait a bit before retrying
                    await asyncio.sleep(60)
        
        # Start the background sync task
        if settings.environment != "development":
            asyncio.create_task(incremental_sync_loop())
            logger.info("Background incremental sync task started")
        else:
            logger.info("Skipping background sync in development mode")
        
        # Optional: Start cache maintenance task if you have one
        # asyncio.create_task(cache_maintenance_task(db.cache))
        
    except Exception as e:
        logger.error(f"Failed to connect to database: {str(e)}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await db.pool.close()
    logger.info("Database disconnected")

app = FastAPI(
    title="Voice Booking System", 
    version="2.0.0", 
    lifespan=lifespan,
    docs_url="/docs" if get_settings().environment != "production" else None,
    redoc_url="/redoc" if get_settings().environment != "production" else None
)

# Include tool routers
app.include_router(location_resolver_router)
app.include_router(confirm_location_router)
app.include_router(find_next_available_router)
app.include_router(availability_checker_router)
app.include_router(appointment_handler_router)
app.include_router(cancel_appointment_router)
app.include_router(get_practitioner_services_router)
app.include_router(get_practitioner_info_router)
app.include_router(get_location_practitioners_router)
app.include_router(get_available_practitioners_router)

# === CORS Configuration ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Authentication ===
async def verify_api_key(x_api_key: str = Header(None)) -> bool:
    """Verify API key for authentication"""
    settings = get_settings()
    
    if settings.environment == "development" and not x_api_key:
        return True
        
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")
        
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
        
    return True

# === Monitoring and Health Endpoints ===

@app.get("/cache-stats")
async def get_cache_stats(
    authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get cache statistics for monitoring"""
    try:
        stats = await db.cache.get_cache_stats()
        hit_rates = await db.cache.get_hit_rates(24)
        
        return {
            "success": True,
            "stats": stats,
            "hit_rates": hit_rates,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting cache stats: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check database connection
        async with db.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "2.0.0",
            "database": "connected"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
            "database": "disconnected"
        }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Voice Booking System",
        "version": "2.0.0",
        "endpoints": [
            "/appointment-handler",
            "/availability-checker",
            "/cancel-appointment",
            "/location-resolver",
            "/confirm-location",
            "/health",
            "/cache-stats",
            "/docs" if get_settings().environment != "production" else None
        ]
    }

# === ElevenLabs Webhook Handlers ===

ELEVENLABS_WEBHOOK_SECRET = os.environ.get("ELEVENLABS_WEBHOOK_SECRET")

async def verify_elevenlabs_signature(request: Request, secret: str) -> bool:
    """Verify ElevenLabs HMAC signature"""
    signature_header = request.headers.get("ElevenLabs-Signature")
    if not signature_header:
        return False
    
    try:
        parts = dict(part.split("=") for part in signature_header.split(","))
        timestamp = parts.get("t")
        signature = parts.get("v1")
        
        if not timestamp or not signature:
            return False
        
        # Check timestamp (5 min window)
        if abs(int(time.time()) - int(timestamp)) > 300:
            return False
        
        body = await request.body()
        payload = f"{timestamp}.{body.decode('utf-8')}"
        expected = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected)
    except:
        return False

async def get_clinic_by_agent_id(agent_id: str, pool: asyncpg.Pool) -> Optional[Dict[str, Any]]:
    """Get clinic by ElevenLabs agent ID"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM clinics WHERE elevenlabs_agent_id = $1",
            agent_id
        )
        return dict(row) if row else None

@app.post("/post-call-webhook")
async def handle_post_call_webhook(request: Request) -> Dict[str, Any]:
    """Handle post-call webhook from ElevenLabs"""
    # Verify signature if secret is set
    if ELEVENLABS_WEBHOOK_SECRET:
        if not await verify_elevenlabs_signature(request, ELEVENLABS_WEBHOOK_SECRET):
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    body = await request.json()
    payload_logger.log_payload("/post-call-webhook", body)
    
    # Log the call
    logger.info(f"Post-call webhook: {body.get('conversation_id')}")
    
    # Get clinic if agent_id present
    agent_id = body.get("agent_id")
    if agent_id:
        clinic = await get_clinic_by_agent_id(agent_id, db.pool)
        if clinic:
            logger.info(f"Call for clinic: {clinic['clinic_name']}")
    
    # Extract call data
    call_data = body.get('data', {})
    analysis = call_data.get('analysis', {})
    
    # Log success/failure
    if analysis.get('call_successful'):
        logger.info("Call completed successfully")
    else:
        logger.warning(f"Call failed: {analysis.get('transcript_summary', 'Unknown')}")
    
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    
    # Get port from environment variable
    port = int(os.environ.get("PORT", 8000))
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=port,
        log_level="info",
        access_log=True
    )