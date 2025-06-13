from services.model import init_openai, init_params
from variables.toolbox import tools
from prompts.prompt_assistant import base_prompt
from datetime import datetime, timedelta, timezone as tzn
from helperFiles.helpers import check_input_not_none, send_whatsapp_message, parse_voice
from services.calendar_service import transform_events_to_text, save_event_to_draft, save_event_to_calendar, get_upcoming_events, update_timezone
from authorization.creds import TWILIO_PHONE_NUMBER
import os
import json
import time

## Function to invoke the model and handle chat completions to be developed