const { app, BrowserWindow, Tray, Menu, ipcMain, screen, dialog, net } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { exec, spawn } = require('child_process');

let mainWindow;
let notificationWindow = null;
let tray = null;
let appIcon = path.join(__dirname, 'assets', 'logo_s_n.ico'); // Placeholder
// Note: You need to extract icons or use pngs. Electron prefers .ico for windows tray.

// Constants
const SERVER_URL = "http://localhost:5000/";
const APP_VERSION = "1.1.8"; // Match package version

let employeeId = 'unknown';
let hostname = os.hostname();
ipcMain.on('set-employee-id', (event, id) => {
    console.log("Main process received employeeId:", id);
    employeeId = id;
});

// Poll for updates every hour
setInterval(checkForUpdates, 3600 * 1000);

// Ensure single instance lock
const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
    app.quit();
} else {
    app.on('second-instance', (event, commandLine, workingDirectory) => {
        // Someone tried to run a second instance, we should focus our window.
        if (mainWindow) {
            if (mainWindow.isMinimized()) mainWindow.restore();
            mainWindow.show();
            mainWindow.focus();
        }
    });

    app.on('ready', () => {
        console.log("App is ready. Creating window...");
        createWindow();
        createTray();
        addToRegistry();

        // Initial checks
        registerDevice();
        checkForUpdates();
    });
}

function registerDevice() {
    // Check if we can get employee ID from hostname
    const request = net.request(`${SERVER_URL}check_registration?hostname=${hostname}`);
    request.on('response', (response) => {
        response.on('data', (chunk) => {
            try {
                const data = JSON.parse(chunk.toString());
                if (data.registered && data.employee_id) {
                    employeeId = data.employee_id;
                    console.log("Device registered to:", employeeId);
                }
            } catch (e) {
                console.error("Error parsing registration:", e);
            }
        });
    });
    request.on('error', (err) => console.log("Registration check failed (server likely offline):", err.message));
    request.end();
}

function checkForUpdates() {
    console.log("Checking for updates...");
    const request = net.request(`${SERVER_URL}updates/version`);
    request.on('response', (response) => {
        response.on('data', (chunk) => {
            const remoteVersion = chunk.toString().trim();
            console.log(`Current: ${APP_VERSION}, Remote: ${remoteVersion}`);

            // Simple version check: if string differs and is not 'unknown'
            if (remoteVersion && remoteVersion !== APP_VERSION && remoteVersion !== 'unknown') {
                console.log("New version found! Initiating update...");

                // Report pending
                reportUpdateStatus(remoteVersion, 'pending');

                // Start download
                performUpdate(remoteVersion);
            }
        });
    });
    request.on('error', (err) => console.log("Update check failed:", err.message));
    request.end();
}

function performUpdate(version) {
    const downloadPath = path.join(os.tmpdir(), `app_${version}.exe`);

    // Create write stream
    const file = fs.createWriteStream(downloadPath);

    const request = net.request(`${SERVER_URL}updates/app`);

    request.on('response', (response) => {
        if (response.statusCode !== 200) {
            reportUpdateStatus(version, 'failed', `Server returned ${response.statusCode}`);
            return;
        }

        response.on('data', (chunk) => {
            file.write(chunk);
        });

        response.on('end', () => {
            file.end();
        });
    });

    file.on('finish', () => {
        file.close(() => {
            console.log("Update downloaded to " + downloadPath);
            reportUpdateStatus(version, 'success');

            // Notify user
            dialog.showMessageBox(mainWindow, {
                type: 'info',
                buttons: ['Update Now', 'Later'],
                title: 'AcornHUB v1.1.8 Available',
                message: `Version ${version} is ready to install.`,
                detail: 'The application will close and the installer will run.'
            }).then(({ response }) => {
                if (response === 0) { // Update Now
                    spawn(downloadPath, [], {
                        detached: true,
                        stdio: 'ignore'
                    }).unref();
                    app.quit();
                }
            });
        });
    });

    file.on('error', (err) => {
        reportUpdateStatus(version, 'failed', "File write error: " + err.message);
        fs.unlink(downloadPath, () => { }); // Delete partial file
    });

    request.on('error', (err) => {
        reportUpdateStatus(version, 'failed', "Download error: " + err.message);
    });
    request.end();
}

function reportUpdateStatus(version, status, errorMsg = '') {
    const postData = JSON.stringify({
        employee_id: employeeId,
        device_id: hostname,
        version: version,
        status: status,
        error_message: errorMsg
    });

    const request = net.request({
        method: 'POST',
        url: `${SERVER_URL}record_update_attempt`,
        headers: {
            'Content-Type': 'application/json'
        }
    });

    request.write(postData);
    request.on('error', (e) => console.error("Failed to report status:", e));
    request.end();
}

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1200,
        height: 600,
        show: true,
        frame: false, // Use custom title bar
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false,
            sandbox: false, // Required for nodeIntegration in recent Electron
            enableRemoteModule: true,
            webSecurity: false
        },
        icon: path.join(__dirname, 'assets', 'icon.png')
    });

    Menu.setApplicationMenu(null); // Remove default menu bar
    mainWindow.loadFile('index.html');
    mainWindow.show();
    // mainWindow.webContents.openDevTools(); // Uncomment if you need to debug later

    mainWindow.on('maximize', () => mainWindow.webContents.send('window-maximized'));
    mainWindow.on('unmaximize', () => mainWindow.webContents.send('window-unmaximized'));

    mainWindow.on('close', (event) => {
        if (!app.isQuitting) {
            event.preventDefault();
            mainWindow.hide();
        }
        return false;
    });
}

function createTray() {
    const iconPath = path.join(__dirname, 'assets', 'logo_s_n.png');
    // Make sure assets exist. The python code uses resource_path("static/images/logo_s_n.png")
    // I will need to copy these assets.

    tray = new Tray(iconPath);
    tray.setToolTip('Client Notification System');

    const contextMenu = Menu.buildFromTemplate([
        { label: 'Show', click: () => mainWindow.show() },
        {
            label: 'Exit', click: () => {
                app.isQuitting = true;
                app.quit();
            }
        }
    ]);

    tray.setContextMenu(contextMenu);
    tray.on('double-click', () => mainWindow.show());
}

// IPC Managers
ipcMain.on('minimize-to-tray', () => {
    mainWindow.hide();
});

ipcMain.on('show-window', () => {
    mainWindow.show();
    mainWindow.focus();
});

ipcMain.on('app-quit', () => {
    app.isQuitting = true;
    app.quit();
});

ipcMain.on('minimize-window', () => {
    if (mainWindow) mainWindow.minimize();
});

ipcMain.on('maximize-window', () => {
    if (mainWindow) {
        if (mainWindow.isMaximized()) {
            mainWindow.restore();
        } else {
            mainWindow.maximize();
        }
    }
});

ipcMain.handle('get-hostname', () => {
    return os.hostname();
});

ipcMain.on('notification-click', () => {
    mainWindow.show();
    mainWindow.focus();
});

ipcMain.on('show-notification', () => {
    if (notificationWindow) {
        notificationWindow.focus();
        return;
    }

    const { width, height } = screen.getPrimaryDisplay().workAreaSize;
    const winW = 400;
    const winH = 450;

    notificationWindow = new BrowserWindow({
        width: winW,
        height: winH,
        x: 20,
        y: height - winH - 20,
        frame: false,
        transparent: true,
        alwaysOnTop: true,
        resizable: false,
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false,
            sandbox: false
        },
        skipTaskbar: true
    });

    notificationWindow.loadFile('notification.html');
    notificationWindow.on('closed', () => {
        notificationWindow = null;
    });
});

ipcMain.on('notification-response', (event, delay) => {
    if (notificationWindow) {
        notificationWindow.close();
    }
    // Send response back to renderer.js if needed or handle here
    if (mainWindow) {
        mainWindow.webContents.send('notification-choice', delay);
    }
});

ipcMain.on('open-edge', (event, url) => {
    if (process.platform === 'win32') {
        exec(`start msedge "${url}"`, (error) => {
            if (error) {
                console.error("Failed to open Edge:", error);
                // Fallback to Shell if Edge fail
                require('electron').shell.openExternal(url);
            }
        });
    } else {
        require('electron').shell.openExternal(url);
    }
});


// Auto-start logic (Windows)
function addToRegistry() {
    if (process.platform === 'win32') {
        const exePath = app.getPath('exe');

        // 1. Use Electron's built-in setLoginItemSettings (Most reliable for packaged apps)
        try {
            app.setLoginItemSettings({
                openAtLogin: true,
                path: exePath,
                enabled: true
            });
            console.log('Auto-start configured via Login Item Settings');
        } catch (err) {
            console.error('Failed to set login item settings:', err);
        }

        // 2. Fallback/Double-check via Registry (useful for some environments)
        const keyPath = 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run';
        const valueName = 'AcornHUBClient'; // Unique name

        // Add to registry with proper quoting for paths with spaces
        const regCommand = `reg add "${keyPath}" /v "${valueName}" /t REG_SZ /d "\\"${exePath}\\"" /f`;

        exec(regCommand, (error) => {
            if (error) console.error('Registry fallback failed:', error);
            else console.log('Registry auto-start entry updated');
        });
    }
}
