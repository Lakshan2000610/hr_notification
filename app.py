from venv import logger
from flask import Flask, request, jsonify,send_file, render_template, session, redirect, url_for
from datetime import datetime, timedelta, timezone
import threading
import time
import uuid
import os
from collections import defaultdict
import shutil
import re
import tempfile
from supabase import create_client, Client
import urllib.parse
from postgrest.exceptions import APIError
import logging
import requests
import pkg_resources
from functools import wraps
import json
from dateutil import parser
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'super_secret_key')  # Load from .env or fallback

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Cortex XDR API configuration
CORTEX_API_URL = os.getenv("CORTEX_API_URL", "https://api-acorntravels.xdr.sg.paloaltonetworks.com/public_api/v1/endpoints/get_endpoint/")
CORTEX_API_KEY_ID = os.getenv("CORTEX_API_KEY_ID")
CORTEX_API_KEY = os.getenv("CORTEX_API_KEY")

# Local directory for uploads
UPLOAD_DIR = "/var/www/hr_notification/uploads"
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

# Initialize Supabase client with retry logic
def init_supabase_client():
    retries = 3
    for attempt in range(retries):
        try:
            if not validate_supabase_url(SUPABASE_URL):
                raise ValueError(f"Invalid Supabase URL: {SUPABASE_URL}")
            if not SUPABASE_KEY.startswith("eyJ"):
                raise ValueError("Invalid Supabase Service Role Key")
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            supabase.table('employees').select('id').limit(1).execute()
            logging.info("Supabase connection successful")
            return supabase
        except APIError as e:
            logging.error(f"Supabase connection attempt {attempt + 1} failed: {str(e)}")
            if attempt == retries - 1:
                logging.critical("Failed to initialize Supabase client")
                exit(1)
            time.sleep(2)
        except Exception as e:
            logging.error(f"Unexpected error in Supabase connection attempt {attempt + 1}: {str(e)}")
            if attempt == retries - 1:
                logging.critical("Failed to initialize Supabase client")
                exit(1)
            time.sleep(2)

supabase: Client = init_supabase_client()

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
def ensure_bucket(bucket_name):
    try:
        response = requests.get(
            f"{SUPABASE_URL}/storage/v1/bucket",
            headers={"Authorization": f"Bearer {SUPABASE_KEY}"}
        )
        response.raise_for_status()
        buckets = response.json()
        bucket_names = [bucket['name'] for bucket in buckets]
        if bucket_name not in bucket_names:
            logging.info(f"Creating bucket: {bucket_name}")
            response = requests.post(
                f"{SUPABASE_URL}/storage/v1/bucket",
                headers={
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json"
                },
                json={"id": bucket_name, "name": bucket_name, "public": True}
            )
            response.raise_for_status()
            logging.info(f"Bucket {bucket_name} created successfully")
        else:
            logging.info(f"Bucket {bucket_name} already exists")

        logging.warning(f"RLS policy for {bucket_name} bucket must be set manually in Supabase Dashboard or SQL Editor.")
    except Exception as e:
        logging.error(f"Error ensuring bucket {bucket_name}: {str(e)}")
        raise Exception(f"Failed to ensure bucket {bucket_name}: {str(e)}")

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
        supabase.table('notifications').insert({
            "content_id": content_id,
            "employees": employees,
            "time": datetime.now(timezone.utc).isoformat()
        }).execute()
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
    return redirect(url_for('login'))


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
            time_threshold = current_time - timedelta(days=1)  # Default to day

        notifications_response = supabase.table('notifications') \
            .select('time') \
            .gt('time', time_threshold.isoformat()) \
            .execute()
        notifications = notifications_response.data or []

        # Group by day or month
        counts = {}
        for notif in notifications:
            notif_time = datetime.fromisoformat(notif['time'].replace('Z', '+00:00'))
            if filter_type == 'day':
                label = notif_time.strftime('%H:00')
            else:  # month
                label = notif_time.strftime('%Y-%m-%d')
            counts[label] = counts.get(label, 0) + 1

        labels = list(counts.keys())
        data = list(counts.values())

        logging.info(f"Sent messages data for {filter_type}: labels={labels}, counts={data}")
        return jsonify({'labels': labels, 'counts': data})
    except APIError as e:
        logging.error(f"Supabase API error fetching sent messages: {str(e)}")
        return jsonify({'labels': [], 'counts': []}), 500
    except Exception as e:
        logging.error(f"Unexpected error fetching sent messages: {str(e)}")
        return jsonify({'labels': [], 'counts': []}), 500
    
@app.route('/')
@login_required
def home():
    try:
        supabase_version = pkg_resources.get_distribution("supabase").version
        logging.debug(f"Supabase Python client version: {supabase_version}")

        employees_response = supabase.table('employees').select('id').execute()
        employee_count = len(employees_response.data or [])
        logging.debug(f"Employees query result: count={employee_count}, data={employees_response.data}")

        # Fetch devices with active_status True
        devices_response = supabase.table('employee_devices') \
            .select('employee_id, hostname, email, status, app_running') \
            .eq('active_status', True) \
            .execute()
        devices = devices_response.data or []

        headers = {
            "x-xdr-auth-id": CORTEX_API_KEY_ID,
            "Authorization": CORTEX_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "request_data": {
                "filters": [],
                "search_from": 0,
                "search_to": 100,
                "sort": {"field": "last_seen", "keyword": "desc"}
            }
        }
        cortex_response = requests.post(CORTEX_API_URL, headers=headers, json=payload)
        cortex_response.raise_for_status()
        cortex_data = cortex_response.json()
        cortex_endpoints = cortex_data.get('reply', {}).get('endpoints', [])

        cortex_map = {endpoint.get('endpoint_name', '').lower(): endpoint.get('endpoint_status') for endpoint in cortex_endpoints}
        department_counts = {}
        for device in devices:
            hostname = device.get('hostname', '').lower()
            email = device.get('email', '').lower()
            if not email or '@' not in email or '@acorn.lk' not in email:
                continue
            # Extract department from email (e.g., laks.ht@acorn.lk → ht)
            parts = email.split('@')[0].split('.')
            department = parts[1] if len(parts) > 1 else 'unknown'
            is_connected = cortex_map.get(hostname, 'DISCONNECTED') == 'ONLINE' and device['status'] == 'online' and device['app_running']
            if is_connected:
                department_counts[department] = department_counts.get(department, 0) + 1

        total_connected = sum(department_counts.values())
        department_data = []
        for dept, count in department_counts.items():
            percent = round((count / total_connected) * 100) if total_connected > 0 else 0
            department_data.append((dept, count, percent))

        department_data.sort(key=lambda x: x[1], reverse=True)  # Sort by count descending

        active_devices = total_connected

        contents_response = supabase.table('scheduled_content').select('*').execute()
        contents = contents_response.data or []
        logging.debug(f"Scheduled content query result: data={contents}")
        content_stats = []
        for content in contents:
            content_id = content['id']
            reactions_response = supabase.table('reactions').select('reaction').eq('content_id', content_id).execute()
            reaction_data = reactions_response.data or []
            reaction_counts = {k: sum(1 for r in reaction_data if r['reaction'] == k) for k in ['like', 'unlike', 'heart', 'cry']}
            feedback_response = supabase.table('feedback').select('id').eq('content_id', content_id).execute()
            feedback_count = len(feedback_response.data or [])
            views_response = supabase.table('views').select('employee_id').eq('content_id', content_id).execute()
            view_count = len(set(view['employee_id'] for view in views_response.data or []))
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

        logging.info(f"Home data: Employees={employee_count}, Active Devices={active_devices}, Department Data={department_data}, Content Stats={content_stats}, Page={page}, Total Pages={total_pages}")
        return render_template('home.html', 
                              employee_count=employee_count,
                              active_devices=active_devices,
                              department_data=department_data,
                              content_stats=content_stats,
                              paginated_stats=paginated_stats,
                              current_page=page,
                              total_pages=total_pages)
    except APIError as e:
        logging.error(f"Supabase API error fetching home data: {str(e)}")
        return render_template('home.html', 
                              employee_count=0,
                              active_devices=0,
                              department_data=[],
                              content_stats=[],
                              paginated_stats=[],
                              current_page=1,
                              total_pages=1,
                              error=f"Database error: {str(e)}")
    except Exception as e:
        logging.error(f"Unexpected error fetching home data: {str(e)}")
        return render_template('home.html', 
                              employee_count=0,
                              active_devices=0,
                              department_data=[],
                              content_stats=[],
                              paginated_stats=[],
                              current_page=1,
                              total_pages=1,
                              error=f"Unexpected error: {str(e)}")
                
@app.route('/get_paginated_stats')
@login_required
def get_paginated_stats():
    try:
        # Fetch all content stats (same logic as in home route)
        contents_response = supabase.table('scheduled_content').select('*').execute()
        contents = contents_response.data or []
        content_stats = []
        for content in contents:
            content_id = content['id']
            reactions_response = supabase.table('reactions').select('reaction').eq('content_id', content_id).execute()
            reaction_data = reactions_response.data or []
            reaction_counts = {k: sum(1 for r in reaction_data if r['reaction'] == k) for k in ['like', 'unlike', 'heart', 'cry']}
            feedback_response = supabase.table('feedback').select('id').eq('content_id', content_id).execute()
            feedback_count = len(feedback_response.data or [])
            views_response = supabase.table('views').select('employee_id').eq('content_id', content_id).execute()
            view_count = len(set(view['employee_id'] for view in views_response.data or []))
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
        employees = supabase.table('employees').select('id, email').execute().data
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
            logging.error("Invalid or missing JSON data in update_status request")
            # Insert failure to device_update_status if possible
            try:
                supabase.table('device_update_status').insert({
                    'id': str(uuid.uuid4()),
                    'employee_id': data.get('employee_id', 'unknown') if data else 'unknown',
                    'device_id': data.get('device_id', 'unknown') if data else 'unknown',
                    'version': 'unknown',
                    'status': 'failed',
                    'error_message': 'Invalid or missing JSON data'
                }).execute()
            except Exception as insert_e:
                logging.error(f"Failed to log invalid data to device_update_status: {str(insert_e)}")
            return jsonify({'error': 'Invalid or missing JSON data'}), 400

        employee_id = data.get('employee_id')
        if not employee_id:
            logging.error("Missing employee_id in update_status request")
            # Similar insert attempt for failure
            try:
                supabase.table('device_update_status').insert({
                    'id': str(uuid.uuid4()),
                    'employee_id': 'unknown',
                    'device_id': data.get('device_id', 'unknown'),
                    'version': 'unknown',
                    'status': 'failed',
                    'error_message': 'Missing employee_id'
                }).execute()
            except Exception as insert_e:
                logging.error(f"Failed to log missing employee_id to device_update_status: {str(insert_e)}")
            return jsonify({'error': 'Missing employee_id'}), 400

        status = data.get('status', 'offline')
        app_running = data.get('app_running', False)
        ip = data.get('ip')
        device_type = data.get('device_type')
        hostname = data.get('hostname', 'unknown-host')
        email = data.get('email')
        current_version = data.get('current_version', 'unknown')
        device_id = data.get('device_id', employee_id)  # Fallback to employee_id if missing
        update_status_val = data.get('update_status', 'pending')  # Renamed to avoid keyword conflict
        error_message = data.get('error_message')

        # Validate inputs
        if status not in ['online', 'offline']:
            logging.error(f"Invalid status: {status}")
            return jsonify({'error': 'Invalid status'}), 400
        if not isinstance(app_running, bool):
            logging.error(f"Invalid app_running: {app_running}")
            return jsonify({'error': 'Invalid app_running value'}), 400
        if email and '@' not in email:
            logging.error(f"Invalid email format: {email}")
            return jsonify({'error': 'Invalid email format'}), 400
        if update_status_val not in ['success', 'pending', 'failed']:  # FIXED: Use update_status_val here
            logging.error(f"Invalid update_status: {update_status_val}")
            return jsonify({'error': 'Invalid update_status'}), 400

        # Validate employee exists
        employee = supabase.table('employees').select('id').eq('id', employee_id).execute().data
        if not employee:
            logging.error(f"Employee ID {employee_id} not found")
            return jsonify({'error': f"Employee ID {employee_id} not found"}), 400

        # Get current version from server
        try:
            server_version = get_current_version() or 'unknown'
            if server_version is None:
                logging.warning("Failed to read server version, treating as unknown")
                server_version = 'unknown'
        except Exception as e:
            logging.error(f"Error reading server version: {str(e)}", exc_info=True)
            server_version = 'unknown'

        update_data = {
            'employee_id': employee_id,
            'status': status,
            'app_running': app_running,
            'ip': ip,
            'device_type': device_type,
            'hostname': hostname,
            'email': email,
            'last_seen': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        update_data = {k: v for k, v in update_data.items() if v is not None}
        
        update_status_data = {
            'id': str(uuid.uuid4()),
            'employee_id': employee_id,
            'device_id': device_id,
            'version': current_version,
            'status': 'success' if current_version == server_version else update_status_val,
            'last_attempted_at': datetime.now(timezone.utc).isoformat(),
            'error_message': error_message if update_status_val == 'failed' else None
        }
        update_status_data = {k: v for k, v in update_status_data.items() if v is not None}

        # Perform upserts, but catch individual failures
        try:
            logging.debug(f"Upserting to employee_devices: {update_data}")
            supabase.table('employee_devices').upsert(update_data, on_conflict=['employee_id']).execute()
        except APIError as e:
            logging.error(f"Failed to upsert employee_devices: {str(e)}")
            # Continue anyway, since this is non-critical

        if current_version != 'unknown':
            try:
                logging.debug(f"Upserting to device_update_status: {update_status_data}")
                supabase.table('device_update_status').upsert(update_status_data, on_conflict=['employee_id', 'device_id']).execute()
            except APIError as e:
                logging.error(f"Failed to upsert device_update_status: {str(e)}")
                # Continue anyway

        logging.info(f"Updated device status for employee {employee_id}, version {current_version}, device_id {device_id}")
        return jsonify({'message': 'Status updated successfully', 'version_status': current_version}), 200

    except APIError as e:
        logging.error(f"Supabase API error updating device status: {str(e)}", exc_info=True)
        return jsonify({'error': f"Database error: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error updating device status: {str(e)}", exc_info=True)
        return jsonify({'error': f"Unexpected error: {str(e)}"}), 500
        
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
        supabase.table('device_update_status').delete().neq('status', 'success').execute()
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

@app.route('/update_status/summary', methods=['GET'])
@login_required
def update_status_summary():
    try:
        response = supabase.table('device_update_status').select('status').execute()
        status_counts = defaultdict(int)
        for record in response.data:
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
        response = supabase.table('device_update_status').select('employee_id, device_id, version, status, last_attempted_at, error_message').execute()
        return jsonify(response.data), 200
    except Exception as e:
        logger.error(f"Error fetching all update statuses: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/update_status/success', methods=['GET'])
@login_required
def update_status_success():
    try:
        response = supabase.table('device_update_status').select('employee_id, device_id, version, last_attempted_at').eq('status', 'success').execute()
        return jsonify(response.data), 200
    except Exception as e:
        logger.error(f"Error fetching successful updates: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/update_status/pending', methods=['GET'])
@login_required
def update_status_pending():
    try:
        response = supabase.table('device_update_status').select('employee_id, device_id, version, last_attempted_at').eq('status', 'pending').execute()
        return jsonify(response.data), 200
    except Exception as e:
        logger.error(f"Error fetching pending updates: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/update_status/failed', methods=['GET'])
@login_required
def update_status_failed():
    try:
        response = supabase.table('device_update_status').select('employee_id, device_id, version, last_attempted_at, error_message').eq('status', 'failed').execute()
        return jsonify(response.data), 200
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
        content_response = supabase.table('scheduled_content').select('title, text, image_url, url').eq('id', content_id).execute()
        content = content_response.data[0] if content_response.data else {'title': 'No title', 'text': 'No content found', 'image_url': None, 'url': None}
        logging.debug(f"Content for content_id {content_id}: {content}")

        reactions_response = supabase.table('reactions').select('*').eq('content_id', content_id).execute()
        reactions = reactions_response.data or []
        logging.debug(f"Reactions for content {content_id}: {reactions}")
        
        feedback_response = supabase.table('feedback').select('*').eq('content_id', content_id).execute()
        feedback = feedback_response.data or []
        logging.debug(f"Feedback for content {content_id}: {feedback}")
        
        employee_ids = set(r['employee_id'] for r in reactions) | set(f['employee_id'] for f in feedback)
        employees_response = supabase.table('employees').select('id, email').in_('id', list(employee_ids)).execute()
        employees = employees_response.data or []
        logging.debug(f"Employees fetched for mapping: {employees}")
        employee_map = {emp['id']: emp['email'] for emp in employees}

        reaction_details = [
            {'employee_email': employee_map.get(r['employee_id'], r['employee_id']), 'reaction': r['reaction'], 'timestamp': r['timestamp']}
            for r in reactions
        ]
        feedback_details = [
            {'employee_email': employee_map.get(f['employee_id'], f['employee_id']), 'feedback': f['feedback'], 'timestamp': f['timestamp']}
            for f in feedback
        ]

        logging.info(f"Reaction details for content {content_id}: {reaction_details}, Feedback details: {feedback_details}")
        return render_template('view_react.html', 
                              content_id=content_id,
                              reaction_details=reaction_details,
                              feedback_details=feedback_details,
                              content_title=content['title'],
                              content_text=content['text'],
                              image_url=content['image_url'],
                              video_url=content['url'])
    except APIError as e:
        logging.error(f"Supabase API error fetching reaction details for content_id {content_id}: {str(e)}")
        return render_template('view_react.html', 
                              content_id=content_id,
                              reaction_details=[],
                              feedback_details=[],
                              content_title='No title',
                              content_text='No content found',
                              image_url=None,
                              video_url=None,
                              error=f"Database error: {str(e)}")
    except Exception as e:
        logging.error(f"Unexpected error fetching reaction details for content_id {content_id}: {str(e)}")
        return render_template('view_react.html', 
                              content_id=content_id,
                              reaction_details=[],
                              feedback_details=[],
                              content_title='No title',
                              content_text='No content found',
                              image_url=None,
                              video_url=None,
                              error=f"Unexpected error: {str(e)}")

@app.route('/send_message')
@login_required
def send_message_page():
    try:
        # Fetch employees with active devices
        active_devices_response = supabase.table('employee_devices') \
            .select('employee_id') \
            .eq('active_status', True) \
            .execute()
        active_employee_ids = [device['employee_id'] for device in active_devices_response.data] if active_devices_response.data else []

        if not active_employee_ids:
            logging.warning("No active employees found in the database")
            return render_template('send_message.html', employees_json='[]', active_employees=[], departments=[], error="No active employees found. Please activate employees via device registration.")

        # Fetch employee details for active employee IDs
        employees_response = supabase.table('employees') \
            .select('id, email') \
            .in_('id', active_employee_ids) \
            .execute()
        employees = employees_response.data if employees_response.data else []
        logging.debug(f"Raw Supabase response: {employees_response}")

        if not employees:
            logging.warning("No employees found matching active device IDs")
            return render_template('send_message.html', employees_json='[]', active_employees=[], departments=[], error="No employees found with active devices.")

        employees_data = []
        departments = set()
        for emp in employees:
            if not emp.get('email') or '.' not in emp['email'] or ('@acron.lk' not in emp['email'] and '@acorn.lk' not in emp['email']):
                logging.warning(f"Skipping invalid employee email: {emp.get('email', 'None')}")
                continue
            try:
                department = emp['email'].split('.')[1].split('@')[0]
                employees_data.append({
                    'id': emp['id'],
                    'email': emp['email'],
                    'department': department
                })
                departments.add(department)
            except IndexError as e:
                logging.error(f"Error parsing email {emp.get('email', 'None')}: {str(e)}")
                continue

        employees_json = json.dumps(employees_data)
        departments = sorted(list(departments))
        logging.info(f"Fetched active employees: {len(employees_data)}, departments: {departments}")
        return render_template('send_message.html', employees_json=employees_json, active_employees=employees, departments=departments)
    except APIError as e:
        logging.error(f"Supabase API error fetching employees: {str(e)}")
        return render_template('send_message.html', employees_json='[]', active_employees=[], departments=[], error=f"Database error: {str(e)}. Please check Supabase configuration.")
    except Exception as e:
        logging.error(f"Unexpected error fetching employees: {str(e)}")
        return render_template('send_message.html', employees_json='[]', active_employees=[], departments=[], error=f"Unexpected error: {str(e)}. Please check server logs.")

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
        devices_response = supabase.table('employee_devices') \
            .select('employee_id, status, active_status, ip, device_type, hostname, email, last_seen, app_running') \
            .execute()
        devices = devices_response.data or []
        logging.debug(f"Fetched {len(devices)} devices from Supabase: {devices}")

        # Fetch all employees to map emails
        employees_response = supabase.table('employees').select('id, email').execute()
        employee_map = {emp['id']: emp['email'] for emp in employees_response.data or []}
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
        active_devices = [d for d in processed_devices if d['active_status']]
        inactive_devices = [d for d in processed_devices if not d['active_status']]
        logging.info(f"Processed {len(active_devices)} active and {len(inactive_devices)} inactive devices")
        logging.debug(f"Active devices: {active_devices}")
        logging.debug(f"Inactive devices: {inactive_devices}")

        return render_template(
            'monitor_devices.html',
            active_devices=active_devices,
            inactive_devices=inactive_devices,
            error=error_message if 'error_message' in locals() else None
        )

    except APIError as e:
        logging.error(f"Supabase API error fetching devices: {str(e)}")
        return render_template('monitor_devices.html', active_devices=[], inactive_devices=[], error=f"Database error: {str(e)}")
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
                # Parse with +0530 timezone (Sri Lanka time)
                scheduled_time = datetime.strptime(scheduled_time_str, '%Y-%m-%dT%H:%M').replace(
                    tzinfo=timezone(timedelta(hours=5, minutes=30))
                )
                # Convert to UTC for storage
                scheduled_time = scheduled_time.astimezone(timezone.utc)
                logging.debug(f"Parsed scheduled_time: {scheduled_time}")
            except ValueError as e:
                logging.error(f"Invalid scheduled_time format: {scheduled_time_str}, error: {str(e)}")
                return jsonify({"message": f"Invalid scheduled_time format: {str(e)}"}), 400
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
                        video_url = f"https://hrnotification.acorngroup.lk/uploads/message/videos/{video_filename}"
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
                        image_url = f"https://hrnotification.acorngroup.lk/uploads/message/images/{image_filename}"
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
            "scheduled_time": scheduled_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            "employees": valid_employees,
        }
        logging.debug(f"Inserting content into scheduled_content: {content}")
        result = supabase.table('scheduled_content').insert(content).execute()
        logging.info(f"Supabase insert result: {result}")

        if not send_now and scheduled_time > datetime.now(timezone.utc):
            schedule_notification(content_id, scheduled_time, valid_employees)
        else:
            send_notification(content_id, valid_employees)
        
        logging.info(f"Message scheduled successfully: {content_id}, employees: {valid_employees}")
        return jsonify({"message": "Message scheduled successfully", "content_id": content_id})
    except APIError as e:
        logging.error(f"Supabase API error sending message: {str(e)} - Content: {content if 'content' in locals() else 'N/A'}, Result: {result if 'result' in locals() else 'N/A'}")
        return jsonify({"message": f"Database error: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error sending message: {str(e)} - Content: {content if 'content' in locals() else 'N/A'}, Result: {result if 'result' in locals() else 'N/A'}")
        return jsonify({"message": f"Error sending message: {str(e)}"}), 500
    
@app.route('/update_bulk_device_status', methods=['POST'])
@login_required
def update_bulk_device_status():
    try:
        data = request.json
        logging.debug(f"Received update_bulk_device_status data: {data}")
        if not data or not isinstance(data, list):
            logging.error("Invalid or missing data for bulk update")
            return jsonify({"message": "Invalid or missing data"}), 400

        for update in data:
            employee_id = update.get('employee_id')
            active_status = update.get('active_status')
            if not employee_id or active_status is None:
                logging.error(f"Missing required fields for employee_id: {employee_id}")
                continue

            # Fetch existing device data to retain current fields (with safe check)
            existing_device = supabase.table('employee_devices').select('status, app_running, hostname, email, ip, device_type').eq('employee_id', employee_id).execute().data
            if existing_device:  # FIXED: Explicit check for empty list
                existing = existing_device[0]
                status = existing.get('status', 'online')
                app_running = existing.get('app_running', False)
                hostname = existing.get('hostname', 'unknown-host')  # FIXED: Safe default as string
                email = existing.get('email')
                ip = existing.get('ip')
                device_type = existing.get('device_type')
                logging.debug(f"Found existing device for {employee_id}: hostname={hostname}")
            else:
                # FIXED: Explicit fallbacks for new records to avoid NULLs
                status = 'online'
                app_running = False
                hostname = 'unknown-host'  # Ensure NOT NULL
                email = None  # Allow NULL if schema permits; adjust if required
                ip = None
                device_type = None
                logging.warning(f"No existing device for {employee_id}; using defaults")

            device_data = {
                "employee_id": employee_id,
                "active_status": active_status,
                "status": status,
                "app_running": app_running,
                "hostname": hostname,  # FIXED: Now guaranteed string
                "email": email,
                "ip": ip,
                "device_type": device_type,
                "last_seen": datetime.now(timezone.utc).isoformat(),
            }
            # Remove None values if schema doesn't allow NULLs for other fields (customize as needed)
            device_data = {k: v for k, v in device_data.items() if v is not None}
            if 'hostname' not in device_data:  # Safety net
                device_data['hostname'] = 'unknown-host'

            supabase.table('employee_devices').upsert(device_data).execute()
            logging.info(f"Device status updated for employee: {employee_id} to active_status: {active_status}, hostname: {hostname}")

        return jsonify({"message": "Bulk device status updated successfully"})
    except APIError as e:
        logging.error(f"Supabase API error updating bulk device status: {str(e)}")
        return jsonify({"message": f"Database error: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error updating bulk device status: {str(e)}")
        return jsonify({"message": f"Unexpected error: {str(e)}"}), 500
        
@app.route('/content/<employee_id>', methods=['GET'])
def get_content(employee_id):
    try:
        logging.debug(f"Fetching content for employee_id: {employee_id}")
        device = supabase.table('employee_devices').select('last_seen').eq('employee_id', employee_id).execute().data
        last_seen = device[0]['last_seen'] if device else (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        
        employee_content = supabase.table('scheduled_content')\
            .select('id, type, title, text, image_url, url, scheduled_time, employees')\
            .contains('employees', [employee_id])\
            .lte('scheduled_time', datetime.now(timezone.utc).isoformat())\
            .execute().data or []
        
        employee_notifications = supabase.table('notifications')\
            .select('*')\
            .contains('employees', [employee_id])\
            .gte('time', (datetime.now(timezone.utc) - timedelta(days=7)).isoformat())\
            .execute().data or []
        
        for notif in employee_notifications:
            content = next((c for c in employee_content if c['id'] == notif['content_id']), None)
            notif['text'] = f"New content: {content.get('title', 'No title')} - {content.get('text', 'No text')}" if content else f"Notification at {notif['time']}"
        
        logging.info(f"Fetched content: {employee_content}, notifications: {employee_notifications}")
        return jsonify({
            "content": employee_content,
            "notifications": employee_notifications
        })
    except APIError as e:
        logging.error(f"Error fetching content for employee {employee_id}: {str(e)}")
        return jsonify({
            "message": f"Error fetching content: {str(e)}",
            "content": [],
            "notifications": []
        }), 500
    except Exception as e:
        logging.error(f"Unexpected error fetching content for employee {employee_id}: {str(e)}")
        return jsonify({
            "message": f"Unexpected error fetching content: {str(e)}",
            "content": [],
            "notifications": []
        }), 500

@app.route('/devices')
@login_required
def devices():
    try:
        devices = supabase.table('employee_devices').select('*').execute().data
        logging.info(f"Fetched devices: {devices}")
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
        response = supabase.table('employees').select('id').eq('email', email).execute()
        if response.data:
            employee_id = response.data[0]['id']
        else:
            employee_id = str(uuid.uuid4())
            supabase.table('employees').insert({'id': employee_id, 'email': email}).execute()
        logging.info(f"Employee ID for {email}: {employee_id}")
        return jsonify({"employee_id": employee_id})
    except APIError as e:
        logging.error(f"Error getting/creating employee: {str(e)}")
        return jsonify({"message": f"Error getting/creating employee: {str(e)}"}), 500
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
        employee = supabase.table('employees').select('id').eq('id', employee_id).execute().data
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
        
        exists = supabase.table('employee_devices').select('active_status').eq('employee_id', employee_id).execute().data
        if not exists:
            device_data_base["active_status"] = False
        
        supabase.table('employee_devices').upsert({"employee_id": employee_id, **device_data_base}).execute()
        logging.info(f"Device registered/updated: {employee_id}, hostname: {hostname}, email: {email}")
        return jsonify({"message": "Device registered"})
    except APIError as e:
        logging.error(f"Error registering device: {str(e)}")
        return jsonify({"message": f"Error registering device: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error registering device: {str(e)}")
        return jsonify({"message": f"Unexpected error registering device: {str(e)}"}), 500

        
@app.route('/set_message_delay', methods=['POST'])
def set_message_delay():
    try:
        logging.debug(f"Received set_message_delay data: {request.json}")
        data = request.json
        employee_id = data['employee_id']
        content_id = data['content_id']
        delay_choice = data['delay_choice']
        
        if not employee_id or not content_id or not delay_choice:
            logging.error("Missing required fields in set_message_delay")
            return jsonify({"message": "Missing required fields: employee_id, content_id, or delay_choice"}), 400
        
        # Determine delay based on choice
        if delay_choice == "Play Immediate":
            delay = timedelta(seconds=0)  # No delay, use current time or scheduled_time
        elif delay_choice == "Play within 15 minutes":
            delay = timedelta(minutes=15)
        elif delay_choice == "Play within 30 minutes":
            delay = timedelta(minutes=30)
        elif delay_choice == "Play within 1 hour":
            delay = timedelta(hours=1)
        elif delay_choice == "Play within 3 hours":
            delay = timedelta(hours=3)
        else:
            logging.error(f"Invalid delay_choice: {delay_choice}")
            return jsonify({"message": f"Invalid delay_choice: {delay_choice}"}), 400
        
        # Fetch the original scheduled_time
        response = supabase.table('scheduled_content').select('scheduled_time').eq('id', content_id).execute()
        if not response.data:
            logging.error(f"Content ID {content_id} not found")
            return jsonify({"message": f"Content ID {content_id} not found"}), 400
        
        # Parse scheduled_time using dateutil.parser
        try:
            scheduled_time_str = response.data[0]['scheduled_time']
            scheduled_time = parser.isoparse(scheduled_time_str)  # More flexible parsing
            logging.debug(f"Parsed scheduled_time: {scheduled_time}")
        except ValueError as e:
            logging.error(f"Failed to parse scheduled_time {scheduled_time_str}: {str(e)}")
            return jsonify({"message": f"Invalid scheduled_time format: {str(e)}"}), 400

        # For delayed options, use current local time as base and add delay
        current_local_time = datetime.now(timezone(offset=timedelta(hours=5, minutes=30)))  # +0530
        if delay_choice in ["Play within 15 minutes", "Play within 30 minutes", "Play within 1 hour", "Play within 3 hours"]:
            display_time = current_local_time + delay
        else:  # "Play Immediate"
            display_time = max(scheduled_time, datetime.now(timezone.utc))

        # Convert display_time to UTC for storage
        display_time_utc = display_time.astimezone(timezone.utc)
        
        # Upsert the preference
        preference_data = {
            "employee_id": employee_id,
            "content_id": content_id,
            "delay_choice": delay_choice,
            "display_time": display_time_utc.isoformat()
        }
        supabase.table('message_preferences').upsert(preference_data).execute()
        
        logging.info(f"Message delay set for content_id: {content_id}, employee_id: {employee_id}, display_time: {display_time_utc}")
        return jsonify({"message": "Delay set successfully"})
    except APIError as e:
        logging.error(f"Supabase API error setting message delay: {str(e)}")
        return jsonify({"message": f"Database error: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error setting message delay: {str(e)}")
        return jsonify({"message": f"Unexpected error: {str(e)}"}), 500
                    
@app.route('/message_preferences/<employee_id>/<content_id>', methods=['GET'])
def get_message_preference(employee_id, content_id):
    logging.debug(f"Fetching message preference for employee_id: {employee_id}, content_id: {content_id}")
    try:
        preference = supabase.table('message_preferences')\
            .select('delay_choice, display_time')\
            .eq('employee_id', employee_id)\
            .eq('content_id', content_id)\
            .execute().data
        logging.info(f"Fetched preference for employee {employee_id}, content {content_id}: {preference}")
        return jsonify({"preference": preference[0] if preference else {}})
    except APIError as e:
        logging.error(f"Supabase API error fetching preference for employee {employee_id}, content {content_id}: {str(e)}")
        return jsonify({"message": f"Error fetching preference: {str(e)}", "preference": {}}), 500
    except Exception as e:
        logging.error(f"Unexpected error fetching preference for employee {employee_id}, content {content_id}: {str(e)}")
        return jsonify({"message": f"Unexpected error fetching preference: {str(e)}", "preference": {}}), 500
        
@app.route('/feedback', methods=['POST'])
def receive_feedback():
    try:
        data = request.json
        logging.debug(f"Received feedback data: {data}")
        feedback_data = {
            "content_id": data['content_id'],
            "employee_id": data['employee_id'],
            "feedback": data['feedback'],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        supabase.table('feedback').insert(feedback_data).execute()
        logging.info(f"Feedback received for content: {data['content_id']}")
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
        existing_reaction = supabase.table('reactions')\
            .select('id', 'reaction', 'timestamp')\
            .eq('content_id', content_id)\
            .eq('employee_id', employee_id)\
            .execute().data

        if existing_reaction:
            # Update the existing reaction
            reaction_id = existing_reaction[0]['id']
            supabase.table('reactions').update({
                "reaction": reaction,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }).eq('id', reaction_id).execute()
            logging.info(f"Reaction updated: {reaction} for content_id {content_id}, employee_id {employee_id}")
        else:
            # Insert a new reaction if none exists
            try:
                supabase.table('reactions').insert({
                    "id": str(uuid.uuid4()),
                    "content_id": content_id,
                    "employee_id": employee_id,
                    "reaction": reaction,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }).execute()
            except APIError as e:
                if "relation \"reactions\" does not exist" in str(e):
                    supabase.table('reactions').create({
                        "id": "uuid",
                        "content_id": "text",
                        "employee_id": "text",
                        "reaction": "text",
                        "timestamp": "timestamptz"
                    }).execute()
                    supabase.table('reactions').insert({
                        "id": str(uuid.uuid4()),
                        "content_id": content_id,
                        "employee_id": employee_id,
                        "reaction": reaction,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }).execute()
                else:
                    raise
            logging.info(f"Reaction recorded: {reaction} for content_id {content_id}, employee_id {employee_id}")

        return jsonify({"message": "Reaction recorded successfully"})
    except APIError as e:
        logging.error(f"Supabase API error recording reaction: {str(e)}")
        return jsonify({"message": f"Database error: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error recording reaction: {str(e)}")
        return jsonify({"message": f"Unexpected error: {str(e)}"}), 500
    
@app.route('/update_device_status', methods=['POST'])
def update_device_status():
    try:
        data = request.json
        logging.debug(f"Received update_device_status data: {data}")
        employee_id = data.get('employee_id')
        active_status = data.get('active_status')
        
        if not employee_id or active_status is None:
            logging.error("Missing required fields in update_device_status: employee_id or active_status")
            return jsonify({"message": "Missing required fields"}), 400
        
        # Fetch existing device data to retain current fields (with safe check)
        existing_device = supabase.table('employee_devices').select('status, app_running, hostname, email, ip, device_type').eq('employee_id', employee_id).execute().data
        if existing_device:  # FIXED: Explicit check for empty list
            existing = existing_device[0]
            status = existing.get('status', 'online')
            app_running = existing.get('app_running', False)
            hostname = existing.get('hostname', 'unknown-host')  # FIXED: Safe default as string
            email = existing.get('email')
            ip = existing.get('ip')
            device_type = existing.get('device_type')
            logging.debug(f"Found existing device for {employee_id}: hostname={hostname}")
        else:
            # FIXED: Explicit fallbacks for new records to avoid NULLs
            status = 'online'
            app_running = False
            hostname = 'unknown-host'  # Ensure NOT NULL
            email = None  # Allow NULL if schema permits
            ip = None
            device_type = None
            logging.warning(f"No existing device for {employee_id}; using defaults")

        # Use client-provided values if available (e.g., from future extensions)
        device_data = {
            "employee_id": employee_id,
            "active_status": active_status,
            "status": status,
            "app_running": app_running,
            "hostname": data.get('hostname', hostname),  # FIXED: Client override with safe default
            "email": data.get('email', email),
            "ip": data.get('ip', ip),
            "device_type": data.get('device_type', device_type),
            "last_seen": datetime.now(timezone.utc).isoformat(),
        }
        # Safety net for hostname
        if not device_data.get('hostname'):
            device_data['hostname'] = 'unknown-host'
        # Remove None values if needed (customize per schema)
        device_data = {k: v for k, v in device_data.items() if v is not None}

        supabase.table('employee_devices').upsert(device_data).execute()
        logging.info(f"Device status updated for employee: {employee_id} to active_status: {active_status}, hostname: {device_data['hostname']}")
        return jsonify({"message": "Device status updated successfully"})
    except APIError as e:
        logging.error(f"Supabase API error updating device status: {str(e)}")
        return jsonify({"message": f"Database error: {str(e)}"}), 500
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
        existing_view = supabase.table('views').select('id, viewed_duration').eq('content_id', content_id).eq('employee_id', employee_id).execute().data
        if existing_view:
            # Update existing view with new duration (e.g., max of current and new duration)
            current_duration = existing_view[0]['viewed_duration']
            new_duration = max(current_duration, viewed_duration)  # Keep longest duration
            supabase.table('views').update({
                "viewed_duration": new_duration,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }).eq('id', existing_view[0]['id']).execute()
            logging.info(f"Updated view for content_id {content_id} by employee_id {employee_id} with duration {new_duration}")
        else:
            # Insert new view
            supabase.table('views').insert({
                "id": str(uuid.uuid4()),
                "content_id": content_id,
                "employee_id": employee_id,
                "viewed_duration": viewed_duration,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }).execute()
            logging.info(f"New view recorded for content_id {content_id} by employee_id {employee_id} with duration {viewed_duration}")
        
        return jsonify({"message": "View recorded successfully"})
    except APIError as e:
        logging.error(f"Supabase API error recording view: {str(e)}")
        return jsonify({"message": f"Database error: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error recording view: {str(e)}")
        return jsonify({"message": f"Unexpected error: {str(e)}"}), 500
    
@app.route('/views/<employee_id>', methods=['GET'])
def get_employee_views(employee_id):
    try:
        logging.debug(f"Fetching views for employee_id: {employee_id}")
        views = supabase.table('views').select('content_id, viewed_duration, timestamp').eq('employee_id', employee_id).execute().data or []
        logging.info(f"Fetched {len(views)} views for employee_id {employee_id}")
        return jsonify({"views": views})
    except APIError as e:
        logging.error(f"Supabase API error fetching views for employee {employee_id}: {str(e)}")
        return jsonify({"message": f"Error fetching views: {str(e)}", "views": []}), 500
    except Exception as e:
        logging.error(f"Unexpected error fetching views for employee {employee_id}: {str(e)}")
        return jsonify({"message": f"Unexpected error: {str(e)}", "views": []}), 500

@app.route('/content_views/<content_id>', methods=['GET'])
@login_required
def get_content_views(content_id):
    try:
        logging.debug(f"Fetching views for content_id: {content_id}")
        views = supabase.table('views').select('employee_id, viewed_duration, timestamp').eq('content_id', content_id).execute().data or []
        # Fetch employee emails for mapping
        employee_ids = [view['employee_id'] for view in views]
        if employee_ids:
            employees = supabase.table('employees').select('id, email').in_('id', employee_ids).execute().data or []
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
    except APIError as e:
        logging.error(f"Supabase API error fetching views for content {content_id}: {str(e)}")
        return jsonify({"message": f"Error fetching views: {str(e)}", "views": []}), 500
    except Exception as e:
        logging.error(f"Unexpected error fetching views for content {content_id}: {str(e)}")
        return jsonify({"message": f"Unexpected error: {str(e)}", "views": []}), 500
     
if __name__ == '__main__':
    app.run(debug=True, threaded=True, host='0.0.0.0', port=5000)