
import mysql.connector
import os
import re
from dotenv import load_dotenv

load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "hr_notification")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))

def parse_sql_file(file_path):
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Simple regex to extract column names from CREATE TABLE blocks
    tables = {}
    # Find all CREATE TABLE blocks
    table_matches = re.finditer(r'CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\) ENGINE', content, re.DOTALL | re.IGNORECASE)
    for match in table_matches:
        table_name = match.group(1)
        columns_block = match.group(2)
        
        cols = []
        # Extract lines that look like column definitions (start with alphanumeric, not PRIMARY KEY, etc.)
        for line in columns_block.split('\n'):
            line = line.strip()
            if not line or line.startswith('--'): continue
            if line.upper().startswith(('PRIMARY KEY', 'FOREIGN KEY', 'INDEX', 'UNIQUE KEY', 'KEY', 'CONSTRAINT')): continue
            
            # Match word at start
            col_match = re.match(r'^(\w+)', line)
            if col_match:
                cols.append(col_match.group(1).lower())
        
        tables[table_name.lower()] = set(cols)
    return tables

def get_live_schema():
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            port=MYSQL_PORT
        )
        cursor = conn.cursor()
        
        cursor.execute("SHOW TABLES")
        tables = [t[0].lower() for t in cursor.fetchall()]
        
        live_schema = {}
        for table in tables:
            cursor.execute(f"DESCRIBE {table}")
            columns = [col[0].lower() for col in cursor.fetchall()]
            live_schema[table] = set(columns)
            
        conn.close()
        return live_schema
    except Exception as e:
        print(f"Error connecting to DB: {e}")
        return None

def compare():
    expected = parse_sql_file('sql.db')
    actual = get_live_schema()
    
    if actual is None: return
    
    all_tables = set(expected.keys()) | set(actual.keys())
    
    found_diff = False
    for table in sorted(all_tables):
        if table not in actual:
            print(f"[MISSING TABLE] {table} is missing in Live DB")
            found_diff = True
        elif table not in expected:
            print(f"[EXTRA TABLE] {table} exists in Live DB but not in sql.db")
            found_diff = True
        else:
            missing_cols = expected[table] - actual[table]
            extra_cols = actual[table] - expected[table]
            
            if missing_cols:
                print(f"[MISSING COLUMNS] Table '{table}' is missing columns: {missing_cols}")
                found_diff = True
            if extra_cols:
                print(f"[EXTRA COLUMNS] Table '{table}' has extra columns: {extra_cols}")
                found_diff = True
                
    if not found_diff:
        print("Schema matches!")
    else:
        print("\nDifferences found.")

if __name__ == "__main__":
    compare()
