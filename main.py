# main.py
"""Main FastAPI application for the Voice Booking System"""

from typing import Dict, Any, Optional
from datetime import datetime
from contextlib import asynccontextmanager
from payload_logger import payload_logger

import hmac
import hashlib
import time
import asyncpg
import os
import logging
from functools import lru_cache
import asyncio
import logging.config
from dotenv import load_dotenv

# FastAPI imports
from fastapi import FastAPI, Request, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware

# Import from our other modules
from cache_manager import CacheManager, IncrementalCacheSync
from tools.availability_router import router as availability_router
from tools.enhanced_availability_router import router as enhanced_availability_router
from tools.booking_router import router as booking_router
from tools.location_router import router as location_router
from tools.practitioner_router import router as practitioner_router
from tools.shared_dependencies import set_db_pool, set_cache_manager
from tools.sync_router import router as sync_router

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


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
        # Enhanced availability router - detailed logging to file
        'tools.enhanced_availability_router': {
            'level': 'DEBUG',
            'handlers': ['debug_file'],
            'propagate': False
        },
        # Enhanced parallel manager - detailed logging to file
        'tools.enhanced_parallel_manager': {
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
    """Application lifespan manager"""
    # Startup
    logger.info("Starting up Voice Booking System...")
    
    # Initialize database connection pool
    db.pool = await asyncpg.create_pool(
        os.getenv("DATABASE_URL"),
        min_size=10,
        max_size=25
    )
        
    # Initialize cache manager
    db.cache = CacheManager(db.pool)
    
    # Set up shared dependencies
    set_db_pool(db.pool)
    set_cache_manager(db.cache)
    
    logger.info("Voice Booking System started successfully")

    # Start background hourly sync task
    async def hourly_sync_loop():
        """Background task for hourly cache sync"""
        sync = IncrementalCacheSync(db.cache, db.pool)
        
        while True:
            try:
                # Wait 1 hour between syncs
                await asyncio.sleep(3600)  # 1 hour
                
                logger.info("=== STARTING HOURLY BACKGROUND SYNC ===")
                
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
                            cliniko,
                            force_full_sync=False  # Use incremental
                        )
                        
                        logger.info(f"Hourly sync for {clinic['clinic_id']}: {stats}")
                        
                    except Exception as e:
                        logger.error(f"Hourly sync failed for clinic {clinic['clinic_id']}: {e}")
                
            except Exception as e:
                logger.error(f"Hourly sync loop error: {e}")
                # Wait a bit before retrying on error
                await asyncio.sleep(60)

    settings = get_settings()
    if settings.environment != "development":
        asyncio.create_task(hourly_sync_loop())
        logger.info("Background hourly sync task started")
    else:
        logger.info("Skipping background sync in development mode")

    yield
    
    # Shutdown
    logger.info("Shutting down Voice Booking System...")
    if db.pool:
        await db.pool.close()
    logger.info("Voice Booking System shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Voice Booking System", 
    description="API for voice-based appointment booking with Cliniko integration",
    version="1.0.0",
    lifespan=lifespan
)

# Include tool routers
app.include_router(availability_router)
app.include_router(enhanced_availability_router)
app.include_router(booking_router)
app.include_router(location_router)
app.include_router(practitioner_router)
app.include_router(sync_router)

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
        
        # Get pool statistics
        pool_stats = {
            "min_size": db.pool.get_min_size(),
            "max_size": db.pool.get_max_size(),
            "size": db.pool.get_size(),
            "free_size": db.pool.get_free_size(),
            "used_connections": db.pool.get_size() - db.pool.get_free_size(),
            "utilization_percent": round((db.pool.get_size() - db.pool.get_free_size()) / db.pool.get_max_size() * 100, 2)
        }
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "2.0.0",
            "database": "connected",
            "pool_stats": pool_stats
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
    except Exception:
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