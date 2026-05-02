// Basic Renderer Initialization
console.log("Renderer script starting...");

let ipcRenderer;
let shell;
let fs, path, os, spawn;

try {
    const electron = require('electron');
    ipcRenderer = electron.ipcRenderer;
    shell = electron.shell;

    // Core modules for updating
    fs = require('fs');
    path = require('path');
    os = require('os');
    spawn = require('child_process').spawn;
} catch (e) {
    console.error("Failed to load electron modules:", e);
}

// Configuration
const SERVER_URL = "http://localhost:5000/";
const POLL_INTERVAL = 60000;
const REG_CHECK_INTERVAL = 3000;
const APP_VERSION = "1.1.8";

// State
let state = {
    employee_id: null,
    employee_email: null,
    registered: false,
    all_content: [],
    processed_content_ids: new Set(),
    viewed_durations: {},
    current_content_index: 0,
    countdown_seconds: 60,
    countdown_timer: null,
    running: true,
    view_start_time: null,
    pending_display: {}, // content_id -> timeout
    device_id: null,
    polling_timer: null,
    notified_ids: new Set()
};

// Elements
const initialPage = document.getElementById('initial-page');
const contentPage = document.getElementById('content-page');
const emailEntry = document.getElementById('email-entry');
const nextButton = document.getElementById('next-button');
const historyList = document.getElementById('history-list');
const messageDisplay = document.getElementById('message-display');
const titleLabel = document.getElementById('title-label');
const titleDisplay = document.getElementById('title-display');
const countdownLabel = document.getElementById('countdown-label');
const stopButton = document.getElementById('stop-button');
const videoPlayer = document.getElementById('video-player');
const imageViewer = document.getElementById('image-viewer');
const contentImage = document.getElementById('content-image');
const emailDisplay = document.getElementById('email-display');
const notificationDialog = document.getElementById('notification-dialog');

// Initialize
async function init() {
    console.log("Initializing app...");

    // Explicitly show loading if we have local data to check
    loadSettings();
    setupEventListeners();
    setupTitleBar();

    if (state.employee_id && state.employee_email) {
        console.log("Checking existing registration for:", state.employee_email);

        // Show loading overlay while validating
        const loadingOverlay = document.getElementById('loading');
        if (loadingOverlay) loadingOverlay.style.display = 'flex';

        const validationResult = await validateExisting();

        if (loadingOverlay) loadingOverlay.style.display = 'none';

        if (validationResult === 'valid') {
            console.log("Registration valid. Loading content page.");
            emailDisplay.textContent = `Email: ${state.employee_email}`;
            showPage('content');
            startPolling();
            // Start minimized if already registered
            if (ipcRenderer) ipcRenderer.send('minimize-to-tray');
        } else if (validationResult === 'offline') {
            // Server down but we have local data? Try to show content anyway
            console.warn("Server offline, using cached data.");
            emailDisplay.textContent = `Email: ${state.employee_email} (Offline)`;
            showPage('content');
            startPolling();
            // Start minimized if already registered
            if (ipcRenderer) ipcRenderer.send('minimize-to-tray');
        } else {
            // Invalid/Deleted - go to login
            console.error("Registration invalid or expired.");
            const errorMsg = document.getElementById('login-error-msg');
            if (errorMsg) errorMsg.style.display = 'block';
            showPage('initial');
        }
    } else {
        console.log("No registration found. Showing initial page.");
        showPage('initial');
    }
}

function showPage(pageName) {
    if (pageName === 'initial') {
        initialPage.style.display = 'block';
        contentPage.style.display = 'none';
        if (ipcRenderer) ipcRenderer.send('show-window');
    } else {
        initialPage.style.display = 'none';
        contentPage.style.display = 'flex';
        renderHistory();
        if (state.all_content.length > 0) {
            displayContent(state.all_content[state.current_content_index]);
        }
    }
}

function loadSettings() {
    try {
        state.employee_id = localStorage.getItem('employee_id');
        state.employee_email = localStorage.getItem('employee_email');
        state.device_id = localStorage.getItem('device_id');

        if (!state.device_id) {
            state.device_id = crypto.randomUUID ? crypto.randomUUID() : 'dev-' + Math.random().toString(36).substr(2, 9);
            localStorage.setItem('device_id', state.device_id);
        }

        const processed = JSON.parse(localStorage.getItem('processed_content_ids') || '[]');
        state.processed_content_ids = new Set(processed);

        if (state.employee_id && ipcRenderer) {
            ipcRenderer.send('set-employee-id', state.employee_id);
        }

        state.viewed_durations = JSON.parse(localStorage.getItem('viewed_durations') || '{}');
    } catch (e) {
        console.error('Error loading settings:', e);
    }
}

function saveSettings() {
    try {
        if (state.employee_id) localStorage.setItem('employee_id', state.employee_id);
        if (state.employee_email) localStorage.setItem('employee_email', state.employee_email);
        if (state.device_id) localStorage.setItem('device_id', state.device_id);

        localStorage.setItem('processed_content_ids', JSON.stringify(Array.from(state.processed_content_ids)));
        localStorage.setItem('viewed_durations', JSON.stringify(state.viewed_durations));
    } catch (e) {
        console.error('Error saving settings:', e);
    }
}

function setupEventListeners() {
    const msLoginBtn = document.getElementById('ms-login-button');
    if (msLoginBtn) {
        msLoginBtn.addEventListener('click', startMsLogin);
    }

    const prevBtn = document.getElementById('prev-btn');
    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            if (state.current_content_index > 0) {
                state.current_content_index--;
                displayContent(state.all_content[state.current_content_index]);
            }
        });
    }

    const nextBtn = document.getElementById('next-btn');
    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            if (state.current_content_index < state.all_content.length - 1) {
                state.current_content_index++;
                displayContent(state.all_content[state.current_content_index]);
            }
        });
    }

    const minimizeBtn = document.getElementById('minimize-btn');
    if (minimizeBtn) {
        minimizeBtn.addEventListener('click', () => {
            if (ipcRenderer) ipcRenderer.send('minimize-to-tray');
        });
    }

    document.querySelectorAll('.reaction-btn-icon').forEach(btn => {
        btn.addEventListener('click', () => {
            const emoji_key = btn.dataset.emoji; // 'like', 'heart', etc.
            const emoji_char = btn.textContent.split(' ')[0];  // '👍', '❤️', etc. (ignore count text)
            const content = state.all_content[state.current_content_index];
            if (content) {
                sendReaction(emoji_key, content.id);
                animateReaction(emoji_char);
            }
        });
    });

    const submitFeedbackBtn = document.getElementById('submit-feedback');
    if (submitFeedbackBtn) {
        submitFeedbackBtn.addEventListener('click', () => {
            const feedbackEntry = document.getElementById('feedback-entry');
            const text = feedbackEntry ? feedbackEntry.value : "";
            const content = state.all_content[state.current_content_index];
            if (content && text) submitFeedback(text, content.id);
        });
    }

    const dialogOkBtn = document.getElementById('dialog-ok');
    if (dialogOkBtn) {
        dialogOkBtn.addEventListener('click', () => {
            const delayOptions = document.getElementById('delay-options');
            const delay = delayOptions ? delayOptions.value : "Play Immediate";
            const pendingContent = state.pendingContent;
            handleDelayChoice(pendingContent, delay);
            if (notificationDialog) notificationDialog.style.display = 'none';
        });
    }

    const zoomInBtn = document.getElementById('zoom-in');
    if (zoomInBtn) {
        zoomInBtn.addEventListener('click', () => {
            if (contentImage) {
                const currentScale = getScale();
                contentImage.style.transform = `scale(${currentScale + 0.2})`;
            }
        });
    }

    const zoomOutBtn = document.getElementById('zoom-out');
    if (zoomOutBtn) {
        zoomOutBtn.addEventListener('click', () => {
            if (contentImage) {
                const currentScale = getScale();
                contentImage.style.transform = `scale(${Math.max(0.2, currentScale - 0.2)})`;
            }
        });
    }

    if (stopButton) stopButton.addEventListener('click', toggleTimer);

    // Download, Fullscreen and Close Fullscreen listeners
    const downloadBtn = document.getElementById('download-btn');
    if (downloadBtn) {
        downloadBtn.addEventListener('click', () => {
            if (contentImage && contentImage.src) {
                downloadImage(contentImage.src);
            }
        });
    }

    const fullscreenBtn = document.getElementById('fullscreen-btn');
    const fullscreenOverlay = document.getElementById('fullscreen-overlay');
    const fullscreenImage = document.getElementById('fullscreen-image');
    if (fullscreenBtn && fullscreenOverlay && fullscreenImage) {
        fullscreenBtn.addEventListener('click', () => {
            if (contentImage && contentImage.src) {
                fullscreenImage.src = contentImage.src;
                fullscreenOverlay.style.display = 'flex';
            }
        });
    }

    const closeFullscreen = document.getElementById('close-fullscreen');
    if (closeFullscreen && fullscreenOverlay) {
        closeFullscreen.addEventListener('click', () => {
            fullscreenOverlay.style.display = 'none';
        });

        // Also close on background click
        fullscreenOverlay.addEventListener('click', (e) => {
            if (e.target === fullscreenOverlay) {
                fullscreenOverlay.style.display = 'none';
            }
        });
    }

    // Escape key to close fullscreen
    window.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && fullscreenOverlay && fullscreenOverlay.style.display === 'flex') {
            fullscreenOverlay.style.display = 'none';
        }
    });

    // Link handling for description
    if (messageDisplay) {
        messageDisplay.addEventListener('click', (e) => {
            const link = e.target.closest('a');
            if (link && (link.href.startsWith('http') || link.classList.contains('external-link'))) {
                e.preventDefault();
                if (ipcRenderer) {
                    ipcRenderer.send('open-edge', link.href);
                } else {
                    window.open(link.href, '_blank');
                }
            }
        });
    }

    // Network Status Monitoring
    window.addEventListener('online', () => {
        updateNetworkStatus();
        checkContent(); // Immediate retry on reconnect
    });
    window.addEventListener('offline', updateNetworkStatus);

    const statusBanner = document.getElementById('connection-status');
    if (statusBanner) {
        statusBanner.addEventListener('click', () => {
            statusBanner.classList.toggle('minimized');
        });
    }

    updateNetworkStatus(); // Initial check

    if (ipcRenderer) {
        ipcRenderer.on('notification-choice', (event, choice) => {
            if (state.pendingContent) {
                handleDelayChoice(state.pendingContent, choice);
            }
        });
    }
}

function updateNetworkStatus() {
    const statusBanner = document.getElementById('connection-status');
    const statusMsg = document.getElementById('status-msg');

    if (!navigator.onLine) {
        statusMsg.textContent = "I am AcornHUB, I can't get new messages, please connect to Wi-Fi.";
        statusBanner.classList.add('show');
        statusBanner.style.background = "#ff7675"; // Red for offline
    } else {
        // We are online, but we might still have server errors
        // We will hide the banner if polling succeeds
        if (state.last_poll_successful) {
            statusBanner.classList.remove('show');
        }
    }
}

function getScale() {
    if (!contentImage) return 1;
    const transform = contentImage.style.transform;
    const match = transform.match(/scale\(([\d.]+)\)/);
    return match ? parseFloat(match[1]) : 1;
}

async function downloadImage(url) {
    try {
        console.log("Starting download for:", url);
        const response = await fetch(url);
        const blob = await response.blob();
        const blobUrl = URL.createObjectURL(blob);

        const a = document.createElement('a');
        a.href = blobUrl;

        // Extract filename from URL or use a default
        let filename = 'downloaded_image.png';
        try {
            const urlPath = new URL(url).pathname;
            const parts = urlPath.split('/');
            const lastPart = parts[parts.length - 1];
            if (lastPart && lastPart.includes('.')) {
                filename = lastPart;
            }
        } catch (e) { }

        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(blobUrl);

        // Show success toast
        showToast("Image Download Started!");
    } catch (err) {
        console.error("Download failed:", err);
        showToast("Download Failed", true);
    }
}

// No showToast here, it's defined globally below

// API Calls (using Microsoft Auth)
async function startMsLogin() {
    try {
        let hostname = "Unknown";
        if (ipcRenderer) {
            hostname = await ipcRenderer.invoke('get-hostname');
        }

        const loginUrl = `${SERVER_URL}login_from_client?hostname=${encodeURIComponent(hostname)}`;
        if (ipcRenderer) {
            ipcRenderer.send('open-edge', loginUrl);
        } else if (shell) {
            shell.openExternal(loginUrl);
        } else {
            window.open(loginUrl, '_blank');
        }

        // Start polling for registration status
        document.getElementById('loading').style.display = 'flex';
        const pollStatus = setInterval(async () => {
            const registered = await checkRegistrationStatus(hostname);
            if (registered) {
                clearInterval(pollStatus);
                document.getElementById('loading').style.display = 'none';
                alert('Login Successful!');
                showPage('content');
                startPolling();
                // Auto-hide after successful registration
                if (ipcRenderer) ipcRenderer.send('minimize-to-tray');
            }
        }, REG_CHECK_INTERVAL);

    } catch (err) {
        console.error('MS Login initiation failed:', err);
    }
}

async function checkRegistrationStatus(hostname) {
    try {
        const response = await fetch(`${SERVER_URL}check_registration?hostname=${encodeURIComponent(hostname)}`);
        const data = await response.json();
        if (data.registered) {
            state.employee_id = data.employee_id;
            state.employee_email = data.email;
            state.registered = true;
            saveSettings();
            if (emailDisplay) emailDisplay.textContent = `Email: ${data.email}`;
            return true;
        }
        return false;
    } catch (err) {
        console.error('Check registration failed:', err);
        return false;
    }
}

async function validateExisting() {
    if (!state.employee_email || !state.employee_id) return 'invalid';
    try {
        const response = await fetch(`${SERVER_URL}content/${state.employee_id}`, {
            method: 'GET',
            headers: { 'Cache-Control': 'no-cache' }
        });

        if (response.ok) {
            state.registered = true;
            return 'valid';
        } else if (response.status === 404 || response.status === 401) {
            console.error('User not found on server, clearing registration');
            state.registered = false;
            state.employee_id = null;
            state.employee_email = null;
            saveSettings();
            return 'invalid';
        } else {
            // Other server errors (500, etc.) - treat as offline/temporary
            return 'offline';
        }
    } catch (err) {
        console.error('Server connection failed in validation:', err);
        return 'offline';
    }
}

async function registerDevice() {
    try {
        let hostname = "Unknown";
        if (ipcRenderer) {
            hostname = await ipcRenderer.invoke('get-hostname');
        }

        const data = {
            employee_id: state.employee_id,
            ip: 'unknown',
            device_type: `Windows (Electron)`,
            hostname: hostname,
            email: state.employee_email
        };

        await fetch(`${SERVER_URL}register_device`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    } catch (e) {
        console.error("Failed to register device", e);
    }
}

// Polling
function startPolling() {
    if (state.polling_timer) clearInterval(state.polling_timer);
    state.polling_timer = setInterval(checkContent, POLL_INTERVAL);
    checkContent();
}

async function checkContent() {
    if (!state.employee_id) return;
    const statusBanner = document.getElementById('connection-status');
    const statusMsg = document.getElementById('status-msg');

    try {
        const response = await fetch(`${SERVER_URL}content/${state.employee_id}`);
        if (!response.ok) throw new Error("Server Error: " + response.status);

        const resData = await response.json();
        const { content } = resData;

        state.last_poll_successful = true;
        if (navigator.onLine) statusBanner.classList.remove('show');

        const newMessages = content.filter(c =>
            !state.processed_content_ids.has(c.id) &&
            (state.viewed_durations[c.id] || 0) <= 30
        );

        let updated = false;
        content.forEach(c => {
            const existingIdx = state.all_content.findIndex(existing => existing.id === c.id);
            if (existingIdx === -1) {
                state.all_content.push(c);
                updated = true;
            } else {
                // Update reaction counts and user reaction for existing content
                state.all_content[existingIdx].reaction_counts = c.reaction_counts;
                state.all_content[existingIdx].user_reaction = c.user_reaction;

                // If this is the currently displayed message, refresh the reaction UI
                if (state.current_content_index === existingIdx) {
                    renderReactions(state.all_content[existingIdx]);
                }
            }
        });

        if (updated) {
            // Sort state.all_content descending by date so newest is always first
            state.all_content.sort((a, b) => {
                const dateA = new Date(a.scheduled_time || a.created_at);
                const dateB = new Date(b.scheduled_time || b.created_at);
                return dateB - dateA;
            });

            renderHistory();
        }

        // Sync employee ID to main process for update reporting
        if (state.employee_id && ipcRenderer) {
            ipcRenderer.send('set-employee-id', state.employee_id);
        }

        if (newMessages.length > 0) {
            const msg = newMessages[0];
            const pref = await checkPreference(msg.id);

            // Check if pref actually contains data (display_time)
            if (pref && pref.display_time) {
                const displayTime = new Date(pref.display_time);
                if (displayTime <= new Date()) {
                    notifyNewContent(msg, true);
                }
            } else {
                // If pref is null or an empty object {}, show the delay dialog
                notifyNewContent(msg, false);
            }
        }

        // Heartbeat
        await fetch(`${SERVER_URL}update_status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                employee_id: state.employee_id,
                status: "online",
                app_running: true,
                email: state.employee_email,
                device_id: state.device_id,
                current_version: APP_VERSION
            })
        });

    } catch (err) {
        console.error('Polling error', err);
        state.last_poll_successful = false;

        if (navigator.onLine) {
            statusMsg.textContent = "I am AcornHUB, Server communication failed. Retrying...";
            statusBanner.style.background = "#fdcb6e"; // Orange for server error
            statusBanner.classList.add('show');
        } else {
            updateNetworkStatus(); // Ensure offline message is shown
        }
    }
}

async function checkPreference(contentId) {
    try {
        const response = await fetch(`${SERVER_URL}message_preferences/${state.employee_id}/${contentId}`);
        const data = await response.json();
        return data && data.preference ? data.preference : null;
    } catch {
        return null;
    }
}

function notifyNewContent(content, immediate) {
    if (state.notified_ids.has(content.id) && !immediate) return;

    if (immediate) {
        if (ipcRenderer) ipcRenderer.send('show-window');
        displayContent(content);
    } else {
        state.pendingContent = content;
        if (ipcRenderer) {
            ipcRenderer.send('show-notification');
            state.notified_ids.add(content.id);
        } else {
            // Fallback for non-electron environments
            if (notificationDialog) notificationDialog.style.display = 'flex';
        }
    }
}

async function handleDelayChoice(content, choice) {
    let delayMs = 0;
    if (choice.includes("15 minutes")) delayMs = 15 * 60 * 1000;
    else if (choice.includes("30 minutes")) delayMs = 30 * 60 * 1000;
    else if (choice.includes("1 hour")) delayMs = 60 * 60 * 1000;
    else if (choice.includes("3 hours")) delayMs = 3 * 60 * 60 * 1000;

    const displayTime = new Date(Date.now() + delayMs).toISOString();
    try {
        await fetch(`${SERVER_URL}set_message_delay`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                employee_id: state.employee_id,
                content_id: content.id,
                delay_choice: choice,
                display_time: displayTime
            })
        });
    } catch (e) {
        console.error('Failed to set delay', e);
    }

    if (delayMs === 0) {
        if (ipcRenderer) ipcRenderer.send('show-window');
        displayContent(content);
    } else {
        if (ipcRenderer) ipcRenderer.send('minimize-to-tray');
        // Restore visibility of main UI in the background so it's ready for manual re-opening
        if (contentPage) contentPage.style.display = 'flex';

        setTimeout(() => {
            notifyNewContent(content, true);
        }, delayMs);
    }
}

function displayContent(content) {
    if (!content) return;

    // Update current index for other operations (reactions/feedback)
    const idx = state.all_content.findIndex(c => c.id === content.id);
    if (idx !== -1) {
        state.current_content_index = idx;
    }

    // Show main interface if it was hidden by delay dialog
    if (contentPage) contentPage.style.display = 'flex';
    if (notificationDialog) notificationDialog.style.display = 'none';

    state.processed_content_ids.add(content.id);
    saveSettings();

    // Render title and text (with auto-links)
    if (titleLabel) titleLabel.textContent = content.title || 'No Title';
    if (titleDisplay) titleDisplay.textContent = content.title || 'No Title';

    if (messageDisplay) {
        const rawText = content.text || '';
        // Auto-link URLs
        const urlRegex = /(https?:\/\/[^\s]+)/g;
        const linkedText = rawText.replace(urlRegex, (url) => `<a href="${url}" class="external-link">${url}</a>`);
        messageDisplay.innerHTML = linkedText;
    }

    // Update reactions UI
    renderReactions(content);

    const mediaContainer = document.getElementById('media-container');
    const rightPane = document.querySelector('.right-pane');
    const leftPane = document.querySelector('.left-pane');

    if (videoPlayer) {
        videoPlayer.style.display = 'none';
        videoPlayer.pause();
    }
    if (imageViewer) imageViewer.style.display = 'none';

    if (content.type === 'video' || content.type === 'both' || content.image_url) {
        // Media exists
        if (rightPane) rightPane.style.display = 'flex';
        if (leftPane) leftPane.style.flex = '1';

        if (content.type === 'video' || content.type === 'both') {
            if (mediaContainer) mediaContainer.style.display = 'flex';
            if (videoPlayer) {
                videoPlayer.style.display = 'block';
                videoPlayer.src = content.url;
                videoPlayer.muted = true;
                videoPlayer.play();
                videoPlayer.onloadedmetadata = () => {
                    state.countdown_seconds = Math.floor(videoPlayer.duration) + 30;
                    startCountdown();
                };
            }
        } else if (content.image_url) {
            if (mediaContainer) mediaContainer.style.display = 'flex';
            if (imageViewer) {
                imageViewer.style.display = 'flex';
                if (contentImage) contentImage.src = content.image_url;
                state.countdown_seconds = 60;
                startCountdown();
            }
        }
    } else {
        // Text Only
        if (rightPane) rightPane.style.display = 'none';
        if (leftPane) leftPane.style.flex = '1'; // Takes full width now
        if (mediaContainer) mediaContainer.style.display = 'none';
        state.countdown_seconds = 60;
        startCountdown();
    }

    state.view_start_time = Date.now();
    setTimeout(() => recordView(content.id), 30000);

    renderHistory();
}

function renderHistory() {
    if (!historyList) return;
    historyList.innerHTML = '';
    state.all_content.forEach((c) => {
        const item = document.createElement('div');
        item.className = 'history-item';

        // Highlight active message
        const currentContent = state.all_content[state.current_content_index];
        if (currentContent && currentContent.id === c.id) {
            item.classList.add('active');
        }

        const createdDate = new Date(c.created_at || Date.now());
        const timeStr = createdDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const dateStr = createdDate.toLocaleDateString();

        item.innerHTML = `
            <div class="history-title">${c.title || 'Message ' + c.id}</div>
            <div class="history-meta">
                <span>${timeStr} | ${dateStr}</span>
                <span class="status-icon ${(state.viewed_durations[c.id] || 0) > 30 ? 'status-ok' : 'status-pending'}">
                    ${(state.viewed_durations[c.id] || 0) > 30 ? 'Viewed' : 'View Pending'}
                </span>
            </div>
        `;
        item.onclick = () => {
            // Find its new index in the sorted list
            const newIndex = state.all_content.findIndex(msg => msg.id === c.id);
            if (newIndex !== -1) {
                state.current_content_index = newIndex;
                displayContent(c);
            }
        };
        historyList.appendChild(item);
    });
}

function startCountdown() {
    if (countdownLabel) countdownLabel.textContent = state.countdown_seconds;
    if (state.countdown_timer) clearInterval(state.countdown_timer);

    state.countdown_timer = setInterval(() => {
        state.countdown_seconds--;
        if (countdownLabel) countdownLabel.textContent = state.countdown_seconds;
        if (state.countdown_seconds <= 0) {
            clearInterval(state.countdown_timer);
            if (ipcRenderer) ipcRenderer.send('minimize-to-tray');
        }
    }, 1000);
}

function toggleTimer() {
    if (state.countdown_timer) {
        clearInterval(state.countdown_timer);
        state.countdown_timer = null;
        if (stopButton) stopButton.innerHTML = '<i class="fas fa-play"></i>';
    } else {
        startCountdown();
        if (stopButton) stopButton.innerHTML = '<i class="fas fa-stop"></i>';
    }
}

async function sendReaction(emoji, contentId) {
    console.log(`Sending reaction: ${emoji} for content: ${contentId} (user: ${state.employee_id})`);

    // Optimistic UI update
    const content = state.all_content.find(c => c.id === contentId);
    if (content) {
        if (content.reaction_counts) {
            // Remove old count if user reaction changed
            if (content.user_reaction && content.reaction_counts[content.user_reaction] > 0) {
                content.reaction_counts[content.user_reaction]--;
            }
            content.reaction_counts[emoji] = (content.reaction_counts[emoji] || 0) + 1;
        }
        content.user_reaction = emoji;
        renderReactions(content);
    }

    try {
        const response = await fetch(`${SERVER_URL}reaction`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                employee_id: state.employee_id,
                content_id: contentId,
                reaction: emoji
            })
        });
        const result = await response.json();
        console.log('Reaction response:', result);

        // Final sync with server after a short delay
        setTimeout(checkContent, 1000);
    } catch (e) {
        console.error('Failed to send reaction:', e);
    }
}

function renderReactions(content) {
    const counts = content.reaction_counts || {};
    const userReact = content.user_reaction;

    document.querySelectorAll('.reaction-btn-icon').forEach(btn => {
        const emoji = btn.dataset.emoji;
        const countSpan = btn.querySelector('.count');

        // Update count text
        if (countSpan) {
            countSpan.textContent = counts[emoji] || 0;
        }

        // Toggle active state
        if (emoji === userReact) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
}

async function submitFeedback(text, contentId) {
    try {
        await fetch(`${SERVER_URL}feedback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                employee_id: state.employee_id,
                content_id: contentId,
                feedback: text
            })
        });
        const feedbackEntry = document.getElementById('feedback-entry');
        if (feedbackEntry) feedbackEntry.value = '';
        showToast('Feedback Sent Successfully!');
    } catch (e) {
        showToast('Failed to submit feedback');
    }
}

function showToast(message, isError = false) {
    const toast = document.getElementById('success-toast');
    if (toast) {
        const span = toast.querySelector('span');
        const icon = toast.querySelector('i');
        if (span) span.textContent = message;
        if (icon) {
            icon.className = isError ? 'fas fa-exclamation-circle' : 'fas fa-check-circle';
            // These styles should ideally be in CSS, but for speed we set them here or rely on the CSS
            icon.style.color = isError ? '#d9534f' : '#43a047';
        }

        // Dynamic colors for error vs success
        toast.style.background = isError ? '#fdecea' : '#e8f5e9';
        toast.style.color = isError ? '#d9534f' : '#2e7d32';
        toast.style.borderColor = isError ? '#f5c6cb' : '#c8e6c9';

        toast.classList.add('show');
        setTimeout(() => {
            toast.classList.remove('show');
        }, 3000);
    }
}

function animateReaction(emoji) {
    const container = document.body;
    const particleCount = 40; // More particles for a better 'rain' feel

    for (let i = 0; i < particleCount; i++) {
        const particle = document.createElement('div');
        particle.className = 'reaction-particle';
        particle.textContent = emoji;

        // Random horizontal position across the full width
        particle.style.left = Math.random() * 100 + 'vw';

        // Randomize falling duration between 2s and 4s
        const duration = 2 + Math.random() * 2;
        particle.style.animationDuration = duration + 's';

        // Stagger the start times over 2 seconds
        particle.style.animationDelay = Math.random() * 2 + 's';

        // Randomize font size for variety
        particle.style.fontSize = (24 + Math.random() * 30) + 'px';

        container.appendChild(particle);

        // Remove particle after its unique animation duration + delay is finished
        setTimeout(() => {
            particle.remove();
        }, (duration + 2) * 1000);
    }
}

async function recordView(contentId) {
    if (!state.view_start_time) return;
    const duration = (Date.now() - state.view_start_time) / 1000;
    state.viewed_durations[contentId] = Math.max(state.viewed_durations[contentId] || 0, duration);
    saveSettings();

    try {
        await fetch(`${SERVER_URL}record_view`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                employee_id: state.employee_id,
                content_id: contentId,
                viewed_duration: duration,
                timestamp: new Date().toISOString()
            })
        });
    } catch (e) { console.error(e); }

    renderHistory();
}

function setupTitleBar() {
    const closeBtn = document.getElementById('title-bar-close');
    const minBtn = document.getElementById('title-bar-minimize');
    const maxBtn = document.getElementById('title-bar-maximize');

    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            if (ipcRenderer) ipcRenderer.send('minimize-to-tray');
        });
    }

    if (minBtn) {
        minBtn.addEventListener('click', () => {
            if (ipcRenderer) ipcRenderer.send('minimize-window');
        });
    }

    if (maxBtn) {
        maxBtn.addEventListener('click', () => {
            if (ipcRenderer) ipcRenderer.send('maximize-window');
        });

        if (ipcRenderer) {
            ipcRenderer.on('window-maximized', () => {
                maxBtn.innerHTML = '<i class="fas fa-compress-alt"></i>';
            });
            ipcRenderer.on('window-unmaximized', () => {
                maxBtn.innerHTML = '<i class="fas fa-expand-alt"></i>';
            });
        }
    }
}

// --- Auto-Update Logic ---

async function checkForUpdates() {
    console.log("Checking for updates...");
    try {
        const response = await fetch(`${SERVER_URL}updates/version`);
        if (!response.ok) return;

        const serverVersion = (await response.text()).trim();
        console.log(`Server version: ${serverVersion}, Local version: ${APP_VERSION}`);

        if (compareVersions(serverVersion, APP_VERSION) > 0) {
            console.log(`Update available: ${serverVersion}`);
            if (confirm(`A new version (${serverVersion}) is available. Update now?`)) {
                downloadAndInstall(serverVersion);
            }
        }
    } catch (e) {
        console.error("Error checking for updates:", e);
    }
}

function compareVersions(v1, v2) {
    const p1 = v1.split('.').map(Number);
    const p2 = v2.split('.').map(Number);
    for (let i = 0; i < Math.max(p1.length, p2.length); i++) {
        const n1 = p1[i] || 0;
        const n2 = p2[i] || 0;
        if (n1 > n2) return 1;
        if (n1 < n2) return -1;
    }
    return 0;
}

async function downloadAndInstall(version) {
    const debugStatus = document.getElementById('debug-status');
    if (debugStatus) {
        debugStatus.textContent = "Downloading Update...";
        debugStatus.style.color = "blue";
    }

    try {
        updateUpdateStatus(version, 'pending');

        const response = await fetch(`${SERVER_URL}updates/app`);
        if (!response.ok) throw new Error("Download failed");

        const buffer = await response.arrayBuffer();
        const tempPath = path.join(os.tmpdir(), `app_installer_${version}.exe`);

        fs.writeFileSync(tempPath, Buffer.from(buffer));
        console.log("Installer downloaded to:", tempPath);

        if (debugStatus) debugStatus.textContent = "Installing...";

        updateUpdateStatus(version, 'downloaded');

        const subprocess = spawn(tempPath, [], {
            detached: true,
            stdio: 'ignore'
        });
        subprocess.unref(); // Allow parent to exit independent of child

        setTimeout(() => {
            if (ipcRenderer) ipcRenderer.send('app-quit');
        }, 1000);

    } catch (e) {
        console.error("Update failed:", e);
        if (debugStatus) {
            debugStatus.textContent = "Update Error: " + e.message;
            debugStatus.style.color = "red";
        }
        alert("Failed to download update: " + e.message);
        updateUpdateStatus(version, 'failed', e.message);
    }
}

async function updateUpdateStatus(version, status, errorMsg = null) {
    if (!state.employee_id) return;
    try {
        await fetch(`${SERVER_URL}update_status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                employee_id: state.employee_id,
                device_id: state.device_id,
                current_version: APP_VERSION,
                update_status: status, // This field needs to be handled by server if not already
                error_message: errorMsg,
                target_version: version // Server might not use this but good for logging
            })
        });
    } catch (e) { console.error("Failed to report status", e); }
}

// Start
try {
    console.log("Starting renderer...");
    // Verify update check
    checkForUpdates();
    init();
} catch (e) {
    console.error("Critical error in init:", e);
    const debugStatus = document.getElementById('debug-status');
    if (debugStatus) debugStatus.textContent = "JS Error: " + e.message;
    alert("App failed to start. Check console (F12). Error: " + e.message);
}
