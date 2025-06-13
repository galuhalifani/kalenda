from __future__ import print_function
import sys
import os
from threading import Thread
import pandas as pd
from pymongo import MongoClient
from openai import OpenAI
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import os.path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from datetime import datetime, timezone as tzn
from authorization.creds import *
from services.database import check_timezone
from helperFiles.helpers import send_error_whatsapp_message, parse_voice,send_whatsapp_message, check_input_not_none
from helperFiles.sentry_helper import set_sentry_context
from services.calendar_service import get_user_calendar_timezone, get_calendar_service
from helperFiles.session_memory import get_latest_memory
from prompts.prompt_full import prompt_init, prompt_analyzer, prompt_finder, prompt_refactored
from helperFiles.redis_helper import get_latest_chat_and_draft_redis

if mode == 'test':
    os.environ["SSL_CERT_FILE"] = os.environ.get("SSL_CERT_FILE")

def init_openai():
    try:
        client = OpenAI()
        print("✅ OpenAI client initialized", flush=True)
        return client
    except Exception as e:
        print(f"❌ Error initializing OpenAI client: {e}", flush=True)
        set_sentry_context(None, None, None, f"Error in init_openai function: OpenAI client initialization failed", e)
        return None
    
def init_params(user_id, is_test=False, twilio_number=TWILIO_PHONE_NUMBER):
    service = get_calendar_service(user_id, is_test)
    now_utc = datetime.now(tzn.utc)    
    cal_timezone = get_user_calendar_timezone(user_id, is_test, service)
    user_timezone = check_timezone(user_id, cal_timezone)

    # Check if there's a credential error
    if (service == "credential_error" or service == "token_revoked") and not is_test:
        return {"service": service, "now_utc": now_utc, "user_timezone": user_timezone, "error": "Your calendar access has expired or been revoked. Please type 'login' to reconnect your Google Calendar."}
    elif (service == "credential_error" or service == "token_revoked") and is_test:
        send_whatsapp_message(ADMIN_NUMBER, "Test calendar access expired or revoked for user: " + user_id, twilio_number)
        return {"service": service, "now_utc": now_utc, "user_timezone": user_timezone, "error": "Your calendar access has expired or been revoked. Please contact administrator to re-authenticate test calendar."}

    return {"service": service, "now_utc": now_utc, "user_timezone": user_timezone, "error": None}

def init_llm(user_id, input, prompt_type, image_data_url=None, user_timezone=None, voice_data_filename=None, other_files=None):
    print(f"############ Initialized with {mode} mode", flush=True)
    try:
        print(f"########### Timezone: {user_timezone}", flush=True)
        try:
            latest_conversations, user_latest_event_draft = get_latest_chat_and_draft_redis(user_id) 
        except Exception as e:
            print(f"########### Error retrieving latest chat and draft from redis: {e}", flush=True)
            latest_conversations, user_latest_event_draft = get_latest_memory(user_id)

        now_utc = datetime.now(tzn.utc)

        client = init_openai()
        if not client:
            return "Sorry, I couldn't connect to the OpenAI service. Please try again later."
        
        if voice_data_filename:
            input = parse_voice(voice_data_filename, client)
            
        check_input_not_none(input, image_data_url)

        print(f"########### Processing with prompt {prompt_type}", flush=True)

        if prompt_type == 'main':   
            prompt = prompt_init(input, now_utc, user_timezone, user_latest_event_draft, latest_conversations)
        elif prompt_type == 'schedule_analyzer':
            prompt = prompt_analyzer(input, now_utc, user_timezone, user_latest_event_draft, latest_conversations, other_files)
        elif prompt_type == 'keyword_finder':
            prompt = prompt_finder(input, now_utc, user_timezone, user_latest_event_draft, latest_conversations, other_files)
        elif prompt_type == 'refactored':
            prompt = prompt_refactored(input, now_utc, user_timezone, user_latest_event_draft, latest_conversations)
        else:
            prompt = prompt_init(input, now_utc, user_timezone, user_latest_event_draft, latest_conversations)

        messages=[{
                'role': 'user',
                'content': [
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
    
        print(f"########### Prompt used: {prompt}", flush=True)
        
        if image_data_url:
            set_sentry_context(user_id, image_data_url, None, f"Entering LLM with Image data URL", None)
            messages[0]['content'].append({
                "type": "image_url",
                "image_url": {"url": image_data_url}
        })
            
        llm = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0,
            max_tokens=1000
        )

        response = llm.choices[0].message.content
        print(f"########### LLM response: {response}", flush=True)
        return response
    except Exception as e:
        print(f"########### Error in LLM: {str(e)}", flush=True)
        set_sentry_context(user_id, input, None, f"Error in init_llm function: LLM processing failed", e)
        return "Sorry, I couldn't process your request. Please try again."
