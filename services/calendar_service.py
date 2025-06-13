from __future__ import print_function
import sys
import os
from threading import Thread
import pandas as pd
from pymongo import MongoClient
from openai import OpenAI
from dotenv import load_dotenv
import pytz
from twilio.rest import Client
import os.path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone as tzn
import json
from cryptography.fernet import Fernet
import secrets
import requests
import base64
from requests.auth import HTTPBasicAuth
import re
from authorization.creds import *
from services.database import user_collection, tokens_collection, add_update_timezone
from authorization.auth import decrypt_token, encrypt_token, save_token
from helperFiles.helpers import readable_date, convert_timezone, all_valid_emails, extract_json_block, init_llm_helper, format_event_datetime
from helperFiles.session_memory import latest_event_draft, get_user_memory, session_memories
from prompts.prompt_full import prompt_calendar_finder
from helperFiles.redis_helper import get_user_chat_redis, add_event_draft_redis, delete_user_draft_redis

def get_calendar_service(user_id, is_test=False):
    try:        
        is_using_test_account = is_test
        print(f"########### is_using_test_account: {is_using_test_account}", flush=True)

        userId = user_id if not is_using_test_account else "test_shared_calendar"
        user_token = tokens_collection.find_one({"user_id": userId})

        if not user_token:
            message = "User not authenticated. Type 'authenticate' to connect to your Google Calendar, or type 'authenticate test' to use joint testing calendar."
            raise Exception(message)
        
        access_token = user_token.get("access_token")
        refresh_token = user_token.get("refresh_token")
        client_id = user_token.get("client_id", CLIENT_ID)
        client_secret = user_token.get("client_secret", CLIENT_SECRET)
        token_expiry_str = user_token.get("expiry", None)
        print(f"########### token_expiry_str: {token_expiry_str}", flush=True)

        if token_expiry_str:
            token_expiry = datetime.fromisoformat(token_expiry_str)
            print(f"########### token_expiry: {token_expiry}", flush=True)

            if token_expiry.tzinfo is None:
                token_expiry = token_expiry.replace(tzinfo=tzn.utc)
                print(f"########### token_expiry with timezone: {token_expiry}", flush=True)
    
            is_token_expired = token_expiry < datetime.now(tzn.utc)
        else:
            is_token_expired = True

        creds = Credentials(
            token=decrypt_token(access_token),
            refresh_token=decrypt_token(refresh_token),
            token_uri=TOKEN_URI,
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )

        is_creds_expired = (creds.expired and creds.refresh_token) or (is_token_expired)
        
        if is_creds_expired:
            try:
                print("########### Token is expired, refreshing...", flush=True)
                creds.refresh(Request())
                
                # Store the updated token info
                updated_token = encrypt_token(creds.token)
                updated_expiry = creds.expiry.isoformat()
                
                if is_using_test_account:
                    result = tokens_collection.update_one(
                        {"user_id": "test_shared_calendar"},
                        {"$set": {
                            "access_token": updated_token, 
                            "expiry": updated_expiry
                        }}
                    )
                else:
                    result = tokens_collection.update_one(
                        {"user_id": user_id},
                        {"$set": {
                            "access_token": updated_token, 
                            "expiry": updated_expiry
                        }}
                    )
            except Exception as refresh_error:
                print(f"########### Error refreshing token: {str(refresh_error)}", flush=True)
                # Check if the error is related to invalid_grant (token revoked)
                if "invalid_grant" in str(refresh_error).lower():
                    # If the token has been revoked, we should delete it from the database so the user can re-authenticate
                    if not is_using_test_account:  # Don't delete test account tokens
                        tokens_collection.delete_one({"user_id": user_id})
                    return "token_revoked"
                raise
            
        service = build('calendar', 'v3', credentials=creds)
        print("########### Calendar service initialized {service}", flush=True)
        return service
    except Exception as e:
        print(f"########### Error initializing calendar service: {str(e)}", flush=True)
        
        # Check if the error is related to credentials
        error_str = str(e).lower()
        if any(term in error_str for term in ["credential", "auth", "token", "unauthorized", "permission", "access", "invalid"]):
            return "credential_error"
        
        return None
    
def get_user_calendar_timezone(user_id, is_test=False, service=None):
    try:
        if not service:
            service = get_calendar_service(user_id, is_test)

        calendar = service.calendars().get(calendarId='primary').execute()
        return calendar.get('timeZone') 
    except Exception as e:
        print(f"########### Error retrieving calendar timezone: {str(e)}")
        return 'Asia/Jakarta'  # Default timezone

def list_calendars(service):
    calendar_list = service.calendarList().list().execute()
    return calendar_list

def get_upcoming_events(instruction, user_id, is_test=False, service=None):
    is_action_in_instruction = 'retrieve_event:' in instruction
    json_str_raw = instruction.split('retrieve_event:')[1].strip() if is_action_in_instruction else instruction.strip()
    json_str = extract_json_block(json_str_raw)
    event_details = json.loads(json_str)
    is_period_provided = event_details.get('start', None) or event_details.get('end', None) or event_details.get('q', None)
    action = event_details.get('action', 'retrieve')

    print(f"############## IS PERIOD PROVIDED: {is_period_provided}", flush=True)

    request_timezone = event_details.get('timezone', None)

    print(f"########### Event details: {event_details}", flush=True)

    start = event_details.get('start', str(datetime.now(tzn.utc))).strip()
    end_raw = event_details.get('end', None)
    calendar_name_filter = event_details.get('calendar', None)
    q = event_details.get('q', None)

    is_start_not_none = bool(start)
    is_end_not_none = bool(end_raw)

    try:
        start = datetime.fromisoformat(start)
        if (start < datetime.now(tzn.utc)):
            start = datetime.now(tzn.utc)
    except ValueError:
        print(f"########### Invalid start date format: {start}", flush=True)
        start = datetime.now()

    end_timedelta = timedelta(days=2) if not q else timedelta(days=30)
    print(f"########### End timedelta: {end_timedelta}", flush=True)
    end = datetime.fromisoformat(end_raw) if is_end_not_none else (start + end_timedelta)
    
    start_str = start.isoformat()
    end_str = end.isoformat()

    if not service:
        service = get_calendar_service(user_id, is_test)

    print(f"########### Start ISO format: {start_str}, End ISO format: {end_str}", flush=True)

    try:
        calendars = list_calendars(service)
    except Exception as e:
        print(f"########### Error retrieving calendar list: {str(e)}")
        calendars = None

    all_events = []

    if not calendars:
        events_result = service.events().list(
            calendarId='primary', 
            timeMin=start_str,
            timeMax=end_str,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])
        print(f"########### Calendar events: {events}")

        if not events:
            print("No upcoming events found.")
            return ([], is_period_provided, request_timezone, action)
        else:
            for event in events:
                all_events.append(event)   
    else:
        for calendar in calendars['items']:
            is_primary = calendar.get('primary', False)
            print(f"########### Calendar: {calendar}", flush=True)
            calendar_id = calendar['id']
            calendar_name = 'primary' if is_primary else calendar['summary']

            if calendar_name_filter and (calendar_name.lower() != calendar_name_filter.lower()):
                continue
            
            print(f"########### fetching all events", flush=True)
            print(f"########### Calendar ID: {calendar_id}", flush=True)
            print(f"########### Start: {start_str}, End: {end_str}", flush=True)
            events_result = service.events().list(
                calendarId=calendar_id, 
                timeMin=start_str,
                timeMax=end_str,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])
            print(f"########### Calendar events: {events}")

            if not events:
                print("No upcoming events found.")
                continue
            else:
                for event in events:
                    all_events.append({
                        "calendar": 'primary' if is_primary else calendar['summary'],
                        **event
                    })
    
    if q:
        action = 'find_with_keyword'
        return (all_events, is_period_provided, request_timezone, action)
    
    return (all_events, is_period_provided, request_timezone, action)

def transform_events_to_text(eventList, user_timezone=None):
    print(f"########### Transforming events to text: {eventList}", flush=True)
    events, is_period_provided, request_timezone, action = eventList

    if not events:
        return "No upcoming events found."
    
    event_list = []
    calendar_list = []
    introduction = "Here is your events for today and tomorrow" if not is_period_provided else "Here are your events"

    tz_to_use = request_timezone if request_timezone else (user_timezone if user_timezone else 'default')
    
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        end = event['end'].get('dateTime', event['end'].get('date'))
        summary = event.get('summary', '(No Title)')
        description = event.get('description', '(No Description)')
        location = event.get('location', '')
        displayName = event.get('displayName', '')
        timezone = event['start'].get('timeZone', '') if tz_to_use == 'default' else tz_to_use
        calendar = event.get('calendar', 'primary')

        description = re.sub(r'<.*?>', '', description)        # Clean HTML from description

        is_datetime = event['start'].get('dateTime', None)
        
        try:
            if is_datetime:
                # converting to user's timezone
                start = convert_timezone(start, timezone)
                end = convert_timezone(end, timezone)
        except Exception as e:
            print(f"########### Error converting timezone: {str(e)}")

        start_str = readable_date(start, is_datetime, False)
        end_str = readable_date(end, is_datetime, False)

        if calendar not in calendar_list:
            lines = [f"____________________\n_*Calendar*_: {calendar}\n\n*{summary}*", f"{start_str} - {end_str} {timezone}"]
            calendar_list.append(calendar)
        else:
            lines = [f"*{summary}*", f"{start_str} - {end_str} {timezone}"]

        if location:
            lines.append(f"Location: {location}")
        if description and description != "(No Description)":
            lines.append(f"Description: {description}")
        if displayName:
            lines.append(f"Calendar: {displayName}")

        event_list.append("\n".join(lines))

    allEvents = f"\n\n".join(event_list)
    return f"{introduction}:\n\n{allEvents}"

def update_event_draft(user_id, new_draft, status='draft'):
    new_draft['status'] = status

    try:
        add_event_draft_redis(user_id, new_draft)
        print(f"########### New draft saved to redis for user: {user_id} {new_draft}", flush=True)
        return new_draft
    except Exception as e:
        index, memory = get_user_memory(user_id)
        if memory:
            session_memories[index]['latest_event_draft'] = new_draft
            print(f"########### New draft appended for user: {user_id} {session_memories[index]}", flush=True)
            return session_memories[index]['latest_event_draft']
        else:
            session_memories.append({
                "user_id": user_id,
                "latest_event_draft": new_draft
            })
            print(f"########### New draft appended for user: {user_id} {session_memories[-1]}", flush=True)
            return session_memories[-1]['latest_event_draft']

def discard_draft(answer, user_id):
    try:
        ai_message = answer.split('discard_draft')[1].strip() if 'discard_draft' in answer else answer.strip()
        delete_user_draft_redis(user_id)
        print(ai_message, flush=True)
        return ai_message
    except Exception as e:
        index, memory = get_user_memory(user_id)
        if memory:
            session_memories[index]['latest_event_draft'] = latest_event_draft
            print(f"########### Draft discarded for user: {user_id} {session_memories[index]}", flush=True)
            return ai_message
        else:
            return ai_message
        
def save_event_to_draft(instruction, user_id, is_test=False, is_assistant=False, client=None):
    print(f"########### save_event_to_draft: {instruction}", flush=True)

    is_action_in_instruction = 'draft_event:' in instruction
    json_str_raw = instruction.split('draft_event:')[1].strip() if is_action_in_instruction else instruction.strip()
    json_str = extract_json_block(json_str_raw)
    print(f"########### details to be parsed: {json_str}", flush=True)

    event_details = json.loads(json_str)
    print(f"########### JSON parsed Event details: {event_details}", flush=True)

    event_calendar = event_details.get('calendar', None)
    start_date = readable_date(event_details['start_date'], True)
    # end_date = readable_date(event_details['end_date'], True)

    is_start_and_end_same = event_details['start_date'] == event_details['end_date']
    formatted_date_range = format_event_datetime(event_details['start_date'], event_details['end_date'])

    date_range = f"{formatted_date_range}" if not is_start_and_end_same else f"{start_date}"

    if event_calendar and event_calendar.lower() != 'primary':
        try:
            service = get_calendar_service(user_id, is_test)
            calendar_list = list_calendars(service)
            prompt = prompt_calendar_finder(event_calendar, calendar_list)
            event_calendar = init_llm_helper(prompt, client)
        except Exception as e:
            print(f"########### Error retrieving calendar list: {str(e)}")

    text_reply = f'''
    Here is your event, please review:\n
    1. *Event Name:* {event_details['name']}
    2. *Event Date and Time:* {date_range}
    3. *Event Location:* {event_details['location']}
    4. *Event Description:* {event_details['description']}
    '''
    num_counter = 4
    if not event_details['participants']:
        num_counter += 1
        indent = ' ' * 4 if num_counter > 5 else ''
        text_reply += f"{indent}{num_counter}. *Attendees (emails):* Not added\n"
    if event_details['participants']:
        if not all_valid_emails(event_details['participants']):
            return "Sorry, only emails are allowed for participants list."
        num_counter += 1
        indent = ' ' * 4 if num_counter > 5 else ''
        text_reply += f"{indent}{num_counter}. *Attendees (emails):* {', '.join(event_details['participants'])}\n"
    if event_details['timezone']:
        num_counter += 1
        indent = ' ' * 4 if num_counter > 5 else ''
        text_reply += f"{indent}{num_counter}. *Event Timezone:* {event_details['timezone']}\n"
    if event_details['calendar']:
        num_counter += 1
        indent = ' ' * 4 if num_counter > 5 else ''
        text_reply += f"{indent}{num_counter}. *Calendar Name:* {event_calendar}\n"
    if event_details['reminder']:
        num_counter += 1
        indent = ' ' * 4 if num_counter > 5 else ''
        text_reply += f"{indent}{num_counter}. *Event Reminder:* {event_details['reminder']} minutes before the event"
    if event_details['send_updates'] and event_details['participants']:
        num_counter += 1
        indent = ' ' * 4 if num_counter > 5 else ''
        text_reply += f"{indent}{num_counter}. *Event Creation Updates:* To be sent to participants\n"
    if event_details.get('recurrence', None):
        num_counter += 1
        indent = ' ' * 4 if num_counter > 5 else ''
        text_reply += f"{indent}{num_counter}. *Event Recurrence:* {', '.join(event_details['recurrence'])}\n"
    
    text_reply += f"\nPlease confirm the above, or let me know if you'd like to modify some details.\n"

    if is_test:
        text_reply += f"\n🔧 You are now using our shared test calendar.\n"

    if not is_assistant:
        update_event_draft(user_id, event_details)

    print(f"########### Event draft: {text_reply}", flush=True)
    return text_reply
        
def confirm_event_draft(user_id):
    try:
        delete_user_draft_redis(user_id)
        return True
    except Exception as e:
        index, memory = get_user_memory(user_id)
        if memory:
            session_memories[index]['latest_event_draft']['status'] = 'confirmed'
            return True
        else:
            return False
    
def save_event_to_calendar(instruction, user_id, is_test=False, service=None):
    if not service:
        service = get_calendar_service(user_id, is_test)

    try:
        is_action_in_instruction = 'add_event:' in instruction
        json_str_raw = instruction.split('add_event:')[1].strip() if is_action_in_instruction else instruction.strip()
        json_str = extract_json_block(json_str_raw)
        print(f"####### JSON string: {json_str}")
        event_details = json.loads(json_str)
        update_event_draft(user_id, event_details)
    except Exception as e:
        print(f"####### Failed to parse event JSON: {e}")
        return "Sorry, I couldn't understand your event details."

    print(f"########### Event details: {event_details}", flush=True)

    name = event_details['name']
    start_date_str = event_details['start_date']
    end_date_str = event_details['end_date']
    start_date = datetime.fromisoformat(start_date_str)
    end_date = (start_date + timedelta(hours=1)) if end_date_str is None else datetime.fromisoformat(end_date_str)
    timezone = event_details.get('timezone', None)
    location = event_details['location']
    description = event_details['description']
    participants = event_details['participants']
    reminder_minutes = event_details['reminder']
    calendar_name = event_details.get('calendar', 'primary')
    sendUpdates = event_details.get('send_updates', False)
    recurrence = event_details.get('recurrence', None)
    calendar_id = 'primary'

    sendUpdates = 'all' if (sendUpdates or sendUpdates == 'true') else 'none'

    if calendar_name != 'primary':
        calendars = list_calendars(service)
        calendar_id = None
        for calendar in calendars['items']:
            if str(calendar['summary']).lower() == str(calendar_name).lower():
                calendar_id = calendar['id']
                break
        if not calendar_id:
            print(f"########### Calendar '{calendar_name}' not found.")
            return "Sorry, I can not find the specific calendar name you're referring to."
        
    attendees = []
    for participant in participants:
        attendees.append({'email': participant})

    if not reminder_minutes:
        reminder = {
            'useDefault': True,
        }
    else:
        reminder = {
                'overrides': [
                    {'method': 'email', 'minutes': reminder_minutes},
                    {'method': 'popup', 'minutes': reminder_minutes},
                ],
            }

    event = {
        'summary': name,
        'location': location,
        'description': description,
        'start': {
            'dateTime': start_date.isoformat()
        },
        'end': {
            'dateTime': end_date.isoformat()
        },
        'attendees': attendees,
        'reminders': reminder,
        "visibility": "default",
    }

    if timezone:
        event['start']['timeZone'] = timezone
        event['end']['timeZone'] = timezone

    if recurrence:
        event['recurrence'] = recurrence

    print(f"########### FINAL event details: {event}", flush=True)
    try:
        if sendUpdates == 'all':
            new_event = service.events().insert(calendarId=calendar_id, body=event, sendUpdates=sendUpdates).execute()
        else:
            new_event = service.events().insert(calendarId=calendar_id, body=event).execute()

        print(f"########### Event created: {new_event}", flush=True)

        confirm_event_draft(user_id)
        calendar_embed =  "https://calendar.google.com/calendar/u/0/embed?src=kalenda.bot@gmail.com&mode=AGENDA#eventpage_6%3A"
        full_link = new_event.get('htmlLink')
        if is_test:
            print(f"########### Test calendar link: {is_test}", flush=True)
            event_id = full_link.split('eid=')[1]
            new_event_link = f"{calendar_embed}{event_id}"
        else:
            print(f"########### User calendar link: {is_test}", flush=True)
            new_event_link = full_link
        
        start_date = new_event['start'].get('dateTime', new_event['start'].get('date'))
        start = readable_date(start_date, True, True)

        summary = f'''
        \n*Event Created!*\n
        📅: {new_event.get('summary', '')}\n
        🕒: {start}\n
        👉: {new_event_link}
        '''
        return f"{summary}"
    except Exception as e:
        print(f"########### Error adding to g-cal: {e}")
        return None
    
def update_timezone(answer, user_id, is_test=False):
    if is_test:
        print(f"########### Sorry, timezone for test account can not be modified: {user_id}", flush=True)
        return "Sorry, timezone for shared / public test account can not be modified."
    
    is_action_in_instruction = 'timezone_set:' in answer
    print(f"########### update_timezone: {answer}", flush=True)
    new_timezone = answer.split('timezone_set: ')[1].strip() if is_action_in_instruction else answer.strip()
    updated_timezone = add_update_timezone(user_id, new_timezone)
    if updated_timezone:
        return f'Your timezone has been changed to {new_timezone}. Please proceed with your request.'
    else:
        return f'Failed to set your timezone. Please try again.'
