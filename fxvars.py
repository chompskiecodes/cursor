#!/usr/bin/env python3
"""
Fix inconsistent environment variable names in the codebase
"""

import os
import re

def fix_env_vars_in_file(filepath):
    """Fix environment variable references in a single file"""
    
    # Mapping of old names to new consistent names
    replacements = {
        # Database URLs - standardize on DATABASE_URL
        r'os\.environ\.get\(["\']SUPABASE_DB_URL["\']\)': 'os.environ.get("DATABASE_URL")',
        r'os\.getenv\(["\']SUPABASE_DB_URL["\']\)': 'os.getenv("DATABASE_URL")',
        
        # Remove fallback checks for SUPABASE_DB_URL
        r'os\.environ\.get\(["\']SUPABASE_DB_URL["\']\)\s*or\s*os\.environ\.get\(["\']DATABASE_URL["\']\)': 'os.environ.get("DATABASE_URL")',
        r'os\.getenv\(["\']SUPABASE_DB_URL["\']\)\s*or\s*os\.getenv\(["\']DATABASE_URL["\']\)': 'os.getenv("DATABASE_URL")',
        
        # In case there are direct references
        r'supabase_db_url\s*=\s*os\.environ\.get\(["\']SUPABASE_DB_URL["\']\)': '# Removed - use database_url instead',
        r'if\s+supabase_db_url:': 'if False:  # Removed supabase_db_url check',
    }
    
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return False
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    changes_made = []
    
    for pattern, replacement in replacements.items():
        matches = re.findall(pattern, content)
        if matches:
            content = re.sub(pattern, replacement, content)
            changes_made.append(f"  - Replaced {len(matches)} instances of: {pattern[:50]}...")
    
    if content != original_content:
        # Create backup
        backup_path = f"{filepath}.backup"
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(original_content)
        
        # Write fixed content
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"✅ Fixed {filepath}")
        for change in changes_made:
            print(change)
        print(f"   Backup saved to: {backup_path}")
        return True
    else:
        print(f"ℹ️  No changes needed in {filepath}")
        return False

def show_current_env_usage():
    """Show how environment variables are currently being used"""
    print("=== CURRENT ENVIRONMENT VARIABLE USAGE ===\n")
    
    # Check what's in .env
    if os.path.exists('.env'):
        print("📄 .env file contains:")
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    var_name = line.split('=')[0]
                    print(f"  - {var_name}")
        print()
    
    # Check what the code expects
    print("📝 Recommended .env file:")
    print("""
# Database Configuration
DATABASE_URL=postgresql://postgres.xdnjnrrnehximkxteidq:sbS1llyw3rd@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres

# Supabase Configuration  
SUPABASE_URL=https://xdnjnrrnehximkxteidq.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# API Security
API_KEY=your-secure-api-key-here

# Cliniko Configuration (if needed for scripts)
CLINIKO_API_KEY=MS0xNzAyMDE4MzQ3NzQ0MzcyMjM4...
CLINIKO_SHARD=au4

# Application Settings
ENVIRONMENT=development
LOG_LEVEL=INFO
DB_POOL_SIZE_MIN=10
DB_POOL_SIZE_MAX=20
""")

def main():
    """Main function"""
    print("=== ENVIRONMENT VARIABLE FIX TOOL ===\n")
    
    # Show current usage
    show_current_env_usage()
    
    # Files to check and fix
    files_to_fix = [
        'main.py',
        'initialize_clinic.py',
        'test_db.py',
        'test_api.py',
        'onboard_single_clinic.py'
    ]
    
    print("\n=== FIXING FILES ===")
    fixed_count = 0
    
    for filepath in files_to_fix:
        if fix_env_vars_in_file(filepath):
            fixed_count += 1
    
    print(f"\n✅ Fixed {fixed_count} files")
    
    if fixed_count > 0:
        print("\n⚠️  IMPORTANT: Review the changes and test your application!")
        print("   Backups have been created with .backup extension")

if __name__ == "__main__":
    main()