from authorization.creds import *
from variables.keywords import *
from llm.chat_completions import invoke_model
from llm.assistant import invoke_assistant, check_thread_status_and_purge
from helperFiles.helpers import send_error_whatsapp_message, send_whatsapp_message, trim_reply
from services.database import deduct_chat_balance, add_interaction
from helperFiles.redis_helper import add_and_delete_user_chat_redis
from helperFiles.buffer import handle_message
from helperFiles.queue_helper import safe_enqueue
from helperFiles.sentry_helper import set_sentry_context

def start_process(resp, user, user_id, record_user_id, incoming_msg, is_test, image_data_url, voice_data_filename, twilio_number, is_assistant=False, prompt_type='main'):
    """
    Start the LLM processing for the incoming message.
    """
    print(f"########### Starting process: {incoming_msg}, {user_id}, image: {bool(image_data_url)}, voice: {bool(voice_data_filename)}", flush=True)
    try:
        if is_assistant:
            result = invoke_assistant(resp, user_id, incoming_msg, is_test, image_data_url, voice_data_filename, twilio_number)
        else:
            result = invoke_model(resp, user_id, incoming_msg, is_test, image_data_url, voice_data_filename, twilio_number, prompt_type)

        if isinstance(result, tuple):
            if len(result) == 2:
                reply_text, input_type = result
            elif len(result) == 1:
                reply_text = result[0]
                input_type = 'unknown'
            else:
                reply_text, input_type = 'Sorry the assistant is not available right now.', 'unknown'
        else:
            reply_text = result
            input_type = 'unknown'
    
        if not isinstance(reply_text, str):
            reply_text = str(reply_text)

        if not is_assistant:
            if len(reply_text) > 1400:
                reply_text = trim_reply(reply_text)

        send_whatsapp_message(record_user_id, reply_text, twilio_number)

        print(f"########### End process {user_id}. Response: {reply_text}", flush=True)

        # sending queue job to add analytics
        safe_enqueue(add_interaction, incoming_msg, reply_text, user_id, input_type)

        if not is_assistant:
            add_and_delete_user_chat_redis(user_id, incoming_msg, reply_text)
        else:
            check_thread_status_and_purge(user_id, 24, 10)

        safe_enqueue(deduct_chat_balance, user.get('user_details', {}) if user else {}, user_id)

        print(f"########### End process {user_id}. Response: {reply_text}", flush=True)
    except Exception as e:
        print(f"########### ERROR in start_process: {e}", flush=True)
        set_sentry_context(user_id, incoming_msg, None, f"Error in start_process function: Processing failed", e)
        raise

def start_or_buffer_message(
    resp,
    user,
    user_id,
    record_user_id,
    incoming_msg,
    is_test,
    twilio_number,
    is_assistant,
    media_url=None,
    image_data_url=None,
    voice_data_filename=None,
    prompt_type='main'
):
    """
    Handle the incoming message, either processing it immediately or buffering it.
    """
    if not incoming_msg and not image_data_url and not voice_data_filename:
        print(f"⚠️ Skipping empty message for {user_id}")
        return

    if media_url and incoming_msg:
        # process immediately
        start_process(resp, user, user_id, record_user_id, incoming_msg, is_test, image_data_url, voice_data_filename, twilio_number, is_assistant, prompt_type)
    else:
        # use buffer for delayed message
        handle_message(
            resp,
            user,
            user_id,
            record_user_id,
            incoming_msg,
            is_test,
            twilio_number,
            is_assistant,
            start_process,
            image_data_url,
            voice_data_filename,
            prompt_type
        )
