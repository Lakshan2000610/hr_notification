import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "hr_notification")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))

try:
    conn = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        port=MYSQL_PORT,
        autocommit=True
    )
    cursor = conn.cursor()
    cursor.execute("ALTER TABLE employee_devices MODIFY COLUMN status VARCHAR(50) DEFAULT 'offline'")
    print("Column 'status' successfully changed to VARCHAR(50) in MySQL!")
    conn.close()
except Exception as e:
    print(f"Error altering table: {e}")
