import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

def check_schema():
    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "hr_notification"),
        port=int(os.getenv("MYSQL_PORT", "3306"))
    )
    cursor = conn.cursor(dictionary=True)
    
    print("--- scheduled_content ---")
    cursor.execute("DESCRIBE scheduled_content")
    for row in cursor.fetchall():
        print(row)
        
    print("\n--- notifications ---")
    cursor.execute("DESCRIBE notifications")
    for row in cursor.fetchall():
        print(row)
        
    cursor.close()
    conn.close()

if __name__ == "__main__":
    check_schema()
