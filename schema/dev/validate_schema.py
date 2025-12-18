#!/usr/bin/env python3
"""
Uderia Prompt Management System - Schema Validation Tool

This script validates the database schema and provides utilities for:
- Schema validation (syntax, constraints, foreign keys)
- Database integration with existing tda_auth.db
- Integrity checking
- Test data generation

Usage:
    python validate_schema.py --validate-only
    python validate_schema.py --integrate /path/to/tda_auth.db
    python validate_schema.py --integrate /path/to/tda_auth.db --with-test-data
    
Note: This script integrates with existing tda_auth.db, not creating a new database.
      It will add prompt management tables to the existing database.
"""

import sqlite3
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent
SCHEMA_DIR = PROJECT_ROOT / "schema"

# Schema files in execution order
SCHEMA_FILES = [
    "00_master.sql",                # Schema version tracking
    "01_core_tables.sql",
    "02_parameters.sql",
    "03_profile_integration.sql",
    "04_indexes.sql",
    "05_views.sql"
]

class Colors:
    """ANSI color codes for terminal output"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_success(message):
    """Print success message in green"""
    print(f"{Colors.GREEN}✓ {message}{Colors.RESET}")

def print_error(message):
    """Print error message in red"""
    print(f"{Colors.RED}✗ {message}{Colors.RESET}")

def print_info(message):
    """Print info message in blue"""
    print(f"{Colors.BLUE}ℹ {message}{Colors.RESET}")

def print_warning(message):
    """Print warning message in yellow"""
    print(f"{Colors.YELLOW}⚠ {message}{Colors.RESET}")

def print_section(title):
    """Print section header"""
    print(f"\n{Colors.BOLD}{'=' * 70}{Colors.RESET}")
    print(f"{Colors.BOLD}{title}{Colors.RESET}")
    print(f"{Colors.BOLD}{'=' * 70}{Colors.RESET}\n")

def read_schema_file(filename):
    """Read and return schema file content"""
    filepath = SCHEMA_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Schema file not found: {filepath}")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

def validate_schema_syntax():
    """Validate SQL syntax of all schema files"""
    print_section("Schema Syntax Validation")
    
    errors = []
    
    # Create single in-memory database for cumulative validation
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    
    for schema_file in SCHEMA_FILES:
        try:
            content = read_schema_file(schema_file)
            
            # Execute schema (cumulative - each file builds on previous)
            cursor.executescript(content)
            
            print_success(f"{schema_file}: Syntax valid")
            
        except sqlite3.Error as e:
            error_msg = f"{schema_file}: {str(e)}"
            print_error(error_msg)
            errors.append(error_msg)
        except FileNotFoundError as e:
            error_msg = str(e)
            print_error(error_msg)
            errors.append(error_msg)
    
    conn.close()
    return len(errors) == 0, errors

def validate_foreign_keys():
    """Validate foreign key relationships"""
    print_section("Foreign Key Validation")
    
    # Create temporary database with all schema
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    
    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")
    
    # Load all schema files
    for schema_file in SCHEMA_FILES:
        content = read_schema_file(schema_file)
        cursor.executescript(content)
    
    # Check foreign key integrity
    cursor.execute("PRAGMA foreign_key_check")
    fk_violations = cursor.fetchall()
    
    if fk_violations:
        print_error(f"Found {len(fk_violations)} foreign key violations")
        for violation in fk_violations:
            print(f"  {violation}")
        return False
    else:
        print_success("All foreign key constraints valid")
    
    # List all foreign keys for review
    cursor.execute("""
        SELECT m.name as table_name, p.seq, p.'from', p.'table', p.'to'
        FROM sqlite_master m
        JOIN pragma_foreign_key_list(m.name) p
        WHERE m.type = 'table'
        ORDER BY m.name, p.seq
    """)
    
    fks = cursor.fetchall()
    if fks:
        print_info(f"\nTotal foreign keys defined: {len(fks)}")
        current_table = None
        for fk in fks:
            table, seq, from_col, to_table, to_col = fk
            if table != current_table:
                print(f"\n  {table}:")
                current_table = table
            print(f"    {from_col} → {to_table}({to_col})")
    
    conn.close()
    return True

def validate_indexes():
    """Validate index definitions"""
    print_section("Index Validation")
    
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    
    # Load all schema files
    for schema_file in SCHEMA_FILES:
        content = read_schema_file(schema_file)
        cursor.executescript(content)
    
    # List all indexes
    cursor.execute("""
        SELECT name, tbl_name, sql 
        FROM sqlite_master 
        WHERE type = 'index' AND name NOT LIKE 'sqlite_%'
        ORDER BY tbl_name, name
    """)
    
    indexes = cursor.fetchall()
    print_info(f"Total indexes defined: {len(indexes)}")
    
    current_table = None
    for idx_name, table_name, idx_sql in indexes:
        if table_name != current_table:
            print(f"\n  {table_name}:")
            current_table = table_name
        print(f"    {idx_name}")
    
    print_success("All indexes created successfully")
    
    conn.close()
    return True

def validate_views():
    """Validate view definitions"""
    print_section("View Validation")
    
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    
    # Load all schema files
    for schema_file in SCHEMA_FILES:
        content = read_schema_file(schema_file)
        cursor.executescript(content)
    
    # List all views
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type = 'view'
        ORDER BY name
    """)
    
    views = cursor.fetchall()
    print_info(f"Total views defined: {len(views)}")
    
    # Test each view can be queried
    errors = []
    for (view_name,) in views:
        try:
            cursor.execute(f"SELECT * FROM {view_name} LIMIT 0")
            print_success(f"{view_name}: Valid")
        except sqlite3.Error as e:
            error_msg = f"{view_name}: {str(e)}"
            print_error(error_msg)
            errors.append(error_msg)
    
    conn.close()
    return len(errors) == 0, errors

def validate_triggers():
    """Validate trigger definitions"""
    print_section("Trigger Validation")
    
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    
    # Load all schema files
    for schema_file in SCHEMA_FILES:
        content = read_schema_file(schema_file)
        cursor.executescript(content)
    
    # List all triggers
    cursor.execute("""
        SELECT name, tbl_name FROM sqlite_master 
        WHERE type = 'trigger'
        ORDER BY tbl_name, name
    """)
    
    triggers = cursor.fetchall()
    print_info(f"Total triggers defined: {len(triggers)}")
    
    for trigger_name, table_name in triggers:
        print_success(f"{trigger_name} on {table_name}")
    
    conn.close()
    return True

def integrate_schema(db_path, with_test_data=False):
    """Integrate prompt schema into existing tda_auth.db"""
    print_section(f"Integrating Schema into: {db_path}")
    
    # Check if database exists
    if not os.path.exists(db_path):
        print_error(f"Database {db_path} does not exist!")
        print_info("Please provide the path to your existing tda_auth.db")
        return False
    
    # Backup warning
    print_warning("IMPORTANT: This will modify your existing database.")
    print_warning("Please ensure you have a backup of tda_auth.db before proceeding.")
    response = input(f"{Colors.YELLOW}Continue with schema integration? (yes/no): {Colors.RESET}")
    if response.lower() != 'yes':
        print_info("Schema integration cancelled")
        return False
    
    # Connect to existing database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")
    
    # Check for existing prompt tables
    cursor.execute("""
        SELECT COUNT(*) FROM sqlite_master 
        WHERE type='table' AND name IN (
            'prompt_classes', 'prompts', 'prompt_versions', 
            'prompt_overrides', 'global_parameters'
        )
    """)
    existing_count = cursor.fetchone()[0]
    
    if existing_count > 0:
        print_warning(f"Found {existing_count} existing prompt tables in database")
        response = input(f"{Colors.YELLOW}Drop and recreate these tables? (yes/no): {Colors.RESET}")
        if response.lower() != 'yes':
            print_info("Schema integration cancelled")
            return False
        
        # Drop existing tables (will be recreated)
        print_info("Dropping existing prompt tables...")
        cursor.execute("DROP TABLE IF EXISTS profile_class_assignments")
        cursor.execute("DROP TABLE IF EXISTS profile_prompt_parameter_values")
        cursor.execute("DROP TABLE IF EXISTS profile_prompt_assignments")
        cursor.execute("DROP TABLE IF EXISTS prompt_class_parameters")
        cursor.execute("DROP TABLE IF EXISTS prompt_parameters")
        cursor.execute("DROP TABLE IF EXISTS global_parameter_overrides")
        cursor.execute("DROP TABLE IF EXISTS global_parameters")
        cursor.execute("DROP TABLE IF EXISTS prompt_overrides")
        cursor.execute("DROP TABLE IF EXISTS prompt_versions")
        cursor.execute("DROP TABLE IF EXISTS prompts")
        cursor.execute("DROP TABLE IF EXISTS prompt_classes")
        cursor.execute("DROP TABLE IF EXISTS schema_version")
    
    # Execute each schema file
    for schema_file in SCHEMA_FILES:
        print_info(f"Executing {schema_file}...")
        content = read_schema_file(schema_file)
        
        try:
            cursor.executescript(content)
            print_success(f"{schema_file} executed successfully")
        except sqlite3.Error as e:
            print_error(f"Error in {schema_file}: {str(e)}")
            conn.rollback()
            conn.close()
            return False
    
    # Add schema version
    cursor.execute("""
        INSERT OR REPLACE INTO schema_version (version, description)
        VALUES ('1.0.0', 'Initial prompt management system schema integrated into tda_auth.db')
    """)
    
    conn.commit()
    
    # Get table counts
    cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
    total_tables = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) FROM sqlite_master 
        WHERE type='table' AND name IN (
            'prompt_classes', 'prompts', 'prompt_versions', 'prompt_overrides',
            'global_parameters', 'global_parameter_overrides', 'prompt_parameters',
            'prompt_class_parameters', 'profile_prompt_assignments',
            'profile_prompt_parameter_values', 'profile_class_assignments',
            'schema_version'
        )
    """)
    prompt_tables = cursor.fetchone()[0]
    
    # Get view count
    cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='view' AND name LIKE 'v_%prompt%'")
    view_count = cursor.fetchone()[0]
    
    # Get index count
    cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name LIKE 'idx_prompt%'")
    index_count = cursor.fetchone()[0]
    
    print_success(f"\nSchema integrated successfully!")
    print_info(f"  Total tables in database: {total_tables}")
    print_info(f"  Prompt management tables: {prompt_tables}")
    print_info(f"  Prompt views: {view_count}")
    print_info(f"  Prompt indexes: {index_count}")
    
    if with_test_data:
        insert_test_data(cursor)
        conn.commit()
    
    conn.close()
    return True

def insert_test_data(cursor):
    """Insert test data for validation"""
    print_section("Inserting Test Data")
    
    # Create a test prompt class
    cursor.execute("""
        INSERT INTO prompt_classes (name, display_name, description, class_type)
        VALUES ('TestStrategicPlanner', 'Test Strategic Planning', 'Test class', 'template')
    """)
    class_id = cursor.lastrowid
    print_success(f"Created test class (id={class_id})")
    
    # Create a test prompt
    cursor.execute("""
        INSERT INTO prompts (name, display_name, content, class_id, role, version)
        VALUES ('TEST_PROMPT', 'Test Prompt', 
                'Test prompt with {param1} and {param2}', 
                ?, 'strategic', 1)
    """, (class_id,))
    prompt_id = cursor.lastrowid
    print_success(f"Created test prompt (id={prompt_id})")
    
    # Add local parameters
    cursor.execute("""
        INSERT INTO prompt_parameters 
        (prompt_id, parameter_name, display_name, parameter_type, default_value)
        VALUES (?, 'param1', 'Parameter 1', 'string', 'default1'),
               (?, 'param2', 'Parameter 2', 'enum', 'option1')
    """, (prompt_id, prompt_id))
    print_success("Added test parameters")
    
    # Add global parameter
    cursor.execute("""
        INSERT INTO global_parameters 
        (parameter_name, display_name, parameter_type, default_value, is_system_managed)
        VALUES ('test_global', 'Test Global Parameter', 'string', 'global_default', 0)
    """)
    print_success("Added test global parameter")
    
    print_info("\nTest data inserted successfully")

def run_validation():
    """Run all validation checks"""
    print_section("Uderia Prompt Management System - Schema Validation")
    print_info(f"Schema directory: {SCHEMA_DIR}")
    print_info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    all_passed = True
    
    # Syntax validation
    passed, errors = validate_schema_syntax()
    if not passed:
        all_passed = False
        print_error(f"\n{len(errors)} syntax error(s) found")
    
    # Foreign key validation
    if not validate_foreign_keys():
        all_passed = False
    
    # Index validation
    if not validate_indexes():
        all_passed = False
    
    # View validation
    passed, errors = validate_views()
    if not passed:
        all_passed = False
        print_error(f"\n{len(errors)} view error(s) found")
    
    # Trigger validation
    if not validate_triggers():
        all_passed = False
    
    # Final summary
    print_section("Validation Summary")
    if all_passed:
        print_success("All validation checks passed! ✓")
        print_info("\nSchema is ready for Phase 2 implementation")
        return True
    else:
        print_error("Some validation checks failed")
        print_warning("Please fix errors before proceeding to Phase 2")
        return False

def main():
    parser = argparse.ArgumentParser(
        description='Uderia Prompt Management System - Schema Validation Tool'
    )
    parser.add_argument(
        '--validate-only',
        action='store_true',
        help='Only validate schema, do not create database'
    )
    parser.add_argument(
        '--integrate',
        type=str,
        metavar='DB_PATH',
        help='Integrate schema into existing tda_auth.db at specified path'
    )
    parser.add_argument(
        '--with-test-data',
        action='store_true',
        help='Include test data when integrating schema'
    )
    
    args = parser.parse_args()
    
    # Default to validation if no args provided
    if not args.validate_only and not args.integrate:
        args.validate_only = True
    
    try:
        if args.validate_only:
            success = run_validation()
            sys.exit(0 if success else 1)
        
        if args.integrate:
            # Run validation first
            print_info("Running validation before schema integration...\n")
            if not run_validation():
                print_error("\nValidation failed. Schema integration aborted.")
                sys.exit(1)
            
            # Integrate schema
            success = integrate_schema(args.integrate, args.with_test_data)
            sys.exit(0 if success else 1)
    
    except KeyboardInterrupt:
        print_warning("\n\nOperation cancelled by user")
        sys.exit(130)
    except Exception as e:
        print_error(f"\nUnexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
