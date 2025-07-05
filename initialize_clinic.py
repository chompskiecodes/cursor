# initialize_clinic.py
import asyncio
import asyncpg
import httpx
from typing import Dict, List, Optional
import os
from dotenv import load_dotenv
import logging
from datetime import datetime

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ClinikoAPI:
    """Minimal Cliniko API client for initialization"""
    def __init__(self, api_key: str, shard: str):
        self.base_url = f"https://api.{shard}.cliniko.com/v1"
        
        # Cliniko expects "Basic {base64(api_key:)}" - note the colon
        import base64
        auth_string = f"{api_key}:"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        self.headers = {
            "Authorization": f"Basic {auth_b64}",
            "Accept": "application/json",
            "User-Agent": "VoiceBookingInit/1.0"
        }
        self.timeout = httpx.Timeout(30.0)    
    async def get_all_pages(self, endpoint: str) -> List[Dict]:
        """Get all pages of results from an endpoint"""
        all_items = []
        url = f"{self.base_url}/{endpoint}"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while url:
                response = await client.get(url, headers=self.headers)
                response.raise_for_status()
                data = response.json()
                
                # Extract items based on endpoint
                if 'businesses' in endpoint:
                    all_items.extend(data.get('businesses', []))
                elif 'practitioners' in endpoint and 'appointment_types' not in endpoint:
                    all_items.extend(data.get('practitioners', []))
                elif 'billable_items' in endpoint:
                    all_items.extend(data.get('billable_items', []))
                elif 'appointment_types' in endpoint:
                    all_items.extend(data.get('appointment_types', []))
                
                # Get next page URL
                links = response.links
                url = links.get('next', {}).get('url')
        
        return all_items

class ClinicInitializer:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.conn = None
    
    async def __aenter__(self):
        self.conn = await asyncpg.connect(self.db_url)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            await self.conn.close()
    
    async def initialize_clinic(self, clinic_data: Dict) -> Dict:
        """
        Initialize a clinic with all necessary data from Cliniko
        
        Args:
            clinic_data: {
                'clinic_name': str,
                'phone_number': str,
                'cliniko_api_key': str,
                'cliniko_shard': str,
                'contact_email': str
            }
        
        Returns:
            Dict with initialization results
        """
        start_time = datetime.now()
        results = {
            'clinic_id': None,
            'businesses': 0,
            'practitioners': 0,
            'billable_items': 0,
            'appointment_types': 0,
            'practitioner_services': 0,
            'practitioner_businesses': 0,
            'errors': []
        }
        
        try:
            # Step 1: Create or update clinic
            logger.info(f"Initializing clinic: {clinic_data['clinic_name']}")
            clinic_id = await self._upsert_clinic(clinic_data)
            results['clinic_id'] = str(clinic_id)
            
            # Initialize Cliniko API
            cliniko = ClinikoAPI(
                clinic_data['cliniko_api_key'],
                clinic_data['cliniko_shard']
            )
            
            # Step 2: Sync businesses
            logger.info("Syncing businesses...")
            businesses = await cliniko.get_all_pages('businesses')
            business_count = await self._sync_businesses(clinic_id, businesses)
            results['businesses'] = business_count
            
            # Step 3: Sync practitioners
            logger.info("Syncing practitioners...")
            practitioners = await cliniko.get_all_pages('practitioners')
            practitioner_count = await self._sync_practitioners(clinic_id, practitioners)
            results['practitioners'] = practitioner_count
            
            # Step 4: Sync billable items
            logger.info("Syncing billable items...")
            billable_items = await cliniko.get_all_pages('billable_items')
            billable_count = await self._sync_billable_items(clinic_id, billable_items)
            results['billable_items'] = billable_count
            
            # Step 5: Sync appointment types
            logger.info("Syncing appointment types...")
            appointment_types = await cliniko.get_all_pages('appointment_types')
            appt_type_count = await self._sync_appointment_types(clinic_id, appointment_types)
            results['appointment_types'] = appt_type_count
            
            # Step 6: Link practitioners to services
            logger.info("Linking practitioners to services...")
            service_links = await self._link_practitioners_to_services(clinic_id, practitioners, cliniko)
            results['practitioner_services'] = service_links
            
            # Step 7: Link practitioners to businesses
            logger.info("Linking practitioners to businesses...")
            business_links = await self._link_practitioners_to_businesses(clinic_id)
            results['practitioner_businesses'] = business_links
            
            # Calculate elapsed time
            elapsed = (datetime.now() - start_time).total_seconds()
            results['elapsed_seconds'] = elapsed
            
            logger.info(f"✅ Clinic initialization completed in {elapsed:.2f} seconds")
            
        except Exception as e:
            logger.error(f"Error initializing clinic: {str(e)}")
            results['errors'].append(str(e))
        
        return results
    
    async def _upsert_clinic(self, clinic_data: Dict) -> str:
        """Create or update clinic record"""
        query = """
            INSERT INTO clinics (
                clinic_name, phone_number, cliniko_api_key, 
                cliniko_shard, contact_email, active
            ) VALUES ($1, $2, $3, $4, $5, true)
            ON CONFLICT (phone_number) 
            DO UPDATE SET
                clinic_name = EXCLUDED.clinic_name,
                cliniko_api_key = EXCLUDED.cliniko_api_key,
                cliniko_shard = EXCLUDED.cliniko_shard,
                contact_email = EXCLUDED.contact_email,
                updated_at = NOW()
            RETURNING clinic_id
        """
        
        result = await self.conn.fetchrow(
            query,
            clinic_data['clinic_name'],
            clinic_data['phone_number'],
            clinic_data['cliniko_api_key'],
            clinic_data['cliniko_shard'],
            clinic_data['contact_email']
        )
        
        return result['clinic_id']
    
    async def _sync_businesses(self, clinic_id: str, businesses: List[Dict]) -> int:
        """Sync businesses from Cliniko"""
        count = 0
        
        for idx, business in enumerate(businesses):
            try:
                await self.conn.execute("""
                    INSERT INTO businesses (business_id, clinic_id, business_name, is_primary)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (business_id) 
                    DO UPDATE SET
                        business_name = EXCLUDED.business_name,
                        is_primary = EXCLUDED.is_primary
                """, 
                    str(business['id']),
                    clinic_id,
                    business.get('business_name') or business.get('label', 'Main Location'),
                    idx == 0  # First business is primary
                )
                count += 1
            except Exception as e:
                logger.error(f"Error syncing business {business['id']}: {e}")
        
        return count
    
    async def _sync_practitioners(self, clinic_id: str, practitioners: List[Dict]) -> int:
        """Sync practitioners from Cliniko"""
        count = 0
        
        for practitioner in practitioners:
            try:
                await self.conn.execute("""
                    INSERT INTO practitioners (
                        practitioner_id, clinic_id, first_name, 
                        last_name, title, active
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (practitioner_id) 
                    DO UPDATE SET
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        title = EXCLUDED.title,
                        active = EXCLUDED.active
                """,
                    str(practitioner['id']),
                    clinic_id,
                    practitioner.get('first_name', ''),
                    practitioner.get('last_name', ''),
                    practitioner.get('title', ''),
                    practitioner.get('active', True)
                )
                count += 1
            except Exception as e:
                logger.error(f"Error syncing practitioner {practitioner['id']}: {e}")
        
        return count
    
    async def _sync_billable_items(self, clinic_id: str, items: List[Dict]) -> int:
        """Sync billable items from Cliniko"""
        count = 0
        
        for item in items:
            try:
                await self.conn.execute("""
                    INSERT INTO billable_items (item_id, clinic_id, item_name, price, active)
                    VALUES ($1, $2, $3, $4, true)
                    ON CONFLICT (item_id) 
                    DO UPDATE SET
                        item_name = EXCLUDED.item_name,
                        price = EXCLUDED.price
                """,
                    str(item['id']),
                    clinic_id,
                    item.get('name', ''),
                    float(item.get('price', 0))
                )
                count += 1
            except Exception as e:
                logger.error(f"Error syncing billable item {item['id']}: {e}")
        
        return count
    
    async def _sync_appointment_types(self, clinic_id: str, types: List[Dict]) -> int:
        """Sync appointment types from Cliniko"""
        count = 0
        
        # Step 1: Sync all appointment types without billable items first
        for appt_type in types:
            try:
                await self.conn.execute("""
                    INSERT INTO appointment_types (
                        appointment_type_id, clinic_id, name, 
                        duration_minutes, billable_item_id, active
                    ) VALUES ($1, $2, $3, $4, NULL, true)
                    ON CONFLICT (appointment_type_id) 
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        duration_minutes = EXCLUDED.duration_minutes
                """,
                    str(appt_type['id']),
                    clinic_id,
                    appt_type.get('name', ''),
                    appt_type.get('duration_in_minutes', 30)
                )
                count += 1
            except Exception as e:
                logger.error(f"Error syncing appointment type {appt_type['id']}: {e}")
        
        # Step 2: Sync billable item relationships
        await self._sync_appointment_type_billable_items(clinic_id)
        
        return count
    
    async def _sync_appointment_type_billable_items(self, clinic_id: str) -> int:
        """Sync appointment type billable item relationships"""
        logger.info("Syncing appointment type billable item relationships...")
        
        # Initialize Cliniko API to get billable item relationships
        cliniko = ClinikoAPI(
            os.getenv('CLINIKO_API_KEY'),
            os.getenv('CLINIKO_SHARD', 'au4')
        )
        
        try:
            # Get all appointment type billable items
            billable_relationships = await cliniko.get_all_pages('appointment_type_billable_items')
            
            updated_count = 0
            for relationship in billable_relationships:
                try:
                    # Extract appointment type ID from the relationship
                    appt_type_link = relationship.get('appointment_type', {}).get('links', {}).get('self')
                    if not appt_type_link:
                        continue
                    
                    # Extract ID from URL like /appointment_types/123
                    appt_type_id = appt_type_link.split('/')[-1]
                    
                    # Extract billable item ID from the relationship
                    billable_item_link = relationship.get('billable_item', {}).get('links', {}).get('self')
                    if not billable_item_link:
                        continue
                    
                    # Extract ID from URL like /billable_items/123
                    billable_item_id = billable_item_link.split('/')[-1]
                    
                    # Update the appointment type with the billable item ID
                    await self.conn.execute("""
                        UPDATE appointment_types 
                        SET billable_item_id = $1
                        WHERE appointment_type_id = $2 AND clinic_id = $3
                    """, billable_item_id, appt_type_id, clinic_id)
                    
                    updated_count += 1
                    logger.info(f"Updated appointment type {appt_type_id} with billable item {billable_item_id}")
                    
                except Exception as e:
                    logger.error(f"Error updating appointment type billable item relationship: {e}")
            
            logger.info(f"Updated {updated_count} appointment type billable item relationships")
            return updated_count
            
        except Exception as e:
            logger.error(f"Error syncing appointment type billable items: {e}")
            return 0
    
    async def _link_practitioners_to_services(self, clinic_id: str, practitioners: List[Dict], cliniko: ClinikoAPI) -> int:
        """Link practitioners to their appointment types"""
        total_links = 0
        
        for practitioner in practitioners:
            try:
                # Get appointment types for this practitioner
                endpoint = f"practitioners/{practitioner['id']}/appointment_types"
                appt_types = await cliniko.get_all_pages(endpoint)
                
                for appt_type in appt_types:
                    await self.conn.execute("""
                        INSERT INTO practitioner_appointment_types 
                        (practitioner_id, appointment_type_id)
                        VALUES ($1, $2)
                        ON CONFLICT DO NOTHING
                    """,
                        str(practitioner['id']),
                        str(appt_type['id'])
                    )
                    total_links += 1
                    
            except Exception as e:
                logger.error(f"Error linking practitioner {practitioner['id']} to services: {e}")
        
        return total_links
    
    async def _link_practitioners_to_businesses(self, clinic_id: str) -> int:
        """Link all practitioners to all businesses for the clinic"""
        # Get all practitioners for this clinic
        practitioners = await self.conn.fetch("""
            SELECT practitioner_id FROM practitioners 
            WHERE clinic_id = $1 AND active = true
        """, clinic_id)
        
        # Get all businesses for this clinic
        businesses = await self.conn.fetch("""
            SELECT business_id FROM businesses 
            WHERE clinic_id = $1
        """, clinic_id)
        
        # Link each practitioner to each business
        total_links = 0
        for practitioner in practitioners:
            for business in businesses:
                try:
                    await self.conn.execute("""
                        INSERT INTO practitioner_businesses 
                        (practitioner_id, business_id)
                        VALUES ($1, $2)
                        ON CONFLICT DO NOTHING
                    """,
                        practitioner['practitioner_id'],
                        business['business_id']
                    )
                    total_links += 1
                except Exception as e:
                    logger.error(f"Error linking practitioner to business: {e}")
        
        return total_links

async def initialize_clinic_from_env():
    """Initialize clinic using environment variables"""
    clinic_data = {
        'clinic_name': os.getenv('CLINIC_NAME', 'Test Clinic'),
        'phone_number': os.getenv('CLINIC_PHONE', '0478621276'),
        'cliniko_api_key': os.getenv('CLINIKO_API_KEY', 'MS0xNzAyMDE4MDE4MzQ3NzQ0MzcyMjM4LUs2YzJodjE2TEM1OVVGM0JTRU1GMHZ1K2Y5V0VmRHNH-au4'),
        'cliniko_shard': os.getenv('CLINIKO_SHARD', 'au4'),
        'contact_email': os.getenv('CLINIC_EMAIL', 'admin@clinic.com')
    }
    
    db_url = os.getenv("DATABASE_URL") or os.getenv('DATABASE_URL')
    
    async with ClinicInitializer(db_url) as initializer:
        results = await initializer.initialize_clinic(clinic_data)
        
        # Print results
        print("\n=== CLINIC INITIALIZATION RESULTS ===")
        print(f"Clinic ID: {results['clinic_id']}")
        print(f"Businesses synced: {results['businesses']}")
        print(f"Practitioners synced: {results['practitioners']}")
        print(f"Billable items synced: {results['billable_items']}")
        print(f"Appointment types synced: {results['appointment_types']}")
        print(f"Practitioner-service links: {results['practitioner_services']}")
        print(f"Practitioner-business links: {results['practitioner_businesses']}")
        
        if results['errors']:
            print(f"\n❌ Errors: {results['errors']}")
        else:
            print(f"\n✅ Completed successfully in {results.get('elapsed_seconds', 0):.2f} seconds")

async def initialize_multiple_clinics(clinics: List[Dict]):
    """Initialize multiple clinics"""
    db_url = os.getenv("DATABASE_URL") or os.getenv('DATABASE_URL')
    
    for clinic_data in clinics:
        async with ClinicInitializer(db_url) as initializer:
            print(f"\n{'='*50}")
            print(f"Initializing: {clinic_data['clinic_name']}")
            print(f"{'='*50}")
            
            results = await initializer.initialize_clinic(clinic_data)
            
            if results['errors']:
                print(f"❌ Failed with errors: {results['errors']}")
            else:
                print(f"✅ Success! Synced {results['practitioners']} practitioners, {results['appointment_types']} services")

if __name__ == "__main__":
    # Run initialization for current clinic
    asyncio.run(initialize_clinic_from_env())