
import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "hr_notification")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))

def sync_db():
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            port=MYSQL_PORT
        )
        cursor = conn.cursor()
        
        # 1. Check groups.created_at type
        cursor.execute("DESCRIBE groups")
        cols = {col[0]: col[1] for col in cursor.fetchall()}
        if cols.get('created_at', '').lower() == 'timestamp':
            print("Changing groups.created_at from TIMESTAMP to DATETIME...")
            cursor.execute("ALTER TABLE groups MODIFY created_at DATETIME DEFAULT CURRENT_TIMESTAMP")

        # 2. Check groups index
        cursor.execute("SHOW INDEX FROM groups WHERE Key_name = 'idx_name'")
        if not cursor.fetchall():
            print("Adding missing index idx_name to groups...")
            cursor.execute("CREATE INDEX idx_name ON groups(name)")

        # 3. Check group_members columns
        cursor.execute("DESCRIBE group_members")
        cols = [col[0] for col in cursor.fetchall()]
        if 'joined_at' not in cols:
            print("Adding missing column joined_at to group_members...")
            cursor.execute("ALTER TABLE group_members ADD COLUMN joined_at DATETIME DEFAULT CURRENT_TIMESTAMP")

        # 4. Check group_members indexes
        cursor.execute("SHOW INDEX FROM group_members")
        indexes = [idx[2] for idx in cursor.fetchall()]
        if 'idx_group' not in indexes:
            print("Adding index idx_group to group_members...")
            cursor.execute("CREATE INDEX idx_group ON group_members(group_id)")
        if 'idx_employee' not in indexes:
            print("Adding index idx_employee to group_members...")
            cursor.execute("CREATE INDEX idx_employee ON group_members(employee_id)")

        # 5. Check version_history index
        cursor.execute("SHOW INDEX FROM version_history WHERE Key_name = 'idx_uploaded_at'")
        if not cursor.fetchall():
            print("Adding index idx_uploaded_at to version_history...")
            cursor.execute("CREATE INDEX idx_uploaded_at ON version_history(uploaded_at)")

        # 6. Check reactions unique constraint (already checked, but good to be sure)
        cursor.execute("SHOW INDEX FROM reactions WHERE Key_name = 'unique_reaction'")
        if not cursor.fetchall():
            print("Adding unique constraint unique_reaction to reactions...")
            cursor.execute("ALTER TABLE reactions ADD UNIQUE KEY unique_reaction (content_id, employee_id)")

        conn.commit()
        print("Database synchronization complete.")
        conn.close()
    except Exception as e:
        print(f"Error during sync: {e}")

if __name__ == "__main__":
    sync_db()
