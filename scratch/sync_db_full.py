
import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

config = {
    'host': os.getenv("MYSQL_HOST", "localhost"),
    'user': os.getenv("MYSQL_USER", "root"),
    'password': os.getenv("MYSQL_PASSWORD", ""),
    'database': os.getenv("MYSQL_DATABASE", "hr_notification"),
    'port': int(os.getenv("MYSQL_PORT", 3306))
}

def sync_all():
    try:
        conn = mysql.connector.connect(**config)
        cursor = conn.cursor()
        
        checks = [
            ('employees', 'INDEX', 'idx_email', '(email)'),
            ('employee_devices', 'INDEX', 'idx_active', '(active_status)'),
            ('employee_devices', 'INDEX', 'idx_last_seen', '(last_seen)'),
            ('scheduled_content', 'INDEX', 'idx_time', '(scheduled_time)'),
            ('notifications', 'INDEX', 'idx_content', '(content_id)'),
            ('notifications', 'INDEX', 'idx_time', '(time)'),
            ('reactions', 'INDEX', 'idx_content', '(content_id)'),
            ('reactions', 'INDEX', 'idx_employee', '(employee_id)'),
            ('reactions', 'UNIQUE KEY', 'unique_reaction', '(content_id, employee_id)'),
            ('feedback', 'INDEX', 'idx_content', '(content_id)'),
            ('feedback', 'INDEX', 'idx_employee', '(employee_id)'),
            ('views', 'INDEX', 'idx_content', '(content_id)'),
            ('views', 'UNIQUE KEY', 'unique_view', '(content_id, employee_id)'),
            ('device_update_status', 'INDEX', 'idx_status', '(status)'),
            ('device_update_status', 'UNIQUE KEY', 'unique_device', '(employee_id, device_id)'),
            ('admin_access', 'INDEX', 'idx_admin_email', '(email)'),
            ('version_history', 'INDEX', 'idx_uploaded_at', '(uploaded_at)'),
            ('groups', 'INDEX', 'idx_name', '(name)'),
            ('group_members', 'INDEX', 'idx_group', '(group_id)'),
            ('group_members', 'INDEX', 'idx_employee', '(employee_id)'),
        ]
        
        for table, type, name, cols in checks:
            cursor.execute(f"SHOW INDEX FROM {table} WHERE Key_name = '{name}'")
            if not cursor.fetchall():
                print(f"Adding {type} {name} to {table}...")
                if type == 'INDEX':
                    cursor.execute(f"CREATE INDEX {name} ON {table}{cols}")
                elif type == 'UNIQUE KEY':
                    cursor.execute(f"ALTER TABLE {table} ADD UNIQUE KEY {name} {cols}")

        conn.commit()
        print("Full index synchronization complete.")
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    sync_all()
