"""
Full appointment sync script for Voice Booking System.
Fetches all existing appointments from Cliniko and syncs them to local DB and cache.
"""

import asyncio
import asyncpg
import httpx
import base64
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, date
import json

# Hardcoded Supabase DB URL
DB_URL = "postgresql://postgres.feywathteocancjzdgtf:seS!llyw3rd@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres"


class ClinikoAPI:
    """Cliniko API client for appointment syncing"""


    def __init__(self, api_key: str, shard: str, user_agent: str = "VoiceBookingSync/1.0"):
        self.base_url = f"https://api.{shard}.cliniko.com/v1"

        # Cliniko expects "Basic {base64(api_key:)}" - note the colon
        auth_string = f"{api_key}:"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')

        self.headers = {
            "Authorization": f"Basic {auth_b64}",
            "Accept": "application/json",
            "User-Agent": user_agent,
            "Content-Type": "application/json"
        }
        self.timeout = httpx.Timeout(30.0, connect=5.0)

    async def get_all_appointments(self, from_date: str = None, to_date: str = None) -> List[Dict]:
        """Get all appointments from Cliniko with optional date filtering"""
        all_appointments = []
        url = f"{self.base_url}/appointments"

        # Add date filters if provided
        params = {}
        if from_date:
            params['from'] = from_date
        if to_date:
            params['to'] = to_date

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while url:
                logger.info(f"Fetching appointments from: {url}")
                response = await client.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                data = response.json()

                appointments = data.get('appointments', [])
                all_appointments.extend(appointments)
                logger.info(f"Fetched {len(appointments)} appointments (total: {len(all_appointments)})")

                # Get next page URL
                links = response.links
                url = links.get('next', {}).get('url')

                # Clear params after first request (they're in the URL now)
                params = {}

        return all_appointments

    async def get_all_patients(self) -> List[Dict]:
        """Get all patients from Cliniko"""
        all_patients = []
        url = f"{self.base_url}/patients"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while url:
                logger.info(f"Fetching patients from: {url}")
                response = await client.get(url, headers=self.headers)
                response.raise_for_status()
                data = response.json()

                patients = data.get('patients', [])
                all_patients.extend(patients)
                logger.info(f"Fetched {len(patients)} patients (total: {len(all_patients)})")

                # Get next page URL
                links = response.links
                url = links.get('next', {}).get('url')

        return all_patients


class AppointmentSync:
    """Handles full appointment synchronization"""


    def __init__(self):
        self.db_url = DB_URL
        self.pool = None

    async def __aenter__(self):
        # Supabase requires SSL and specific connection parameters
        # Use very small pool size to avoid Supabase connection limits
        self.pool = await asyncpg.create_pool(
            self.db_url,
            ssl='require',  # Supabase requires SSL
            command_timeout=60,  # Increase timeout for large operations
            min_size=1,  # Very small pool to avoid Supabase limits
            max_size=2,  # Very small pool to avoid Supabase limits
            server_settings={
                'application_name': 'voice_booking_sync'
            }
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.pool:
            await self.pool.close()

    async def sync_all_appointments(self, clinic_id: str, cliniko_api: ClinikoAPI) -> Dict[str, Any]:
        """
        Perform full appointment sync for a clinic

        Args:
            clinic_id: The clinic ID to sync
            cliniko_api: Initialized ClinikoAPI instance

        Returns:
            Dict with sync results
        """
        start_time = datetime.now()
        results = {
            'clinic_id': clinic_id,
            'patients_synced': 0,
            'appointments_synced': 0,
            'appointments_updated': 0,
            'appointments_deleted': 0,
            'cache_entries_created': 0,
            'errors': [],
            'elapsed_seconds': 0
        }

        try:
            logger.info(f"Starting full appointment sync for clinic {clinic_id}")

            # Step 1: Get clinic info
            clinic_info = await self._get_clinic_info(clinic_id)
            if not clinic_info:
                raise Exception(f"Clinic {clinic_id} not found")

            logger.info(f"Syncing appointments for clinic: {clinic_info['clinic_name']}")

            # Step 2: Sync all patients first
            logger.info("Step 1: Syncing patients...")
            patients = await cliniko_api.get_all_patients()
            patient_count = await self._sync_patients(clinic_id, patients)
            results['patients_synced'] = patient_count
            logger.info(f"Synced {patient_count} patients")

            # Step 3: Sync all appointments
            logger.info("Step 2: Syncing appointments...")

            # Get appointments from last 30 days to future 90 days
            from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            to_date = (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d')

            appointments = await cliniko_api.get_all_appointments(from_date, to_date)
            appointment_results = await self._sync_appointments(clinic_id, appointments, from_date, to_date)

            results['appointments_synced'] = appointment_results['synced']
            results['appointments_updated'] = appointment_results['updated']
            results['appointments_deleted'] = appointment_results['deleted']

            logger.info(f"Synced {appointment_results['synced']} appointments")
            logger.info(f"Updated {appointment_results['updated']} appointments")
            logger.info(f"Deleted {appointment_results['deleted']} appointments")

            # Step 4: Warm availability cache for all practitioner-location combinations
            logger.info("Step 3: Warming availability cache...")
            cache_entries = await self._warm_availability_cache(clinic_id, cliniko_api)
            results['cache_entries_created'] = cache_entries

            # Calculate elapsed time
            elapsed = (datetime.now() - start_time).total_seconds()
            results['elapsed_seconds'] = elapsed

            logger.info(f"✅ Full appointment sync completed in {elapsed:.2f} seconds")

        except Exception as e:
            logger.error(f"Error during appointment sync: {str(e)}")
            results['errors'].append(str(e))

        return results

    async def _get_clinic_info(self, clinic_id: str) -> Optional[Dict[str, Any]]:
        """Get clinic information"""
        query = """
            SELECT clinic_id, clinic_name, cliniko_api_key, cliniko_shard, contact_email
            FROM clinics
            WHERE clinic_id = $1 AND active = true
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, clinic_id)
            return dict(row) if row else None

    async def _sync_patients(self, clinic_id: str, patients: List[Dict]) -> int:
        """Sync patients to local database"""
        count = 0

        for patient in patients:
            try:
                # Extract phone number (take first one if multiple)
                phone_number = None
                if patient.get('phone_numbers'):
                    phone_number = patient['phone_numbers'][0].get('number')

                # Extract email
                email = patient.get('email')

                await self.pool.execute("""
                    INSERT INTO patients (
                        patient_id, clinic_id, first_name, last_name,
                        phone_number, email, active
                    ) VALUES ($1, $2, $3, $4, $5, $6, true)
                    ON CONFLICT (patient_id)
                    DO UPDATE SET
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        phone_number = EXCLUDED.phone_number,
                        email = EXCLUDED.email,
                        updated_at = NOW()
                """,
                    str(patient['id']),
                    clinic_id,
                    patient.get('first_name', ''),
                    patient.get('last_name', ''),
                    phone_number,
                    email
                )
                count += 1

            except Exception as e:
                logger.error(f"Error syncing patient {patient.get('id')}: {e}")

        return count

    async def _sync_appointments(self, clinic_id: str, appointments: List[Dict], from_date: str = \
        None, to_date: str = None) -> Dict[str, int]:
        """Sync appointments to local database. Deletes local appointments not present in Cliniko."""
        results = {'synced': 0, 'updated': 0, 'deleted': 0}
        cliniko_ids = set()
        for appointment in appointments:
            try:
                # Extract IDs from links
                practitioner_id = \
                    self._extract_id_from_link(appointment.get('practitioner', {}).get('links', {}).get('sel'))
                patient_id = self._extract_id_from_link(appointment.get('patient', {}).get('links', {}).get('sel'))
                business_id = self._extract_id_from_link(appointment.get('business', {}).get('links', {}).get('sel'))
                appointment_type_id = \
                    self._extract_id_from_link(appointment.get('appointment_type', {}).get('links', {}).get('sel'))
                appointment_id = str(appointment['id'])
                cliniko_ids.add(appointment_id)
                if not all([practitioner_id, patient_id, business_id, appointment_type_id]):
                    logger.warning(f"Skipping appointment {appointment.get('id')} - missing required IDs")
                    continue
                # Parse appointment times
                starts_at = appointment.get('appointment_start')
                ends_at = appointment.get('appointment_end')
                if not starts_at:
                    logger.warning(f"Skipping appointment {appointment.get('id')} - no start time")
                    continue
                # Convert to datetime
                start_dt = datetime.fromisoformat(starts_at.replace('Z', '+00:00'))
                end_dt = \
                    datetime.fromisoformat(ends_at.replace('Z', '+00:00')) if ends_at else start_dt + timedelta(minutes=30)
                # Determine status
                status = 'booked'
                if appointment.get('cancelled_at'):
                    status = 'cancelled'
                elif appointment.get('completed_at'):
                    status = 'completed'
                elif appointment.get('deleted_at'):
                    status = 'deleted'
                # Insert or update appointment
                await self.pool.execute("""
                    INSERT INTO appointments (
                        appointment_id, clinic_id, patient_id, practitioner_id,
                        appointment_type_id, business_id, starts_at, ends_at,
                        status, notes, created_at, updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ON CONFLICT (appointment_id)
                    DO UPDATE SET
                        patient_id = EXCLUDED.patient_id,
                        practitioner_id = EXCLUDED.practitioner_id,
                        appointment_type_id = EXCLUDED.appointment_type_id,
                        business_id = EXCLUDED.business_id,
                        starts_at = EXCLUDED.starts_at,
                        ends_at = EXCLUDED.ends_at,
                        status = EXCLUDED.status,
                        notes = EXCLUDED.notes,
                        updated_at = EXCLUDED.updated_at
                """,
                    appointment_id,
                    clinic_id,
                    patient_id,
                    practitioner_id,
                    appointment_type_id,
                    business_id,
                    start_dt,
                    end_dt,
                    status,
                    appointment.get('notes', ''),
                    start_dt,  # created_at
                    datetime.now()  # updated_at
                )
                if status == 'deleted':
                    results['deleted'] += 1
                else:
                    results['synced'] += 1
            except Exception as e:
                logger.error(f"Error syncing appointment {appointment.get('id')}: {e}")
        # --- DELETE LOCAL APPOINTMENTS NOT IN CLINIKO ---
        if from_date and to_date:
            try:
                from_date_obj = datetime.strptime(from_date, "%Y-%m-%d").date()
                to_date_obj = datetime.strptime(to_date, "%Y-%m-%d").date()
                async with self.pool.acquire() as conn:
                    # Get all local appointment IDs in the window
                    rows = await conn.fetch(
                        """
                        SELECT appointment_id FROM appointments
                        WHERE clinic_id = $1
                          AND starts_at >= $2
                          AND starts_at <= $3
                        """,
                        clinic_id, from_date_obj, to_date_obj
                    )
                    local_ids = {str(row['appointment_id']) for row in rows}
                    to_delete = local_ids - cliniko_ids
                    if to_delete:
                        await conn.execute(
                            """
                            DELETE FROM appointments
                            WHERE clinic_id = $1
                              AND appointment_id = ANY($2::text[])
                            """,
                            clinic_id, list(to_delete)
                        )
                        logger.info(f"Deleted {len(to_delete)} local appointments not present in Cliniko.")
                        results['deleted'] += len(to_delete)
            except Exception as e:
                logger.error(f"Error deleting orphaned appointments: {e}")
        return results

    async def _warm_availability_cache(self, clinic_id: str, cliniko_api: ClinikoAPI) -> int:
        """Warm availability cache for all practitioner-location combinations"""
        cache_entries = 0

        # Get all active practitioner-business combinations
        query = """
            SELECT DISTINCT
                p.practitioner_id,
                pb.business_id,
                pat.appointment_type_id,
                p.first_name || ' ' || p.last_name as practitioner_name,
                b.business_name
            FROM practitioners p
            JOIN practitioner_businesses pb ON p.practitioner_id = pb.practitioner_id
            JOIN practitioner_appointment_types pat ON p.practitioner_id = pat.practitioner_id
            JOIN businesses b ON pb.business_id = b.business_id
            WHERE p.clinic_id = $1
              AND p.active = true
              AND b.clinic_id = $1
        """

        async with self.pool.acquire() as conn:
            combinations = await conn.fetch(query, clinic_id)

        logger.info(f"Warming cache for {len(combinations)} practitioner-location-service combinations")

        # For each combination, fetch availability for next 7 days
        for combo in combinations:
            try:
                practitioner_id = combo['practitioner_id']
                business_id = combo['business_id']
                appointment_type_id = combo['appointment_type_id']

                # Fetch availability for next 7 days
                for day_offset in range(0, 7):
                    check_date = date.today() + timedelta(days=day_offset)

                    # Get availability from Cliniko
                    from_date = check_date.isoformat()
                    to_date = check_date.isoformat()

                    try:
                        slots = await cliniko_api.get_available_times(
                            business_id,
                            practitioner_id,
                            appointment_type_id,
                            from_date,
                            to_date
                        )

                        # Cache the availability
                        await self._cache_availability(
                            clinic_id,
                            practitioner_id,
                            business_id,
                            check_date,
                            slots
                        )

                        cache_entries += 1

                    except Exception as e:
                        logger.debug(f"Could not fetch availability for {practitioner_id} at {business_id} on {check_date}: {e}")
                        continue

            except Exception as e:
                logger.error(f"Error warming cache for combination: {e}")

        return cache_entries

    async def _cache_availability(
        self,
        clinic_id: str,
        practitioner_id: str,
        business_id: str,
        check_date: date,
        slots: List[Dict]
    ):
        """Cache availability data"""
        query = """
            INSERT INTO availability_cache
            (clinic_id, practitioner_id, business_id, date, available_slots, expires_at)
            VALUES ($1, $2, $3, $4, $5, (NOW() AT TIME ZONE 'UTC') + INTERVAL '15 minutes')
            ON CONFLICT (practitioner_id, business_id, date)
            DO UPDATE SET
                available_slots = EXCLUDED.available_slots,
                cached_at = NOW() AT TIME ZONE 'UTC',
                expires_at = (NOW() AT TIME ZONE 'UTC') + INTERVAL '15 minutes',
                is_stale = false
        """

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    query,
                    clinic_id,
                    practitioner_id,
                    business_id,
                    check_date,
                    json.dumps(slots)
                )
        except Exception as e:
            logger.error(f"Failed to cache availability: {e}")


    def _extract_id_from_link(self, link: str) -> Optional[str]:
        """Extract ID from Cliniko API link"""
        if not link:
            return None

        # Extract ID from URL like /practitioners/123 or /patients/456
        parts = link.split('/')
        if len(parts) >= 2:
            return parts[-1]
        return None

async def sync_clinic_appointments(clinic_id: str):
    """Sync appointments for a specific clinic"""
    # Get clinic info
    db_url = DB_URL
    print(f"Connecting to database: {db_url.split('@')[1] if '@' in db_url else 'unknown'}")

    async with AppointmentSync() as sync:
        print("✅ Database connection established successfully")

        # Get clinic info to initialize Cliniko API
        clinic_info = await sync._get_clinic_info(clinic_id)
        if not clinic_info:
            raise Exception(f"Clinic {clinic_id} not found")

        # Initialize Cliniko API
        cliniko_api = ClinikoAPI(
            clinic_info['cliniko_api_key'],
            clinic_info['cliniko_shard'],
            clinic_info['contact_email']
        )

        # Perform sync
        results = await sync.sync_all_appointments(clinic_id, cliniko_api)

        # Print results
        print("\n=== APPOINTMENT SYNC RESULTS ===")
        print(f"Clinic: {clinic_info['clinic_name']}")
        print(f"Patients synced: {results['patients_synced']}")
        print(f"Appointments synced: {results['appointments_synced']}")
        print(f"Appointments updated: {results['appointments_updated']}")
        print(f"Appointments deleted: {results['appointments_deleted']}")
        print(f"Cache entries created: {results['cache_entries_created']}")

        if results['errors']:
            print(f"\n❌ Errors: {results['errors']}")
        else:
            print(f"\n✅ Completed successfully in {results['elapsed_seconds']:.2f} seconds")

        return results

async def sync_all_clinics():
    """Sync appointments for all active clinics"""
    db_url = DB_URL
    print(f"Connecting to database: {db_url.split('@')[1] if '@' in db_url else 'unknown'}")

    async with AppointmentSync() as sync:
        # Get all active clinics
        query = "SELECT clinic_id, clinic_name FROM clinics WHERE active = true"
        async with sync.pool.acquire() as conn:
            clinics = await conn.fetch(query)

        print(f"Found {len(clinics)} active clinics to sync")

        for clinic in clinics:
            print(f"\n{'='*50}")
            print(f"Syncing: {clinic['clinic_name']}")
            print(f"{'='*50}")

            try:
                await sync_clinic_appointments(clinic['clinic_id'])
            except Exception as e:
                print(f"❌ Failed to sync {clinic['clinic_name']}: {e}")
                import traceback
                print("Full error traceback:")
                print(traceback.format_exc())

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Sync specific clinic
        clinic_id = sys.argv[1]
        asyncio.run(sync_clinic_appointments(clinic_id))
    else:
        # Sync all clinics
        asyncio.run(sync_all_clinics())
