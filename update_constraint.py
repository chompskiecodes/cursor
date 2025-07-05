#!/usr/bin/env python3
"""Update voice_bookings constraint to include 'reschedule' action"""

import asyncio
import asyncpg
import os
from database import update_voice_bookings_constraint

async def main():
    """Update the database constraint"""
    # Get database connection from environment
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("Error: DATABASE_URL environment variable not set")
        return
    
    try:
        # Create connection pool
        pool = await asyncpg.create_pool(database_url)
        
        # Update the constraint
        await update_voice_bookings_constraint(pool)
        
        print("✓ Successfully updated voice_bookings constraint")
        
    except Exception as e:
        print(f"Error updating constraint: {e}")
    finally:
        if 'pool' in locals():
            await pool.close()

if __name__ == "__main__":
    asyncio.run(main()) 