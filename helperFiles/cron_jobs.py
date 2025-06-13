import os
from datetime import datetime, timedelta, timezone as tzn
from authorization.creds import *
from authorization.auth import check_key_rotation_needed
from helperFiles.helpers import send_whatsapp_message
import time
import requests

def check_key_rotation():
    """
    Standalone function to check if key rotation is needed.
    This can be called by a scheduler or cron job.
    """
    print(f"########### Running scheduled key rotation check at {datetime.now(tzn.utc)}", flush=True)
    
    # Check if key rotation is needed
    rotation_needed = check_key_rotation_needed(TWILIO_PHONE_NUMBER)
    
    # If rotation is needed, notify admin
    if rotation_needed:
        try:
            # Send notification to admin
            send_whatsapp_message(
                f"whatsapp:{ADMIN_NUMBER}", 
                "🔐 SECURITY ALERT: Encryption key rotation needed! Please rotate your encryption keys as soon as possible.",
                TWILIO_PHONE_NUMBER
            )
        except Exception as e:
            print(f"########### Error sending key rotation notification: {e}", flush=True)
    
    # Update the last check date
    os.environ['LAST_KEY_ROTATION_CHECK_DATE'] = datetime.now(tzn.utc).strftime('%Y-%m-%d')
    
    return rotation_needed

def run_scheduler():
    """
    Run the scheduler in a loop, checking for key rotation once per day.
    This function is designed to be run as a background process on Render.
    """
    print(f"########### Starting key rotation scheduler at {datetime.now(tzn.utc)}", flush=True)
    
    while True:
        try:
            # Get current date
            today = datetime.now(tzn.utc).strftime('%Y-%m-%d')
            last_check_date = os.environ.get('LAST_KEY_ROTATION_CHECK_DATE', '')
            
            # Only check once per day
            if last_check_date != today:
                print(f"########### Running daily key rotation check on {today}", flush=True)
                check_key_rotation()
            
            # Sleep for 1 hour before checking again
            time.sleep(3600)  # 3600 seconds = 1 hour
            
        except Exception as e:
            print(f"########### Error in scheduler: {e}", flush=True)
            # Sleep for 5 minutes before retrying after an error
            time.sleep(300)

def ping_self():
    """
    Function to ping the application itself to keep it alive on Render.
    This is useful for free tier Render services that sleep after inactivity.
    """
    app_url = os.environ.get("APP_URL")
    if app_url:
        try:
            response = requests.get(app_url)
            print(f"########### Ping self status: {response.status_code}", flush=True)
        except Exception as e:
            print(f"########### Error pinging self: {e}", flush=True)

# if __name__ == "__main__":
#     # This allows the script to be run directly
#     check_key_rotation()
