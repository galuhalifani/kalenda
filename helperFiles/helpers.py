import os
from datetime import datetime, timedelta, timezone as tzn
import re
import requests
import base64
from requests.auth import HTTPBasicAuth
import re
from authorization.creds import *
import pytz
from twilio.rest import Client as TwilioClient
import time
import uuid
import json
from flask import render_template_string, render_template
import markdown
import cloudinary
import cloudinary.uploader
from io import BytesIO

def trim_reply(reply_text):
    max_length=1400
    split = [reply_text[i:i+max_length] for i in range(0, len(reply_text), max_length)]
    trimmed_reply = split[0]
    reply_text = f"Your list is too long, I can only show partial results. For more complete list, please specify a shorter date range.\n\n {trimmed_reply}"
    return reply_text

def clean_instruction_block(instruction):
    instruction = instruction.replace("```json", "").replace("```", "").strip()
    return instruction

def readable_date(date_str, is_datetime=None, with_timezone=True):
    try:
        date = datetime.fromisoformat(date_str)

        if is_datetime:
            transformed = date.strftime("%a, %d %b %Y %H:%M %Z") if with_timezone else date.strftime("%a, %d %b %Y %H:%M")
        else:
            transformed = date.strftime("%a, %d %b %Y")

        return transformed
    except ValueError:
        return date_str
    
def format_event_datetime(start_date_str, end_date_str):
    """
    Formats event date and time in a more readable format based on whether dates are the same or different.
    
    Args:
        start_date_str (str): ISO format start date string
        end_date_str (str): ISO format end date string
        
    Returns:
        str: Formatted date and time string in one of these formats:
            - "Fri, 27 Jun 2025, 00:00 - 01:00 (UTC+7)" (if same date)
            - "Fri, 27 Jun 00:00 - Sat, 28 Jun 01:00 2025 (UTC+7)" (if different date but same year)
            - "Fri, 27 Jun 2025, 00:00 - Sat, 28 Jul 2026, 01:00 (UTC+7)" (if different year)
    """
    try:
        start_date = datetime.fromisoformat(start_date_str)
        end_date = datetime.fromisoformat(end_date_str)
        
        # Extract timezone information
        tz_info = start_date.tzinfo
        tz_str = f"UTC+{int(start_date.utcoffset().total_seconds() / 3600)}" if tz_info else "UTC"
        
        # Check if dates are the same, or if year/month/day differ
        same_date = (start_date.year == end_date.year and 
                     start_date.month == end_date.month and 
                     start_date.day == end_date.day)
        
        same_year = start_date.year == end_date.year
        
        if same_date:
            # Format: "Fri, 27 Jun 2025, 00:00 - 01:00 (UTC+7)"
            formatted = f"{start_date.strftime('%a, %d %b %Y')}, {start_date.strftime('%H:%M')} - {end_date.strftime('%H:%M')} ({tz_str})"
        elif same_year:
            # Format: "Fri, 27 Jun 00:00 - Sat, 28 Jun 01:00 2025 (UTC+7)"
            formatted = f"{start_date.strftime('%a, %d %b')} {start_date.strftime('%H:%M')} - {end_date.strftime('%a, %d %b')} {end_date.strftime('%H:%M')} {start_date.year} ({tz_str})"
        else:
            # Format: "Fri, 27 Jun 2025, 00:00 - Sat, 28 Jul 2026, 01:00 (UTC+7)"
            formatted = f"{start_date.strftime('%a, %d %b %Y')}, {start_date.strftime('%H:%M')} - {end_date.strftime('%a, %d %b %Y')}, {end_date.strftime('%H:%M')} ({tz_str})"
        
        return formatted
    except ValueError:
        # Return original strings if parsing fails
        return f"{start_date_str} - {end_date_str}"

def clean_description(text):
    cleaned = re.sub(r'<.*?>', '', text)
    return cleaned.strip()

def extract_phone_number(user_id):
    print(f"########### Extracting phone number from user_id: {user_id}", flush=True)

    if not user_id:
        raise ValueError("Unauthenticated. Please login again")
    
    phone_number = re.findall(r'\d+', user_id)
    if phone_number and len(phone_number) > 0:
        return phone_number[0]
    else:
        raise ValueError("Invalid user ID format. Phone number not found.")
    
def get_image_data_url(media_url, content_type, is_assistant=False):
    try:
        allowed_types = {"image/png", "image/jpeg", "image/gif", "image/webp"}
        if content_type not in allowed_types:
            print(f"❌ Unsupported image type: {content_type}")
            return "Only PNG, JPEG, GIF, or WEBP image formats are supported."
        
        response = requests.get(media_url, auth=HTTPBasicAuth(TWILIO_SID, TWILIO_AUTH_TOKEN))

        if is_assistant:
            print(f"########### Uploading image to Cloudinary: {media_url}", flush=True)
            # image_data_url = upload_image_to_imgbb(media_url, IMGBB_API_KEY, image_data)
            image_bytes = BytesIO(response.content)
            image_data_url = upload_to_cloudinary(image_bytes)
            is_accessible = is_image_accessible(image_data_url)
            print(f"########### Image accessible: {is_accessible}", flush=True)
        else:        
            image_data = base64.b64encode(response.content).decode('utf-8')
            image_data_url = f"data:{content_type};base64,{image_data}"       
        return image_data_url
    except Exception as e:
        raise Exception(f"Error fetching media: {e}")

def get_voice_data_url(media_url, content_type, user_id):
    response = requests.get(media_url, auth=HTTPBasicAuth(TWILIO_SID, TWILIO_AUTH_TOKEN))
    if not response.headers["Content-Type"].startswith("audio/"):
        print("❌ Response Content-Type not audio:", response.headers["Content-Type"])
        return "Invalid audio file."
    contentType = content_type.split("/")[-1]
    filename = f"{user_id}_{uuid.uuid4().hex}.{contentType}"  # e.g., input.ogg, input.m4a
    with open(filename, "wb") as f:
        f.write(response.content)
    return filename

def transcribe_audio(voice_data_filename, client):
    print(f"########### Transcribing audio file: {voice_data_filename}", flush=True)
    with open(voice_data_filename, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="text"
        )

    print(f"########### Transcription result: {transcript}", flush=True)
    return transcript
    
def split_message(text, max_length=1530):
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]
    
def convert_timezone(time_str, target_tz='Asia/Jakarta'):
    try:
        dt = datetime.fromisoformat(time_str)
        target_tz = pytz.timezone(target_tz)
        dt_converted = dt.astimezone(target_tz)
        return dt_converted.isoformat()
    except Exception as e:
        print(f"Error converting timezone: {e}")
        return None

def send_whatsapp_message(to, message, twilio_number_main=TWILIO_PHONE_NUMBER):
    twilio_number = twilio_number_main if mode == 'production' else TWILIO_PHONE_NUMBER_SANDBOX
    print(f"########### Sending WhatsApp message from: {twilio_number} to {to}: {message}", flush=True)
    try: 
        client = TwilioClient(TWILIO_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(
            from_=twilio_number,
            to=to,
            body=message
        )
        print(f"########### WhatsApp message sent successfully", flush=True)
        time.sleep(0.05) # Sleep to avoid rate limiting
    except Exception as e:
        print(f"########### Error sending WhatsApp message: {e}", flush=True)
        raise Exception("Error sending WhatsApp message")

EMAIL_REGEX = re.compile(r"^[^@]+@[^@]+\.[^@]+$")

def all_valid_emails(email_list):
    print(f"########### Checking email validity: {email_list}", flush=True)
    return all(EMAIL_REGEX.match(email) for email in email_list)

def extract_emails(args):
    cleaned = args[1].strip()
    if cleaned:
        match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', cleaned)
        if match:
            user_email = match.group(0)
            print(f"########### User email: {user_email}", flush=True)
            return user_email
        else:
            print("########### No email found in the text", flush=True)
            return None
        
def extract_json_block(text):
    start_index = text.find('{')
    if start_index == -1:
        return None

    brace_count = 0
    for i in range(start_index, len(text)):
        if text[i] == '{':
            brace_count += 1
        elif text[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                return text[start_index:i+1]
                
    return None

def parse_llm_answer(answer):
    try:
        is_answer_string = isinstance(answer, str)

        if not is_answer_string:
            answer = str(answer)
        
        clean_answer = answer.strip()

        if 'add_event:' in clean_answer:
            return 'add_event'
        elif 'draft_event:' in clean_answer:
            return 'draft_event'
        elif 'retrieve_event:' in clean_answer:
            return 'retrieve_event'
        elif 'timezone_set:' in clean_answer:
            return 'timezone_set'
        elif 'discard_draft' in clean_answer:
            return 'discard_draft'
        else:
            json_str = extract_json_block(clean_answer)
            if not json_str:
                print("########### No valid JSON block found", flush=True)
                return None
            
            try:
                event_details = json.loads(json_str)
                action = event_details.get('action', None)
                if action == 'add_event':
                    return 'add_event'
                elif action == 'draft_event':
                    return 'draft_event'
                elif action == 'retrieve_event':
                    return 'retrieve_event'
                elif action == 'retrieve_free_time':
                    return 'retrieve_event'
                elif action == 'timezone_set':
                    return 'timezone_set'
                elif action == 'discard_draft':
                    return 'discard_draft'
                else:
                    return None
            except json.JSONDecodeError as e:
                print(f"########### Malformed JSON block: {e}", flush=True)
                print(f"########### JSON string: {json_str}", flush=True)
                return None
        
    except Exception as e:
        print(f"########### Error parsing LLM answer: {e}", flush=True)
        return None
    
def render_markdown_page(filepath, title):
    with open(filepath, "r", encoding="utf-8") as f:
        md_content = f.read()
        html_content = markdown.markdown(md_content)
    return render_template_string("""
    <html>
    <head><title>{{ title }}</title></head>
    <body>{{ content|safe }}</body>
    </html>
    """, title=title, content=html_content)

def parse_voice(voice_data_filename, client):
    """
    Parse the voice data filename to extract the actual filename.
    Ensures temporary files are cleaned up after use.
    """
    if not voice_data_filename:
        return None

    transcription = ""
    try:
        print(f"########### Entering with Voice data filename: {voice_data_filename}", flush=True)
        transcription = transcribe_audio(voice_data_filename, client)
    except Exception as e:
        print(f"########### Error transcribing audio: {str(e)}", flush=True)
    finally:
        # Clean up the temporary file to prevent disk space leaks
        try:
            if os.path.exists(voice_data_filename):
                os.remove(voice_data_filename)
                print(f"########### Temporary file deleted: {voice_data_filename}", flush=True)
        except Exception as e:
            print(f"########### Error deleting temporary file: {str(e)}", flush=True)

    return transcription

def is_image_accessible(url):
    try:
        response = requests.get(url, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"[Image Check] Failed to access image: {e}")
        return False
    
def get_filenames(media_url, content_type, user_id, is_assistant=False):
    is_audio = False
    is_image = False

    if content_type:
        is_audio = bool(media_url) and content_type.startswith("audio/")
        is_image = bool(media_url) and content_type.startswith("image/")

    image_data_url = get_image_data_url(media_url, content_type, is_assistant) if is_image else None
    voice_data_filename = get_voice_data_url(media_url, content_type, user_id) if is_audio else None

    return is_audio, is_image, image_data_url, voice_data_filename

def upload_image_to_imgbb(media_url, imgbb_api_key, image_base64):
    """
    Downloads image from Twilio and uploads it to ImgBB. Returns new URL.
    """
    try:
        upload_url = "https://api.imgbb.com/1/upload"
        payload = {
            "key": imgbb_api_key,
            "image": image_base64,
            "expiration": 86400  # 1 day in seconds
        }
        upload_resp = requests.post(upload_url, data=payload)
        upload_data = upload_resp.json()

        if not upload_resp.ok or "data" not in upload_data:
            raise Exception(f"ImgBB upload failed: {upload_data}")

        return upload_data["data"]["url"]
    
    except Exception as e:
        print(f"########### ImgBB upload error: {str(e)}")
        return None

def upload_to_cloudinary(file_path_or_url, title=None):
    try:
        cloudinary.config(
            cloud_name=CLOUDINARY_CLOUD_NAME,
            api_key=CLOUDINARY_API_KEY,
            api_secret=CLOUDINARY_SECRET_KEY,
            secure=True
        )

        response = cloudinary.uploader.upload(
            file_path_or_url,
            folder="kalenda", 
            overwrite=True,
            resource_type="image"
        )
        print(f"[Cloudinary] Upload successful: {response['secure_url']}")
        return response['secure_url']
    except Exception as e:
        print(f"[Cloudinary] Upload failed: {e}")
        return None

def check_input_not_none(input, image_data_url):
    if input is None and image_data_url is None:
        print(f"########### Invalid input: {input}", flush=True)
        raise ValueError("Sorry, I couldn't understand your request. Please try again.")

def is_message_expired(data, client, thread_id):
    now = datetime.now(tzn.utc)
    for msg in data:
        created_at = msg.created_at

        message_time = datetime.fromtimestamp(created_at, tz=tzn.utc)
        if message_time.tzinfo is None:
            message_time = message_time.replace(tzinfo=tzn.utc)

        if now > message_time + timedelta(hours=24):
            client.beta.threads.messages.delete(thread_id=thread_id, message_id=msg.id)

    return False

def init_llm_helper(prompt, client):
    messages=[{
                'role': 'user',
                'content': [
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
    
    llm = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0,
            max_tokens=1000
        )

    response = llm.choices[0].message.content
    return response

def send_error_whatsapp_message(error_message):
    try:
        message = f"### ERROR LOG: {error_message}"
        send_whatsapp_message(ADMIN_NUMBER, message, TWILIO_PHONE_NUMBER_TEST)
    except Exception as e:
        print(f"########### Error sending error message to admin: {e}", flush=True)
