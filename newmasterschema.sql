-- ==========================================
-- COMPLETE VOICE BOOKING SYSTEM SCHEMA
-- Production-ready with all fixes
-- ==========================================

-- ==========================================
-- 1. EXTENSIONS
-- ==========================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==========================================
-- 2. HELPER FUNCTIONS (Must be defined first)
-- ==========================================

-- Function for updated_at triggers
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function to normalize phone numbers (CRITICAL - was missing)
CREATE OR REPLACE FUNCTION normalize_phone(phone text)
RETURNS text AS $$
BEGIN
    IF phone IS NULL THEN
        RETURN NULL;
    END IF;
    
    -- Remove all non-numeric characters
    phone := regexp_replace(phone, '[^0-9]', '', 'g');
    
    -- If starts with 0, replace with 61 (Australian)
    IF LEFT(phone, 1) = '0' THEN
        phone := '61' || SUBSTRING(phone FROM 2);
    END IF;
    
    RETURN phone;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ==========================================
-- 3. CORE TABLES
-- ==========================================

-- 3.1 Clinics (Multi-tenant support)
CREATE TABLE IF NOT EXISTS clinics (
    clinic_id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_name text NOT NULL,
    phone_number text UNIQUE NOT NULL,
    cliniko_api_key text NOT NULL,
    cliniko_shard text NOT NULL CHECK (cliniko_shard IN ('au1', 'au2', 'au3', 'au4', 'uk1', 'us1')),
    active boolean DEFAULT true,
    contact_email text,
    elevenlabs_agent_id text UNIQUE,
    created_at timestamptz DEFAULT NOW(),
    updated_at timestamptz DEFAULT NOW(),
    timezone TEXT DEFAULT 'Australia/Sydney' CHECK (timezone != '')
);
CREATE INDEX IF NOT EXISTS idx_clinics_phone_number ON clinics(phone_number);
CREATE INDEX IF NOT EXISTS idx_clinics_elevenlabs_agent ON clinics(elevenlabs_agent_id) WHERE elevenlabs_agent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_clinics_timezone ON clinics(timezone);

DROP TRIGGER IF EXISTS update_clinics_updated_at ON clinics;
CREATE TRIGGER update_clinics_updated_at BEFORE UPDATE ON clinics
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Add comment for documentation
COMMENT ON COLUMN clinics.timezone IS 'IANA timezone identifier for the clinic location (e.g., Australia/Sydney, America/New_York)';

-- 3.2 Businesses (Physical locations/branches)
-- CRITICAL: business_id is Cliniko's location ID, NOT to be confused with clinic_id
CREATE TABLE IF NOT EXISTS businesses (
    business_id text PRIMARY KEY, -- From Cliniko, represents a physical location
    clinic_id uuid NOT NULL REFERENCES clinics(clinic_id) ON DELETE CASCADE,
    business_name text NOT NULL,
    is_primary boolean DEFAULT false,
    created_at timestamptz DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_businesses_clinic_id ON businesses(clinic_id);
CREATE INDEX IF NOT EXISTS idx_businesses_primary ON businesses(clinic_id, is_primary) WHERE is_primary = true;

-- 3.3 Practitioners
CREATE TABLE IF NOT EXISTS practitioners (
    practitioner_id text PRIMARY KEY,
    clinic_id uuid NOT NULL REFERENCES clinics(clinic_id) ON DELETE CASCADE,
    first_name text,
    last_name text,
    title text,
    active boolean DEFAULT true,
    default_appointment_type_id text REFERENCES appointment_types(appointment_type_id),
    created_at timestamptz DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_practitioners_clinic_id ON practitioners(clinic_id);
CREATE INDEX IF NOT EXISTS idx_practitioners_active ON practitioners(clinic_id, active) WHERE active = true;

-- 3.4 Billable Items
CREATE TABLE IF NOT EXISTS billable_items (
    item_id text PRIMARY KEY,
    clinic_id uuid NOT NULL REFERENCES clinics(clinic_id) ON DELETE CASCADE,
    item_name text NOT NULL,
    price numeric(10, 2),
    active boolean DEFAULT true
);
CREATE INDEX IF NOT EXISTS idx_billable_items_clinic_id ON billable_items(clinic_id);

-- 3.5 Appointment Types (Services)
CREATE TABLE IF NOT EXISTS appointment_types (
    appointment_type_id text PRIMARY KEY,
    clinic_id uuid NOT NULL REFERENCES clinics(clinic_id) ON DELETE CASCADE,
    name text NOT NULL,
    duration_minutes integer NOT NULL,
    billable_item_id text REFERENCES billable_items(item_id),
    active boolean DEFAULT true
);
CREATE INDEX IF NOT EXISTS idx_appointment_types_clinic_id ON appointment_types(clinic_id);
CREATE INDEX IF NOT EXISTS idx_appointment_types_active ON appointment_types(clinic_id, active) WHERE active = true;

-- 3.6 Patients
CREATE TABLE IF NOT EXISTS patients (
    patient_id text PRIMARY KEY,
    clinic_id uuid NOT NULL REFERENCES clinics(clinic_id) ON DELETE CASCADE,
    phone_number text NOT NULL,
    first_name text,
    last_name text,
    email text,
    active boolean DEFAULT true,
    created_at timestamptz DEFAULT NOW(),
    updated_at timestamptz DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_patients_clinic_id ON patients(clinic_id);
CREATE INDEX IF NOT EXISTS idx_patients_phone_number ON patients(phone_number);
CREATE INDEX IF NOT EXISTS idx_patients_active ON patients(clinic_id, active) WHERE active = true;

DROP TRIGGER IF EXISTS update_patients_updated_at ON patients;
CREATE TRIGGER update_patients_updated_at BEFORE UPDATE ON patients
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Add unique constraint
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'uq_patient_clinic_phone'
          AND table_name = 'patients'
    ) THEN
ALTER TABLE patients 
            ADD CONSTRAINT uq_patient_clinic_phone UNIQUE (clinic_id, phone_number);
    END IF;
END;
$$;

-- 3.7 Appointments
CREATE TABLE IF NOT EXISTS appointments (
    appointment_id text PRIMARY KEY,
    clinic_id uuid NOT NULL REFERENCES clinics(clinic_id) ON DELETE CASCADE,
    patient_id text REFERENCES patients(patient_id),
    practitioner_id text REFERENCES practitioners(practitioner_id),
    appointment_type_id text REFERENCES appointment_types(appointment_type_id),
    business_id text REFERENCES businesses(business_id),
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    status text DEFAULT 'booked' CHECK (status IN ('booked', 'confirmed', 'cancelled', 'completed')),
    notes text,
    created_at timestamptz DEFAULT NOW(),
    updated_at timestamptz DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_appointments_clinic_id ON appointments(clinic_id);
CREATE INDEX IF NOT EXISTS idx_appointments_patient_id ON appointments(patient_id);
CREATE INDEX IF NOT EXISTS idx_appointments_practitioner_id ON appointments(practitioner_id);
CREATE INDEX IF NOT EXISTS idx_appointments_business_id ON appointments(business_id);
CREATE INDEX IF NOT EXISTS idx_appointments_starts_at ON appointments(starts_at);
CREATE INDEX IF NOT EXISTS idx_appointments_status ON appointments(status, starts_at) WHERE status = 'booked';

DROP TRIGGER IF EXISTS update_appointments_updated_at ON appointments;
CREATE TRIGGER update_appointments_updated_at BEFORE UPDATE ON appointments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 3.8 Voice Booking Logs
CREATE TABLE IF NOT EXISTS voice_bookings (
    booking_id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    appointment_id text, -- No FK constraint as per original
    clinic_id uuid NOT NULL REFERENCES clinics(clinic_id) ON DELETE CASCADE,
    session_id text NOT NULL,
    caller_phone text NOT NULL,
    action text NOT NULL CHECK (action IN ('book', 'check', 'modify', 'cancel', 'reschedule')),
    status text NOT NULL CHECK (status IN ('completed', 'failed')),
    error_message text,
    created_at timestamptz DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_voice_bookings_session_id ON voice_bookings(session_id);
CREATE INDEX IF NOT EXISTS idx_voice_bookings_caller_phone ON voice_bookings(caller_phone);
CREATE INDEX IF NOT EXISTS idx_voice_bookings_created ON voice_bookings(created_at DESC);

-- 3.9 Phone Lookup
CREATE TABLE IF NOT EXISTS phone_lookup (
    phone_normalized text PRIMARY KEY,
    clinic_id uuid REFERENCES clinics(clinic_id) ON DELETE CASCADE,
    created_at timestamptz DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_phone_lookup_clinic_id ON phone_lookup(clinic_id);

-- 3.10 Location Aliases (CRITICAL - was missing)
CREATE TABLE IF NOT EXISTS location_aliases (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    business_id text NOT NULL REFERENCES businesses(business_id) ON DELETE CASCADE,
    alias text NOT NULL,
    created_at timestamptz DEFAULT NOW(),
    CONSTRAINT unique_business_alias UNIQUE(business_id, alias)
);
CREATE INDEX IF NOT EXISTS idx_location_aliases_business ON location_aliases(business_id);
CREATE INDEX IF NOT EXISTS idx_location_aliases_alias ON location_aliases(LOWER(alias));

-- 3.11 ElevenLabs Numbers
CREATE TABLE IF NOT EXISTS elevenlabs_numbers (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_id uuid NOT NULL REFERENCES clinics(clinic_id) ON DELETE CASCADE,
    business_id text REFERENCES businesses(business_id) ON DELETE CASCADE,
    phone_number text NOT NULL,
    phone_normalized text NOT NULL,
    description text,
    is_active boolean DEFAULT true,
    created_at timestamptz DEFAULT NOW(),
    updated_at timestamptz DEFAULT NOW(),
    CONSTRAINT unique_phone UNIQUE(phone_normalized)
);
CREATE INDEX IF NOT EXISTS idx_elevenlabs_numbers_clinic ON elevenlabs_numbers(clinic_id);
CREATE INDEX IF NOT EXISTS idx_elevenlabs_numbers_active ON elevenlabs_numbers(clinic_id, is_active);

DROP TRIGGER IF EXISTS update_elevenlabs_numbers_updated_at ON elevenlabs_numbers;
CREATE TRIGGER update_elevenlabs_numbers_updated_at 
BEFORE UPDATE ON elevenlabs_numbers
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ==========================================
-- 4. JUNCTION TABLES
-- ==========================================

-- 4.1 Practitioner can work at multiple businesses
CREATE TABLE IF NOT EXISTS practitioner_businesses (
    practitioner_id text NOT NULL REFERENCES practitioners(practitioner_id) ON DELETE CASCADE,
    business_id text NOT NULL REFERENCES businesses(business_id) ON DELETE CASCADE,
    PRIMARY KEY (practitioner_id, business_id)
);
CREATE INDEX IF NOT EXISTS idx_practitioner_businesses_practitioner ON practitioner_businesses(practitioner_id);
CREATE INDEX IF NOT EXISTS idx_practitioner_businesses_business ON practitioner_businesses(business_id);

-- 4.2 Which appointment types each practitioner offers
CREATE TABLE IF NOT EXISTS practitioner_appointment_types (
    practitioner_id text NOT NULL REFERENCES practitioners(practitioner_id) ON DELETE CASCADE,
    appointment_type_id text NOT NULL REFERENCES appointment_types(appointment_type_id) ON DELETE CASCADE,
    PRIMARY KEY (practitioner_id, appointment_type_id)
);
CREATE INDEX IF NOT EXISTS idx_practitioner_appointment_types_practitioner ON practitioner_appointment_types(practitioner_id);
CREATE INDEX IF NOT EXISTS idx_practitioner_appointment_types_appointment ON practitioner_appointment_types(appointment_type_id);

-- ==========================================
-- 5. CACHE TABLES (Fixed version)
-- ==========================================

-- 5.1 Availability Cache
CREATE TABLE IF NOT EXISTS availability_cache (
    cache_id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_id uuid NOT NULL REFERENCES clinics(clinic_id) ON DELETE CASCADE,
    practitioner_id text NOT NULL REFERENCES practitioners(practitioner_id) ON DELETE CASCADE,
    business_id text NOT NULL REFERENCES businesses(business_id) ON DELETE CASCADE,
    date date NOT NULL,
    available_slots jsonb NOT NULL DEFAULT '[]'::jsonb,
    cached_at timestamptz DEFAULT NOW(),
    expires_at timestamptz DEFAULT NOW() + INTERVAL '15 minutes',
    is_stale boolean DEFAULT false,
    CONSTRAINT uq_availability_cache UNIQUE (practitioner_id, business_id, date)
);
CREATE INDEX IF NOT EXISTS idx_availability_cache_lookup ON availability_cache(clinic_id, date, expires_at) WHERE NOT is_stale;
CREATE INDEX IF NOT EXISTS idx_availability_cache_practitioner ON availability_cache(practitioner_id, date) WHERE NOT is_stale;
CREATE INDEX IF NOT EXISTS idx_availability_cache_business ON availability_cache(business_id, date) WHERE NOT is_stale;
CREATE INDEX IF NOT EXISTS idx_availability_cache_expires ON availability_cache(expires_at) WHERE NOT is_stale;
CREATE INDEX IF NOT EXISTS idx_availability_cache_stale ON availability_cache(is_stale, expires_at);

-- 5.2 Booking Context Cache
CREATE TABLE IF NOT EXISTS booking_context_cache (
    phone_normalized text PRIMARY KEY,
    clinic_id uuid REFERENCES clinics(clinic_id) ON DELETE CASCADE,
    context_data jsonb NOT NULL,
    cached_at timestamptz DEFAULT NOW(),
    expires_at timestamptz DEFAULT NOW() + INTERVAL '1 hour',
    hit_count integer DEFAULT 0,
    last_accessed timestamptz DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_booking_context_expires ON booking_context_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_booking_context_clinic ON booking_context_cache(clinic_id);
CREATE INDEX IF NOT EXISTS idx_booking_context_accessed ON booking_context_cache(last_accessed);

-- 5.3 Patient Cache
CREATE TABLE IF NOT EXISTS patient_cache (
    cache_id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    phone_normalized text NOT NULL,
    clinic_id uuid NOT NULL REFERENCES clinics(clinic_id) ON DELETE CASCADE,
    patient_id text REFERENCES patients(patient_id) ON DELETE CASCADE,
    patient_data jsonb NOT NULL,
    cached_at timestamptz DEFAULT NOW(),
    expires_at timestamptz DEFAULT NOW() + INTERVAL '24 hours',
    CONSTRAINT uq_patient_cache UNIQUE (phone_normalized, clinic_id)
);
CREATE INDEX IF NOT EXISTS idx_patient_cache_phone ON patient_cache(phone_normalized);
CREATE INDEX IF NOT EXISTS idx_patient_cache_clinic ON patient_cache(clinic_id);
CREATE INDEX IF NOT EXISTS idx_patient_cache_expires ON patient_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_patient_cache_patient ON patient_cache(patient_id);

-- 5.4 Service Match Cache
CREATE TABLE IF NOT EXISTS service_match_cache (
    cache_id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    cache_key text UNIQUE NOT NULL,
    clinic_id uuid NOT NULL REFERENCES clinics(clinic_id) ON DELETE CASCADE,
    search_term text NOT NULL,
    matches jsonb NOT NULL,
    usage_count integer DEFAULT 1,
    cached_at timestamptz DEFAULT NOW(),
    expires_at timestamptz DEFAULT NOW() + INTERVAL '7 days'
);
CREATE INDEX IF NOT EXISTS idx_service_match_clinic ON service_match_cache(clinic_id);
CREATE INDEX IF NOT EXISTS idx_service_match_usage ON service_match_cache(usage_count DESC);
CREATE INDEX IF NOT EXISTS idx_service_match_expires ON service_match_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_service_match_search ON service_match_cache(clinic_id, search_term);

-- 5.5 Cache Statistics (partitioned)
CREATE TABLE IF NOT EXISTS cache_statistics (
    stat_date date NOT NULL DEFAULT CURRENT_DATE,
    cache_type text NOT NULL,
    hit_count integer DEFAULT 0,
    miss_count integer DEFAULT 0,
    refresh_count integer DEFAULT 0,
    api_calls_saved integer DEFAULT 0,
    avg_response_time_ms numeric(10,2),
    created_at timestamptz DEFAULT NOW(),
    PRIMARY KEY (stat_date, cache_type)
) PARTITION BY RANGE (stat_date);

CREATE INDEX IF NOT EXISTS idx_cache_statistics_type ON cache_statistics(cache_type, stat_date DESC);

-- ==========================================
-- 6. ALL FUNCTIONS
-- ==========================================

-- Auto-populate phone lookup when clinic is created
CREATE OR REPLACE FUNCTION update_phone_lookup_on_clinic()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO phone_lookup (phone_normalized, clinic_id)
    VALUES (normalize_phone(NEW.phone_number), NEW.clinic_id)
    ON CONFLICT (phone_normalized) DO UPDATE
    SET clinic_id = NEW.clinic_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Auto-sync elevenlabs numbers to phone_lookup
CREATE OR REPLACE FUNCTION sync_elevenlabs_to_lookup()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND NEW.is_active = false) THEN
        DELETE FROM phone_lookup WHERE phone_normalized = OLD.phone_normalized;
    END IF;
    
    IF TG_OP != 'DELETE' AND NEW.is_active = true THEN
        INSERT INTO phone_lookup (phone_normalized, clinic_id)
        VALUES (NEW.phone_normalized, NEW.clinic_id)
        ON CONFLICT (phone_normalized) DO UPDATE
        SET clinic_id = NEW.clinic_id;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Add default location aliases
CREATE OR REPLACE FUNCTION add_default_location_aliases()
RETURNS TRIGGER AS $$
DECLARE
    num text;
BEGIN
    -- Add common aliases for primary locations
    IF NEW.is_primary THEN
        INSERT INTO location_aliases (business_id, alias)
        VALUES 
            (NEW.business_id, 'main'),
            (NEW.business_id, 'primary'),
            (NEW.business_id, 'head office'),
            (NEW.business_id, 'main clinic'),
            (NEW.business_id, 'first location')
        ON CONFLICT DO NOTHING;
    END IF;
    
    -- Add numbered aliases based on business name
    IF NEW.business_name ~ '[0-9]' THEN
        num := regexp_replace(NEW.business_name, '[^0-9]', '', 'g');
        IF num != '' THEN
            INSERT INTO location_aliases (business_id, alias)
            VALUES 
                (NEW.business_id, 'location ' || num),
                (NEW.business_id, 'clinic ' || num),
                (NEW.business_id, 'branch ' || num)
            ON CONFLICT DO NOTHING;
        END IF;
    END IF;
    
        RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Dynamic business matching function (CRITICAL - was missing)
CREATE OR REPLACE FUNCTION find_business_by_name_dynamic(
    clinic_id_param uuid,
    business_name_param text
)
RETURNS TABLE (
    business_id text,
    business_name text,
    is_primary boolean,
    match_type text,
    similarity_score numeric
) AS $$
DECLARE
    search_term text;
BEGIN
    -- Normalize the search term
    search_term := LOWER(TRIM(business_name_param));
    
    -- If no search term, return primary business
    IF search_term = '' OR search_term IS NULL THEN
        RETURN QUERY
        SELECT 
            b.business_id,
            b.business_name,
            b.is_primary,
            'default_primary'::text as match_type,
            0.5::numeric as similarity_score
        FROM businesses b
        WHERE b.clinic_id = clinic_id_param
        AND b.is_primary = true
        LIMIT 1;
        RETURN;
    END IF;
    
    -- Return all businesses with calculated similarity scores
    RETURN QUERY
    WITH business_scores AS (
        SELECT 
            b.business_id,
            b.business_name,
            b.is_primary,
            LOWER(b.business_name) as business_lower,
            CASE 
                -- Exact match
                WHEN LOWER(b.business_name) = search_term THEN 1.0
                -- Check aliases
                WHEN EXISTS (
                    SELECT 1 FROM location_aliases la 
                    WHERE la.business_id = b.business_id 
                    AND LOWER(la.alias) = search_term
                ) THEN 0.95
                -- Contains search term
                WHEN LOWER(b.business_name) LIKE '%' || search_term || '%' THEN 
                    0.8 * (LENGTH(search_term)::numeric / LENGTH(b.business_name))
                -- Search term contains business name
                WHEN search_term LIKE '%' || LOWER(b.business_name) || '%' THEN 
                    0.8 * (LENGTH(b.business_name)::numeric / LENGTH(search_term))
                -- Generic terms favor primary
                WHEN (search_term IN ('main', 'primary', 'first', 'central', 'head', 'office') 
                      AND b.is_primary = true) THEN 0.8
                -- Numbered locations
                WHEN (search_term ~ '^(location|site|branch|office)\s*[0-9]+$' 
                      OR search_term ~ '^[0-9]+$') THEN
                    CASE WHEN ROW_NUMBER() OVER (ORDER BY b.is_primary DESC, b.business_name) = 
                              CAST(regexp_replace(search_term, '[^0-9]', '', 'g') AS INTEGER) 
                    THEN 0.9 ELSE 0.1 END
                ELSE 0.0
            END + CASE WHEN b.is_primary THEN 0.1 ELSE 0.0 END as score
        FROM businesses b
        WHERE b.clinic_id = clinic_id_param
    )
    SELECT 
        bs.business_id,
        bs.business_name,
        bs.is_primary,
        CASE 
            WHEN bs.score >= 0.8 THEN 'high_confidence'
            WHEN bs.score >= 0.5 THEN 'medium_confidence'
            WHEN bs.score >= 0.2 THEN 'low_confidence'
            ELSE 'no_match'
        END::text as match_type,
        ROUND(bs.score, 3) as similarity_score
    FROM business_scores bs
    WHERE bs.score > 0
    ORDER BY bs.score DESC, bs.is_primary DESC
    LIMIT 5;
    
    -- If no matches found, return primary business as fallback
    IF NOT FOUND THEN
        RETURN QUERY
        SELECT 
            b.business_id,
            b.business_name,
            b.is_primary,
            'fallback_primary'::text as match_type,
            0.3::numeric as similarity_score
        FROM businesses b
        WHERE b.clinic_id = clinic_id_param
        AND b.is_primary = true
        LIMIT 1;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Cache-related functions
CREATE OR REPLACE FUNCTION record_cache_stat(
    p_cache_type text,
    p_is_hit boolean,
    p_response_time_ms numeric DEFAULT NULL
) RETURNS void AS $$
BEGIN
    INSERT INTO cache_statistics (stat_date, cache_type, hit_count, miss_count, avg_response_time_ms)
    VALUES (
        CURRENT_DATE,
        p_cache_type,
        CASE WHEN p_is_hit THEN 1 ELSE 0 END,
        CASE WHEN p_is_hit THEN 0 ELSE 1 END,
        p_response_time_ms
    )
    ON CONFLICT (stat_date, cache_type) DO UPDATE
    SET 
        hit_count = cache_statistics.hit_count + CASE WHEN p_is_hit THEN 1 ELSE 0 END,
        miss_count = cache_statistics.miss_count + CASE WHEN p_is_hit THEN 0 ELSE 1 END,
        avg_response_time_ms = CASE 
            WHEN cache_statistics.avg_response_time_ms IS NULL THEN p_response_time_ms
            WHEN p_response_time_ms IS NULL THEN cache_statistics.avg_response_time_ms
            ELSE (
                (cache_statistics.avg_response_time_ms * (cache_statistics.hit_count + cache_statistics.miss_count) + p_response_time_ms) / 
                (cache_statistics.hit_count + cache_statistics.miss_count + 1)
            )
        END,
        api_calls_saved = cache_statistics.api_calls_saved + CASE WHEN p_is_hit THEN 1 ELSE 0 END;
EXCEPTION
    WHEN OTHERS THEN
        RAISE WARNING 'Failed to record cache stat: %', SQLERRM;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION get_cached_availability(
    p_practitioner_id text,
    p_business_id text,
    p_date date
) RETURNS jsonb AS $$
DECLARE
    v_result jsonb;
    v_is_hit boolean;
BEGIN
    SELECT available_slots INTO v_result
    FROM availability_cache
    WHERE practitioner_id = p_practitioner_id
      AND business_id = p_business_id
      AND date = p_date
      AND expires_at > NOW()
      AND NOT is_stale;
    
    v_is_hit := (v_result IS NOT NULL);
    PERFORM record_cache_stat('availability', v_is_hit);
    
    RETURN v_result;
EXCEPTION
    WHEN OTHERS THEN
        RAISE WARNING 'Cache lookup error: %', SQLERRM;
        RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION invalidate_availability_cache()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        UPDATE availability_cache
        SET is_stale = true
        WHERE practitioner_id = NEW.practitioner_id
          AND business_id = NEW.business_id
          AND date = DATE(NEW.starts_at);
    END IF;
    
    IF TG_OP = 'DELETE' THEN
        UPDATE availability_cache
        SET is_stale = true
        WHERE practitioner_id = OLD.practitioner_id
          AND business_id = OLD.business_id
          AND date = DATE(OLD.starts_at);
        RETURN OLD; -- FIX: Return OLD for DELETE
    END IF;
    
    IF TG_OP = 'UPDATE' AND OLD.starts_at IS DISTINCT FROM NEW.starts_at THEN
        UPDATE availability_cache
        SET is_stale = true
        WHERE practitioner_id = OLD.practitioner_id
          AND business_id = OLD.business_id
          AND date = DATE(OLD.starts_at);
    END IF;
    
    RETURN NEW;
EXCEPTION
    WHEN OTHERS THEN
        RAISE WARNING 'Cache invalidation error: %', SQLERRM;
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        ELSE
            RETURN NEW;
        END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION cleanup_expired_cache()
RETURNS integer AS $$
DECLARE
    v_deleted_count integer := 0;
    v_temp_count integer;
BEGIN
    DELETE FROM availability_cache 
    WHERE expires_at < NOW() - INTERVAL '1 hour'
       OR (is_stale AND cached_at < NOW() - INTERVAL '24 hours');
    GET DIAGNOSTICS v_temp_count = ROW_COUNT;
    v_deleted_count := v_deleted_count + v_temp_count;
    
    DELETE FROM booking_context_cache 
    WHERE expires_at < NOW() - INTERVAL '1 day';
    GET DIAGNOSTICS v_temp_count = ROW_COUNT;
    v_deleted_count := v_deleted_count + v_temp_count;
    
    DELETE FROM patient_cache 
    WHERE expires_at < NOW() - INTERVAL '1 day';
    GET DIAGNOSTICS v_temp_count = ROW_COUNT;
    v_deleted_count := v_deleted_count + v_temp_count;
    
    DELETE FROM service_match_cache 
    WHERE expires_at < NOW() 
       OR (usage_count < 3 AND cached_at < NOW() - INTERVAL '3 days');
    GET DIAGNOSTICS v_temp_count = ROW_COUNT;
    v_deleted_count := v_deleted_count + v_temp_count;
    
    DELETE FROM cache_statistics 
    WHERE stat_date < CURRENT_DATE - INTERVAL '30 days';
    
    RETURN v_deleted_count;
EXCEPTION
    WHEN OTHERS THEN
        RAISE WARNING 'Cache cleanup error: %', SQLERRM;
        RETURN 0;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION invalidate_clinic_cache(p_clinic_id uuid)
RETURNS void AS $$
BEGIN
    UPDATE availability_cache
    SET is_stale = true
    WHERE clinic_id = p_clinic_id;
    
    DELETE FROM booking_context_cache
    WHERE clinic_id = p_clinic_id;
    
    DELETE FROM patient_cache
    WHERE clinic_id = p_clinic_id;
    
    DELETE FROM service_match_cache
    WHERE clinic_id = p_clinic_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION create_monthly_partition()
RETURNS void AS $$
DECLARE
    start_date date;
    end_date date;
    partition_name text;
BEGIN
    start_date := DATE_TRUNC('month', CURRENT_DATE + INTERVAL '1 month');
    end_date := start_date + INTERVAL '1 month';
    partition_name := 'cache_statistics_' || TO_CHAR(start_date, 'YYYY_MM');
    
    IF NOT EXISTS (
        SELECT 1 FROM pg_tables 
        WHERE tablename = partition_name
    ) THEN
        EXECUTE format(
            'CREATE TABLE %I PARTITION OF cache_statistics FOR VALUES FROM (%L) TO (%L)',
            partition_name, start_date, end_date
        );
    END IF;
END;
$$ LANGUAGE plpgsql;

-- ==========================================
-- 7. ALL VIEWS
-- ==========================================

-- Phone lookup view (was missing)
CREATE OR REPLACE VIEW v_phone_lookup AS
SELECT 
    c.clinic_id,
    c.phone_number as clinic_phone,
    normalize_phone(c.phone_number) as clinic_phone_normalized,
    p.patient_id,
    p.phone_number as patient_phone,
    normalize_phone(p.phone_number) as patient_phone_normalized
FROM clinics c
LEFT JOIN patients p ON c.clinic_id = p.clinic_id;

-- Services with business
CREATE OR REPLACE VIEW v_available_services_with_business AS
SELECT 
    at.appointment_type_id,
    at.name as service_name,
    at.duration_minutes,
    bi.item_name,
    bi.price,
    p.practitioner_id,
    COALESCE(NULLIF(p.title, ''), '') || 
        CASE WHEN p.title IS NOT NULL AND p.title != '' THEN ' ' ELSE '' END ||
        p.first_name || ' ' || p.last_name as practitioner_name,
    b.business_id,
    b.business_name,
    b.is_primary,
    c.clinic_id,
    c.clinic_name
FROM appointment_types at
JOIN billable_items bi ON at.billable_item_id = bi.item_id
JOIN practitioner_appointment_types pat ON at.appointment_type_id = pat.appointment_type_id
JOIN practitioners p ON pat.practitioner_id = p.practitioner_id
JOIN practitioner_businesses pb ON p.practitioner_id = pb.practitioner_id
JOIN businesses b ON pb.business_id = b.business_id
JOIN clinics c ON at.clinic_id = c.clinic_id
WHERE at.active = true AND p.active = true;

-- Backward compatibility
CREATE OR REPLACE VIEW v_available_services AS
SELECT DISTINCT
    appointment_type_id,
    service_name,
    duration_minutes,
    item_name,
    price,
    practitioner_id,
    practitioner_name,
    clinic_id,
    clinic_name
FROM v_available_services_with_business;

-- Business lookup view (was missing)
CREATE OR REPLACE VIEW v_business_lookup AS
SELECT 
    b.business_id,
    b.business_name,
    b.is_primary,
    b.clinic_id,
    c.clinic_name,
    c.phone_number as clinic_phone,
    LOWER(b.business_name) as business_name_lower,
    CASE 
        WHEN b.is_primary THEN 'main,primary,first'
        ELSE ''
    END as business_aliases
FROM businesses b
JOIN clinics c ON b.clinic_id = c.clinic_id;

-- Practitioner locations
CREATE OR REPLACE VIEW v_practitioner_locations AS
SELECT 
    p.practitioner_id,
    COALESCE(NULLIF(p.title, ''), '') || 
        CASE WHEN p.title IS NOT NULL AND p.title != '' THEN ' ' ELSE '' END ||
        p.first_name || ' ' || p.last_name as practitioner_name,
    b.business_id,
    b.business_name,
    b.is_primary,
    p.clinic_id
FROM practitioners p
JOIN practitioner_businesses pb ON p.practitioner_id = pb.practitioner_id
JOIN businesses b ON pb.business_id = b.business_id
WHERE p.active = true;

-- Comprehensive services
CREATE OR REPLACE VIEW v_comprehensive_services AS
SELECT 
    at.appointment_type_id,
    at.name as service_name,
    at.duration_minutes,
    bi.item_name,
    bi.price,
    p.practitioner_id,
    COALESCE(NULLIF(p.title, ''), '') || 
        CASE WHEN p.title IS NOT NULL AND p.title != '' THEN ' ' ELSE '' END ||
        p.first_name || ' ' || p.last_name as practitioner_name,
    p.first_name as practitioner_first_name,
    p.last_name as practitioner_last_name,
    p.title as practitioner_title,
    b.business_id,
    b.business_name,
    b.is_primary as is_primary_location,
    c.clinic_id,
    c.clinic_name,
    c.phone_number as clinic_phone,
    LOWER(at.name) as service_name_search,
    LOWER(COALESCE(NULLIF(p.title, ''), '') || 
        CASE WHEN p.title IS NOT NULL AND p.title != '' THEN ' ' ELSE '' END ||
        p.first_name || ' ' || p.last_name) as practitioner_name_search,
    LOWER(p.first_name) as practitioner_first_search,
    LOWER(p.last_name) as practitioner_last_search,
    LOWER(b.business_name) as business_name_search
FROM appointment_types at
JOIN billable_items bi ON at.billable_item_id = bi.item_id
JOIN practitioner_appointment_types pat ON at.appointment_type_id = pat.appointment_type_id
JOIN practitioners p ON pat.practitioner_id = p.practitioner_id
JOIN practitioner_businesses pb ON p.practitioner_id = pb.practitioner_id
JOIN businesses b ON pb.business_id = b.business_id
JOIN clinics c ON at.clinic_id = c.clinic_id
WHERE at.active = true AND p.active = true;

-- ElevenLabs numbers view
CREATE OR REPLACE VIEW v_elevenlabs_numbers AS
SELECT 
    en.id,
    en.phone_number,
    en.phone_normalized,
    en.description,
    en.is_active,
    c.clinic_id,
    c.clinic_name,
    b.business_id,
    b.business_name,
    en.created_at,
    en.updated_at
FROM elevenlabs_numbers en
JOIN clinics c ON en.clinic_id = c.clinic_id
LEFT JOIN businesses b ON en.business_id = b.business_id
WHERE en.is_active = true
ORDER BY c.clinic_name, b.business_name, en.phone_number;

-- Location names view (was missing)
CREATE OR REPLACE VIEW v_location_names AS
SELECT 
    b.business_id,
    b.business_name,
    b.is_primary,
    c.clinic_id,
    c.clinic_name,
    ARRAY_AGG(DISTINCT la.alias ORDER BY la.alias) as aliases
FROM businesses b
JOIN clinics c ON b.clinic_id = c.clinic_id
LEFT JOIN location_aliases la ON b.business_id = la.business_id
GROUP BY b.business_id, b.business_name, b.is_primary, c.clinic_id, c.clinic_name
ORDER BY c.clinic_name, b.is_primary DESC, b.business_name;

-- Cache efficiency view
CREATE OR REPLACE VIEW v_cache_efficiency AS
SELECT 
    cache_type,
    DATE_TRUNC('hour', stat_date + '00:00:00'::time) as hour,
    SUM(hit_count) as hits,
    SUM(miss_count) as misses,
    ROUND(
        CASE 
            WHEN SUM(hit_count) + SUM(miss_count) = 0 THEN 0
            ELSE SUM(hit_count)::numeric / (SUM(hit_count) + SUM(miss_count)) * 100
        END, 2
    ) as hit_rate,
    SUM(api_calls_saved) as api_calls_saved,
    AVG(avg_response_time_ms) as avg_response_ms
FROM cache_statistics
WHERE stat_date >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY cache_type, DATE_TRUNC('hour', stat_date + '00:00:00'::time)
ORDER BY hour DESC, cache_type;

-- Cache status view
CREATE OR REPLACE VIEW v_cache_status AS
SELECT 
    'availability' as cache_type,
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE NOT is_stale AND expires_at > NOW()) as valid_entries,
    COUNT(*) FILTER (WHERE is_stale) as stale_entries,
    MIN(cached_at) as oldest_entry,
    MAX(cached_at) as newest_entry
FROM availability_cache
UNION ALL
SELECT 
    'booking_context' as cache_type,
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE expires_at > NOW()) as valid_entries,
    0 as stale_entries,
    MIN(cached_at) as oldest_entry,
    MAX(cached_at) as newest_entry
FROM booking_context_cache
UNION ALL
SELECT 
    'patient' as cache_type,
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE expires_at > NOW()) as valid_entries,
    0 as stale_entries,
    MIN(cached_at) as oldest_entry,
    MAX(cached_at) as newest_entry
FROM patient_cache
UNION ALL
SELECT 
    'service_match' as cache_type,
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE expires_at > NOW()) as valid_entries,
    0 as stale_entries,
    MIN(cached_at) as oldest_entry,
    MAX(cached_at) as newest_entry
FROM service_match_cache;

-- Availability cache details view
CREATE OR REPLACE VIEW v_availability_cache_details AS
SELECT 
    ac.cache_id,
    ac.date,
    p.practitioner_id,
    COALESCE(
        CONCAT(NULLIF(p.title, ''), ' ', p.first_name, ' ', p.last_name),
        CONCAT(p.first_name, ' ', p.last_name)
    ) as practitioner_name,
    b.business_id,
    b.business_name,
    ac.available_slots,
    jsonb_array_length(ac.available_slots) as slot_count,
    ac.cached_at,
    ac.expires_at,
    ac.is_stale,
    c.clinic_name
FROM availability_cache ac
JOIN practitioners p ON ac.practitioner_id = p.practitioner_id
JOIN businesses b ON ac.business_id = b.business_id
JOIN clinics c ON ac.clinic_id = c.clinic_id
WHERE ac.date >= CURRENT_DATE
ORDER BY ac.date, p.last_name, p.first_name;

-- ==========================================
-- 8. ALL TRIGGERS
-- ==========================================

-- Clinic phone lookup trigger
DROP TRIGGER IF EXISTS update_phone_lookup_after_clinic_insert ON clinics;
CREATE TRIGGER update_phone_lookup_after_clinic_insert
AFTER INSERT OR UPDATE ON clinics
FOR EACH ROW EXECUTE FUNCTION update_phone_lookup_on_clinic();

-- ElevenLabs sync trigger
DROP TRIGGER IF EXISTS sync_elevenlabs_numbers ON elevenlabs_numbers;
CREATE TRIGGER sync_elevenlabs_numbers
AFTER INSERT OR UPDATE OR DELETE ON elevenlabs_numbers
FOR EACH ROW EXECUTE FUNCTION sync_elevenlabs_to_lookup();

-- Location aliases trigger
DROP TRIGGER IF EXISTS add_location_aliases_on_business ON businesses;
CREATE TRIGGER add_location_aliases_on_business
AFTER INSERT ON businesses
FOR EACH ROW EXECUTE FUNCTION add_default_location_aliases();

-- Cache invalidation trigger
DROP TRIGGER IF EXISTS invalidate_cache_on_appointment ON appointments;
CREATE TRIGGER invalidate_cache_on_appointment
AFTER INSERT OR UPDATE OR DELETE ON appointments
FOR EACH ROW EXECUTE FUNCTION invalidate_availability_cache();

-- ==========================================
-- 9. RLS POLICIES (Complete for all tables)
-- ==========================================

-- Enable RLS on all tables
ALTER TABLE clinics ENABLE ROW LEVEL SECURITY;
ALTER TABLE businesses ENABLE ROW LEVEL SECURITY;
ALTER TABLE practitioners ENABLE ROW LEVEL SECURITY;
ALTER TABLE billable_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE appointment_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_bookings ENABLE ROW LEVEL SECURITY;
ALTER TABLE phone_lookup ENABLE ROW LEVEL SECURITY;
ALTER TABLE practitioner_businesses ENABLE ROW LEVEL SECURITY;
ALTER TABLE practitioner_appointment_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE availability_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE booking_context_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE patient_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE service_match_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE cache_statistics ENABLE ROW LEVEL SECURITY;
ALTER TABLE location_aliases ENABLE ROW LEVEL SECURITY;
ALTER TABLE elevenlabs_numbers ENABLE ROW LEVEL SECURITY;

-- Create policies for all tables (service role access)
DO $$
DECLARE
    t text;
BEGIN
    FOR t IN 
        SELECT tablename FROM pg_tables 
        WHERE schemaname = 'public' 
        AND tablename IN (
            'clinics', 'businesses', 'practitioners', 'billable_items',
            'appointment_types', 'patients', 'appointments', 'voice_bookings',
            'phone_lookup', 'practitioner_businesses', 'practitioner_appointment_types',
            'availability_cache', 'booking_context_cache', 'patient_cache',
            'service_match_cache', 'cache_statistics', 'location_aliases',
            'elevenlabs_numbers'
        )
    LOOP
        EXECUTE format('
            DO $inner$
BEGIN
    IF NOT EXISTS (
                    SELECT 1 FROM pg_policies 
                    WHERE tablename = %L AND policyname = %L
    ) THEN
                    CREATE POLICY "Service role access" ON %I 
                    FOR ALL USING (auth.role() = %L);
    END IF;
            END $inner$;
        ', t, 'Service role access', t, 'service_role');
    END LOOP;
END;
$$;

-- ==========================================
-- 10. INITIAL SETUP & DATA
-- ==========================================

-- Create initial partitions for cache_statistics
DO $$
DECLARE
    i integer;
    start_date date;
    end_date date;
    partition_name text;
BEGIN
    FOR i IN 0..2 LOOP
        start_date := DATE_TRUNC('month', CURRENT_DATE + (i || ' months')::interval);
        end_date := start_date + INTERVAL '1 month';
        partition_name := 'cache_statistics_' || TO_CHAR(start_date, 'YYYY_MM');
        
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables 
            WHERE tablename = partition_name
        ) THEN
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I PARTITION OF cache_statistics FOR VALUES FROM (%L) TO (%L)',
                partition_name, start_date, end_date
            );
        END IF;
    END LOOP;
END;
$$;

-- Backfill aliases for any existing businesses
DO $$
DECLARE
    biz RECORD;
BEGIN
    -- Add aliases for all existing businesses
    FOR biz IN SELECT business_id, business_name, is_primary FROM businesses
    LOOP
        -- Primary location aliases
        IF biz.is_primary THEN
            INSERT INTO location_aliases (business_id, alias)
            VALUES 
                (biz.business_id, 'main'),
                (biz.business_id, 'primary'),
                (biz.business_id, 'main clinic')
            ON CONFLICT DO NOTHING;
        END IF;
        
        -- Common variations
        INSERT INTO location_aliases (business_id, alias)
        VALUES
            (biz.business_id, LOWER(biz.business_name)),
            (biz.business_id, REPLACE(LOWER(biz.business_name), ' clinic', '')),
            (biz.business_id, REPLACE(LOWER(biz.business_name), ' branch', ''))
        ON CONFLICT DO NOTHING;
    END LOOP;
END;
$$;

-- ==========================================
-- FINAL VALIDATION
-- ==========================================
DO $$
BEGIN
    RAISE NOTICE 'Schema deployment complete. Run the following to verify:';
    RAISE NOTICE 'SELECT COUNT(*) as table_count FROM pg_tables WHERE schemaname = ''public'';';
    RAISE NOTICE 'SELECT COUNT(*) as view_count FROM pg_views WHERE schemaname = ''public'';';
    RAISE NOTICE 'SELECT COUNT(*) as function_count FROM pg_proc WHERE pronamespace = ''public''::regnamespace;';
END;
$$;

CREATE EXTENSION IF NOT EXISTS pg_trgm;
ALTER TABLE appointments 
DROP CONSTRAINT appointments_patient_id_fkey;

CREATE TABLE IF NOT EXISTS failed_booking_attempts (
    clinic_id uuid NOT NULL,
    practitioner_id text NOT NULL,
    business_id text NOT NULL,
    appointment_date date NOT NULL,
    appointment_time time NOT NULL,
    failure_reason text,
    created_at timestamptz DEFAULT NOW(),
    PRIMARY KEY (practitioner_id, business_id, appointment_date, appointment_time)
);

CREATE INDEX idx_failed_booking_recent 
ON failed_booking_attempts(created_at) 
WHERE created_at > NOW() - INTERVAL '2 hours';

-- Production-ready cache schema improvements
-- Run these to prevent caching issues in production

-- 1. Add indexes for faster cache lookups
CREATE INDEX IF NOT EXISTS idx_availability_cache_clinic_date 
ON availability_cache(clinic_id, date, practitioner_id) 
WHERE NOT is_stale AND expires_at > NOW();

CREATE INDEX IF NOT EXISTS idx_patient_cache_phone_clinic 
ON patient_cache(phone_normalized, clinic_id) 
WHERE expires_at > NOW();

CREATE INDEX IF NOT EXISTS idx_service_match_cache_usage 
ON service_match_cache(clinic_id, usage_count DESC) 
WHERE expires_at > NOW();

-- 2. Add cache performance monitoring table
CREATE TABLE IF NOT EXISTS cache_performance_log (
    id SERIAL PRIMARY KEY,
    operation_type VARCHAR(50) NOT NULL, -- 'read', 'write', 'invalidate'
    cache_type VARCHAR(50) NOT NULL,
    response_time_ms NUMERIC,
    cache_size_bytes INTEGER,
    hit_ratio NUMERIC,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_cache_performance_time ON cache_performance_log(created_at DESC);

-- 3. Add automatic cache cleanup for old entries
CREATE OR REPLACE FUNCTION auto_cleanup_expired_cache()
RETURNS void AS $$
DECLARE
    v_deleted_availability INTEGER;
    v_deleted_patient INTEGER;
    v_deleted_service INTEGER;
    v_deleted_context INTEGER;
BEGIN
    -- Delete expired availability cache entries older than 1 day
    DELETE FROM availability_cache 
    WHERE expires_at < NOW() - INTERVAL '1 day'
    OR (is_stale AND cached_at < NOW() - INTERVAL '3 days');
    GET DIAGNOSTICS v_deleted_availability = ROW_COUNT;
    
    -- Delete expired patient cache entries
    DELETE FROM patient_cache 
    WHERE expires_at < NOW() - INTERVAL '7 days';
    GET DIAGNOSTICS v_deleted_patient = ROW_COUNT;
    
    -- Delete low-usage service match cache
    DELETE FROM service_match_cache 
    WHERE expires_at < NOW() 
    OR (usage_count < 5 AND cached_at < NOW() - INTERVAL '30 days');
    GET DIAGNOSTICS v_deleted_service = ROW_COUNT;
    
    -- Delete old booking context
    DELETE FROM booking_context_cache 
    WHERE expires_at < NOW() - INTERVAL '1 day';
    GET DIAGNOSTICS v_deleted_context = ROW_COUNT;
    
    -- Log cleanup results
    INSERT INTO cache_performance_log (operation_type, cache_type, response_time_ms)
    VALUES ('cleanup', 'all', v_deleted_availability + v_deleted_patient + v_deleted_service + v_deleted_context);
    
    RAISE NOTICE 'Cache cleanup: % availability, % patient, % service, % context entries deleted',
        v_deleted_availability, v_deleted_patient, v_deleted_service, v_deleted_context;
END;
$$ LANGUAGE plpgsql;

-- 4. Schedule automatic cleanup (using pg_cron if available, otherwise call periodically)
-- If you have pg_cron extension:
-- SELECT cron.schedule('cache-cleanup', '0 3 * * *', 'SELECT auto_cleanup_expired_cache()');

-- 5. Add cache warmup tracking
CREATE TABLE IF NOT EXISTS cache_warmup_log (
    id SERIAL PRIMARY KEY,
    clinic_id UUID NOT NULL REFERENCES clinics(clinic_id),
    warmup_type VARCHAR(50) NOT NULL, -- 'on_call', 'scheduled', 'manual'
    practitioners_warmed INTEGER DEFAULT 0,
    days_warmed INTEGER DEFAULT 0,
    total_slots_cached INTEGER DEFAULT 0,
    duration_ms INTEGER,
    success BOOLEAN DEFAULT true,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_cache_warmup_clinic_time ON cache_warmup_log(clinic_id, created_at DESC);

-- 6. Add conflict prevention table for concurrent bookings
CREATE TABLE IF NOT EXISTS booking_locks (
    practitioner_id TEXT NOT NULL,
    appointment_start TIMESTAMPTZ NOT NULL,
    session_id TEXT NOT NULL,
    locked_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '2 minutes',
    PRIMARY KEY (practitioner_id, appointment_start)
);

CREATE INDEX idx_booking_locks_expires ON booking_locks(expires_at);

-- 7. Function to acquire booking lock
CREATE OR REPLACE FUNCTION acquire_booking_lock(
    p_practitioner_id TEXT,
    p_appointment_start TIMESTAMPTZ,
    p_session_id TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_lock_acquired BOOLEAN;
BEGIN
    -- Clean expired locks first
    DELETE FROM booking_locks WHERE expires_at < NOW();
    
    -- Try to acquire lock
    INSERT INTO booking_locks (practitioner_id, appointment_start, session_id)
    VALUES (p_practitioner_id, p_appointment_start, p_session_id)
    ON CONFLICT (practitioner_id, appointment_start) DO NOTHING;
    
    GET DIAGNOSTICS v_lock_acquired = ROW_COUNT > 0;
    
    RETURN v_lock_acquired;
END;
$$ LANGUAGE plpgsql;

-- 8. Add cache hit rate view for monitoring
CREATE OR REPLACE VIEW v_cache_hit_rates AS
SELECT 
    cache_type,
    DATE_TRUNC('hour', NOW()) as hour,
    SUM(hit_count) as hits,
    SUM(miss_count) as misses,
    CASE 
        WHEN SUM(hit_count) + SUM(miss_count) = 0 THEN 0
        ELSE ROUND(100.0 * SUM(hit_count) / (SUM(hit_count) + SUM(miss_count)), 2)
    END as hit_rate_pct,
    SUM(api_calls_saved) as api_calls_saved
FROM cache_statistics
WHERE stat_date = CURRENT_DATE
GROUP BY cache_type;

-- 9. Add monitoring for slow cache operations
CREATE TABLE IF NOT EXISTS cache_slow_queries (
    id SERIAL PRIMARY KEY,
    operation TEXT NOT NULL,
    duration_ms NUMERIC NOT NULL,
    cache_type VARCHAR(50),
    query_details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_cache_slow_queries_time ON cache_slow_queries(created_at DESC);

-- 10. Add cache size monitoring
CREATE OR REPLACE VIEW v_cache_sizes AS
SELECT 
    'availability_cache' as cache_name,
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE NOT is_stale AND expires_at > NOW()) as valid_entries,
    pg_size_pretty(pg_relation_size('availability_cache')) as table_size
FROM availability_cache
UNION ALL
SELECT 
    'patient_cache' as cache_name,
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE expires_at > NOW()) as valid_entries,
    pg_size_pretty(pg_relation_size('patient_cache')) as table_size
FROM patient_cache
UNION ALL
SELECT 
    'service_match_cache' as cache_name,
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE expires_at > NOW()) as valid_entries,
    pg_size_pretty(pg_relation_size('service_match_cache')) as table_size
FROM service_match_cache;

-- 11. Alert thresholds
CREATE TABLE IF NOT EXISTS cache_alert_thresholds (
    id SERIAL PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL UNIQUE,
    threshold_value NUMERIC NOT NULL,
    alert_enabled BOOLEAN DEFAULT true,
    description TEXT
);

-- Insert default thresholds
INSERT INTO cache_alert_thresholds (metric_name, threshold_value, description) VALUES
('min_hit_rate_pct', 70, 'Alert if cache hit rate falls below 70%'),
('max_cache_size_mb', 1000, 'Alert if total cache size exceeds 1GB'),
('max_response_time_ms', 100, 'Alert if cache response time exceeds 100ms'),
('max_stale_entries_pct', 30, 'Alert if more than 30% of entries are stale')
ON CONFLICT (metric_name) DO NOTHING;

-- 12. Add connection pooling recommendations as comments
COMMENT ON TABLE availability_cache IS 'Main availability cache. For production: Use connection pooling with min_size=10, max_size=50';
COMMENT ON TABLE cache_statistics IS 'Cache performance stats. Partitioned by month. Monitor partition size and create new partitions monthly';

-- 13. Create function to monitor cache health
CREATE OR REPLACE FUNCTION check_cache_health()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    details TEXT
) AS $$
BEGIN
    -- Check hit rate
    RETURN QUERY
    SELECT 
        'Cache Hit Rate'::TEXT,
        CASE 
            WHEN AVG(CASE WHEN hit_count + miss_count = 0 THEN 0 
                         ELSE hit_count::numeric / (hit_count + miss_count) * 100 END) > 70 
            THEN 'OK'::TEXT 
            ELSE 'WARNING'::TEXT 
        END,
        'Average: ' || ROUND(AVG(CASE WHEN hit_count + miss_count = 0 THEN 0 
                                      ELSE hit_count::numeric / (hit_count + miss_count) * 100 END), 2) || '%'
    FROM cache_statistics
    WHERE stat_date >= CURRENT_DATE - INTERVAL '1 day';
    
    -- Check stale entries
    RETURN QUERY
    SELECT 
        'Stale Entries'::TEXT,
        CASE 
            WHEN COUNT(*) FILTER (WHERE is_stale) * 100.0 / NULLIF(COUNT(*), 0) < 30 
            THEN 'OK'::TEXT 
            ELSE 'WARNING'::TEXT 
        END,
        'Stale: ' || COUNT(*) FILTER (WHERE is_stale) || ' of ' || COUNT(*) || ' entries'
    FROM availability_cache;
    
    -- Check cache size
    RETURN QUERY
    SELECT 
        'Cache Size'::TEXT,
        CASE 
            WHEN pg_database_size(current_database()) < 1000000000 
            THEN 'OK'::TEXT 
            ELSE 'WARNING'::TEXT 
        END,
        'Total DB size: ' || pg_size_pretty(pg_database_size(current_database()));
END;
$$ LANGUAGE plpgsql;

-- Recreate v_cache_status
CREATE OR REPLACE VIEW v_cache_status AS
SELECT 
    'availability' as cache_type,
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE NOT is_stale AND expires_at > NOW() AT TIME ZONE 'UTC') as valid_entries,
    COUNT(*) FILTER (WHERE is_stale) as stale_entries,
    MIN(cached_at) as oldest_entry,
    MAX(cached_at) as newest_entry
FROM availability_cache
UNION ALL
SELECT 
    'booking_context' as cache_type,
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE expires_at > NOW() AT TIME ZONE 'UTC') as valid_entries,
    0 as stale_entries,
    MIN(cached_at) as oldest_entry,
    MAX(cached_at) as newest_entry
FROM booking_context_cache
UNION ALL
SELECT 
    'patient' as cache_type,
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE expires_at > NOW() AT TIME ZONE 'UTC') as valid_entries,
    0 as stale_entries,
    MIN(cached_at) as oldest_entry,
    MAX(cached_at) as newest_entry
FROM patient_cache
UNION ALL
SELECT 
    'service_match' as cache_type,
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE expires_at > NOW() AT TIME ZONE 'UTC') as valid_entries,
    0 as stale_entries,
    MIN(cached_at) as oldest_entry,
    MAX(cached_at) as newest_entry
FROM service_match_cache;

-- Recreate v_cache_efficiency
CREATE OR REPLACE VIEW v_cache_efficiency AS
SELECT 
    cache_type,
    DATE_TRUNC('hour', stat_date + '00:00:00'::time) as hour,
    SUM(hit_count) as hits,
    SUM(miss_count) as misses,
    ROUND(
        CASE 
            WHEN SUM(hit_count) + SUM(miss_count) = 0 THEN 0
            ELSE SUM(hit_count)::numeric / (SUM(hit_count) + SUM(miss_count)) * 100
        END, 2
    ) as hit_rate,
    SUM(api_calls_saved) as api_calls_saved,
    AVG(avg_response_time_ms) as avg_response_ms
FROM cache_statistics
WHERE stat_date >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY cache_type, DATE_TRUNC('hour', stat_date + '00:00:00'::time)
ORDER BY hour DESC, cache_type;

-- Recreate v_availability_cache_details
CREATE OR REPLACE VIEW v_availability_cache_details AS
SELECT 
    ac.cache_id,
    ac.date,
    p.practitioner_id,
    COALESCE(
        CONCAT(NULLIF(p.title, ''), ' ', p.first_name, ' ', p.last_name),
        CONCAT(p.first_name, ' ', p.last_name)
    ) as practitioner_name,
    b.business_id,
    b.business_name,
    ac.available_slots,
    jsonb_array_length(ac.available_slots) as slot_count,
    ac.cached_at AT TIME ZONE 'UTC' as cached_at_utc,
    ac.cached_at AT TIME ZONE 'Australia/Sydney' as cached_at_local,
    ac.expires_at AT TIME ZONE 'UTC' as expires_at_utc,
    ac.expires_at AT TIME ZONE 'Australia/Sydney' as expires_at_local,
    ac.is_stale,
    c.clinic_name
FROM availability_cache ac
JOIN practitioners p ON ac.practitioner_id = p.practitioner_id
JOIN businesses b ON ac.business_id = b.business_id
JOIN clinics c ON ac.clinic_id = c.clinic_id
WHERE ac.date >= CURRENT_DATE
ORDER BY ac.date, p.last_name, p.first_name;

-- Recreate v_cache_hit_rates
CREATE OR REPLACE VIEW v_cache_hit_rates AS
SELECT 
    cache_type,
    DATE_TRUNC('hour', NOW() AT TIME ZONE 'UTC') as hour,
    SUM(hit_count) as hits,
    SUM(miss_count) as misses,
    CASE 
        WHEN SUM(hit_count) + SUM(miss_count) = 0 THEN 0
        ELSE ROUND(100.0 * SUM(hit_count) / (SUM(hit_count) + SUM(miss_count)), 2)
    END as hit_rate_pct,
    SUM(api_calls_saved) as api_calls_saved
FROM cache_statistics
WHERE stat_date = (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date
GROUP BY cache_type;

-- Drop views that depend on the cache tables
DROP VIEW IF EXISTS v_cache_status CASCADE;
DROP VIEW IF EXISTS v_cache_efficiency CASCADE;
DROP VIEW IF EXISTS v_availability_cache_details CASCADE;
DROP VIEW IF EXISTS v_cache_sizes CASCADE;
DROP VIEW IF EXISTS v_cache_hit_rates CASCADE;

-- Now alter the columns
ALTER TABLE availability_cache 
ALTER COLUMN cached_at TYPE timestamptz USING cached_at AT TIME ZONE 'UTC',
ALTER COLUMN expires_at TYPE timestamptz USING expires_at AT TIME ZONE 'UTC';

-- Also update other cache tables while we're at it
ALTER TABLE booking_context_cache
ALTER COLUMN cached_at TYPE timestamptz USING cached_at AT TIME ZONE 'UTC',
ALTER COLUMN expires_at TYPE timestamptz USING expires_at AT TIME ZONE 'UTC',
ALTER COLUMN last_accessed TYPE timestamptz USING last_accessed AT TIME ZONE 'UTC';

ALTER TABLE patient_cache
ALTER COLUMN cached_at TYPE timestamptz USING cached_at AT TIME ZONE 'UTC',
ALTER COLUMN expires_at TYPE timestamptz USING expires_at AT TIME ZONE 'UTC';

ALTER TABLE service_match_cache
ALTER COLUMN cached_at TYPE timestamptz USING cached_at AT TIME ZONE 'UTC',
ALTER COLUMN expires_at TYPE timestamptz USING expires_at AT TIME ZONE 'UTC';

-- Recreate v_cache_sizes
CREATE OR REPLACE VIEW v_cache_sizes AS
SELECT 
    'availability_cache' as cache_name,
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE NOT is_stale AND expires_at > NOW() AT TIME ZONE 'UTC') as valid_entries,
    pg_size_pretty(pg_relation_size('availability_cache')) as table_size
FROM availability_cache
UNION ALL
SELECT 
    'patient_cache' as cache_name,
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE expires_at > NOW() AT TIME ZONE 'UTC') as valid_entries,
    pg_size_pretty(pg_relation_size('patient_cache')) as table_size
FROM patient_cache
UNION ALL
SELECT 
    'service_match_cache' as cache_name,
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE expires_at > NOW() AT TIME ZONE 'UTC') as valid_entries,
    pg_size_pretty(pg_relation_size('service_match_cache')) as table_size
FROM service_match_cache
UNION ALL
SELECT 
    'booking_context_cache' as cache_name,
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE expires_at > NOW() AT TIME ZONE 'UTC') as valid_entries,
    pg_size_pretty(pg_relation_size('booking_context_cache')) as table_size
FROM booking_context_cache;

-- Optional: Add a function to validate timezone
CREATE OR REPLACE FUNCTION validate_timezone(tz TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    PERFORM '2023-01-01'::date AT TIME ZONE tz;
    RETURN TRUE;
EXCEPTION
    WHEN OTHERS THEN
        RETURN FALSE;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Add constraint to ensure valid timezone
ALTER TABLE clinics 
ADD CONSTRAINT valid_timezone CHECK (validate_timezone(timezone));

-- Example update for testing
-- UPDATE clinics 
-- SET timezone = 'America/New_York' 
-- WHERE clinic_name = 'Test US Clinic';

-- Verify the change
SELECT 
    clinic_id,
    clinic_name,
    timezone,
    NOW() AT TIME ZONE timezone as clinic_current_time
FROM clinics;