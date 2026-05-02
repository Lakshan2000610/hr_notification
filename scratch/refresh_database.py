
import mysql.connector
import os
import sys
from dotenv import load_dotenv

# Add current directory to path to find .env
sys.path.append(os.getcwd())
load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "hr_notification")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))

def refresh_db():
    print(f"Connecting to MySQL at {MYSQL_HOST}:{MYSQL_PORT} as {MYSQL_USER}...")
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            port=MYSQL_PORT
        )
        cursor = conn.cursor()
        
        # 1. Capture current admins to restore them if needed
        # We check if the DB exists first
        cursor.execute(f"SHOW DATABASES LIKE '{MYSQL_DATABASE}'")
        if cursor.fetchone():
            cursor.execute(f"USE {MYSQL_DATABASE}")
            cursor.execute("SELECT email FROM admin_access")
            current_admins = [row[0] for row in cursor.fetchall()]
            print(f"Current admins found: {current_admins}")
        else:
            current_admins = ["pamuditha.it@acorn.lk"]
            print("Database does not exist. Using default admin.")

        # 2. Drop and recreate database
        print(f"Dropping database '{MYSQL_DATABASE}'...")
        cursor.execute(f"DROP DATABASE IF EXISTS {MYSQL_DATABASE}")
        
        print(f"Creating database '{MYSQL_DATABASE}'...")
        cursor.execute(f"CREATE DATABASE {MYSQL_DATABASE} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cursor.execute(f"USE {MYSQL_DATABASE}")
        
        # 3. Load and execute schema from sql.db
        sql_file_path = os.path.join(os.getcwd(), 'sql.db')
        print(f"Reading schema from {sql_file_path}...")
        with open(sql_file_path, 'r') as f:
            sql_script = f.read()
        
        print("Executing schema script...")
        # mysql-connector-python's execute can handle multiple statements with multi=True
        for result in cursor.execute(sql_script, multi=True):
            # We don't need to do anything with the result objects
            pass
        
        # 4. Restore admins
        print("Restoring admins...")
        for email in current_admins:
            cursor.execute("INSERT IGNORE INTO admin_access (email) VALUES (%s)", (email,))
        
        conn.commit()
        print("\nSUCCESS: Database refreshed and old data removed!")
        print(f"Tables recreated and {len(current_admins)} admins restored.")
        
    except Exception as e:
        print(f"\nERROR: {e}")
        if 'conn' in locals():
            conn.rollback()
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    refresh_db()
