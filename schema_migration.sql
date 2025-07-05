-- ==========================================
-- SCHEMA MIGRATION SCRIPT
-- Fixes missing columns and constraints for voice booking system
-- ==========================================

-- ==========================================
-- 1. ADD MISSING COLUMNS
-- ==========================================

-- 1.1 Add 'active' column to patients table
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'patients' AND column_name = 'active'
    ) THEN
        ALTER TABLE patients ADD COLUMN active boolean DEFAULT true;
        RAISE NOTICE 'Added active column to patients table';
    ELSE
        RAISE NOTICE 'active column already exists in patients table';
    END IF;
END $$;

-- 1.2 Add index for active patients
CREATE INDEX IF NOT EXISTS idx_patients_active ON patients(clinic_id, active) WHERE active = true;

-- ==========================================
-- 2. ENSURE APPOINTMENT TYPES EXIST
-- ==========================================

-- 2.1 Add missing appointment type if it doesn't exist
-- This handles the foreign key constraint error for appointment_type_id = 1701928805452490131
DO $$
DECLARE
    clinic_uuid uuid;
BEGIN
    -- Get the clinic ID (assuming there's at least one clinic)
    SELECT clinic_id INTO clinic_uuid FROM clinics LIMIT 1;
    
    IF clinic_uuid IS NOT NULL THEN
        -- Insert the missing appointment type if it doesn't exist
        INSERT INTO appointment_types (
            appointment_type_id,
            clinic_id,
            name,
            duration_minutes,
            active
        ) VALUES (
            '1701928805452490131',
            clinic_uuid,
            'Default Appointment',
            30,
            true
        ) ON CONFLICT (appointment_type_id) DO NOTHING;
        
        RAISE NOTICE 'Ensured default appointment type exists';
    ELSE
        RAISE NOTICE 'No clinics found - cannot create default appointment type';
    END IF;
END $$;

-- ==========================================
-- 3. ADD MISSING CONSTRAINTS AND INDEXES
-- ==========================================

-- 3.1 Ensure unique constraint on patient clinic+phone exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'uq_patient_clinic_phone'
          AND table_name = 'patients'
    ) THEN
        ALTER TABLE patients 
        ADD CONSTRAINT uq_patient_clinic_phone UNIQUE (clinic_id, phone_number);
        RAISE NOTICE 'Added unique constraint on patient clinic+phone';
    ELSE
        RAISE NOTICE 'Unique constraint on patient clinic+phone already exists';
    END IF;
END $$;

-- 3.2 Add missing indexes for better performance
CREATE INDEX IF NOT EXISTS idx_appointments_appointment_type_id ON appointments(appointment_type_id);
CREATE INDEX IF NOT EXISTS idx_appointments_clinic_date ON appointments(clinic_id, starts_at);

-- ==========================================
-- 4. DATA CLEANUP AND VALIDATION
-- ==========================================

-- 4.1 Update any patients without active status to be active
UPDATE patients SET active = true WHERE active IS NULL;

-- 4.2 Ensure all appointments have valid status
UPDATE appointments 
SET status = 'booked' 
WHERE status IS NULL OR status NOT IN ('booked', 'confirmed', 'cancelled', 'completed');

-- ==========================================
-- 5. VERIFICATION QUERIES
-- ==========================================

-- 5.1 Check if all required columns exist
SELECT 
    'patients' as table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'patients' 
ORDER BY ordinal_position;

-- 5.2 Check appointment types
SELECT 
    'appointment_types' as table_name,
    COUNT(*) as total_types,
    COUNT(*) FILTER (WHERE active = true) as active_types
FROM appointment_types;

-- 5.3 Check for orphaned appointments (missing appointment types)
SELECT 
    'orphaned_appointments' as check_type,
    COUNT(*) as count
FROM appointments a
LEFT JOIN appointment_types at ON a.appointment_type_id = at.appointment_type_id
WHERE a.appointment_type_id IS NOT NULL 
  AND at.appointment_type_id IS NULL;

-- 5.4 Check for orphaned appointments (missing patients)
SELECT 
    'orphaned_appointments_no_patient' as check_type,
    COUNT(*) as count
FROM appointments a
LEFT JOIN patients p ON a.patient_id = p.patient_id
WHERE a.patient_id IS NOT NULL 
  AND p.patient_id IS NULL;

-- 5.5 Check for orphaned appointments (missing practitioners)
SELECT 
    'orphaned_appointments_no_practitioner' as check_type,
    COUNT(*) as count
FROM appointments a
LEFT JOIN practitioners pr ON a.practitioner_id = pr.practitioner_id
WHERE a.practitioner_id IS NOT NULL 
  AND pr.practitioner_id IS NULL;

-- 5.6 Check for orphaned appointments (missing businesses)
SELECT 
    'orphaned_appointments_no_business' as check_type,
    COUNT(*) as count
FROM appointments a
LEFT JOIN businesses b ON a.business_id = b.business_id
WHERE a.business_id IS NOT NULL 
  AND b.business_id IS NULL;

-- ==========================================
-- 6. MIGRATION COMPLETION
-- ==========================================

DO $$
BEGIN
    RAISE NOTICE 'Schema migration completed successfully!';
    RAISE NOTICE 'Please review the verification queries above for any data issues.';
END $$; 