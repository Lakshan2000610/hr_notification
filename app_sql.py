from venv import logger
from flask import Flask, request, jsonify,send_file, render_template, session, redirect, url_for
from datetime import datetime, timedelta, timezone
import threading
import time
import uuid
import os
from collections import defaultdict
import shutil
from datetime import datetime, timezone, timedelta
from dateutil import parser
import re
import tempfile
import urllib.parse
import logging
import requests
import pkg_resources
from functools import wraps
import json
from dateutil import parser
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import mysql.connector
from mysql.connector import Error
from mysql.connector.pooling import MySQLConnectionPool
import pytz


app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'super_secret_key')  # Load from .env or fallback

# MySQL configuration (add to your .env)
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "hr_notification")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))

# Connection pool (recommended)
db_pool = None

SERVER_URL = "http://127.0.0.1:5000/"

# Load environment variables from .env file
load_dotenv()

def get_db_connection():
    global db_pool
    if db_pool is None:
        try:
            db_pool = mysql.connector.pooling.MySQLConnectionPool(
                pool_name="hr_pool",
                pool_size=10,
                host=MYSQL_HOST,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE,
                port=MYSQL_PORT,
                autocommit=True,
                charset='utf8mb4',
                init_command='SET SESSION time_zone = "+00:00"'
            )
            logging.info("MySQL connection pool created successfully")
        except Error as e:
            logging.critical(f"Failed to create MySQL pool: {e}")
            # DO NOT exit() — just return None and let execute_query handle it
            return None
    
    try:
        return db_pool.get_connection()
    except Error as e:
        logging.error(f"Failed to get connection from pool: {e}")
        # Try direct connection as fallback
        try:
            return mysql.connector.connect(
                host=MYSQL_HOST,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE,
                port=MYSQL_PORT,
                autocommit=True,
                charset='utf8mb4',
                init_command='SET SESSION time_zone = "+00:00"'
            )
        except Error as e2:
            logging.error(f"Direct connection also failed: {e2}")
            return None
            
def execute_query(query, params=None, fetch=False, commit=False):
    conn = get_db_connection()
    if conn is None:
        logging.error("No database connection available")
        raise mysql.connector.Error("Database unavailable")
    
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(query, params or ())
        result = None
        if fetch:
            result = cursor.fetchall()
        if commit:
            conn.commit()
        return {"data": result or []}
    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Query failed: {query} | Error: {e}")
        raise e
    finally:
        cursor.close()
        if conn:
            conn.close()

def format_datetime_for_client(dt):
    """
    Convert any datetime (naive or aware) to proper ISO format with Z
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Assume UTC if naive
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


# Cortex XDR API configuration
CORTEX_API_URL = os.getenv("CORTEX_API_URL", "https://api-acorntravels.xdr.sg.paloaltonetworks.com/public_api/v1/endpoints/get_endpoint/")
CORTEX_API_KEY_ID = os.getenv("CORTEX_API_KEY_ID")
CORTEX_API_KEY = os.getenv("CORTEX_API_KEY")

# Local directory for uploads
UPLOAD_DIR = "hr_notification\\uploads"
VIDEO_DIR = os.path.join(UPLOAD_DIR, "message", "videos")
IMAGE_DIR = os.path.join(UPLOAD_DIR, "message", "images")
app.config['UPLOAD_FOLDER'] = UPLOAD_DIR


# Ensure upload directories exist
for directory in [UPLOAD_DIR, VIDEO_DIR, IMAGE_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)
        logging.info(f"Created directory: {directory}")




# Validate Supabase URL
def validate_supabase_url(url):
    try:
        result = urllib.parse.urlparse(url)
        return all([result.scheme == "https", result.netloc.endswith(".supabase.co")])
    except ValueError:
        return False


# Ensure upload directory exists
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)




# Validate Supabase URL
def validate_supabase_url(url):
    try:
        result = urllib.parse.urlparse(url)
        return all([result.scheme == "https", result.netloc.endswith(".supabase.co")])
    except ValueError:
        return False

# Verify file exists in local directory
def verify_file(directory, filename):
    try:
        file_path = os.path.join(directory, filename)
        if not os.path.exists(file_path):
            logging.error(f"File not found: {file_path}")
            return False
        file_size = os.path.getsize(file_path)
        if file_size < 1024:  # Minimum size check (1KB)
            logging.error(f"File too small: {file_path}, size: {file_size} bytes")
            return False
        logging.info(f"File verified: {file_path}, size: {file_size} bytes")
        return True
    except Exception as e:
        logging.error(f"Error verifying file {file_path}: {str(e)}")
        return False
    
# Create storage bucket and set RLS policies if it doesn't exist

# Schedule a notification 5 minutes before content delivery
def schedule_notification(content_id, scheduled_time, employees):
    try:
        notify_time = scheduled_time - timedelta(minutes=5)
        time_to_wait = (notify_time - datetime.now(timezone.utc)).total_seconds()
        if time_to_wait > 0:
            threading.Timer(time_to_wait, send_notification, args=(content_id, employees)).start()
    except Exception as e:
        logging.error(f"Error scheduling notification for content_id {content_id}: {str(e)}")


def send_notification(content_id, employees):
    try:
        execute_query(
            "INSERT INTO notifications (content_id, employees, time) VALUES (%s, %s, %s)",
            (content_id, json.dumps(employees), datetime.now(timezone.utc)),
            commit=True
        )

        logging.info(f"Notification sent for content_id: {content_id}")
    except Exception as e:
        logging.error(f"Error sending notification: {str(e)}")


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def get_current_version():
    version_path = os.path.join(app.config['UPLOAD_FOLDER'], 'version.txt')
    try:
        with open(version_path, 'r') as f:
            return f.read().strip()
    except Exception:
        return None


# Serve files from uploads directory
@app.route('/uploads/<path:filename>')
def serve_uploaded_file(filename):
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if not os.path.exists(file_path):
            logging.error(f"File not found: {file_path}")
            return jsonify({"message": "File not found"}), 404
        logging.info(f"Serving file: {file_path}")
        return send_file(file_path, as_attachment=False)
    except Exception as e:
        logging.error(f"Error serving file {file_path}: {str(e)}")
        return jsonify({"message": f"Error serving file: {str(e)}"}), 500
    
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == 'hracron@gmail.com' and password == 'hracron':
            session['logged_in'] = True
            return redirect(url_for('home'))
        else:
            return render_template('login.html', error="Invalid username or password")
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('welcome'))




@app.route('/get_sent_messages')
@login_required
def get_sent_messages():
    try:
        filter_type = request.args.get('filter', 'day')
        current_time = datetime.now(timezone.utc)

        if filter_type == 'day':
            time_threshold = current_time - timedelta(days=1)
        elif filter_type == 'month':
            time_threshold = current_time - timedelta(days=30)
        else:
            time_threshold = current_time - timedelta(days=1)

        time_threshold_str = time_threshold.strftime('%Y-%m-%d %H:%M:%S')

        # Fix: Use COUNT(*) and GROUP BY instead of fetching all rows
        query = """
            SELECT 
                DATE_FORMAT(time, %s) as label,
                COUNT(*) as count
            FROM notifications 
            WHERE time >= %s
            GROUP BY label
            ORDER BY label
        """

        if filter_type == 'day':
            format_str = '%H:00'           # Group by hour
        else:
            format_str = '%Y-%m-%d'         # Group by date

        result = execute_query(query, (format_str, time_threshold_str), fetch=True)
        rows = result.get("data", []) or []

        labels = [row['label'] for row in rows]
        counts = [row['count'] for row in rows]  # ← This is integer, not string!

        logging.info(f"Sent messages ({filter_type}): {len(counts)} entries")
        return jsonify({'labels': labels, 'counts': counts})

    except Exception as e:
        logging.error(f"Error in get_sent_messages: {str(e)}", exc_info=True)
        return jsonify({'labels': [], 'counts': []}), 500
    

@app.route('/')
def welcome():
    """Redirect to welcome page if not logged in"""
    if 'logged_in' in session:
        return redirect(url_for('home'))
    return render_template('welcome.html')




@app.route('/home')
@login_required
def home():
    try:
        # 1. Total registered employees
        employees_response = execute_query("SELECT id FROM employees", fetch=True)
        employee_count = len(employees_response.get("data", []) or [])

        # 2. Active devices = those with active_status = 1 (admin approved
        active_devices_result = execute_query("""
            SELECT COUNT(*) as count 
            FROM employee_devices 
            WHERE active_status = 1
        """, fetch=True)
        active_devices = active_devices_result.get("data", [{}])[0].get("count", 0)

        # 3. Fetch all scheduled content with created_at or scheduled_time
        contents_result = execute_query("""
            SELECT id, title, text, scheduled_time, created_at 
            FROM scheduled_content 
            ORDER BY scheduled_time DESC
        """, fetch=True)
        contents = contents_result.get("data", []) or []

        content_stats = []
        for content in contents:
            content_id = content['id']

            # Reactions
            reactions_result = execute_query("""
                SELECT reaction FROM reactions WHERE content_id = %s
            """, (content_id,), fetch=True)
            reaction_data = reactions_result.get("data", []) or []
            reaction_counts = {k: sum(1 for r in reaction_data if r['reaction'] == k) 
                              for k in ['like', 'unlike', 'heart', 'cry']}

            # Feedback count
            feedback_result = execute_query("SELECT id FROM feedback WHERE content_id = %s", (content_id,), fetch=True)
            feedback_count = len(feedback_result.get("data", []) or [])

            # Unique views
            views_result = execute_query("SELECT employee_id FROM views WHERE content_id = %s", (content_id,), fetch=True)
            view_count = len(set(v['employee_id'] for v in views_result.get("data", []) or []))

            # Format sent date (use scheduled_time, fallback to created_at)
            sent_date = content.get('scheduled_time') or content.get('created_at')
            if sent_date:
                # Convert to Sri Lanka time (UTC+5:30)
                if isinstance(sent_date, str):
                    sent_date = datetime.fromisoformat(sent_date.replace('Z', '+00:00'))
                if sent_date.tzinfo is None:
                    sent_date = sent_date.replace(tzinfo=timezone.utc)
                sent_date = sent_date.astimezone(timezone(timedelta(hours=5, minutes=30)))
                sent_date_str = sent_date.strftime("%d %b %Y<br>%I:%M %p")
            else:
                sent_date_str = "—"

            sent_date_str = sent_date.strftime("%d %b %Y, %I:%M %p")  # One line format
            content_stats.append({
                'id': content_id,
                'title': content.get('title', 'No title'),
                'like_count': reaction_counts.get('like', 0),
                'unlike_count': reaction_counts.get('unlike', 0),
                'heart_count': reaction_counts.get('heart', 0),
                'cry_count': reaction_counts.get('cry', 0),
                'feedback_count': feedback_count,
                'view_count': view_count,
                'sent_date_one_line': sent_date_str,           # ← New: One line
                'sent_date_raw': sent_date.isoformat() if sent_date else ''  # ← For filter
            })

        # Pagination
        items_per_page = 10
        page = int(request.args.get('page', 1))
        total_items = len(content_stats)
        total_pages = (total_items + items_per_page - 1) // items_per_page
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        paginated_stats = content_stats[start_idx:end_idx]

        return render_template('home.html',
                              employee_count=employee_count,
                              active_devices=active_devices,
                              content_stats=content_stats,
                              paginated_stats=paginated_stats,
                              current_page=page,
                              total_pages=total_pages)

    except Exception as e:
        logging.error(f"Error in home route: {str(e)}", exc_info=True)
        return render_template('home.html',
                              employee_count=0,
                              active_devices=0,
                              content_stats=[],
                              paginated_stats=[],
                              current_page=1,
                              total_pages=1,
                              error="Server error occurred")
                    
@app.route('/get_paginated_stats')
@login_required
def get_paginated_stats():
    try:
        # Fetch all scheduled content (ordered by time — most logical)
        contents_result = execute_query(
            "SELECT * FROM scheduled_content ORDER BY scheduled_time DESC",
            fetch=True
        )
        contents = contents_result.get("data", []) or []
        content_stats = []
        for content in contents:
            content_id = content['id']
            reactions_result = execute_query("""
                SELECT reaction 
                FROM reactions 
                WHERE content_id = %s
            """, (content_id,), fetch=True)
            reaction_data = reactions_result.get("data", []) or []
            reaction_counts = {k: sum(1 for r in reaction_data if r['reaction'] == k) for k in ['like', 'unlike', 'heart', 'cry']}
            feedback_result = execute_query("SELECT id FROM feedback WHERE content_id = %s", (content_id,), fetch=True)
            feedback_count = len(feedback_result.get("data", []) or [])
            views_result = execute_query("SELECT employee_id FROM views WHERE content_id = %s", (content_id,), fetch=True)
            view_count = len(set(view['employee_id'] for view in views_result.get("data", []) or []))
            content_stats.append({
                'id': content_id,
                'title': content.get('title', 'No title'),
                'text': content.get('text', 'No text'),
                'like_count': reaction_counts.get('like', 0),
                'unlike_count': reaction_counts.get('unlike', 0),
                'heart_count': reaction_counts.get('heart', 0),
                'cry_count': reaction_counts.get('cry', 0),
                'feedback_count': feedback_count,
                'view_count': view_count
            })


        # Pagination logic
        items_per_page = 10
        page = int(request.args.get('page', 1))
        total_items = len(content_stats)
        total_pages = (total_items + items_per_page - 1) // items_per_page
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        paginated_stats = content_stats[start_idx:end_idx]


        return jsonify({
            'paginated_stats': paginated_stats,
            'current_page': page,
            'total_pages': total_pages
        })
    except Exception as e:
        logging.error(f"Error fetching paginated stats: {str(e)}")
        return jsonify({
            'paginated_stats': [],
            'current_page': 1,
            'total_pages': 1,
            'error': str(e)
        }), 500


@app.route('/employees')
@login_required
def get_employees():
    try:
        employees = execute_query("SELECT id, email FROM employees", fetch=True).get("data", []) or []
        logging.info(f"Fetched employees: {employees}")
        return jsonify(employees)
    except Exception as e:
        logging.error(f"Error fetching employees: {str(e)}")
        return jsonify({"message": f"Error fetching employees: {str(e)}"}), 500




# Updated /updates/version
@app.route('/updates/version', methods=['GET'])
def get_version():
    """Serve the latest version number from local directory."""
    try:
        version_path = os.path.join(app.config['UPLOAD_FOLDER'], "version.txt")
        if not os.path.exists(version_path):
            logger.error(f"Version file not found: {version_path}")
            return jsonify({"message": "Version file not found", "version": "unknown"}), 404


        with open(version_path, 'r') as f:
            version_text = f.read().strip()
            if not version_text:
                logger.error("Version file is empty")
                return jsonify({"message": "Version file is empty", "version": "unknown"}), 404


        logger.info(f"Served version: {version_text}")
        return version_text, 200, {'Content-Type': 'text/plain'}
    except Exception as e:
        logger.error(f"Error serving version.txt: {str(e)}")
        return jsonify({"message": f"Error serving version: {str(e)}", "version": "unknown"}), 500
    
# Updated /updates/app
@app.route('/updates/app', methods=['GET'])
def get_app():
    """Serve the app.exe file with integrity check."""
    try:
        exe_path = os.path.join(app.config['UPLOAD_FOLDER'], 'app.exe')
        if not os.path.exists(exe_path):
            logger.error(f"App executable not found: {exe_path}")
            return jsonify({'error': 'App executable not found'}), 404


        # Optional: Add file size check (e.g., ensure not empty)
        file_size = os.path.getsize(exe_path)
        if file_size < 1024:  # Example: Minimum size check
            logger.error(f"App executable too small: {file_size} bytes")
            return jsonify({'error': 'Invalid app executable'}), 400


        logger.info(f"Serving app.exe: {exe_path}, size: {file_size} bytes")
        return send_file(exe_path, as_attachment=True, download_name='app.exe')
    except Exception as e:
        logger.error(f"Error serving app executable: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/update_status', methods=['POST'])
def update_status():
    try:
        data = request.get_json()
        logging.debug(f"Received update_status data: {data}")

        if not data or not isinstance(data, dict):
            return jsonify({'error': 'Invalid or missing JSON data'}), 400

        employee_id = data.get('employee_id')
        if not employee_id:
            return jsonify({'error': 'Missing employee_id'}), 400


        # === CLIENT CANNOT CONTROL active_status ANYMORE ===
        update_data = {
            'employee_id': employee_id,
            'status': data.get('status', 'offline'),
            'app_running': data.get('app_running', False),
            'ip': data.get('ip'),
            'device_type': data.get('device_type'),
            'hostname': data.get('hostname') or 'unknown-host',
            'email': data.get('email'),
            'last_seen': datetime.now(timezone.utc).isoformat(),
        }

        # Remove None values (safe because active_status not included)
        update_data = {k: v for k, v in update_data.items() if v is not None}

        # CRITICAL: DO NOT TOUCH active_status in this route!
        execute_query("""
            INSERT INTO employee_devices 
                (employee_id, status, app_running, hostname, email, last_seen, ip, device_type)
            VALUES 
                (%(employee_id)s, %(status)s, %(app_running)s, %(hostname)s, %(email)s, %(last_seen)s, %(ip)s, %(device_type)s)
            ON DUPLICATE KEY UPDATE
                status = VALUES(status),
                app_running = VALUES(app_running),
                hostname = VALUES(hostname),
                email = VALUES(email),
                last_seen = VALUES(last_seen),
                ip = VALUES(ip),
                device_type = VALUES(device_type)
                -- active_status is NOT updated → admin setting preserved forever
        """, update_data, commit=True)

        # Optional: still update device_update_status table for app version tracking
        try:
            server_version = get_current_version() or 'unknown'
            device_id = data.get('device_id', employee_id)
            current_version = data.get('current_version', 'unknown')

            update_status_data = {
                'id': str(uuid.uuid4()),
                'employee_id': employee_id,
                'device_id': device_id,
                'version': current_version,
                'status': 'success' if current_version == server_version else data.get('update_status', 'pending'),
                'last_attempted_at': datetime.now(timezone.utc).isoformat(),
                'error_message': data.get('error_message') if data.get('update_status') == 'failed' else None
            }
            update_status_data = {k: v for k, v in update_status_data.items() if v is not None}

            execute_query("""
                INSERT INTO device_update_status 
                    (id, employee_id, device_id, version, status, last_attempted_at, error_message)
                VALUES 
                    (%(id)s, %(employee_id)s, %(device_id)s, %(version)s, %(status)s, %(last_attempted_at)s, %(error_message)s)
                ON DUPLICATE KEY UPDATE
                    version = VALUES(version),
                    status = VALUES(status),
                    last_attempted_at = VALUES(last_attempted_at),
                    error_message = VALUES(error_message)
            """, update_status_data, commit=True)
        except Exception as e:
            logging.warning(f"Failed to update device_update_status (non-critical): {e}")

        logging.info(f"Heartbeat OK → employee {employee_id} | active_status preserved by admin preserved")
        return jsonify({'message': 'Status updated successfully'}), 200

    except Exception as e:
        logging.error(f"Error in update_status: {str(e)}", exc_info=True)
        return jsonify({'error': 'Server error'}), 500
            
# Updated /upload_version
@app.route('/upload_version', methods=['GET', 'POST'])
@login_required
def upload_version():
    current_version = get_current_version()
    if request.method == 'GET':
        return render_template('upload_version.html', current_version=current_version)


    if 'version_file' not in request.files or 'exe_file' not in request.files:
        logger.error("Missing version_file or exe_file")
        return render_template('upload_version.html', error="Both version.txt and app.exe are required.", current_version=current_version)


    version_file = request.files['version_file']
    exe_file = request.files['exe_file']


    if not version_file.filename.endswith('.txt') or not exe_file.filename.endswith('.exe'):
        logger.error("Invalid file types uploaded")
        return render_template('upload_version.html', error="Invalid file types. Upload version.txt and app.exe.", current_version=current_version)


    version_path = os.path.join(app.config['UPLOAD_FOLDER'], 'version.txt')
    exe_path = os.path.join(app.config['UPLOAD_FOLDER'], 'app.exe')


    try:
        # Save files to temporary location first
        temp_dir = tempfile.gettempdir()
        temp_version_path = os.path.join(temp_dir, f"version_{uuid.uuid4()}.txt")
        temp_exe_path = os.path.join(temp_dir, f"app_{uuid.uuid4()}.exe")
        version_file.save(temp_version_path)
        exe_file.save(temp_exe_path)


        # Validate version format
        with open(temp_version_path, 'r') as f:
            new_version = f.read().strip()
            if not re.match(r'^\d+\.\d+\.\d+$', new_version):
                logger.error(f"Invalid version format: {new_version}")
                os.remove(temp_version_path)
                os.remove(temp_exe_path)
                return render_template('upload_version.html', error="Invalid version format.", current_version=current_version)


        # Move files to final location
        shutil.move(temp_version_path, version_path)
        shutil.move(temp_exe_path, exe_path)


        # Verify files were saved
        if not os.path.exists(version_path) or not os.path.exists(exe_path):
            logger.error("Failed to save version file or app executable")
            return render_template('upload_version.html', error="Failed to save files.", current_version=current_version)


        # Clear old pending/failed statuses
        execute_query("""
            DELETE FROM device_update_status 
            WHERE status IS NULL OR status != 'success'
        """, commit=True)

        logger.info(f"New version {new_version} uploaded by {session.get('user_email', 'unknown')}")
        return render_template('upload_version.html', success="Version uploaded successfully.", current_version=new_version)
    except Exception as e:
        logger.error(f"Error uploading version: {str(e)}")
        return render_template('upload_version.html', error=f"Error uploading version: {str(e)}", current_version=current_version)
    finally:
        # Clean up temporary files if they exist
        for temp_file in [temp_version_path, temp_exe_path]:
            if 'temp_version_path' in locals() and os.path.exists(temp_file):
                os.remove(temp_file)

@app.route('/delete_version', methods=['POST'])
@login_required
def delete_version():
    data = request.get_json()
    version = data.get('version')
    if not version:
        return jsonify({"error": "Version required"}), 400

    backup_dir = os.path.join(app.config['UPLOAD_FOLDER'], "backups")
    version_backup = os.path.join(backup_dir, f"app_{version}.exe")
    version_txt_backup = os.path.join(backup_dir, f"version_{version}.txt")

    try:
        if os.path.exists(version_backup):
            os.remove(version_backup)
        if os.path.exists(version_txt_backup):
            os.remove(version_txt_backup)

        # Also remove from version_history DB table if you have one
        execute_query("DELETE FROM version_history WHERE version = %s", (version,), commit=True)

        logger.info(f"Version {version} deleted by {session['user_email']}")
        return jsonify({"message": "Deleted"}), 200
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        return jsonify({"error": str(e)}), 500
    
@app.route('/update_status/summary', methods=['GET'])
@login_required
def update_status_summary():
    try:
        response = execute_query("SELECT status FROM device_update_status")
        status_counts = defaultdict(int)
        for record in response.get("data", []):
            status_counts[record['status']] += 1
        return jsonify({
            'successful': status_counts['success'],
            'pending': status_counts['pending'],
            'failed': status_counts['failed']
        }), 200
    except Exception as e:
        logger.error(f"Error fetching update status summary: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/update_status/all', methods=['GET'])
@login_required
def update_status_all():
    try:
        response = execute_query("SELECT employee_id, device_id, version, status, last_attempted_at, error_message FROM device_update_status")
        return jsonify(response.get("data", [])), 200
    except Exception as e:
        logger.error(f"Error fetching all update statuses: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/update_status/success', methods=['GET'])
@login_required
def update_status_success():
    try:
        response = execute_query("SELECT employee_id, device_id, version, last_attempted_at FROM device_update_status WHERE status = 'success'")
        return jsonify(response.get("data", [])), 200
    except Exception as e:
        logger.error(f"Error fetching successful updates: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/update_status/pending', methods=['GET'])
@login_required
def update_status_pending():
    try:
        response = execute_query("SELECT employee_id, device_id, version, last_attempted_at FROM device_update_status WHERE status = 'pending'")
        return jsonify(response.get("data", [])), 200
    except Exception as e:
        logger.error(f"Error fetching pending updates: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/update_status/failed', methods=['GET'])
@login_required
def update_status_failed():
    try:
        response = execute_query("SELECT employee_id, device_id, version, last_attempted_at, error_message FROM device_update_status WHERE status = 'failed'")
        return jsonify(response.get("data", [])), 200
    except Exception as e:
        logger.error(f"Error fetching failed updates: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/check_upload_readiness', methods=['GET'])
@login_required
def check_upload_readiness():
    try:
        total, used, free = shutil.disk_usage(app.config['UPLOAD_FOLDER'])
        if free < 1024 * 1024 * 100:  # Less than 100MB free
            return jsonify({'status': 'error', 'message': 'Insufficient disk space'}), 500
        if not os.access(app.config['UPLOAD_FOLDER'], os.W_OK):
            return jsonify({'status': 'error', 'message': 'No write permission for upload folder'}), 500
        return jsonify({'status': 'ready'}), 200
    except Exception as e:
        logger.error(f"Error checking upload readiness: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
        
@app.route('/view_reactions/<content_id>')
@login_required
def view_reactions(content_id):
    try:
        # Fixed: Select 'url', not 'image_url' twice!
        content_result = execute_query(
            "SELECT title, text, image_url, url, type FROM scheduled_content WHERE id = %s",
            (content_id,), fetch=True
        )
        content_data = content_result.get("data", [])
        if not content_data:
            content = {'title': 'Not Found', 'text': '', 'image_url': None, 'url': None, 'type': 'text'}
        else:
            content = content_data[0]

        views_result = execute_query("""
            SELECT v.viewed_duration, v.timestamp, COALESCE(e.email, v.employee_id) as email
            FROM views v
            LEFT JOIN employees e ON v.employee_id = e.id
            WHERE v.content_id = %s
            ORDER BY v.timestamp DESC
        """, (content_id,), fetch=True)
        views = views_result.get("data", []) or []
        views_details = [
            {
                'employee_email': v['email'],
                'viewed_duration': v['viewed_duration'],
                'timestamp': v['timestamp'].strftime("%d %b %Y, %I:%M %p") if v['timestamp'] else '—'
            }
            for v in views
        ]
        # Reactions with email
        reactions_result = execute_query(
            "SELECT r.reaction, r.timestamp, COALESCE(e.email, r.employee_id) as email "
            "FROM reactions r LEFT JOIN employees e ON r.employee_id = e.id "
            "WHERE r.content_id = %s ORDER BY r.timestamp DESC",
            (content_id,), fetch=True
        )
        logging.debug(f"Reactions query result: {reactions_result}")
        reactions = reactions_result.get("data", []) or []

        # Feedback with email
        feedback_result = execute_query(
            "SELECT f.feedback, f.timestamp, COALESCE(e.email, f.employee_id) as email "
            "FROM feedback f LEFT JOIN employees e ON f.employee_id = e.id "
            "WHERE f.content_id = %s ORDER BY f.timestamp DESC",
            (content_id,), fetch=True
        )
        feedback = feedback_result.get("data", []) or []

        # Format data
        reaction_details = [
            {
                'employee_email': r['email'],
                'reaction': r['reaction'],
                'timestamp': r['timestamp'].strftime("%d %b %Y, %I:%M %p") if r['timestamp'] else '—'
            }
            for r in reactions
        ]
        logging.debug(f"Formatted reaction details: {reaction_details}")
        feedback_details = [
            {
                'employee_email': f['email'],
                'feedback': f['feedback'],
                'timestamp': f['timestamp'].strftime("%d %b %Y, %I:%M %p") if f['timestamp'] else '—'
            }
            for f in feedback
        ]

        return render_template('view_react.html',
                       content_id=content_id,
                       content_title=content.get('title', 'No Title'),
                       content_text=content.get('text', ''),
                       content_type=content.get('type', 'text'),
                       image_url=content.get('image_url'),
                       video_url=content.get('url'),
                       reaction_details=reaction_details or [],   # ← Add "or []"
                       feedback_details=feedback_details or [],
                       views_details=views_details or [],
                       error=None)

    except Exception as e:
        logging.error(f"Error in view_reactions/{content_id}: {e}", exc_info=True)
        return render_template('view_react.html',
                              content_id=content_id,
                              content_title="Error",
                              content_text="Failed to load content",
                              content_type="text",
                              image_url=None,
                              video_url=None,
                              reaction_details="[]",
                              feedback_details=[],
                              views_details=[],
                              error="Failed to load data")
            

@app.route('/send_message')
@login_required
def send_message_page():
    try:
        # FIXED: Added fetch=True
        active_devices_result = execute_query("""
            SELECT employee_id 
            FROM employee_devices 
            WHERE status = 1
        """, fetch=True)

        active_employee_ids = [
            row['employee_id'] 
            for row in active_devices_result.get("data", [])
        ]

        if not active_employee_ids:
            logging.warning("No active employees found")
            return render_template('send_message.html', 
                                 employees_json='[]', 
                                 active_employees=[], 
                                 departments=[], 
                                 error="No active employees found. Please activate employees via device registration.")

        # FIXED: Proper IN query with tuple + fetch=True
        placeholders = ','.join(['%s'] * len(active_employee_ids))
        employees_result = execute_query(
            f"SELECT id, email FROM employees WHERE id IN ({placeholders})",
            tuple(active_employee_ids),
            fetch=True
        )

        employees = employees_result.get("data", [])
        logging.debug(f"Fetched {len(employees)} active employees")

        if not employees:
            return render_template('send_message.html', 
                                 employees_json='[]', 
                                 active_employees=[], 
                                 departments=[], 
                                 error="No employees found with active devices.")

        employees_data = []
        departments = set()
        for emp in employees:
            email = emp.get('email', '')
            if not email or '@' not in email:
                continue
            try:
                dept = email.split('@')[0].split('.')[-1]  # e.g., john.ht@acorn.lk → ht
                employees_data.append({
                    'id': emp['id'],
                    'email': email,
                    'department': dept
                })
                departments.add(dept)
            except:
                continue

        employees_json = json.dumps(employees_data)
        departments = sorted(departments)

        return render_template('send_message.html', 
                             employees_json=employees_json, 
                             active_employees=employees, 
                             departments=departments)

    except mysql.connector.Error as e:
        logging.error(f"MySQL error in send_message_page: {e}")
        return render_template('send_message.html', 
                             employees_json='[]', 
                             active_employees=[], 
                             departments=[], 
                             error="Database connection failed. Please try again later.")
    except Exception as e:
        logging.error(f"Unexpected error in send_message_page: {e}", exc_info=True)
        return render_template('send_message.html', 
                             employees_json='[]', 
                             active_employees=[], 
                             departments=[], 
                             error="Server error")
    

@app.route('/cortex_logs')
@login_required
def cortex_logs():
    try:
        headers = {
            "x-xdr-auth-id": CORTEX_API_KEY_ID,
            "Authorization": CORTEX_API_KEY,
            "Content-Type": "application/json"
        }


        payload = {
            "request_data": {
                "filters": [],
                "search_from": 0,
                "search_to": 10,
                "sort": {
                    "field": "last_seen",
                    "keyword": "desc"
                }
            }
        }


        response = requests.post(CORTEX_API_URL, headers=headers, json=payload)
        response.raise_for_status()


        data = response.json()
        endpoints = data.get('reply', {}).get('endpoints', [])


        processed_endpoints = []
        for endpoint in endpoints:
            processed_endpoints.append({
                'hostname': endpoint.get('endpoint_name', 'N/A'),
                'ip': endpoint.get('ip', []),   # Cortex returns "ip"
                'os_type': endpoint.get('platform', 'N/A'),
                'os_version': endpoint.get('os_version', 'N/A'),
                'endpoint_status': endpoint.get('status', 'N/A'),
                'last_seen': endpoint.get('last_seen', 'N/A'),
                'email': endpoint.get('email', 'N/A')
            })


        logging.info(f"Fetched {len(processed_endpoints)} endpoints from Cortex XDR API")
        return render_template('cortex_logs.html', endpoints=processed_endpoints)


    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching data from Cortex XDR API: {str(e)}")
        return render_template('cortex_logs.html', endpoints=[], error=f"Failed to fetch endpoint data: {str(e)}")
    except Exception as e:
        logging.error(f"Unexpected error in cortex_logs route: {str(e)}")
        return render_template('cortex_logs.html', endpoints=[], error=f"Unexpected error: {str(e)}")






@app.route('/monitor_devices')
@login_required
def monitor_devices():
    try:
            # Fetch devices from Supabase
        devices_result = execute_query("""
        SELECT 
            employee_id, status, active_status, ip, device_type, 
            hostname, email, last_seen, app_running 
            FROM employee_devices 
            
            ORDER BY last_seen DESC
        """, fetch=True)
    
        devices = devices_result.get("data", []) or []
        logging.debug(f"Fetched {len(devices)} devices from Supabase: {devices}")


        # Fetch all employees to map emails
        employees_result = execute_query(
            "SELECT id, email FROM employees",
            fetch=True
        )
        employee_map = {
            emp['id']: emp['email'] 
            for emp in employees_result.get("data", [])
        }
        logging.debug(f"Fetched {len(employee_map)} employees from Supabase: {employee_map}")


        # Prepare headers for Cortex XDR API
        headers = {
            "x-xdr-auth-id": CORTEX_API_KEY_ID,
            "Authorization": CORTEX_API_KEY,
            "Content-Type": "application/json"
        }


        # Payload for Cortex API
        payload = {
            "request_data": {
                "filters": [],
                "search_from": 0,
                "search_to": 100,  # Adjust as needed
                "sort": {"field": "last_seen", "keyword": "desc"}
            }
        }


        # Fetch endpoint data from Cortex XDR
        try:
            cortex_response = requests.post(CORTEX_API_URL, headers=headers, json=payload)
            cortex_response.raise_for_status()
            cortex_data = cortex_response.json()
            cortex_endpoints = cortex_data.get('reply', {}).get('endpoints', [])
            logging.debug(f"Fetched {len(cortex_endpoints)} endpoints from Cortex XDR API")
            # Log full endpoint data for debugging
            for endpoint in cortex_endpoints:
                logging.debug(f"Cortex XDR endpoint data: {endpoint}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Cortex XDR API request failed: {str(e)}")
            cortex_endpoints = []
            error_message = f"Cortex XDR API error: {str(e)}"


        # Create lookup maps
        cortex_hostname_map = {}
        cortex_email_map = {}
        cortex_ip_map = {}
        for endpoint in cortex_endpoints:
            hostname = endpoint.get('endpoint_name', '').lower().strip()
            # Placeholder for correct email field - replace 'correct_email_field' with the field name from the image
            email = (
                endpoint.get('correct_email_field', '') or  # Replace with actual field (e.g., 'user_email')
                endpoint.get('email', '') or
                endpoint.get('user', '') or
                endpoint.get('user_email', '') or
                endpoint.get('username', '')
            ).lower().strip()
            ip = endpoint.get('ip', '')  # Handle single IP or list as string
            if isinstance(ip, list):
                ip = ip[0] if ip else ''  # Use first IP if list
            logging.debug(f"Processing Cortex endpoint: hostname={hostname}, email={email}, ip={ip}")
            if hostname:
                cortex_hostname_map[hostname] = endpoint
            if email:
                cortex_email_map[email] = endpoint
            if ip:
                cortex_ip_map[ip] = endpoint
        logging.debug(f"Cortex hostname map keys: {list(cortex_hostname_map.keys())}")
        logging.debug(f"Cortex email map keys: {list(cortex_email_map.keys())}")
        logging.debug(f"Cortex ip map keys: {list(cortex_ip_map.keys())}")


        # Process devices with verification
        processed_devices = []
        for device in devices:
            employee_id = device['employee_id']
            hostname = (device.get('hostname') or '').lower().strip()
            # Prefer email from employees table, fallback to device email
            email = employee_map.get(employee_id, device.get('email', '')).lower().strip()
            ip = device.get('ip', '')


            is_hostname_valid = bool(hostname and hostname in cortex_hostname_map)
            is_email_valid = bool(email and email in cortex_email_map)
            is_ip_valid = bool(ip and ip in cortex_ip_map)


            processed_devices.append({
                'employee_id': employee_id,
                'status': device['status'],
                'active_status': device['active_status'],
                'ip': device.get('ip', 'N/A'),
                'device_type': device.get('device_type', 'N/A'),
                'hostname': device.get('hostname', 'N/A'),
                'email': email or 'N/A',  # Use resolved email
                'last_seen': device.get('last_seen', 'N/A'),
                'app_running': device.get('app_running'),
                'is_hostname_valid': is_hostname_valid,
                'is_email_valid': is_email_valid,
                'is_ip_valid': is_ip_valid
            })


        # Split devices
        active_devices = [d for d in processed_devices if d['status']]
        inactive_devices = [d for d in processed_devices if not d['status']]
      


        return render_template(
            'monitor_devices.html',
            active_devices=active_devices,
            inactive_devices=inactive_devices,
            error=error_message if 'error_message' in locals() else None
        )


    except mysql.connector.Error as e:
        logging.error(f"MySQL error fetching devices: {e}")
        return render_template('monitor_devices.html', active_devices=[], inactive_devices=[], error=f"Database error: {e}")
    except Exception as e:
        logging.error(f"Unexpected error in monitor_devices route: {str(e)}")
        return render_template('monitor_devices.html', active_devices=[], inactive_devices=[], error=f"Unexpected error: {str(e)}")
                    
@app.route('/send_message', methods=['POST'])
@login_required
def send_message():
    try:
        logging.debug(f"Received send_message data: {dict(request.form)}, files: {request.files}")
        if 'title' not in request.form or 'text' not in request.form or ('send_now' not in request.form and 'scheduled_time' not in request.form) or not request.form.getlist('employees'):
            logging.error("Missing required fields in send_message: title, text, send_now or scheduled_time, or employees")
            return jsonify({"message": "Missing required fields: title, text, send_now or scheduled_time, or employees"}), 400
        
        title = request.form['title'].strip()
        if len(title) > 100:
            logging.error("Title exceeds 100 characters")
            return jsonify({"message": "Title cannot exceed 100 characters"}), 400
        
        text = request.form['text']
        send_now = request.form.get('send_now') == 'on'
        scheduled_time_str = request.form.get('scheduled_time')
        employees = request.form.getlist('employees')
        
        logging.debug(f"Selected employees: {employees}")
        valid_employees = [emp for emp in employees if emp and emp.strip()]
        if not valid_employees:
            logging.error("No valid employees selected after filtering")
            return jsonify({"message": "No valid employees selected"}), 400
        
        scheduled_time = None
        if not send_now and scheduled_time_str:
            try:
                # Parse as Sri Lanka time (UTC+5:30)
                scheduled_time = datetime.strptime(scheduled_time_str, '%Y-%m-%dT%H:%M').replace(
                    tzinfo=timezone(timedelta(hours=5, minutes=30))
                )
                # Convert to UTC for storage
                scheduled_time = scheduled_time.astimezone(timezone.utc)
                logging.debug(f"Parsed scheduled_time (UTC): {scheduled_time}")
            except ValueError as e:
                logging.error(f"Invalid scheduled_time format: {scheduled_time_str}")
                return jsonify({"message": "Invalid date/time format"}), 400
        else:
            scheduled_time = datetime.now(timezone.utc)


        video_url = None
        if 'video' in request.files and request.files['video'].filename:
            video = request.files['video']
            if not video.filename.lower().endswith('.mp4'):
                logging.error("Invalid video format. Only MP4 supported")
                return jsonify({"message": "Only MP4 videos are supported"}), 400
            
            video_id = str(uuid.uuid4())
            video_filename = secure_filename(f"{video_id}.mp4")
            video_path = os.path.join(VIDEO_DIR, video_filename)
            
            try:
                retries = 3
                for attempt in range(retries):
                    try:
                        video.save(video_path)
                        if not verify_file(VIDEO_DIR, video_filename):
                            raise Exception(f"Video save verification failed for {video_filename}")
                        video_url = f"{SERVER_URL}/uploads/message/videos/{video_filename}"
                        logging.info(f"Video saved successfully: {video_url}")
                        break
                    except Exception as e:
                        logging.error(f"Video save attempt {attempt + 1} failed: {str(e)}")
                        if attempt == retries - 1:
                            if os.path.exists(video_path):
                                os.remove(video_path)
                            raise Exception(f"Failed to save video after {retries} attempts: {str(e)}")
                        time.sleep(2)
            except Exception as e:
                logging.error(f"Video save failed: {str(e)}")
                return jsonify({"message": f"Failed to save video: {str(e)}"}), 500


        image_url = None
        if 'image' in request.files and request.files['image'].filename:
            image = request.files['image']
            if not image.filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                logging.error("Invalid image format. Only JPG/PNG supported")
                return jsonify({"message": "Only JPG/PNG images are supported"}), 400
            
            image_id = str(uuid.uuid4())
            image_ext = image.filename.rsplit('.', 1)[1].lower()
            image_filename = secure_filename(f"{image_id}.{image_ext}")
            image_path = os.path.join(IMAGE_DIR, image_filename)
            
            try:
                retries = 3
                for attempt in range(retries):
                    try:
                        image.save(image_path)
                        if not verify_file(IMAGE_DIR, image_filename):
                            raise Exception(f"Image save verification failed for {image_filename}")
                        image_url = f"{SERVER_URL}/uploads/message/images/{image_filename}"
                        logging.info(f"Image saved successfully: {image_url}")
                        break
                    except Exception as e:
                        logging.error(f"Image save attempt {attempt + 1} failed: {str(e)}")
                        if attempt == retries - 1:
                            if os.path.exists(image_path):
                                os.remove(image_path)
                            raise Exception(f"Failed to save image after {retries} attempts: {str(e)}")
                        time.sleep(2)
            except Exception as e:
                logging.error(f"Image save failed: {str(e)}")
                return jsonify({"message": f"Failed to save image: {str(e)}"}), 500
        
        # Determine content type
        content_type = "text"
        if video_url and image_url:
            content_type = "both"
        elif video_url:
            content_type = "video"
        elif image_url:
            content_type = "image"


        content_id = str(uuid.uuid4())
        content = {
            "id": content_id,
            "type": content_type,
            "title": title,
            "text": text,
            "image_url": image_url,
            "url": video_url,
            "scheduled_time": scheduled_time.strftime('%Y-%m-%d %H:%M:%S'),
            "employees": valid_employees,
        }

        logging.debug(f"Inserting content into scheduled_content: {content}")

        execute_query("""
            INSERT INTO scheduled_content
                (id, type, title, text, image_url, url, scheduled_time, employees)
            VALUES (%(id)s, %(type)s, %(title)s, %(text)s, %(image_url)s, %(url)s, %(scheduled_time)s, %(employees)s)
        """, {
            'id': content['id'],
            'type': content['type'],
            'title': content['title'],
            'text': content['text'],
            'image_url': content.get('image_url'),
            'url': content.get('url'),
            'scheduled_time': content['scheduled_time'],
            'employees': json.dumps(content['employees'])
        }, commit=True)

        logging.info(f"Content inserted successfully: {content['id']}")

        if not send_now and scheduled_time > datetime.now(timezone.utc):
            schedule_notification(content_id, scheduled_time, valid_employees)
        else:
            send_notification(content_id, valid_employees)
        
        logging.info(f"Message scheduled successfully: {content_id}, employees: {valid_employees}")
        return jsonify({"message": "Message scheduled successfully", "content_id": content_id})
    
    except mysql.connector.Error as e:
            logging.error(f"MySQL error in send_message: {e}")
            return jsonify({"message": "Database error. Please try again later."}), 500

    except Exception as e:
            logging.error(f"Unexpected error in send_message: {e}", exc_info=True)
            return jsonify({"message": "An error occurred. Please try again."}), 500
    
@app.route('/update_bulk_device_status', methods=['POST'])
@login_required
def update_bulk_device_status():
    try:
        data = request.json
        logging.debug(f"Received update_bulk_device_status data: {data}")
        if not data or not isinstance(data, list):
            logging.error("Invalid or missing data for bulk update")
            return jsonify({"message": "Invalid or missing data"}), 400


        success_count = 0
        for update in data:
            employee_id = update.get('employee_id')
            
            active_status = update.get('active_status')
            logging.debug(f"Processing update for employee_id: {employee_id}, active_status: {active_status}")
            if not employee_id or active_status is None:
                logging.error(f"Missing required fields for employee_id: {employee_id}")
                continue


            # Step 1: Fetch employee email (required for NOT NULL)
            employee_result = execute_query(
                "SELECT email FROM employees WHERE id = %s LIMIT 1",
                (employee_id,),
                fetch=True
            )

            if not employee_result.get("data"):
                logging.error(f"Employee {employee_id} not found in employees table")
                continue
            
            email = employee_result["data"][0]["email"]
            logging.debug(f"Fetched email for {employee_id}: {email}")

            # Step 2: Fetch existing device data (with safe check)
            existing_result = execute_query("""
                SELECT status, app_running, ip, device_type, hostname 
                FROM employee_devices 
                WHERE employee_id = %s 
                LIMIT 1
            """, (employee_id,), fetch=True)

            existing_device = existing_result.get("data", [])

            if existing_device:
                existing = existing_device[0]
                status = existing.get('status', 'online')
                app_running = existing.get('app_running', False)
                ip = existing.get('ip')
                device_type = existing.get('device_type')
                hostname = existing.get('hostname', 'unknown-host')  # Fallback if somehow null
                logging.debug(f"Found existing device for {employee_id}: hostname={hostname}")
            else:
                # Defaults for new records (NO NULLs for required fields)
                status = 'online'
                app_running = False
                ip = None  # Optional
                device_type = None  # Optional
                hostname = 'unknown-host'  # FIXED: Required, always string
                logging.warning(f"No existing device for {employee_id}; using defaults, email={email}")


            # Step 3: Build device_data with ALL required fields (no None for NOT NULL)
            device_data = {
                "employee_id": employee_id,
                "status": status,  # NOT NULL
                "active_status": active_status,  # NOT NULL
                "hostname": hostname,  # NOT NULL, guaranteed string
                "email": email,  # NOT NULL, from employees
                "last_seen": datetime.now(timezone.utc).isoformat(),  # NOT NULL
                "app_running": app_running,  # NOT NULL
                # Optional fields (can be None)
                "ip": ip,
                "device_type": device_type,
            }
            # FIXED: DON'T filter None for required fields—only optionals if needed (but here, all required are set)

            execute_query("""
                INSERT INTO employee_devices 
                    (employee_id, status, active_status, hostname, email, last_seen, app_running, ip, device_type)
                VALUES 
                    (%(employee_id)s, %(status)s, %(active_status)s, %(hostname)s, %(email)s, %(last_seen)s, %(app_running)s, %(ip)s, %(device_type)s)
                ON DUPLICATE KEY UPDATE
                    status = VALUES(status),
                    active_status = VALUES(active_status),
                    hostname = VALUES(hostname),
                    email = VALUES(email),
                    last_seen = VALUES(last_seen),
                    app_running = VALUES(app_running),
                    ip = VALUES(ip),
                    device_type = VALUES(device_type)
            """, device_data, commit=True)

            success_count += 1
            logging.info(f"Device status updated for employee: {employee_id} to active_status: {active_status}, hostname: {device_data.get('hostname')}, email: {email}")


        return jsonify({"message": f"Bulk device status updated successfully ({success_count} devices)"})
    except mysql.connector.Error as e:
        logging.error(f"MySQL error updating bulk device status: {e}")
        return jsonify({"message": f"Database error: {e}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error updating bulk device status: {str(e)}")
        return jsonify({"message": f"Unexpected error: {str(e)}"}), 500
    
@app.route('/content/<employee_id>', methods=['GET'])
def get_content(employee_id):
    try:
        logging.debug(f"Fetching content for employee_id: {employee_id}")

        # Get content visible to this employee and already scheduled
        content_result = execute_query("""
            SELECT id, type, title, text, image_url, url, scheduled_time, employees
            FROM scheduled_content
            WHERE JSON_CONTAINS(employees, %s)
              AND scheduled_time <= NOW()
            ORDER BY scheduled_time DESC
        """, (json.dumps([employee_id]),), fetch=True)

        employee_content = content_result.get("data", []) or []

        # CRITICAL FIX: Format scheduled_time properly for client
        for item in employee_content:
            if item['scheduled_time']:
                item['scheduled_time'] = format_datetime_for_client(item['scheduled_time'])
            else:
                item['scheduled_time'] = None

        # Notifications (last 7 days)
        notif_result = execute_query("""
            SELECT *
            FROM notifications
            WHERE JSON_CONTAINS(employees, %s)
              AND time >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            ORDER BY time DESC
        """, (json.dumps([employee_id]),), fetch=True)

        employee_notifications = notif_result.get("data", []) or []

        # Add readable text to notifications
        for notif in employee_notifications:
            content = next((c for c in employee_content if c['id'] == notif['content_id']), None)
            if content:
                notif['text'] = f"New content: {content.get('title', 'No title')} - {content.get('text', 'No text')}"
            else:
                notif['text'] = f"Notification at {notif.get('time', 'unknown time')}"

        logging.info(f"Returning {len(employee_content)} contents for employee {employee_id}")
        return jsonify({
            "content": employee_content,
            "notifications": employee_notifications
        })

    except Exception as e:
        logging.error(f"Error in get_content for {employee_id}: {str(e)}", exc_info=True)
        return jsonify({"content": [], "notifications": []}), 500
                    
@app.route('/devices')
@login_required
def devices():
    try:
        devices = execute_query("SELECT * FROM employee_devices ORDER BY last_seen DESC", fetch=True).get("data", []) or []
        logging.info(f"Fetched {len(devices)} devices from MySQL")
        return jsonify({device['employee_id']: device for device in devices})
    except Exception as e:
        logging.error(f"Error fetching devices: {str(e)}")
        return jsonify({"message": f"Error fetching devices: {str(e)}"}), 500


@app.route('/get_or_create_employee', methods=['POST'])
def get_or_create_employee():
    try:
        data = request.json
        logging.debug(f"Received get_or_create_employee data: {data}")
        email = data['email']
        if not email:
            logging.error("Missing email")
            return jsonify({"message": "Missing email"}), 400
        response = execute_query("SELECT id FROM employees WHERE email = %s", (email,), fetch=True)
        if response.get("data"):
            employee_id = response["data"][0]['id']
        else:
            employee_id = str(uuid.uuid4())

            execute_query("""
                INSERT IGNORE INTO employees (id, email) 
                VALUES (%s, %s)
            """, (employee_id, email), commit=True)

            logging.info(f"Employee ID for {email}: {employee_id}")

        return jsonify({"employee_id": employee_id})
    except mysql.connector.Error as e:
        logging.error(f"Error getting/creating employee: {e}")
        return jsonify({"message": f"Error getting/creating employee: {e}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error getting/creating employee: {str(e)}")
        return jsonify({"message": f"Unexpected error getting/creating employee: {str(e)}"}), 500


@app.route('/register_device', methods=['POST'])
def register_device():
    try:
        data = request.json
        logging.debug(f"Received register_device data: {data}")
        employee_id = data['employee_id']
        ip = data.get('ip')
        device_type = data.get('device_type')
        hostname = data.get('hostname')
        email = data.get('email')
        if not employee_id:
            logging.error("Missing employee_id")
            return jsonify({"message": "Missing employee_id"}), 400
        employee = execute_query("SELECT id FROM employees WHERE id = %s", (employee_id,), fetch=True).get("data", []) or []
        if not employee:
            logging.error(f"Employee ID {employee_id} not found")
            return jsonify({"message": f"Employee ID {employee_id} not found in employees table"}), 400
        
        device_data_base = {
            "status": "online",
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "app_running": True
        }


        if ip:
            device_data_base["ip"] = ip
        if device_type:
            device_data_base["device_type"] = device_type
        if hostname:
            device_data_base["hostname"] = hostname
        if email:
            device_data_base["email"] = email
        
        exists = execute_query("SELECT active_status FROM employee_devices WHERE employee_id = %s", (employee_id,), fetch=True).get("data", []) or []
        if not exists:
            device_data_base["active_status"] = False
        
        execute_query("""
            INSERT INTO employee_devices (employee_id, ip, device_type, hostname, email, status, last_seen, app_running, active_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                ip = VALUES(ip),
                device_type = VALUES(device_type),
                hostname = VALUES(hostname),
                email = VALUES(email),
                status = VALUES(status),
                last_seen = VALUES(last_seen),
                app_running = VALUES(app_running),
                active_status = VALUES(active_status)
        """, (
            employee_id,
            device_data_base.get("ip"),
            device_data_base.get("device_type"),
            device_data_base.get("hostname"),
            device_data_base.get("email"),
            device_data_base.get("status"),
            device_data_base.get("last_seen"),
            device_data_base.get("app_running"),
            device_data_base.get("active_status")
        ), commit=True)
        logging.info(f"Device registered/updated: {employee_id}, hostname: {hostname}, email: {email}")
        return jsonify({"message": "Device registered"})
    except mysql.connector.Error as e:
        logging.error(f"Error registering device: {e}")
        return jsonify({"message": f"Error registering device: {e}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error registering device: {str(e)}")
        return jsonify({"message": f"Unexpected error registering device: {str(e)}"}), 500


        

@app.route('/set_message_delay', methods=['POST'])
def set_message_delay():
    try:
        data = request.get_json()
        logging.debug(f"Received set_message_delay data: {data}")

        employee_id = data.get('employee_id')
        content_id = data.get('content_id')
        delay_choice = data.get('delay_choice')

        if not all([employee_id, content_id, delay_choice]):
            return jsonify({"message": "Missing required fields"}), 400

        # Delay mapping
        delay_map = {
            "Play Immediate": 0,
            "Play within 15 minutes": 15 * 60,
            "Play within 30 minutes": 30 * 60,
            "Play within 1 hour": 60 * 60,
            "Play within 3 hours": 3 * 60 * 60,
        }
        if delay_choice not in delay_map:
            return jsonify({"message": "Invalid delay choice"}), 400

        delay_seconds = delay_map[delay_choice]

        # Fetch scheduled_time (MySQL returns naive datetime)
        result = execute_query(
            "SELECT scheduled_time FROM scheduled_content WHERE id = %s LIMIT 1",
            (content_id,),
            fetch=True
        )
        row = result.get("data", [])
        if not row:
            return jsonify({"message": "Content not found"}), 400

        scheduled_time_naive = row[0]['scheduled_time']  # ← This is naive

        # Make it aware (assume it's stored in UTC)
        scheduled_time = scheduled_time_naive.replace(tzinfo=timezone.utc)

        # Calculate display time
        if delay_choice == "Play Immediate":
            # Compare both as UTC-aware
            now_utc = datetime.now(timezone.utc)
            display_time = max(scheduled_time, now_utc)
        else:
            # Local time: Sri Lanka = UTC+5:30
            local_tz = timezone(timedelta(hours=5, minutes=30))
            now_local = datetime.now(local_tz)
            display_time = now_local + timedelta(seconds=delay_seconds)

        # Convert final display_time to UTC for storage
        if display_time.tzinfo is None:
            display_time = display_time.replace(tzinfo=local_tz)
        display_time_utc = display_time.astimezone(timezone.utc)

        # Save to DB
        execute_query("""
            INSERT INTO message_preferences (employee_id, content_id, delay_choice, display_time)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                delay_choice = VALUES(delay_choice),
                display_time = VALUES(display_time)
        """, (
            employee_id,
            content_id,
            delay_choice,
            display_time_utc.strftime('%Y-%m-%d %H:%M:%S')
        ), commit=True)

        logging.info(f"Delay set successfully: {employee_id} → {content_id} → {delay_choice}")
        return jsonify({"message": "Delay set successfully"})

    except Exception as e:
        logging.error(f"Error in set_message_delay: {e}", exc_info=True)
        return jsonify({"message": "Server error"}), 500
                                    
@app.route('/message_preferences/<employee_id>/<content_id>', methods=['GET'])
def get_message_preference(employee_id, content_id):
    logging.debug(f"Fetching message preference for employee_id: {employee_id}, content_id: {content_id}")
    try:
        preference_result = execute_query("""
            SELECT delay_choice, display_time 
            FROM message_preferences 
            WHERE employee_id = %s AND content_id = %s 
            LIMIT 1
        """, (employee_id, content_id), fetch=True)

        preference = preference_result.get("data", [])

        logging.info(f"Fetched preference for employee {employee_id}, content {content_id}: {preference}")
        return jsonify({"preference": preference[0] if preference else {}})
    except mysql.connector.Error as e:
        logging.error(f"MySQL error fetching preference for employee {employee_id}, content {content_id}: {e}")
        return jsonify({"message": f"Error fetching preference: {e}", "preference": {}}), 500
    except Exception as e:
        logging.error(f"Unexpected error fetching preference for employee {employee_id}, content {content_id}: {str(e)}")
        return jsonify({"message": f"Unexpected error fetching preference: {str(e)}", "preference": {}}), 500
        
@app.route('/feedback', methods=['POST'])
def receive_feedback():
    try:
        data = request.json
        logging.debug(f"Received feedback data: {data}")
        execute_query("""
            INSERT INTO feedback 
                (content_id, employee_id, feedback, timestamp)
            VALUES 
                (%s, %s, %s, NOW())
        """, (
            data['content_id'],
            data['employee_id'],
            data['feedback']
        ), commit=True)

        logging.info(f"Feedback received for content: {data['content_id']} from employee: {data['employee_id']}")
       
        return jsonify({"message": "Feedback received"})
    except Exception as e:
        logging.error(f"Error receiving feedback: {str(e)}")
        return jsonify({"message": f"Error receiving feedback: {str(e)}"}), 500


@app.route('/reaction', methods=['POST'])  
def record_reaction():
    try:
        data = request.json
        content_id = data.get('content_id')
        employee_id = data.get('employee_id')
        reaction = data.get('reaction')
        
        if not all([content_id, employee_id, reaction]):
            logging.error("Missing required fields in reaction: content_id, employee_id, or reaction")
            return jsonify({"message": "Missing required fields"}), 400
        
        if reaction not in ["like", "unlike", "heart", "cry"]:
            logging.error(f"Invalid reaction type: {reaction}")
            return jsonify({"message": "Invalid reaction type"}), 400


        # Check if a reaction already exists for this content_id and employee_id
        existing_reaction = execute_query("""
            SELECT id, reaction, timestamp 
            FROM reactions 
            WHERE content_id = %s AND employee_id = %s 
            LIMIT 1
        """, (content_id, employee_id), fetch=True).get("data", [])

        if existing_reaction:
            # Update the existing reaction
            reaction_id = existing_reaction[0]['id']

            execute_query("""
                UPDATE reactions 
                SET reaction = %s, timestamp = NOW()
                WHERE id = %s
            """, (reaction, reaction_id), commit=True)

            logging.info(f"Reaction updated: {reaction} for content_id {content_id}, employee_id {employee_id}")

        else:
            # Insert a new reaction if none exists
            try:
                execute_query("""
                    INSERT INTO reactions 
                        (id, content_id, employee_id, reaction, timestamp)
                    VALUES 
                        (%s, %s, %s, %s, %s)
                """, (
                    str(uuid.uuid4()),
                    content_id,
                    employee_id,
                    reaction,
                    datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
                ), commit=True)

            except mysql.connector.Error as e:
                if "Duplicate entry" in str(e):
                    logging.warning(f"Duplicate reaction entry detected for content_id {content_id}, employee_id {employee_id}. Retrying update.")
                    # If a duplicate entry error occurs, it means another reaction was inserted concurrently
                    existing_reaction = execute_query("""
                        SELECT id 
                        FROM reactions 
                        WHERE content_id = %s AND employee_id = %s 
                        LIMIT 1
                    """, (content_id, employee_id), fetch=True).get("data", [])
                    if existing_reaction:
                        reaction_id = existing_reaction[0]['id']
                        execute_query("""
                            UPDATE reactions 
                            SET reaction = %s, timestamp = NOW()
                            WHERE id = %s
                        """, (reaction, reaction_id), commit=True)
                        logging.info(f"Reaction updated after duplicate entry: {reaction} for content_id {content_id}, employee_id {employee_id}")
                else:
                    raise
            logging.info(f"Reaction recorded: {reaction} for content_id {content_id}, employee_id {employee_id}")


        return jsonify({"message": "Reaction recorded successfully"})
    except mysql.connector.Error as e:
        logging.error(f"MySQL error recording reaction: {e}")
        return jsonify({"message": f"Database error: {e}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error recording reaction: {str(e)}")
        return jsonify({"message": f"Unexpected error: {str(e)}"}), 500
    
@app.route('/update_device_status', methods=['POST'])
def update_device_status():
    try:
        data = request.json
        logging.debug(f"Received update_device_status data: {data}")
        employee_id = data.get('employee_id')
        active_status = data.get('status')
       
        if not employee_id or active_status is None:
            logging.error("Missing required fields in update_device_status: employee_id, active_status, or status")
            return jsonify({"message": "Missing required fields"}), 400
        
        # Step 1: Fetch employee email (required for NOT NULL)
        employee_resp = execute_query(
            "SELECT email FROM employees WHERE id = %s LIMIT 1",
            (employee_id,),
            fetch=True
        )
        if not employee_resp.get("data", []):
            logging.error(f"Employee {employee_id} not found in employees table")
            return jsonify({"message": f"Employee {employee_id} not found"}), 400
        email = employee_resp.get("data", [])[0]['email']  # Guaranteed NOT NULL
        logging.debug(f"Fetched email for {employee_id}: {email}")


        # Step 2: Fetch existing device data (with safe check)
        existing_result = execute_query("""
            SELECT status, app_running, ip, device_type, hostname 
            FROM employee_devices 
            WHERE employee_id = %s 
            LIMIT 1
            """, (employee_id,), fetch=True)

        existing_device = existing_result.get("data", [])
    
        if existing_device:
            existing = existing_device[0]
            status = existing.get('status', 'online')
            app_running = existing.get('app_running', False)
            ip = existing.get('ip')
            device_type = existing.get('device_type')
            hostname = existing.get('hostname', 'unknown-host')  # Fallback
            logging.debug(f"Found existing device for {employee_id}: hostname={hostname}")
        else:
            # Defaults for new records (NO NULLs)
            status = 'online'
            app_running = False
            ip = None
            device_type = None
            hostname = 'unknown-host'
            logging.warning(f"No existing device for {employee_id}; using defaults, email={email}")


        # Step 3: Build device_data with client overrides + ALL required fields
        device_data = {
            "employee_id": employee_id,
            "status": data.get('status', status),  # Allow client override
            "active_status": active_status,
            "hostname": data.get('hostname', hostname),  # Client override + fallback
            "email": data.get('email', email),  # Client override + from employees
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "app_running": data.get('app_running', app_running),
            # Optionals
            "ip": data.get('ip', ip),
            "device_type": data.get('device_type', device_type),
        }
        # FIXED: Safety net for required fields
        if not device_data.get('hostname'):
            device_data['hostname'] = 'unknown-host'
        if not device_data.get('email'):
            device_data['email'] = email  # Re-ensure from employees
        if not device_data.get('status'):
            device_data['status'] = 'online'


        execute_query("""
            INSERT INTO employee_devices 
                (employee_id, status, active_status, hostname, email, last_seen, app_running, ip, device_type)
            VALUES 
                (%(employee_id)s, %(status)s, %(active_status)s, %(hostname)s, %(email)s, %(last_seen)s, %(app_running)s, %(ip)s, %(device_type)s)
            ON DUPLICATE KEY UPDATE
                status = VALUES(status),
                active_status = VALUES(active_status),
                hostname = VALUES(hostname),
                email = VALUES(email),
                last_seen = VALUES(last_seen),
                app_running = VALUES(app_running),
                ip = VALUES(ip),
                device_type = VALUES(device_type)
        """, device_data, commit=True)

        logging.info(f"Device status updated for employee: {employee_id} to active_status: {active_status}, hostname: {device_data['hostname']}, email: {device_data['email']}")
        return jsonify({"message": "Device status updated successfully"})
    except mysql.connector.Error as e:
        logging.error(f"MySQL error updating device status: {e}")
        return jsonify({"message": f"Database error: {e}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error updating device status: {str(e)}")
        return jsonify({"message": f"Unexpected error: {str(e)}"}), 500
                        
@app.route('/record_view', methods=['POST'])
def record_view():
    try:
        data = request.json
        content_id = data.get('content_id')
        employee_id = data.get('employee_id')
        viewed_duration = data.get('viewed_duration', 0)


        if not content_id or not employee_id:
            logging.error("Missing required fields in record_view: content_id or employee_id")
            return jsonify({"message": "Missing required fields"}), 400
        
        # Check if view already exists
        existing_view = execute_query("""
            SELECT id, viewed_duration 
            FROM views 
            WHERE content_id = %s AND employee_id = %s 
            LIMIT 1
        """, (content_id, employee_id), fetch=True).get("data", [])

        if existing_view:
            # Update existing view with new duration (e.g., max of current and new duration)
            current_duration = existing_view[0]['viewed_duration']
            new_duration = max(current_duration, viewed_duration)  # Keep longest duration
            execute_query("""
                UPDATE views 
                SET viewed_duration = %s, timestamp = NOW()
                WHERE id = %s
            """, (new_duration, existing_view[0]['id']), commit=True)

            logging.info(f"Updated view for content_id {content_id} by employee_id {employee_id} with duration {new_duration}")

            
        else:
            # Insert new view
            execute_query("""
                INSERT INTO views 
                    (id, content_id, employee_id, viewed_duration, timestamp)
                VALUES 
                    (%s, %s, %s, %s, NOW())
            """, (
                str(uuid.uuid4()),
                content_id,
                employee_id,
                viewed_duration
            ), commit=True)

            logging.info(f"New view recorded for content_id {content_id} by employee_id {employee_id} with duration {viewed_duration}")

        return jsonify({"message": "View recorded successfully"})
    except mysql.connector.Error as e:
        logging.error(f"MySQL error recording view: {e}")
        return jsonify({"message": f"Database error: {e}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error recording view: {str(e)}")
        return jsonify({"message": f"Unexpected error: {str(e)}"}), 500
    

@app.route('/views/<employee_id>', methods=['GET'])
def get_employee_views(employee_id):
    try:
        logging.debug(f"Fetching views for employee_id: {employee_id}")
        views_result = execute_query("""
            SELECT content_id, viewed_duration, timestamp 
            FROM views 
            WHERE employee_id = %s 
            ORDER BY timestamp DESC
        """, (employee_id,), fetch=True)

        views = views_result.get("data", []) or []

        logging.info(f"Fetched {len(views)} views for employee_id {employee_id}")
        return jsonify({"views": views})
    except mysql.connector.Error as e:
        logging.error(f"MySQL error fetching views for employee {employee_id}: {e}")
        return jsonify({"message": f"Error fetching views: {e}", "views": []}), 500
    except Exception as e:
        logging.error(f"Unexpected error fetching views for employee {employee_id}: {str(e)}")
        return jsonify({"message": f"Unexpected error: {str(e)}", "views": []}), 500


@app.route('/content_views/<content_id>', methods=['GET'])
@login_required
def get_content_views(content_id):
    try:
        logging.debug(f"Fetching views for content_id: {content_id}")
        views_result = execute_query("""
            SELECT employee_id, viewed_duration, timestamp 
            FROM views 
            WHERE content_id = %s 
            ORDER BY timestamp DESC
        """, (content_id,), fetch=True)

        views = views_result.get("data", []) or []

        # Fetch employee emails for mapping
        employee_ids = [view['employee_id'] for view in views]
        if employee_ids:
            employees = execute_query(
                "SELECT id, email FROM employees WHERE id IN ({})".format(','.join(['%s'] * len(employee_ids or [0]))),
                tuple(employee_ids or [0]),
                fetch=True
            ).get("data", []) if employee_ids else []

            employee_map = {emp['id']: emp['email'] for emp in employees}
        
        else:
            employee_map = {}
        # Add email to each view
        views_with_email = [
            {
                "employee_id": view['employee_id'],
                "email": employee_map.get(view['employee_id'], view['employee_id']),
                "viewed_duration": view['viewed_duration'],
                "timestamp": view['timestamp'],
                "status": "viewed" if view['viewed_duration'] > 30 else "pending"
            }
            for view in views
        ]
        logging.info(f"Fetched {len(views_with_email)} views for content_id {content_id}")
        return jsonify({"views": views_with_email})
    except mysql.connector.Error as e:
        logging.error(f"MySQL error fetching views for content {content_id}: {e}")
        return jsonify({"message": f"Error fetching views: {e}", "views": []}), 500
    except Exception as e:
        logging.error(f"Unexpected error fetching views for content {content_id}: {str(e)}")
        return jsonify({"message": f"Unexpected error: {str(e)}", "views": []}), 500
     
if __name__ == '__main__':
    app.run(debug=True, threaded=True, host='0.0.0.0', port=5000)

