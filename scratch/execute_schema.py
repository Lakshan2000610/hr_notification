import mysql.connector
import os
from dotenv import load_dotenv
import re

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
        port=MYSQL_PORT,
        autocommit=True
    )
    cursor = conn.cursor()

    # Read the file
    with open("sql.db", "r", encoding="utf-8") as f:
        sql_script = f.read()

    # Remove SQL comments and split by semicolon
    # Semicolons inside quotes/parentheses shouldn't be matched naively, but sql.db doesn't have semicolons inside text.
    statements = sql_script.split(";")
    for stmt in statements:
        stmt = stmt.strip()
        if not stmt:
            continue
        # Skip comment lines
        lines = [line for line in stmt.split("\n") if not line.strip().startswith("--")]
        clean_stmt = "\n".join(lines).strip()
        if not clean_stmt:
            continue
        print(f"Executing: {clean_stmt[:50]}...")
        cursor.execute(clean_stmt)

    print("\nDatabase schema successfully applied!")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
