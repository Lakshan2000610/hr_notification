import requests

def verify_send_message_route():
    url = "https://hrnotification.acorngroup.lk/send_message"
    # We need to bypass login_required or provide a session
    # Since I'm running locally, I'll just check if the app is running and if the route exists
    try:
        # We can't easily authenticate via request without a lot of setup
        # But we can check if it redirects to login (which means the route exists and is protected)
        # instead of a 500 server error
        response = requests.get(url, allow_redirects=False)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 302:
            print("Route exists and redirects to login (Expected for protected route).")
        elif response.status_code == 200:
            print("Route returned 200 OK (Unexpected if not logged in, but better than 500).")
        elif response.status_code == 500:
            print("Route returned 500 Internal Server Error (Fix failed).")
        else:
            print(f"Route returned status: {response.status_code}")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    verify_send_message_route()
