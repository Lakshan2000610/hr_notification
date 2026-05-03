import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))

try:
    conn = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        port=MYSQL_PORT
    )
    cursor = conn.cursor()
    cursor.execute("SHOW DATABASES")
    dbs = cursor.fetchall()
    print("Databases in MySQL:")
    for db in dbs:
        print(f" - {db[0]}")
    
    # Let's inspect 'hr_notification' if it exists
    cursor.execute("SHOW DATABASES LIKE 'hr_notification'")
    if cursor.fetchone():
        print("\nTables in 'hr_notification':")
        cursor.execute("USE hr_notification")
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        for t in tables:
            print(f" - {t[0]}")
            # print table schema
            cursor.execute(f"DESCRIBE {t[0]}")
            for col in cursor.fetchall():
                print(f"    {col}")
    else:
        print("\n'hr_notification' database does not exist.")
    
    conn.close()
except Exception as e:
    print(f"Error: {e}")
