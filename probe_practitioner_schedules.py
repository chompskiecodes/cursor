import asyncio
import asyncpg
import os
import csv
from datetime import date, timedelta, datetime
from dotenv import load_dotenv
import logging
from cliniko import ClinikoAPI
from cache_manager import CacheManager
from tools.enhanced_parallel_manager import EnhancedParallelManager
from models import ClinicData

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def get_days_to_check(conn, clinic_id, practitioner_id, business_id, future_start, max_days, force_full_scan=True):
    """
    Returns a list of days to check for a practitioner-business pair.
    If force_full_scan is True, returns all days in the window.
    Otherwise, queries practitioner_schedules for scheduled days only.
    """
    if force_full_scan:
        return [future_start + timedelta(days=i) for i in range(max_days)]
    else:
        # Query practitioner_schedules for this practitioner/business in the window
        rows = await conn.fetch(
            """
            SELECT date_checked FROM practitioner_schedules
            WHERE clinic_id = $1 AND practitioner_id = $2 AND business_id = $3
              AND date_checked >= $4 AND date_checked < $5
            """,
            clinic_id, practitioner_id, business_id, future_start, future_start + timedelta(days=max_days)
        )
        return [row['date_checked'] for row in rows]

async def main():
    # === CONFIGURATION FLAG ===
    # Set to True for initialization (full scan), False for production (optimized scan)
    force_full_scan = True
    max_days = 14
    # Load config from env
    DATABASE_URL = os.getenv("DATABASE_URL")
    CLINIKO_API_KEY = os.getenv("CLINIKO_API_KEY")
    CLINIKO_SHARD = os.getenv("CLINIKO_SHARD", "au1")
    CLINIC_NAME = os.getenv("CLINIC_NAME")
    CLINIC_PHONE = os.getenv("CLINIC_PHONE")
    CLINIKO_CONTACT_EMAIL = os.getenv("CLINIKO_CONTACT_EMAIL")

    # Connect to DB
    pool = await asyncpg.create_pool(DATABASE_URL)

    # Upsert clinic and get clinic_id (mimic initialize_clinic.py)
    async with pool.acquire() as conn:
        clinic_row = await conn.fetchrow("""
            INSERT INTO clinics (clinic_name, phone_number, cliniko_api_key, cliniko_shard, contact_email)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (phone_number) DO UPDATE SET
                clinic_name=EXCLUDED.clinic_name,
                cliniko_api_key=EXCLUDED.cliniko_api_key,
                cliniko_shard=EXCLUDED.cliniko_shard,
                contact_email=EXCLUDED.contact_email,
                updated_at=NOW()
            RETURNING *
        """, CLINIC_NAME, CLINIC_PHONE, CLINIKO_API_KEY, CLINIKO_SHARD, CLINIKO_CONTACT_EMAIL)
    clinic_id = clinic_row['clinic_id']
    logger.info(f"Using clinic_id: {clinic_id}")

    # Build ClinicData for EnhancedParallelManager
    async with pool.acquire() as conn:
        businesses = await conn.fetch("""
            SELECT business_id, business_name, is_primary FROM businesses WHERE clinic_id = $1
        """, clinic_id)
    businesses_list = [
        {
            'business_id': str(b['business_id']),
            'business_name': b['business_name'],
            'is_primary': b['is_primary']
        } for b in businesses
    ]
    clinic_timezone = clinic_row.get('timezone', 'Australia/Sydney')
    clinic = ClinicData(
        clinic_id=str(clinic_row['clinic_id']),
        clinic_name=clinic_row['clinic_name'],
        cliniko_api_key=clinic_row['cliniko_api_key'],
        cliniko_shard=clinic_row['cliniko_shard'],
        contact_email=clinic_row['contact_email'] or 'noreply@clinic.com',
        businesses=businesses_list,
        timezone=clinic_timezone
    )

    # Get all practitioner-business pairs
    pairs = await pool.fetch("""
        SELECT pb.practitioner_id, pb.business_id, p.first_name, p.last_name, b.business_name
        FROM practitioner_businesses pb
        JOIN practitioners p ON pb.practitioner_id = p.practitioner_id
        JOIN businesses b ON pb.business_id = b.business_id
        WHERE p.clinic_id = $1 AND b.clinic_id = $1
    """, clinic_id)

    # Initialize CacheManager and EnhancedParallelManager
    cache = CacheManager(pool)
    parallel_manager = EnhancedParallelManager(pool, cache, clinic)

    # Prepare search_criteria: one per practitioner-business pair, using the first appointment type
    cliniko = ClinikoAPI(CLINIKO_API_KEY, CLINIKO_SHARD, user_agent="probe_practitioner_schedules.py")
    search_criteria = []
    pair_info = {}  # Map (practitioner_id, business_id) to names for CSV
    raw_response_logged = False
    for pair in pairs:
        practitioner_id = pair['practitioner_id']
        business_id = pair['business_id']
        prac_name = f"{pair['first_name']} {pair['last_name']}"
        biz_name = pair['business_name']
        try:
            appt_types_response = await cliniko.get_all_pages(f"practitioners/{practitioner_id}/appointment_types")
        except Exception as e:
            logger.error(f"Error fetching appointment types for practitioner {practitioner_id}: {e}")
            continue
        # Expect the API response to be a dict with 'appointment_types' key
        if not isinstance(appt_types_response, dict) or 'appointment_types' not in appt_types_response:
            logger.error(f"Unexpected appointment types response for practitioner {practitioner_id}: {appt_types_response}")
            continue
        appt_types = appt_types_response['appointment_types']
        if not appt_types:
            logger.info(f"No appointment types for practitioner {prac_name} ({practitioner_id})")
            if not raw_response_logged:
                logger.info(f"Raw appointment types response for {practitioner_id}: {appt_types_response}")
                raw_response_logged = True
            continue
        appt_type = appt_types[0]  # Just one per user request
        appt_type_id = appt_type.get('id')
        if not appt_type_id:
            continue
        search_criteria.append({
            'practitioner_id': practitioner_id,
            'practitioner_name': prac_name,
            'appointment_type_id': appt_type_id,
            'service_name': appt_type.get('name', ''),
            'business_id': business_id,
            'business_name': biz_name
        })
        pair_info[(practitioner_id, business_id)] = (prac_name, biz_name)

    # Probe up to 11.5 months (350 days) in the future to avoid Cliniko API errors
    today = date.today()
    max_probe_days = 350  # 11.5 months
    max_days = min(max_days, max_probe_days)
    try:
        future_start = today + timedelta(days=max_probe_days)
    except ValueError:
        future_start = today + timedelta(days=max_probe_days)

    # Use EnhancedParallelManager to probe all pairs/days in parallel
    # We'll build a new search_criteria list for all (pair, day)
    expanded_criteria = []
    for criteria in search_criteria:
        practitioner_id = criteria['practitioner_id']
        business_id = criteria['business_id']
        # Only include days within the allowed window
        days = [today + timedelta(days=i) for i in range(max_days)]
        for day in days:
            if (day - today).days > max_probe_days:
                continue
            crit = criteria.copy()
            crit['check_date'] = day
            expanded_criteria.append((crit, day))

    # Run all (criteria, day) checks in parallel using the manager's _check_single_availability
    from functools import partial
    tasks = [partial(parallel_manager._check_single_availability, crit, day) for crit, day in expanded_criteria]
    results = await parallel_manager.execute_parallel_calls(tasks, timeout=90.0)

    # Aggregate results for CSV
    schedule_rows = []
    for result in results:
        if result.success and result.data:
            criteria = result.data['criteria']
            check_date = result.data['check_date']
            slots = result.data['slots']
            if slots:
                slot_times = [datetime.fromisoformat(s['appointment_start'].replace('Z', '+00:00')).time() for s in slots]
                earliest = min(slot_times) if slot_times else None
                latest = max(slot_times) if slot_times else None
                schedule_rows.append({
                    'practitioner_id': criteria['practitioner_id'],
                    'practitioner_name': criteria['practitioner_name'],
                    'business_id': criteria['business_id'],
                    'business_name': criteria['business_name'],
                    'day_of_week': check_date.weekday(),
                    'date_checked': check_date.isoformat(),
                    'earliest_time': earliest.strftime('%H:%M') if earliest else '',
                    'latest_time': latest.strftime('%H:%M') if latest else '',
                })
            else:
                # Not working that day
                schedule_rows.append({
                    'practitioner_id': criteria['practitioner_id'],
                    'practitioner_name': criteria['practitioner_name'],
                    'business_id': criteria['business_id'],
                    'business_name': criteria['business_name'],
                    'day_of_week': check_date.weekday(),
                    'date_checked': check_date.isoformat(),
                    'earliest_time': '',
                    'latest_time': '',
                })

    # === UPSERT INTO practitioner_schedules TABLE ===
    upsert_count = 0
    async with pool.acquire() as conn:
        for row in schedule_rows:
            if not row.get('practitioner_id') or not row.get('business_id') or not row.get('date_checked'):
                continue
            try:
                date_checked = row['date_checked']
                day_of_week = row['day_of_week']
                earliest_time = row['earliest_time'] if row['earliest_time'] else None
                latest_time = row['latest_time'] if row['latest_time'] else None
                await conn.execute(
                    """
                    INSERT INTO practitioner_schedules (
                        clinic_id, practitioner_id, business_id, day_of_week, earliest_time, latest_time, date_checked
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (clinic_id, practitioner_id, business_id, day_of_week, date_checked)
                    DO UPDATE SET
                        earliest_time = EXCLUDED.earliest_time,
                        latest_time = EXCLUDED.latest_time,
                        updated_at = NOW()
                    """,
                    clinic_id,
                    row['practitioner_id'],
                    row['business_id'],
                    int(day_of_week) if day_of_week != '' else None,
                    earliest_time,
                    latest_time,
                    date_checked
                )
                upsert_count += 1
            except Exception as e:
                logger.error(f"Failed to upsert schedule row: {row} Error: {e}")
    logger.info(f"Upserted {upsert_count} rows into practitioner_schedules table.")

    csv_file = f"practitioner_schedules_probe_{clinic_id}.csv"
    with open(csv_file, 'w', newline='') as f:
        fieldnames = ['practitioner_id', 'practitioner_name', 'business_id', 'business_name', 'day_of_week', 'date_checked', 'earliest_time', 'latest_time']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in schedule_rows:
            writer.writerow(row)
    logger.info(f"Wrote {len(schedule_rows)} schedule rows to {csv_file}")

    await pool.close()
    logger.info("Probed using 12 months (1 year) as the future window for all availability checks.")

if __name__ == "__main__":
    asyncio.run(main()) 
    
    