from services.model import init_openai, init_params, init_llm
from variables.toolbox import tools
from datetime import datetime, timedelta, timezone as tzn
from helperFiles.helpers import clean_instruction_block, send_whatsapp_message, parse_llm_answer
from services.calendar_service import discard_draft, transform_events_to_text, save_event_to_draft, save_event_to_calendar, get_upcoming_events, update_timezone
from authorization.creds import TWILIO_PHONE_NUMBER
from helperFiles.sentry_helper import set_sentry_context
import os
import json
import time

def invoke_model(resp, user_id, input, is_test=False, image_data_url=None, voice_data_filename=None, twilio_number=TWILIO_PHONE_NUMBER, prompt_type='main'):
    params = init_params(user_id, is_test, twilio_number)
    error = params['error']
    input_type = 'unknown'

    if error:
        print(f"########### Error: {error}", flush=True)
        return error, input_type
    
    service = params['service']
    user_timezone = params['user_timezone']

    raw_answer = init_llm(user_id, input, prompt_type, image_data_url, user_timezone, voice_data_filename, None)
    answer = clean_instruction_block(raw_answer)
    whatsappNum = f'whatsapp:+{user_id}'
    parsed_answer = parse_llm_answer(answer)

    if parsed_answer == 'draft_event':
        print(f"########### Drafting event: {answer}", flush=True)
        input_type = 'draft_event'
        try:
            loading_message = "Drafting..."
            send_whatsapp_message(f'{whatsappNum}', loading_message, twilio_number)
        except Exception as e:
            print(f"########### Error sending loading message: {str(e)}", flush=True)
        try:
            text_reply = save_event_to_draft(answer, user_id, is_test)
            print(f"########### Replying event draft: {text_reply}", flush=True)
            return text_reply, input_type
        except Exception as e:
            print(f"########### Error parsing event details: {str(e)}", flush=True)
            return "Sorry, I couldn't understand the event details.", input_type
    
    elif parsed_answer == 'discard_draft':
        print(f"########### Discarding draft: {answer}", flush=True)
        input_type = 'discard_draft'
        try:
            discard_reply = discard_draft(answer, user_id)
            return discard_reply, input_type
        except Exception as e:
            print(f"########### Error discarding draft: {str(e)}", flush=True)
            return "Sorry, I could not discard the draft.", input_type

    elif parsed_answer == 'add_event':
        print(f"########### Adding event: {answer}", flush=True)
        input_type = 'add_event'
        try:
            loading_message = "Adding your event..."
            send_whatsapp_message(f'{whatsappNum}', loading_message, twilio_number)
        except Exception as e:
            print(f"########### Error sending loading message: {str(e)}", flush=True)

        try:
            new_event = save_event_to_calendar(answer, user_id, is_test, service)
            print(f"########### Replying event: {new_event}", flush=True)
            return new_event, input_type
        except Exception as e:
            print(f"########### Error adding new event: {e}", flush=True)
            return "Sorry, I could not add the event to your calendar.", input_type
        
    elif parsed_answer == 'retrieve_event':
        print(f"########### Retrieving events: {answer}", flush=True)
        try:
            is_using_test_calendar_remark = f"_(you are using our shared test calendar)_"
            loading_message = f"Fetching your events...{is_using_test_calendar_remark if is_test else ''}"
            send_whatsapp_message(f'{whatsappNum}', loading_message, twilio_number)
        except Exception as e:
            print(f"########### Error sending loading message: {str(e)}", flush=True)

        try:
            events = get_upcoming_events(answer, user_id, is_test)
            print(f"########### All list of Events: {events}", flush=True)
            event_list, _, _, action = events
            if action == 'retrieve':
                input_type = 'retrieve_event'
                user_events = transform_events_to_text(events, user_timezone)
                return user_events, input_type
            elif action == 'retrieve_free_time':
                input_type = 'analyze_availability'
                raw_answer_analyzer = init_llm(user_id, input, 'schedule_analyzer', image_data_url, user_timezone, voice_data_filename, event_list)
                return raw_answer_analyzer, input_type
            elif action == 'find_with_keyword':
                input_type = 'retrieve_event_with_keyword'
                raw_answer_finder = init_llm(user_id, input, 'keyword_finder', image_data_url, user_timezone, voice_data_filename, event_list)
                return raw_answer_finder, input_type
            else:
                return event_list, input_type
        except Exception as e:
            print(f"########### Error retrieving events: {str(e)}", flush=True)
            return "Sorry, I am unable to fetch your events at the moment.", input_type

    elif parsed_answer == 'timezone_set':
        print(f"########### Setting timezone: {answer}", flush=True)
        input_type = 'set_timezone'
        try:
            return update_timezone(answer, user_id), input_type
        except Exception as e:
            print(f"########### Error updating timezone: {str(e)}", flush=True)
            return "Sorry, I could not set your timezone. Please try again.", input_type

    else:
        print(f"########### Instruction not recognized: {answer}", flush=True)
        input_type = 'freeform_answer'
        set_sentry_context(user_id, input, answer, f"Freeform answer generated", None)
        return answer, input_type