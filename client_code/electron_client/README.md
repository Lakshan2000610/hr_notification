# HR Notification Client - Electron

This is the Electron version of the client application, replicating the functionality of `client_code/new_work_final_client_copy.py`.

## Setup

1.  Make sure you have [Node.js](https://nodejs.org/) installed.
2.  Open a terminal in this directory:
    ```bash
    cd "e:\hr_notification - Copy\client_code\electron_client"
    ```
3.  Install dependencies (if not already installed):
    ```bash
    npm install
    ```

## Running the App

1.  Start the application:
    ```bash
    npm start
    ```

## Structure

-   `main.js`: Main process handling window creation, tray icon, and registry auto-start.
-   `renderer.js`: Frontend logic handling API calls, polling, and UI updates.
-   `index.html`: The user interface.
-   `styles.css`: Styling matching the Python application.
-   `assets/`: Icons and images.

## Features

-   **Auto-Start**: Adds itself to Windows Registry on first run.
-   **System Tray**: Runs in the background, minimizes to tray.
-   **Notifications**: Polls the server for new messages.
-   **Message Display**: Shows messages with support for images and videos.
-   **Feedback**: Allows submitting feedback and reactions.
-   **View Tracking**: Records view durations and syncs with the server.
