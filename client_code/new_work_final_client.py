import getpass
import subprocess
import sys
import tempfile
import uuid
import requests
import time
import logging
import threading
import winreg
import os
import json
from datetime import datetime, timezone, timedelta
from random import randint  # Remove 'random' from imports
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                              QScrollArea, QFrame, QComboBox, QDialog, QMessageBox, QSystemTrayIcon, QMenu, QProgressBar,
                              QStackedWidget, QTextEdit, QGraphicsView, QGraphicsScene, QSizePolicy)
from PySide6.QtGui import QImage, QPixmap, QIcon, QAction, QCursor
from PySide6.QtCore import Qt, QTimer, QUrl, QSize, Signal, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QGraphicsOpacityEffect
import socket
import platform
from packaging import version

# Helper function to get correct path for bundled assets
def resource_path(relative_path):
    """Get absolute path to resource, works for dev and PyInstaller."""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(__file__)
    return os.path.join(base_path, relative_path)

# Configure logging with UTF-8 encoding
# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename=os.path.join(os.getenv('TEMP'), f'student_app_{getpass.getuser()}.log')
)


class StudentApp(QMainWindow):
    APP_VERSION = "1.0.0"
    SERVER_URL = "https://hrnotification.acorngroup.lk"
    new_content_signal = Signal(dict)
    update_scroll_signal = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Client Notification System")
        self.resize(1200, 600)
        self.setStyleSheet("""
            QMainWindow { background-color: #ece4f7; }
            QLabel { color: #333333; font-size: 14px; }
            QLineEdit, QComboBox { background-color: #ffffff; color: #333333; padding: 8px; border: 1px solid #b8a9d9; border-radius: 5px; }
            QPushButton { background-color: #b8a9d9; color: #ffffff; padding: 8px; border: none; border-radius: 5px; font-weight: bold; }
            QPushButton:hover { background-color: #a38cd5; }
            QPushButton:disabled { background-color: #d3c4e9; color: #ffffff; }
            QFrame, QScrollArea, QTextEdit { background-color: #ece4f7; }
            QProgressBar { background-color: #ffffff; border: 1px solid #b8a9d9; border-radius: 5px; }
            QProgressBar::chunk { background-color: #b8a9d9; }
        """)
        self.employee_id = None
        self.employee_email = None
        self.ip = self.get_ip()
        self.server_url = "https://hrnotification.acorngroup.lk/"
        self.add_to_registry()
        self.device_type = self.get_device_type()
        self.hostname = self.get_hostname()
        self.host_email = self.get_host_email()
        self.device_id = self.load_device_id()
        self.content_thread = None
        self.running = True
        self.media_player = None
        self.video_widget = None
        self.audio_output = None
        self.update_scroll_signal.connect(self.update_scroll_area)
        self.tray_icon = None
        self.all_content = []
        self.current_content_index = 0
        self.registered = False
        self.processed_content_ids = set()
        self.emoji_map = {
            'like': '👍',
            'unlike': '👎',
            'heart': '❤️',
            'cry': '😢'
        }
        self.notifications = []
        self.pending_display = {}
        self.play_again_button = None
        self.countdown_timer = None
        self.countdown_label = None
        self.stop_button = None
        self.countdown_seconds = 60
        self.viewed_durations = {}
        self.view_start_time = None
        self.countdown_remaining = self.countdown_seconds
        self.countdown_active = False
        self.graphics_view = None
        self.scene = None
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        logging.info("Starting student_app.py")
        self.load_registration_data()  # Now this will work as it's an instance method
        self.setup_ui()
        self.setup_system_tray()
        self.new_content_signal.connect(self.show_message_dialog)
        if self.employee_id:
            self.validate_existing_registration()
        else:
            self.stack.setCurrentWidget(self.initial_page)
        QTimer.singleShot(randint(0, 86400000), self.check_for_updates)
        
    def get_ip(self):
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = 'unknown'
        logging.debug(f"Detected IP: {ip}")
        return ip

    def load_registration_data(self):
        """Load stored registration data from a local file."""
        reg_file = os.path.join(os.getenv('TEMP'), f'student_app_{getpass.getuser()}_reg.json')
        if os.path.exists(reg_file):
            try:
                with open(reg_file, 'r') as f:
                    data = json.load(f)
                    self.employee_id = data.get('employee_id')
                    self.employee_email = data.get('employee_email')
                    logging.info(f"Loaded registration data: employee_id={self.employee_id}, email={self.employee_email}")
            except Exception as e:
                logging.error(f"Failed to load registration data: {str(e)}")

    def save_registration_data(self):
        """Save registration data to a local file."""
        reg_file = os.path.join(os.getenv('TEMP'), f'student_app_{getpass.getuser()}_reg.json')
        data = {'employee_id': self.employee_id, 'employee_email': self.employee_email}
        try:
            with open(reg_file, 'w') as f:
                json.dump(data, f)
                logging.info(f"Saved registration data to {reg_file}")
        except Exception as e:
            logging.error(f"Failed to save registration data: {str(e)}")

    def validate_existing_registration(self):
        """Validate existing employee_id with the server and proceed if valid."""
        if not self.employee_id:
            return
        try:
            # Use /get_or_create_employee with the stored email to validate
            response = requests.post(f"{self.server_url}/get_or_create_employee", json={"email": self.employee_email}, timeout=5)
            response.raise_for_status()
            server_employee_id = response.json().get('employee_id')
            if server_employee_id == self.employee_id:
                self.registered = True
                self.email_display.setText(f"Email: {self.employee_email}")
                self.stack.setCurrentWidget(self.content_page)
                self.start_content_check()
                logging.info(f"Validated existing registration for employee_id {self.employee_id}")
            else:
                self.employee_id = None
                self.employee_email = None
                self.stack.setCurrentWidget(self.initial_page)
                logging.warning("Existing registration invalid, showing email page")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error validating registration: {str(e)}")
            self.stack.setCurrentWidget(self.initial_page)

    # New method to load/generate persistent device_id
    def load_device_id(self):
        """Load or generate a persistent device_id stored locally."""
        reg_file = os.path.join(os.getenv('TEMP'), f'student_app_{getpass.getuser()}_device.json')
        if os.path.exists(reg_file):
            try:
                with open(reg_file, 'r') as f:
                    data = json.load(f)
                    device_id = data.get('device_id')
                    if device_id:
                        logging.info(f"Loaded device_id: {device_id}")
                        return device_id
            except Exception as e:
                logging.error(f"Failed to load device_id: {str(e)}")

        # Generate new device_id if not found
        device_id = str(uuid.uuid4())
        try:
            with open(reg_file, 'w') as f:
                json.dump({'device_id': device_id}, f)
            logging.info(f"Generated and saved new device_id: {device_id}")
        except Exception as e:
            logging.error(f"Failed to save device_id: {str(e)}")
        return device_id

    def setup_logging(self):
        log_file = os.path.join(os.getenv('TEMP'), f"student_app_{self.employee_id or 'unknown'}.log")
        logging.basicConfig(
            level=logging.INFO,  # Changed to INFO for production
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )

    def add_to_registry(self):
        """Add app.exe to Windows Registry for auto-start."""
        try:
            exe_path = sys.executable  # Path to the running executable (app.exe)
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "StudentApp", 0, winreg.REG_SZ, exe_path)
            winreg.CloseKey(key)
            logging.info(f"Added to registry auto-start: {exe_path}")
        except Exception as e:
            logging.error(f"Failed to add to registry: {str(e)}")

    def init_ui(self):
        """Initialize the UI without the close button."""
        self.setWindowTitle("StudentApp")
        # Remove close button and other system menu options
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowCloseButtonHint & ~Qt.WindowSystemMenuHint)
        self.setFixedSize(400, 300)  # Fixed size to prevent resizing

        # Create a central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Add a custom close button
        self.close_button = QPushButton("Close Application")
        self.close_button.clicked.connect(self.close_app)
        layout.addWidget(self.close_button)
        layout.addStretch()  # Push button to the top

        self.show()

    def close_app(self):
        """Handle app closure via custom button."""
        logging.info("Application closed by user via custom button")
        self.close()

    def check_for_updates(self):
        """Check for updates and report status to server."""
        try:
            self.report_update_status('pending', 'Checking for updates')
            response = requests.get(f"{self.SERVER_URL}/updates/version", timeout=5)
            response.raise_for_status()
            server_version = response.text.strip()
            if version.parse(server_version) > version.parse(self.APP_VERSION):
                logging.info(f"Update available: {server_version} (current: {self.APP_VERSION})")
                self.download_update(server_version)
            else:
                logging.info("No new version available")
                self.report_update_status('success', 'Version up to date')
        except Exception as e:
            logging.error(f"Error checking for updates: {str(e)}")
            self.report_update_status('failed', f"Error checking updates: {str(e)}")
        finally:
            QTimer.singleShot(4 * 60 * 60 * 1000, self.check_for_updates)  # Retry in 4 hours

    # Updated download_update method
    def download_update(self, new_version):
        """Download new app.exe, update registry, and report status."""
        try:
            temp_dir = os.getenv('TEMP')
            temp_exe_path = os.path.join(temp_dir, f"app_{new_version}.exe")
            self.report_update_status('pending', f"Downloading version {new_version}")

            # Clean up old .exe files
            for old_file in os.listdir(temp_dir):
                if old_file.startswith("app_") and old_file.endswith(".exe"):
                    try:
                        os.remove(os.path.join(temp_dir, old_file))
                        logging.info(f"Removed old update file: {old_file}")
                    except Exception as e:
                        logging.warning(f"Failed to remove old file {old_file}: {str(e)}")

            response = requests.get(f"{self.SERVER_URL}/updates/app", stream=True, timeout=10)
            response.raise_for_status()
            with open(temp_exe_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logging.info(f"Downloaded update to {temp_exe_path}")

            # Create batch file to replace executable
            current_exe = sys.executable
            batch_path = os.path.join(temp_dir, "update.bat")
            batch_content = f"""@echo off
    timeout /t 3 /nobreak >nul
    taskkill /IM app.exe /F >nul 2>&1
    copy "{temp_exe_path}" "{current_exe}" /Y
    start "" "{current_exe}"
    del "{batch_path}"
    """
            with open(batch_path, 'w') as f:
                f.write(batch_content)

            # Update registry
            self.add_to_registry()

            # Report success before restarting
            self.report_update_status('success', f"Updated to version {new_version}")

            # Run batch file and exit
            subprocess.Popen(batch_path, shell=True)
            self.close()
        except Exception as e:
            logging.error(f"Update failed: {str(e)}")
            self.report_update_status('failed', f"Update failed: {str(e)}")
            if os.path.exists(temp_exe_path):
                try:
                    os.remove(temp_exe_path)
                    logging.info(f"Cleaned up failed download: {temp_exe_path}")
                except Exception as e:
                    logging.warning(f"Failed to clean up {temp_exe_path}: {str(e)}")
    
    def show_update_dialog(self, exe_url, new_version):
        dialog = QDialog(self)
        dialog.setWindowTitle("Updating Application")
        dialog.setFixedSize(300, 100)
        dialog.setStyleSheet("background-color: #ece4f7;")
        dialog.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        layout = QVBoxLayout(dialog)
        label = QLabel(f"Downloading update to version {new_version}...")
        label.setStyleSheet("color: #333333; font-size: 14px;")
        layout.addWidget(label)
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        layout.addWidget(progress_bar)
        dialog.show()

        def download_and_update():
            try:
                temp_dir = tempfile.gettempdir()
                new_exe_path = os.path.join(temp_dir, f"app_{new_version}.exe")
                # Clean up old .exe files
                for old_file in os.listdir(temp_dir):
                    if old_file.startswith("app_") and old_file.endswith(".exe"):
                        try:
                            os.remove(os.path.join(temp_dir, old_file))
                            logging.info(f"Removed old update file: {old_file}")
                        except Exception as e:
                            logging.warning(f"Failed to remove old file {old_file}: {str(e)}")
                response = requests.get(exe_url, timeout=10, stream=True)
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                with open(new_exe_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                progress_bar.setValue(int((downloaded / total_size) * 100))
                logging.info(f"Downloaded update to {new_exe_path}")
                current_exe = sys.executable
                batch_path = os.path.join(temp_dir, "update.bat")
                with open(batch_path, 'w') as batch:
                    batch.write(f"""@echo off
    timeout /t 3 /nobreak >nul
    del "{current_exe}"
    copy "{new_exe_path}" "{current_exe}"
    start "" "{current_exe}"
    del "{batch_path}"
    """)
                subprocess.Popen(batch_path, shell=True)
                dialog.close()
                logging.info("Update batch started. Exiting app...")
                QApplication.quit()
            except requests.exceptions.RequestException as e:
                logging.error(f"Update failed: {str(e)}")
                dialog.close()
                QMessageBox.warning(self, "Update Failed", f"Failed to update: {str(e)}")
                try:
                    if os.path.exists(new_exe_path):
                        os.remove(new_exe_path)
                        logging.info(f"Cleaned up failed download: {new_exe_path}")
                except Exception as e:
                    logging.warning(f"Failed to clean up {new_exe_path}: {str(e)}")

        QTimer.singleShot(0, download_and_update)

    def fetch_views(self):
        """Fetch view data from server to populate viewed_durations."""
        retries = 3
        for attempt in range(retries):
            try:
                logging.debug(f"Fetching views for employee_id: {self.employee_id}, attempt {attempt + 1}")
                response = requests.get(f"{self.server_url}/views/{self.employee_id}", timeout=10)
                response.raise_for_status()
                views = response.json().get('views', [])
                server_durations = {view['content_id']: view['viewed_duration'] for view in views}
                for content_id, duration in server_durations.items():
                    if content_id not in self.viewed_durations or duration > self.viewed_durations[content_id]:
                        self.viewed_durations[content_id] = duration
                logging.debug(f"Merged viewed_durations: {self.viewed_durations}")
                self.update_scroll_signal.emit()
                break
            except requests.exceptions.RequestException as e:
                logging.error(f"Error fetching views, attempt {attempt + 1}: {str(e)}")
                if attempt == retries - 1:
                    QMessageBox.warning(self, "Warning", f"Failed to fetch view data after {retries} attempts: {str(e)}")
                time.sleep(2)  # Wait before retrying

    def get_device_type(self):
        system = platform.system()
        if system == 'Windows':
            return f"Windows {platform.release()}"
        elif system == 'Darwin':
            return 'Apple'
        else:
            return system
        logging.debug(f"Detected device type: {system}")
        return device_type
    
    def get_hostname(self):
        try:
            hostname = socket.gethostname()
        except Exception:
            hostname = 'unknown'
        logging.debug(f"Detected hostname: {hostname}")
        return hostname
    
    def get_host_email(self):
        try:
            username = getpass.getuser().lower()
            domain = 'acorn.lk'
            host_email = f"{username}@{domain}"
            logging.debug(f"Constructed host email: {host_email}")
            return host_email
        except Exception as e:
            logging.error(f"Error getting host email: {str(e)}")
            return 'unknown@acorn.lk'

    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        self.stack = QStackedWidget()
        self.main_layout.addWidget(self.stack)

        self.initial_page = QWidget()
        initial_layout = QVBoxLayout(self.initial_page)
        logo_path = resource_path("logo_s.ico")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path).scaled(QSize(100, 100), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label = QLabel()
            logo_label.setPixmap(pixmap)
            initial_layout.addWidget(logo_label, alignment=Qt.AlignCenter)

        email_label = QLabel("Enter your email:")
        initial_layout.addWidget(email_label, alignment=Qt.AlignCenter)
        self.email_entry = QLineEdit()
        initial_layout.addWidget(self.email_entry, alignment=Qt.AlignCenter)
        self.next_button = QPushButton("Next")
        self.next_button.setEnabled(False)
        self.next_button.clicked.connect(self.validate_email)
        initial_layout.addWidget(self.next_button, alignment=Qt.AlignCenter)
        self.next_button.enterEvent = lambda event: self.animate_button(self.next_button, True)
        self.next_button.leaveEvent = lambda event: self.animate_button(self.next_button, False)
        self.email_entry.textChanged.connect(self.check_email_validity)
        self.initial_page.setLayout(initial_layout)
        self.stack.addWidget(self.initial_page)

        self.content_page = QWidget()
        content_layout = QHBoxLayout(self.content_page)

        sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_widget.setFixedWidth(200)
        label = QLabel("Message History")
        label.setStyleSheet("color: #333333; font-weight: bold; font-size: 16px;")
        sidebar_layout.addWidget(label)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_area.setWidget(self.scroll_content)
        sidebar_layout.addWidget(self.scroll_area)
        sidebar_widget.setLayout(sidebar_layout)
        content_layout.addWidget(sidebar_widget)

        main_content_widget = QWidget()
        self.main_content_layout = QVBoxLayout(main_content_widget)

        # Modified top frame to align title, logo, countdown, and stop button
        top_frame = QFrame()
        top_layout = QHBoxLayout(top_frame)
    
        # Title on the left
        self.title_label = QLabel("")
        self.title_label.setAlignment(Qt.AlignLeft)
        self.title_label.setStyleSheet("color: #333333; font-size: 18px; font-weight: bold;")
        top_layout.addWidget(self.title_label)

        # Spacer to push logo, countdown, and stop button to the right
        top_layout.addStretch()

        # Logo
        logo_path = resource_path("logo_s.ico")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path).scaled(QSize(100, 70), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.logo_label = QLabel()
            self.logo_label.setPixmap(pixmap)
            top_layout.addWidget(self.logo_label)

        # Countdown label
        self.countdown_label = QLabel("60")
        self.countdown_label.setStyleSheet("color: #333333; font-size: 14px; font-weight: bold;")
        top_layout.addWidget(self.countdown_label)

        # Stop button
        self.stop_button = QPushButton()
        stop_icon_path = resource_path("stop.png")
        if os.path.exists(stop_icon_path):
            self.stop_button.setIcon(QIcon(stop_icon_path))
        else:
            self.stop_button.setIcon(QIcon.fromTheme("media-playback-stop"))
        self.stop_button.setStyleSheet("background-color: #b8a9d9; padding: 5px; border-radius: 5px;")
        self.stop_button.setFixedSize(30, 30)
        self.stop_button.clicked.connect(self.toggle_countdown)
        self.stop_button.enterEvent = lambda event: self.animate_button(self.stop_button, True)
        self.stop_button.leaveEvent = lambda event: self.animate_button(self.stop_button, False)
        top_layout.addWidget(self.stop_button)

        self.main_content_layout.addWidget(top_frame)

        self.message_display = QTextEdit("")
        self.message_display.setReadOnly(True)
        self.message_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.message_display.setStyleSheet("font-size: 14px; border: none; background-color: #ece4f7; color: #333333;")

        self.media_frame = QFrame()
        media_layout = QVBoxLayout(self.media_frame)
        self.media_frame.setLayout(media_layout)

        self.loading_bar = QProgressBar()
        self.loading_bar.setMinimum(0)
        self.loading_bar.setMaximum(0)
        self.loading_bar.setVisible(False)
        self.main_content_layout.addWidget(self.loading_bar)

        self.content_container = QWidget()
        self.main_content_layout.addWidget(self.content_container)

        # Move buttons, email, and developed_by to bottom
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        self.button_frame = QFrame()
        button_layout = QHBoxLayout(self.button_frame)
        for emoji in ['like', 'unlike', 'heart', 'cry']:
            btn = QPushButton(self.emoji_map[emoji])
            btn.setStyleSheet("background-color: transparent; padding: 2px; border: none; font-size: 24px;")
            btn.clicked.connect(lambda checked, e=emoji: self.send_reaction(e, self.all_content[self.current_content_index]['id']))
            btn.setFixedSize(40, 40)
            btn.enterEvent = lambda event: self.animate_button(btn, True)
            btn.leaveEvent = lambda event: self.animate_button(btn, False)
            button_layout.addWidget(btn)
        bottom_layout.addWidget(self.button_frame)

        self.feedback_entry = QLineEdit()
        bottom_layout.addWidget(self.feedback_entry)
        self.submit_button = QPushButton("Submit Feedback")
        self.submit_button.clicked.connect(self.submit_feedback)
        self.submit_button.enterEvent = lambda event: self.animate_button(self.submit_button, True)
        self.submit_button.leaveEvent = lambda event: self.animate_button(self.submit_button, False)
        bottom_layout.addWidget(self.submit_button)

        self.nav_frame = QFrame()
        nav_layout = QHBoxLayout(self.nav_frame)
        prev_button = QPushButton("Previous")
        prev_button.clicked.connect(self.show_previous_content)
        prev_button.enterEvent = lambda event: self.animate_button(prev_button, True)
        prev_button.leaveEvent = lambda event: self.animate_button(prev_button, False)
        nav_layout.addWidget(prev_button)
        next_button = QPushButton("Next")
        next_button.clicked.connect(self.show_next_content)
        next_button.enterEvent = lambda event: self.animate_button(next_button, True)
        next_button.leaveEvent = lambda event: self.animate_button(next_button, False)
        nav_layout.addWidget(next_button)
        bottom_layout.addWidget(self.nav_frame)

        self.minimize_button = QPushButton("Minimize to Tray")
        self.minimize_button.clicked.connect(self.minimize_to_tray)
        self.minimize_button.enterEvent = lambda event: self.animate_button(self.minimize_button, True)
        self.minimize_button.leaveEvent = lambda event: self.animate_button(self.minimize_button, False)
        bottom_layout.addWidget(self.minimize_button)

        self.email_display = QLabel("")
        self.email_display.setAlignment(Qt.AlignCenter)
        bottom_layout.addSpacing(2)  # 2px gap between minimize and email
        bottom_layout.addWidget(self.email_display)

        self.developed_by_label = QLabel("@Developed by Acorn Group IT")
        self.developed_by_label.setAlignment(Qt.AlignCenter)
        self.developed_by_label.setStyleSheet("color: #666666; font-size: 10px; padding: 5px;")
        bottom_layout.addWidget(self.developed_by_label)

        bottom_widget.setLayout(bottom_layout)
        self.main_content_layout.addWidget(bottom_widget)

        main_content_widget.setLayout(self.main_content_layout)
        content_layout.addWidget(main_content_widget)

        self.content_page.setLayout(content_layout)
        self.stack.addWidget(self.content_page)
        if self.employee_id and self.registered:
            self.stack.setCurrentWidget(self.content_page)
        else:
            self.stack.setCurrentWidget(self.initial_page)

    def animate_button(self, button, grow):
        anim = QPropertyAnimation(button, b"geometry")
        anim.setDuration(200)
        rect = button.geometry()
        if grow:
            anim.setStartValue(rect)
            anim.setEndValue(rect.adjusted(-5, -5, 5, 5))
            anim.setEasingCurve(QEasingCurve.OutBounce)
        else:
            anim.setStartValue(rect)
            anim.setEndValue(rect.adjusted(5, 5, -5, -5))
            anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.start()

    def setup_system_tray(self):
        logo_path = resource_path("logo_s.ico")
        if os.path.exists(logo_path):
            icon = QIcon(logo_path)
            self.tray_icon = QSystemTrayIcon(self)
            self.tray_icon.setIcon(icon)
            self.tray_icon.setToolTip("Client Notification System")
            menu = QMenu()
            show_action = QAction("Show", self)
            show_action.triggered.connect(self.show_window)
            exit_action = QAction("Exit", self)
            exit_action.triggered.connect(self.on_exit)
            menu.addAction(show_action)
            menu.addAction(exit_action)
            self.tray_icon.setContextMenu(menu)
            self.tray_icon.show()

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()
        logging.debug(f"Showing main window, visible: {self.isVisible()}, geometry: {self.geometry()}")
        if self.registered:
            self.stack.setCurrentWidget(self.content_page)

    def check_email_validity(self):
        email = self.email_entry.text().strip()
        self.next_button.setEnabled(bool(email) and '@' in email)


    def validate_email(self):
        email = self.email_entry.text().strip()
        if not email or '@' not in email:
            logging.error("Invalid email entered")
            QMessageBox.critical(self, "Error", "Please enter a valid email address")
            return
        self.employee_email = email
        logging.debug(f"Sending request to {self.server_url}/get_or_create_employee with email {email}")
        try:
            response = requests.post(f"{self.server_url}/get_or_create_employee", json={"email": email}, timeout=5)
            logging.debug(f"Response status: {response.status_code}, body: {response.text}")
            response.raise_for_status()
            self.employee_id = response.json()['employee_id']
            logging.info(f"Got/created employee_id: {self.employee_id} for email {email}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error details: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to get/create employee: {str(e)}")
            return
        self.setup_logging()  # Set up logging after employee_id is available
        self.fetch_views()  # Fetch views after employee_id is set
        self.stack.setCurrentWidget(self.content_page)
        self.email_display.setText(f"Email: {email}")
        self.register_device_request()

    def register_device_request(self):
        logging.debug(f"Registering device for employee_id: {self.employee_id}, ip: {self.ip}, device_type: {self.device_type}, hostname: {self.hostname}, email: {self.host_email}")
        retries = 3
        for attempt in range(retries):
            try:
                response = requests.post(f"{self.server_url}/register_device", json={
                    "employee_id": self.employee_id,
                    "ip": self.ip,
                    "device_type": self.device_type,
                    "hostname": self.hostname,
                    "email": self.host_email
                }, timeout=5)
                response.raise_for_status()
                logging.info(f"Device registered: {self.employee_id}")
                break
            except requests.exceptions.RequestException as e:
                logging.error(f"Device registration attempt {attempt + 1} failed: {str(e)}")
                if attempt == retries - 1:
                    QMessageBox.critical(self, "Error", f"Failed to register device: {str(e)}")
                    return
                time.sleep(2)

        QMessageBox.information(self, "Success", "Employee and device registered successfully")
        self.registered = True
        self.save_registration_data()  # Save data locally
        self.start_content_check()

    def start_content_check(self):
        self.content_thread = threading.Thread(target=self.check_content, daemon=True)
        self.content_thread.start()
        self.hide()
        self.stack.setCurrentWidget(self.content_page)

    def show_message_dialog(self, content):
        logging.debug(f"Showing message dialog for content {content['id']}")
        dialog = QDialog(self)
        dialog.setWindowTitle("New Message Notification")
        dialog.setStyleSheet("background-color: #ece4f7;")
        dialog.setFixedSize(300, 200)
        dialog.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout(dialog)
        label = QLabel("You have a new message, are you free?")
        label.setStyleSheet("color: #333333; font-size: 14px;")
        layout.addWidget(label, alignment=Qt.AlignCenter)

        delay_options = ["at now free", "late of 30 minutes", "late of 1 hour", "late of 3 hours"]
        delay_combo = QComboBox()
        delay_combo.addItems(delay_options)
        delay_combo.setStyleSheet("padding: 5px;")
        layout.addWidget(delay_combo, alignment=Qt.AlignCenter)

        ok_button = QPushButton("OK")
        ok_button.setStyleSheet("background-color: #b8a9d9; color: #ffffff; padding: 5px; font-weight: bold;")
        ok_button.clicked.connect(lambda: self.handle_delay_choice(content, delay_combo.currentText(), dialog))
        layout.addWidget(ok_button, alignment=Qt.AlignCenter)

        opacity_effect = QGraphicsOpacityEffect(dialog)
        dialog.setGraphicsEffect(opacity_effect)
        self.dialog_animation = QPropertyAnimation(opacity_effect, b"opacity")
        self.dialog_animation.setDuration(500)
        self.dialog_animation.setStartValue(0.0)
        self.dialog_animation.setEndValue(1.0)
        self.dialog_animation.setEasingCurve(QEasingCurve.InOutQuad)
        self.dialog_animation.start()

        screen = QApplication.primaryScreen().geometry()
        dialog.move((screen.width() - 300) // 2, (screen.height() - 200) // 2)
        logging.debug(f"Showing dialog for content {content['id']}, visible: {dialog.isVisible()}")
        dialog.exec()
        logging.debug(f"Dialog closed for content {content['id']}, visible: {dialog.isVisible()}")

    def handle_delay_choice(self, content, delay_choice, dialog):
        logging.debug(f"Handling delay choice '{delay_choice}' for content {content['id']}")
        delay_seconds = 0
        if delay_choice == "late of 30 minutes":
            delay_seconds = 30 * 60
        elif delay_choice == "late of 1 hour":
            delay_seconds = 60 * 60
        elif delay_choice == "late of 3 hours":
            delay_seconds = 3 * 60 * 60

        try:
            logging.debug(f"Setting delay choice '{delay_choice}' for content {content['id']}")
            response = requests.post(
                f"{self.server_url}/set_message_delay",
                json={
                    "employee_id": self.employee_id,
                    "content_id": content['id'],
                    "delay_choice": delay_choice
                },
                timeout=10,
                allow_redirects=True
            )
            logging.debug(f"set_message_delay response: status={response.status_code}, text={response.text}")
            if response.status_code == 302:
                logging.warning(f"Redirect detected for set_message_delay to {response.headers.get('Location')}, proceeding to display content {content['id']}")
            else:
                response.raise_for_status()
                logging.info(f"Delay choice {delay_choice} set for content {content['id']}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error setting delay choice for content {content['id']}: {str(e)}")
            QMessageBox.warning(self, "Warning", f"Failed to set delay choice: {str(e)}. Displaying content anyway.")

        try:
            if delay_seconds == 0:
                logging.debug(f"Displaying content {content['id']} immediately")
                self.show()
                self.raise_()
                self.activateWindow()
                logging.debug(f"Window shown for immediate display, visible: {self.isVisible()}, geometry: {self.geometry()}")
                self.display_content(content)
            else:
                timer_id = QTimer.singleShot(int(delay_seconds * 1000), lambda: self.display_content(content))
                self.pending_display[content['id']] = timer_id
                logging.debug(f"Scheduled display for content {content['id']} after {delay_seconds} seconds")
        except Exception as e:
            logging.error(f"Error displaying content {content['id']}: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to display content: {str(e)}")
        finally:
            dialog.close()
            if delay_seconds != 0:
                self.hide()


    def check_content(self):
        while self.running:
            try:
                response = requests.get(f"{self.server_url}/content/{self.employee_id}", timeout=5)
                response.raise_for_status()
                data = response.json()
                logging.debug(f"Content response for {self.employee_id}: {data}")
                self.notifications = data.get('notifications', [])
                new_content = data.get('content', [])

                # Fetch updated view data to ensure status icons are current
                self.fetch_views()

                current_ids = {c['id'] for c in self.all_content}
                new_messages = [c for c in new_content if c['id'] not in current_ids]
                logging.debug(f"New messages detected: {[c['id'] for c in new_messages]}")
                for content in new_content:
                    if content['id'] not in current_ids:
                        self.all_content.append(content)

                for content in new_messages:
                    if content['id'] not in self.processed_content_ids:
                        logging.debug(f"Emitting signal for new content {content['id']}")
                        self.new_content_signal.emit(content)

                current_time = datetime.now(timezone.utc)
                for content in new_content:
                    if content['id'] in self.processed_content_ids or content['id'] in self.pending_display:
                        logging.debug(f"Skipping content {content['id']} (processed or pending)")
                        continue
                    try:
                        preference_response = requests.get(f"{self.server_url}/message_preferences/{self.employee_id}/{content['id']}", timeout=5)
                        preference_response.raise_for_status()
                        preference_data = preference_response.json().get('preference', {})
                        logging.debug(f"Preference for content {content['id']}: {preference_data}")
                        display_time = preference_data.get('display_time')
                        if display_time:
                            display_time = datetime.fromisoformat(display_time)
                            if display_time <= current_time:
                                logging.debug(f"Displaying content {content['id']} as display_time reached")
                                QTimer.singleShot(0, lambda c=content: self.display_content(c))
                                if content['id'] in self.pending_display:
                                    del self.pending_display[content['id']]
                    except requests.exceptions.RequestException as e:
                        logging.error(f"Error fetching preference for content {content['id']}: {str(e)}")
                        if content['id'] not in self.processed_content_ids:
                            logging.debug(f"Fallback: Emitting signal for content {content['id']} due to preference fetch failure")
                            self.new_content_signal.emit(content)

                try:
                    requests.post(f"{self.server_url}/update_status", json={
                        "employee_id": self.employee_id,
                        "status": "online",
                        "app_running": True,
                        "ip": self.ip,
                        "device_type": self.device_type,
                        "hostname": self.hostname,  # Add hostname
                        "email": self.host_email    # Add email
                    }, timeout=5)
                except requests.exceptions.RequestException as e:
                    logging.error(f"Error updating status: {str(e)}")

            except requests.exceptions.RequestException as e:
                logging.error(f"Error checking content: {str(e)}")

            time.sleep(60)

    def display_content(self, content):
        self.current_content_index = self.all_content.index(content) if content in self.all_content else 0
        self.stack.setCurrentWidget(self.content_page)
        self.show()
        self.raise_()
        self.activateWindow()
        logging.debug(f"Displaying content window for content {content['id']}, window visible: {self.isVisible()}, geometry: {self.geometry()}")
        self.show_content()

    def start_countdown(self):
        self.countdown_remaining = self.countdown_seconds
        self.countdown_active = True
        self.countdown_label.setText(f"{self.countdown_remaining}")
        self.stop_button.setIcon(QIcon.fromTheme("media-playback-stop"))
        if self.countdown_timer:
            self.countdown_timer.stop()
        self.countdown_timer = QTimer()
        self.countdown_timer.timeout.connect(self.update_countdown)
        self.countdown_timer.start(1000)
        logging.debug("Countdown started")

    def update_countdown(self):
        if not self.countdown_active:
            return
        self.countdown_remaining -= 1
        self.countdown_label.setText(f"{self.countdown_remaining}")
        if self.countdown_remaining <= 0:
            self.countdown_timer.stop()
            self.countdown_active = False
            self.minimize_to_tray()
            logging.debug("Countdown finished, minimizing to tray")

    def toggle_countdown(self):
        if self.countdown_active:
            self.countdown_active = False
            self.countdown_timer.stop()
            self.stop_button.setIcon(QIcon.fromTheme("media-playback-start"))
            logging.debug(f"Countdown stopped at {self.countdown_remaining} seconds")
        else:
            self.countdown_active = True
            self.countdown_timer.start(1000)
            self.stop_button.setIcon(QIcon.fromTheme("media-playback-stop"))
            logging.debug(f"Countdown resumed with {self.countdown_remaining} seconds remaining")


    def show_content(self):
        if not self.all_content:
            self.message_display.setText("")
            self.title_label.setText("")
            self.loading_bar.setVisible(False)
            logging.debug(f"No content to display for {self.employee_id}")
            return

        content = self.all_content[self.current_content_index]

        # Set title and ensure visibility
        self.title_label.setText(content.get('title', 'No Title'))
        self.title_label.setVisible(True)

        # Set message text
        self.message_display.setText(content['text'])

        # Track view start time for duration calculation
        self.view_start_time = datetime.now()
        if content['id'] not in self.viewed_durations:
            self.viewed_durations[content['id']] = 0

        # Reset media player and graphics view
        if self.media_player:
            self.media_player.stop()
            self.media_player.mediaStatusChanged.disconnect()
            try:
                self.media_player.errorOccurred.disconnect()
            except TypeError:
                pass
            self.media_player = None
            self.video_widget = None
            self.audio_output = None
        if self.graphics_view:
            self.graphics_view = None
            self.scene = None

        # Remove previous content_container if exists
        if hasattr(self, 'content_container') and self.content_container:
            self.main_content_layout.removeWidget(self.content_container)
            self.content_container.deleteLater()
            self.content_container = None

        # Remove buttons from main_content_layout to reposition
        self.main_content_layout.removeWidget(self.button_frame)
        self.main_content_layout.removeWidget(self.feedback_entry)
        self.main_content_layout.removeWidget(self.submit_button)
        self.main_content_layout.removeWidget(self.nav_frame)
        self.main_content_layout.removeWidget(self.minimize_button)
        self.main_content_layout.removeWidget(self.email_display.parent())  # Remove left_info_widget

        # Create buttons_container
        buttons_container = QWidget()
        buttons_layout = QVBoxLayout(buttons_container)
        buttons_layout.addWidget(self.button_frame)
        buttons_layout.addWidget(self.feedback_entry)
        buttons_layout.addWidget(self.submit_button)
        buttons_layout.addWidget(self.nav_frame)
        buttons_layout.addWidget(self.minimize_button)

        # Create new content_container
        self.content_container = QWidget()
        self.main_content_layout.insertWidget(2, self.content_container)

        has_image = bool(content.get('image_url'))
        has_video = bool(content.get('type') == 'video' and content.get('url'))
        has_both = bool(content.get('type') == 'both' and content.get('url') and content.get('image_url'))

        self.loading_bar.setVisible(has_image or has_video or has_both)

        self.start_countdown()

        if has_both or has_video or has_image:
            content_container_layout = QHBoxLayout(self.content_container)
            # Left side: text, buttons, and info
            left_container = QWidget()
            left_layout = QVBoxLayout(left_container)
            left_layout.addWidget(self.message_display)
            left_layout.addWidget(buttons_container)
            left_layout.addWidget(self.email_display.parent())  # Add left_info_widget back
            content_container_layout.addWidget(left_container, 1)

            # Right side: media
            right_container = QWidget()
            right_layout = QVBoxLayout(right_container)

            if has_both or has_video:
                # Video container
                video_container = QWidget()
                video_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                video_layout = QVBoxLayout(video_container)
                try:
                    response = requests.head(content['url'], timeout=5, allow_redirects=True)
                    if response.status_code != 200:
                        raise ValueError(f"Video URL inaccessible: {response.status_code}")

                    self.media_player = QMediaPlayer()
                    self.audio_output = QAudioOutput()
                    self.media_player.setAudioOutput(self.audio_output)
                    self.media_player.setSource(QUrl(content['url']))
                    self.video_widget = QVideoWidget()
                    self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                    self.video_widget.setMinimumSize(150 if has_both else 300, 100 if has_both else 200)
                    self.media_player.setVideoOutput(self.video_widget)
                    video_layout.addWidget(self.video_widget)

                    video_button_frame = QFrame()
                    video_button_layout = QHBoxLayout(video_button_frame)
                    self.audio_output.setMuted(True)
                    unmute_button = QPushButton("Unmute")
                    unmute_button.clicked.connect(self.toggle_mute)
                    unmute_button.enterEvent = lambda event: self.animate_button(unmute_button, True)
                    unmute_button.leaveEvent = lambda event: self.animate_button(unmute_button, False)
                    video_button_layout.addWidget(unmute_button)

                    self.play_again_button = QPushButton("Play Again")
                    self.play_again_button.setEnabled(False)
                    self.play_again_button.clicked.connect(self.play_again)
                    self.play_again_button.enterEvent = lambda event: self.animate_button(self.play_again_button, True)
                    self.play_again_button.leaveEvent = lambda event: self.animate_button(self.play_again_button, False)
                    video_button_layout.addWidget(self.play_again_button)

                    video_layout.addWidget(video_button_frame)
                    self.video_widget.setVisible(True)
                    self.media_player.play()
                    self.media_player.mediaStatusChanged.connect(self.handle_media_status)
                    self.media_player.errorOccurred.connect(self.handle_media_error)
                    logging.debug(f"Video playing for content {content['id']}")
                except Exception as e:
                    logging.error(f"Error loading video for content {content['id']}: {str(e)}")
                    error_label = QLabel("Failed to load video")
                    error_label.setStyleSheet("color: #ff0000; font-size: 14px;")
                    video_layout.addWidget(error_label, alignment=Qt.AlignCenter)
                right_layout.addWidget(video_container, 1)

            if has_both or has_image:
                # Image container
                image_container = QWidget()
                image_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                image_layout = QVBoxLayout(image_container)
                image_layout.setContentsMargins(0, 0, 0, 0)
                image_layout.setSpacing(0)
                try:
                    response = requests.get(content['image_url'], timeout=10)
                    response.raise_for_status()
                    image_data = response.content
                    image = QImage()
                    if not image.loadFromData(image_data):
                        raise ValueError("Failed to load image from data")
                    self.scene = QGraphicsScene()
                    pix_item = self.scene.addPixmap(QPixmap.fromImage(image))
                    self.graphics_view = QGraphicsView(image_container)
                    self.graphics_view.setScene(self.scene)
                    self.graphics_view.setDragMode(QGraphicsView.ScrollHandDrag)
                    self.graphics_view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
                    self.graphics_view.setAlignment(Qt.AlignCenter)
                    self.graphics_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                    image_layout.addWidget(self.graphics_view)

                    # Default zoom out
                    self.graphics_view.scale(0.4, 0.4)

                    zoom_frame = QFrame()
                    zoom_layout = QHBoxLayout(zoom_frame)
                    zoom_layout.setContentsMargins(0, 0, 0, 0)
                    zoom_layout.setSpacing(5)

                    zoom_in_btn = QPushButton("+", image_container)
                    zoom_in_btn.setFixedSize(30, 30)
                    zoom_in_btn.clicked.connect(self.zoom_in_image)
                    zoom_in_btn.enterEvent = lambda event: self.animate_button(zoom_in_btn, True)
                    zoom_in_btn.leaveEvent = lambda event: self.animate_button(zoom_in_btn, False)
                    zoom_layout.addWidget(zoom_in_btn)

                    zoom_out_btn = QPushButton("-", image_container)
                    zoom_out_btn.setFixedSize(30, 30)
                    zoom_out_btn.clicked.connect(self.zoom_out_image)
                    zoom_out_btn.enterEvent = lambda event: self.animate_button(zoom_out_btn, True)
                    zoom_out_btn.leaveEvent = lambda event: self.animate_button(zoom_out_btn, False)
                    zoom_layout.addWidget(zoom_out_btn)

                    zoom_frame.setLayout(zoom_layout)
                    image_layout.addWidget(zoom_frame, alignment=Qt.AlignCenter)
                    logging.debug(f"Image loaded for content {content['id']}")
                except Exception as e:
                    logging.error(f"Error loading image for content {content['id']}: {str(e)}")
                    error_label = QLabel("Image failed to load (showing placeholder)")
                    error_label.setStyleSheet("color: #ff0000; font-size: 14px;")
                    image_layout.addWidget(error_label, alignment=Qt.AlignCenter)
                    placeholder_path = resource_path("logo_s.png")
                    if os.path.exists(placeholder_path):
                        placeholder = QImage(placeholder_path)
                        if not placeholder.isNull():
                            self.scene = QGraphicsScene()
                            self.scene.addPixmap(QPixmap.fromImage(placeholder))
                            self.graphics_view = QGraphicsView(image_container)
                            self.graphics_view.setScene(self.scene)
                            self.graphics_view.setAlignment(Qt.AlignCenter)
                            self.graphics_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                            image_layout.addWidget(self.graphics_view)
                right_layout.addWidget(image_container, 1)

                content_container_layout.addWidget(right_container, 1)
        else:
            # Only text
            content_container_layout = QVBoxLayout(self.content_container)
            content_container_layout.addWidget(self.message_display)
            # Add buttons back below content
            self.main_content_layout.insertWidget(3, self.button_frame)
            self.main_content_layout.insertWidget(4, self.feedback_entry)
            self.main_content_layout.insertWidget(5, self.submit_button)
            self.main_content_layout.insertWidget(6, self.nav_frame)
            self.main_content_layout.insertWidget(7, self.minimize_button)
            self.main_content_layout.insertWidget(8, self.email_display.parent())  # Add left_info_widget back

        QTimer.singleShot(30000, lambda: self.record_view(content['id']))
        self.loading_bar.setVisible(False)

        self.processed_content_ids.add(content['id'])
        logging.debug(f"Marked content {content['id']} as processed")
        self.update_scroll_signal.emit()
        logging.debug(f"Content displayed, window visible: {self.isVisible()}, geometry: {self.geometry()}")

    def handle_media_error(self, error):
        logging.error(f"Media player error: {error}, {self.media_player.errorString()}")
        QMessageBox.warning(self, "Media Error", f"Failed to play video: {self.media_player.errorString()}")

    def zoom_in_image(self):
        if self.graphics_view:
            factor = 1.25
            self.graphics_view.scale(factor, factor)
            self.graphics_view.centerOn(self.scene.sceneRect().center())
            logging.debug("Image zoomed in")

    def zoom_out_image(self):
        if self.graphics_view:
            factor = 0.8
            self.graphics_view.scale(factor, factor)
            self.graphics_view.centerOn(self.scene.sceneRect().center())
            logging.debug("Image zoomed out")

    def handle_media_status(self, status):
        if status == QMediaPlayer.EndOfMedia:
            if self.play_again_button:
                self.play_again_button.setEnabled(True)
                logging.debug("Video finished, enabling Play Again button")
        elif status == QMediaPlayer.PlayingState:
            if self.play_again_button:
                self.play_again_button.setEnabled(False)
                logging.debug("Video playing, disabling Play Again button")

    def play_again(self):
        if self.media_player:
            self.media_player.setPosition(0)
            self.media_player.play()
            self.play_again_button.setEnabled(False)
            logging.debug("Playing video again")

    def update_scroll_area(self):
        for i in reversed(range(self.scroll_layout.count())):
            widget = self.scroll_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        def split_title(title, chunk_size=20):
            if not title:
                return ["Message " + content.get('id', '')]
            result = []
            for i in range(0, len(title), chunk_size):
                result.append(title[i:i + chunk_size])
            return result

        content_by_id = {}
        for content in self.all_content:
            content_id = content['id']
            if content_id not in content_by_id or (content.get('scheduled_time') and content_by_id[content_id].get('scheduled_time') and
                                                  datetime.fromisoformat(content['scheduled_time'].replace('Z', '+00:00')) >
                                                  datetime.fromisoformat(content_by_id[content_id]['scheduled_time'].replace('Z', '+00:00'))):
                content_by_id[content_id] = content

        sorted_content = sorted(
            content_by_id.values(),
            key=lambda x: datetime.fromisoformat(x.get('scheduled_time', '1970-01-01T00:00:00Z').replace('Z', '+00:00'))
            if x.get('scheduled_time') else datetime.min,
            reverse=True
        )

        for i, content in enumerate(sorted_content):
            title = content.get('title', f"Message {content.get('id', '')}")
            title_lines = split_title(title)

            scheduled_time_str = content.get('scheduled_time', '')
            if scheduled_time_str:
                try:
                    utc_time = datetime.fromisoformat(scheduled_time_str.replace('Z', '+00:00'))
                    local_time = utc_time.astimezone(timezone(timedelta(hours=5, minutes=30)))
                    formatted_time = local_time.strftime("%d %b %Y, %I:%M %p")
                except ValueError as e:
                    logging.error(f"Error parsing scheduled_time {scheduled_time_str}: {str(e)}")
                    formatted_time = "Unknown time"
            else:
                formatted_time = "No time specified"

            viewed_duration = self.viewed_durations.get(content['id'], 0)
            status_icon = 'OK' if viewed_duration > 30 else 'Pending'
            status_color = '#28a745' if viewed_duration > 30 else '#ffc107'
            logging.debug(f"Content {content['id']}: viewed_duration={viewed_duration}, status_icon={status_icon}, status_color={status_color}")

            label_text = '<br>'.join(title_lines)
            label_text += f"<br><span style='font-size: 10px; color: #666666;'>{formatted_time} <span style='color: {status_color};'>{status_icon}</span></span>"
            sidebar_label = QLabel(label_text)
            sidebar_label.setStyleSheet("color: #333333; padding: 5px; background-color: #ffffff; border-radius: 3px; margin: 2px;")
            sidebar_label.setAlignment(Qt.AlignLeft)
            sidebar_label.setTextFormat(Qt.RichText)
            sidebar_label.setCursor(QCursor(Qt.PointingHandCursor))
            sidebar_label.mousePressEvent = lambda e, idx=i: self.show_selected_content(idx)
            sidebar_label.setFixedWidth(220)
            self.scroll_layout.addWidget(sidebar_label)

        self.scroll_content.setLayout(self.scroll_layout)
        self.scroll_area.setWidget(self.scroll_content)
        self.scroll_area.setFixedWidth(240)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def toggle_mute(self):
        if not self.media_player or not self.audio_output:
            logging.error("Media player or audio output not initialized")
            return
        
        try:
            is_muted = self.audio_output.isMuted()
            self.audio_output.setMuted(not is_muted)
            sender = self.sender()
            if sender:
                sender.setText("Unmute" if is_muted else "Mute")
            logging.debug(f"Video {'unmuted' if not is_muted else 'muted'}")
        except Exception as e:
            logging.error(f"Error toggling mute: {str(e)}")

    def record_view(self, content_id):
        """Record view with duration to server and update viewed_durations."""
        # Calculate duration locally
        duration = 0
        if self.view_start_time:
            duration = (datetime.now() - self.view_start_time).total_seconds()
            self.viewed_durations[content_id] = max(self.viewed_durations.get(content_id, 0), duration)
        else:
            logging.warning(f"No view_start_time for content {content_id}, using existing duration")

        logging.debug(f"Recording view for content {content_id} with duration {self.viewed_durations.get(content_id, 0)} seconds")
        try:
            response = requests.post(
                f"{self.server_url}/record_view",
                json={
                    "content_id": content_id,
                    "employee_id": self.employee_id,
                    "viewed_duration": self.viewed_durations.get(content_id, 0)
                },
                timeout=5,
                allow_redirects=True
            )
            response.raise_for_status()
            logging.info(f"View recorded successfully for content_id {content_id}, response: {response.text}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error recording view for content_id {content_id}: {str(e)}")
            QMessageBox.warning(self, "Warning", f"Failed to record view: {str(e)}")

        # Update sidebar via signal
        self.update_scroll_signal.emit()

    def start_reaction_animation(self, emoji):
        if emoji not in self.emoji_map:
            logging.error(f"No emoji defined for: {emoji}")
            return

        logging.debug(f"Starting raining reaction animation for emoji: {emoji}")

        overlay = QWidget(self)
        overlay.setGeometry(0, 0, self.width(), self.height())
        overlay.setStyleSheet("background-color: transparent;")
        overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        overlay.setAttribute(Qt.WA_TranslucentBackground)
        overlay.raise_()
        overlay.show()
        logging.debug(f"Overlay created, visible: {overlay.isVisible()}, geometry: {overlay.geometry()}")

        self.animation_active = True

        QTimer.singleShot(5000, lambda: setattr(self, 'animation_active', False) or overlay.deleteLater() or logging.debug("Overlay deleted and animation stopped"))

        def spawn_emojis():
            if not self.animation_active or not overlay or not overlay.isVisible():
                logging.debug("Stopping spawn_emojis: animation inactive or overlay not visible")
                return
            num_emojis = max(10, self.width() // 50)
            spacing = self.width() // num_emojis
            logging.debug(f"Spawning {num_emojis} emojis, spacing: {spacing}")
            for i in range(num_emojis):
                label = QLabel(self.emoji_map[emoji], overlay)
                label.setStyleSheet("background-color: transparent; font-size: 24px;")
                label.setAttribute(Qt.WA_TransparentForMouseEvents)
                start_x = i * spacing + randint(-20, 20)
                label.move(start_x, -32)
                label.show()
                logging.debug(f"Emoji label created at x={start_x}, y=-32, visible: {label.isVisible()}")

                anim = QPropertyAnimation(label, b"pos")
                anim.setDuration(randint(1500, 2500))
                anim.setStartValue(QPoint(label.x(), -32))
                anim.setEndValue(QPoint(label.x() + randint(-30, 30), self.height() + 32))
                anim.setEasingCurve(QEasingCurve.Linear)
                anim.finished.connect(label.deleteLater)
                anim.start()

                opacity_effect = QGraphicsOpacityEffect(label)
                label.setGraphicsEffect(opacity_effect)
                opacity_anim = QPropertyAnimation(opacity_effect, b"opacity")
                opacity_anim.setDuration(anim.duration() * 0.8)
                opacity_anim.setStartValue(1.0)
                opacity_anim.setEndValue(0.0)
                opacity_anim.setEasingCurve(QEasingCurve.InQuad)
                opacity_anim.start()

            QTimer.singleShot(200, spawn_emojis)

        self.show()
        self.raise_()
        self.activateWindow()
        logging.debug(f"Window ensured visible for animation, visible: {self.isVisible()}, geometry: {self.geometry()}")

        overlay.update()
        self.update()

        static_label = QLabel(self.emoji_map[emoji], overlay)
        static_label.setStyleSheet("background-color: transparent; font-size: 24px;")
        static_label.move(self.width() // 2, self.height() // 2)
        static_label.show()
        logging.debug(f"Static test emoji created at x={self.width() // 2}, y={self.height() // 2}, visible: {static_label.isVisible()}")

        spawn_emojis()

    def send_reaction(self, reaction, content_id):
        try:
            logging.debug(f"Sending reaction {reaction} for content_id {content_id}")
            response = requests.post(
                f"{self.server_url}/reaction",
                json={
                    "content_id": content_id,
                    "employee_id": self.employee_id,
                    "reaction": reaction
                },
                timeout=5
            )
            response.raise_for_status()
            logging.info(f"Reaction {reaction} sent for content_id {content_id}")
            self.start_reaction_animation(reaction)
        except requests.exceptions.RequestException as e:
            logging.error(f"Error sending reaction for content_id {content_id}: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to send reaction: {str(e)}")

    def submit_feedback(self):
        if not self.all_content:
            QMessageBox.critical(self, "Error", "No content to provide feedback for")
            return
        
        feedback = self.feedback_entry.text().strip()
        if not feedback:
            QMessageBox.critical(self, "Error", "Please enter feedback")
            return
        
        content_id = self.all_content[self.current_content_index]['id']
        try:
            logging.debug(f"Sending feedback for content_id {content_id}: {feedback}")
            response = requests.post(
                f"{self.server_url}/feedback",
                json={
                    "content_id": content_id,
                    "employee_id": self.employee_id,
                    "feedback": feedback
                },
                timeout=5
            )
            response.raise_for_status()
            logging.info(f"Feedback sent for content_id {content_id}")
            QMessageBox.information(self, "Success", "Feedback submitted successfully")
            self.feedback_entry.clear()
        except requests.exceptions.RequestException as e:
            logging.error(f"Error sending feedback for content_id {content_id}: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to send feedback: {str(e)}")

    def minimize_to_tray(self):
        self.hide()
        if self.countdown_timer:
            self.countdown_timer.stop()
            self.countdown_active = False
        self.countdown_label.setText(f"{self.countdown_seconds}")
        if self.tray_icon:
            self.tray_icon.showMessage(
                "Client Notification System",
                "Application minimized to system tray",
                QSystemTrayIcon.Information,
                2000
            )
        logging.debug(f"Minimized to tray, window visible: {self.isVisible()}")

    def on_exit(self):
        self.running = False
        if self.content_thread:
            self.content_thread.join(timeout=2.0)
        if self.countdown_timer:
            self.countdown_timer.stop()
        try:
            requests.post(f"{self.server_url}/update_status", json={
                "employee_id": self.employee_id,
                "status": "offline",
                "app_running": False,
                "ip": self.ip,
                "device_type": self.device_type
            }, timeout=5)
            logging.info("Status updated to offline on exit")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error updating status to offline: {str(e)}")
        QApplication.quit()

    def show_previous_content(self):
        if self.all_content and self.current_content_index > 0:
            self.current_content_index -= 1
            self.show_content()

    def show_next_content(self):
        if self.all_content and self.current_content_index < len(self.all_content) - 1:
            self.current_content_index += 1
            self.show_content()

    # Updated update_status method
    def update_status(self):
        """Update device status with version and device_id."""
        retries = 3
        for attempt in range(retries):
            try:
                response = requests.post(
                    f"{self.server_url}/update_status",
                    json={
                        "employee_id": self.employee_id,
                        "device_id": self.device_id,
                        "status": "online",
                        "app_running": True,
                        "ip": self.ip,
                        "device_type": self.device_type,
                        "hostname": self.hostname,
                        "email": self.host_email,
                        "current_version": self.APP_VERSION
                    },
                    timeout=10
                )
                response.raise_for_status()
                logging.info("Status updated successfully")
                break
            except requests.exceptions.RequestException as e:
                logging.error(f"Error updating status, attempt {attempt + 1}: {str(e)}")
                if attempt == retries - 1:
                    logging.warning("All status update attempts failed")
                    QMessageBox.warning(self, "Warning", f"Failed to update status: {str(e)}")
                time.sleep(2 ** attempt)

    # New method for reporting update status
    def report_update_status(self, status, message=None):
        """Report update status to server."""
        if not self.employee_id or not self.device_id:
            logging.warning("Cannot report update status: missing employee_id or device_id")
            return
        try:
            response = requests.post(
                f"{self.server_url}/update_status",
                json={
                    "employee_id": self.employee_id,
                    "device_id": self.device_id,
                    "current_version": self.APP_VERSION,
                    "update_status": status,
                    "error_message": message if status == 'failed' else None
                },
                timeout=5
            )
            response.raise_for_status()
            logging.info(f"Reported update status: {status}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error reporting update status: {str(e)}")
    
    def show_selected_content(self, index):
        logging.debug(f"Selected content index: {index}")
        sorted_content = sorted(
            self.all_content,
            key=lambda x: datetime.fromisoformat(x.get('scheduled_time', '1970-01-01T00:00:00Z').replace('Z', '+00:00'))
            if x.get('scheduled_time') else datetime.min,
            reverse=True
        )
        if 0 <= index < len(sorted_content):
            self.current_content_index = self.all_content.index(sorted_content[index])
        else:
            logging.warning(f"Invalid index {index} for sorted content length {len(sorted_content)}")
            self.current_content_index = 0
        self.show_content()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = StudentApp()
    window.show()
    sys.exit(app.exec())