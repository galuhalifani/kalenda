from services.model import init_openai, init_params, init_llm
from services.database import get_assistant_id, save_assistant_id, get_thread_id, save_thread_id
from variables.toolbox import tools
from prompts.prompt_assistant import base_prompt
from datetime import datetime, timedelta, timezone as tzn
from helperFiles.helpers import check_input_not_none, send_whatsapp_message, parse_voice
from services.calendar_service import transform_events_to_text, save_event_to_draft, save_event_to_calendar, get_upcoming_events, update_timezone
from authorization.creds import TWILIO_PHONE_NUMBER
import os
import json
import time

def init_assistant(client=None):
    if not client:
        client = init_openai()
        if not client:
            return "Sorry, I couldn't connect to the OpenAI service. Please try again later."
    
    basePrompt = base_prompt()
    assistant = client.beta.assistants.create(
        name="Kalenda Assistant",
        instructions=basePrompt,
        tools=tools,
        model="gpt-4o"
    )
    ASSISTANT_ID = assistant.id
    is_saved = save_assistant_id(ASSISTANT_ID)
    return ASSISTANT_ID if is_saved else None


def check_thread_status_and_purge(user_id, max_age_hours=24, max_messages=10):
    try:
        client = init_openai()
        if not client:
            return "Sorry, I couldn't connect to OpenAI. Try again later."

        print("Check AI status and purge old messages", flush=True)
        # Use thread_id per user (e.g., saved in MongoDB or memory)
        thread_id = get_thread_id(user_id)
    
        messages = client.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=1)
        print(f"########### Messages in thread {thread_id}: {messages.data}", flush=True)
        if not messages.data:
            return 
    
        now = datetime.now(tzn.utc)

        for index, msg in enumerate(messages.data):
            if index >= max_messages:
                # delete older messages
                client.beta.threads.messages.delete(thread_id=thread_id, message_id=msg.id)
                continue

            # check if the message is older than max_age_hours
            created_at = msg.created_at

            message_time = datetime.fromtimestamp(created_at, tz=tzn.utc)
            if message_time.tzinfo is None:
                message_time = message_time.replace(tzinfo=tzn.utc)

            if now > message_time + timedelta(hours=max_age_hours):
                client.beta.threads.messages.delete(thread_id=thread_id, message_id=msg.id)

    except Exception as e:
        print(f"Failed to check thread activity: {e}")
        return
    
def update_assistant_prompt_once():
    PROMPT_UPDATE_FLAG = ".kalenda_prompt_updated"
    if not os.path.exists(PROMPT_UPDATE_FLAG):
        print("Updating assistant prompt...")
        
        client = init_openai()
        if not client:
            return "Sorry, I couldn't connect to the OpenAI service. Please try again later."
        
        assistant_id = get_assistant_id()
        if not assistant_id:
            assistant_id = init_assistant(client)

        basePrompt = base_prompt()

        client.beta.assistants.update(
            assistant_id=assistant_id,
            instructions=basePrompt
        )
        with open(PROMPT_UPDATE_FLAG, "w") as f:
            f.write("updated")
    else:
        print("Assistant prompt already updated.")
        return
        
def init_llm_assistant(user_id, input, today, service, twilio_number, image_data_url=None, timezone=None, voice_data_filename=None, is_test=False):
    input_type = 'unknown'
    try:
        client = init_openai()
        if not client:
            return "Sorry, I couldn't connect to OpenAI. Try again later.", input_type

        # Parse voice input
        if voice_data_filename:
            input = parse_voice(voice_data_filename, client)

        check_input_not_none(input, image_data_url)

        input += (
            f"\n\n[NOTE FOR KALENDA]\n"
            f"DEFAULT_TIMEZONE: {timezone if timezone else 'Asia/Jakarta'}\n"
            f"CURRENT_DATE: {today}\n"
        )

        # Use thread_id per user (e.g., saved in MongoDB or memory)
        thread_id = get_thread_id(user_id)
        print(f"########### Thread ID for user {user_id}: {thread_id}", flush=True)
        
        if not thread_id:
            print(f"########### Creating new thread for user: {user_id}", flush=True)
            # Create a new thread if it doesn't exist
            new_thread = client.beta.threads.create()
            save_thread_id(user_id, new_thread.id)
            thread_id = new_thread.id            

        # Send message to thread
        content_blocks = [{"type": "text", "text": input}]
        if image_data_url:
            content_blocks.append({"type": "image_url", "image_url": {"url": image_data_url}})
            
        print(f"########### Sending message to thread {thread_id}: {content_blocks}", flush=True)
        
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=content_blocks
        )

        assistant_id = get_assistant_id()
        if not assistant_id:
            assistant_id = init_assistant()
        
        print(f"########### Using assistant ID: {assistant_id}", flush=True)

        if not assistant_id:
            return "Sorry, I couldn't initialize the assistant. Please try again later.", input_type

        # Run the assistant
        run = client.beta.threads.runs.create(
            assistant_id=assistant_id,
            thread_id=thread_id
        )

        print(f"########### Run created with ID: {run.id} for thread {thread_id}", flush=True)
        # Wait for completion
        max_attempts = 60  # e.g., 60 seconds
        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            try:
                run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
                print(f"########### Run status: {run_status.status}", flush=True)
            except Exception as e:
                print(f"########### Error retrieving run status: {str(e)}", flush=True)
                return "Sorry, I couldn't retrieve the run status. Please try again later.", input_type
            
            if run_status.status == "completed":
                print(f"########### Run completed with ID: {run.id}", flush=True)
                break
            
            elif run_status.status == "requires_action":
                print(f"########### Run requires action with ID: {run.id}", flush=True)
                tool_calls = run_status.required_action.submit_tool_outputs.tool_calls
                results = []

                for tool in tool_calls:
                    fn_name = tool.function.name
                    args = json.loads(tool.function.arguments)

                    args["user_id"] = user_id
                    args["is_test"] = is_test
                    whatsappNum = f'whatsapp:+{user_id}'

                    print(f"########### Function called: {fn_name} with args: {args}", flush=True)
                    if fn_name == "save_event_to_draft":
                        input_type = 'draft_event'
                        try:
                            loading_message = "Drafting..."
                            send_whatsapp_message(f'{whatsappNum}', loading_message, twilio_number)
                        except Exception as e:
                            print(f"########### Error sending loading message: {str(e)}", flush=True)
                        try:
                            print(f"########### Saving event to draft with args: {args}", flush=True)
                            args['is_assistant'] = True
                            result = save_event_to_draft(**args)
                            print(f"########### Result of event draft: {result}", flush=True)
                        except Exception as e:
                            print(f"########### Error parsing event details: {str(e)}", flush=True)
                            result = "Sorry, I couldn't understand the event details."

                    elif fn_name == "save_confirmed_event_to_calendar":
                        input_type = 'add_event'
                        try:
                            loading_message = "Adding your event..."
                            send_whatsapp_message(f'{whatsappNum}', loading_message, twilio_number)
                        except Exception as e:
                            print(f"########### Error sending loading message: {str(e)}", flush=True)
                        
                        try:
                            print(f"########### Saving event to calendar with args: {args}", flush=True)
                            args["service"] = service
                            result = save_event_to_calendar(**args)
                        except Exception as e:
                            print(f"########### Error saving event to calendar: {e}", flush=True)
                            result = "Sorry, I could not add the event to your calendar."

                    elif fn_name == "get_upcoming_events":
                        try:
                            is_using_test_calendar_remark = f"_(you are using our shared test calendar)_"
                            loading_message = f"Fetching your events...{is_using_test_calendar_remark if is_test else ''}"
                            send_whatsapp_message(f'{whatsappNum}', loading_message, twilio_number)
                        except Exception as e:
                            print(f"########### Error sending loading message: {str(e)}", flush=True)

                        try:
                            args["service"] = service
                            events = get_upcoming_events(**args)
                            print(f"########### All list of Events: {events}", flush=True)
                            event_list, _, _, action = events
                            if action == 'retrieve':
                                input_type = 'retrieve_event'
                                user_events = transform_events_to_text(events, timezone)
                                result = user_events
                            elif action == 'retrieve_free_time':
                                input_type = 'analyze_availability'
                                raw_answer_analyzer = init_llm(user_id, input, 'schedule_analyzer', image_data_url, timezone, voice_data_filename, event_list)
                                result = raw_answer_analyzer
                            elif action == 'find_with_keyword':
                                input_type = 'retrieve_event_with_keyword'
                                raw_answer_finder = init_llm(user_id, input, 'keyword_finder', image_data_url, timezone, voice_data_filename, event_list)
                                result = raw_answer_finder
                            else:
                                input_type = 'retrieve_event'
                                result = event_list
                        except Exception as e:
                            print(f"########### Error retrieving events: {str(e)}", flush=True)
                            result = "Sorry, I am unable to fetch your events at the moment."

                    elif fn_name == "update_timezone":
                        input_type = 'set_timezone'
                        result = update_timezone(**args)
                        
                    else:
                        input_type = 'unknown'
                        print(f"########### Unknown tool called: {fn_name}", flush=True)
                        result = f"Tool `{fn_name}` is not implemented."

                    results.append({
                        "tool_call_id": tool.id,
                        "output": json.dumps(result)
                    })

                    print(f"########### Run status: {run_status.status}; RESULTS: {results}", flush=True)

                client.beta.threads.runs.submit_tool_outputs(
                    thread_id=thread_id,
                    run_id=run.id,
                    tool_outputs=results
                )
                continue

            elif run_status.status == "failed":
                print(f"########### Run failed with ID: {run.id}", flush=True)
                last_error = run_status.last_error
                error_message = last_error.message if last_error else "Unknown error"
                print(f"########### Error message: {error_message}", flush=True)

                if "Error while downloading" in error_message:
                    print("Error while downloading, deleting last message...")
                    messages = client.beta.threads.messages.list(thread_id=thread_id)
                    last_msg = messages.data[0]
                    last_msg_id = last_msg.id if last_msg else None
                    if last_msg_id:
                        client.beta.threads.messages.delete(thread_id=thread_id, message_id=last_msg_id)
                        print(f"########### Deleted last message with ID: {last_msg_id}", flush=True)
                    else:
                        print("########### No messages to delete", flush=True)

                return f"Sorry, I couldn't process your request. Error: {error_message}", input_type

            time.sleep(0.05)
        else:
            return "Sorry, the assistant is taking too long to respond. Please try again later.", input_type
        
        # Get response
        print(f"########### Fetching messages from thread {thread_id}", flush=True)
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        for msg in messages.data:
            print(f"########### Message from thread: {msg.role} - {msg.content}", flush=True)
            if msg.role == "assistant":
                response = msg.content[0].text.value
                print(f"########### Assistant Response: {response}", flush=True)
                return response, input_type

        return "Sorry, I didn't get a response from the assistant.", input_type

    except Exception as e:
        print(f"########### Error in Assistants API: {str(e)}", flush=True)
        return "Sorry, I couldn't process your request.", input_type
    
def invoke_assistant(resp, user_id, input, is_test=False, image_data_url=None, voice_data_filename=None, twilio_number=TWILIO_PHONE_NUMBER):
    params = init_params(user_id, is_test, twilio_number)
    error = params['error']

    if error:
        print(f"########### Error: {error}", flush=True)
        return error
    
    service = params['service']
    now_utc = params['now_utc']
    user_timezone = params['user_timezone']
    result = init_llm_assistant(user_id, input, now_utc, service, twilio_number, image_data_url, user_timezone, voice_data_filename, is_test)
    if isinstance(result, tuple):
        if len(result) == 2:
            assistant_answer, input_type = result
        elif len(result) == 1:
            assistant_answer = result[0]
            input_type = 'unknown'
        else:
            assistant_answer, input_type = None, 'unknown'
    else:
        assistant_answer = result
        input_type = 'unknown'

    return assistant_answer if isinstance(assistant_answer, str) else "Sorry, I couldn't process your request. Please try again.", input_type