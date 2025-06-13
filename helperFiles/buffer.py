from datetime import datetime, timezone as tzn
import threading
from collections import defaultdict

message_buffer = defaultdict(list)  # user_id -> list of messages
timers = {}          # user_id -> Timer

from helperFiles.helpers import send_error_whatsapp_message
from helperFiles.sentry_helper import set_sentry_context

def handle_message(
    resp,
    user,
    user_id,
    record_user_id,
    incoming_msg,
    is_test,
    twilio_number,
    is_assistant,
    start_process,
    image_data_url=None,
    voice_data_filename=None,
    prompt_type='main'
):
    try:
        now = datetime.now(tzn.utc)
        message = {"incoming_msg": incoming_msg, "image_data_url": image_data_url, "voice_data_filename": voice_data_filename, "timestamp": now}

        message_buffer[user_id].append(message)

        # Cancel previous timer if exists
        if user_id in timers:
            timers[user_id].cancel()

        # Start a new 2-second timer with all args
        timers[user_id] = threading.Timer(
            2,
            process_buffered_messages,
            args=[
                resp,
                user,
                user_id,
                record_user_id,
                is_test,
                twilio_number,
                is_assistant,
                start_process,
                prompt_type
            ]
        )
        timers[user_id].start()
        print(f"[BUFFER] Queued message for {user_id} at {now.isoformat()}: text={bool(incoming_msg)}, image={bool(image_data_url)}, voice={bool(voice_data_filename)}")
    except Exception as e:
        print(f"[BUFFER] Error in handle_message: {e}", flush=True)
        set_sentry_context(user_id, incoming_msg, None, f"Error in handle_message function: Failed to queue message", e)

def process_buffered_messages(
    resp,
    user,
    user_id,
    record_user_id,
    is_test,
    twilio_number,
    is_assistant,
    start_process,
    prompt_type='main'
):
    try:
        messages = message_buffer.pop(user_id, [])
        if not messages:
            return # nothing to process
        
        timers.pop(user_id, None)

        text_messages = " ".join(m["incoming_msg"] for m in messages if m["incoming_msg"])
        image_data_url = next((m["image_data_url"] for m in reversed(messages) if m["image_data_url"]), None)
        voice_data_filename = next((m["voice_data_filename"] for m in reversed(messages) if m["voice_data_filename"]), None)

        return start_process(
            resp, user, user_id, record_user_id,
            text_messages, is_test, image_data_url, voice_data_filename,
            twilio_number, is_assistant, prompt_type
        )
    except Exception as e:
        print(f"[BUFFER] Error in process_buffered_messages: {e}", flush=True)
        set_sentry_context(user_id, None, None, f"Error in process_buffered_messages function: Failed to process messages", e)
        return ''
