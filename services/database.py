from pymongo import MongoClient
from authorization.creds import *
from datetime import datetime, timedelta, timezone as tzn
from helperFiles.helpers import send_error_whatsapp_message, send_whatsapp_message
from variables.text import using_test_calendar, using_test_calendar_whitelist
from helperFiles.session_memory import get_user_memory
from helperFiles.redis_helper import get_latest_chat_and_draft_redis
from helperFiles.sentry_helper import set_sentry_context

def init_mongodb():
    try:
        client = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=5000)
        client.server_info()
        return client
    except Exception as e:
        error_msg = f"⚠️ Failed connecting to database: {str(e)}"
        set_sentry_context(None, None, None, f"Error in init_mongodb function: Database connection failed", e)
        return error_msg
    
client = init_mongodb()

if client:
    db = client['kalenda']
    user_collection = db['user']
    tokens_collection = db['tokens']
    email_collection = db['email']
    feedback_collection = db['feedback']
    pending_auth_collection = db['pending_auth']
    assistant_collection = db['assistant']
    thread_collections = db['threads']
    analytics_collection = db['analytics']

    # Create TTL index for pending_auth (15 minutes)
    pending_auth_collection.create_index("created_at", expireAfterSeconds=900)
    
    # Create TTL index for tokens (2 weeks = 1,209,600 seconds)
    # This will automatically remove tokens after 2 weeks
    # Documents without token_expiry_date field (like test_shared_calendar) won't expire
    tokens_collection.create_index("token_expiry_date", expireAfterSeconds=1209600)
else:
    user_collection = None
    tokens_collection = None
    email_collection = None
    feedback_collection = None
    pending_auth_collection = None
    assistant_collection = None
    thread_collections = None
    analytics_collection = None

def add_interaction(input, answer, user_id, type="unknown"):
    print(f"########### Adding interaction: {input}, {answer}, {user_id}, type: {type}", flush=True)
    try:
        # Record interaction data with generated id
        # change input and answer to character count
        input_count = len(input)
        answer_count = len(answer)
        interaction_id = analytics_collection.insert_one({
            "key": "interactions",
            "user_id": user_id,
            "type": type,
            "input_char_count": input_count,
            "answer_char_count": answer_count,
            "total_char_count": input_count + answer_count,
            "timestamp": datetime.now(tzn.utc)
        }).inserted_id
        print(f"########### Interaction added: {interaction_id}", flush=True)
        return True
    except Exception as e:
        print(f"Error adding interaction: {e}", flush=True)
        set_sentry_context(user_id=user_id, input=None, answer=None, message="add_interaction error", error=str(e))
        return False

def get_interactions(type="unknown"):
    try:
        # Find all interactions of a specific type
        interactions = analytics_collection.find({"key": "interactions", "type": type})
        interaction_list = []
        for interaction in interactions:
            interaction_list.append({
                "id": str(interaction["_id"]),
                "user_id": interaction.get("user_id", None),
                "input_word_count": interaction.get("input_word_count", 0),
                "answer_word_count": interaction.get("answer_word_count", 0),
                "total_word_count": interaction.get("total_word_count", 0),
                "timestamp": interaction.get("timestamp", None)
            })
        return interaction_list
    except Exception as e:
        print(f"Error getting interactions: {e}", flush=True)
        set_sentry_context(user_id=None, input=None, answer=None, message="get_interactions error", error=str(e))
        return []

def check_ipaddr_like(ipaddr):
    try:
        # Check if the IP address has already liked
        like = analytics_collection.find_one({"key": "total_likes", "ipaddr": ipaddr})
        if like:
            return True
        else:
            return False
    except Exception as e:
        print(f"Error checking IP address like: {e}", flush=True)
        set_sentry_context(user_id=None, input=None, answer=None, message="check_ipaddr_like error", error=str(e))
        return False
    
def get_likes():
    try:
        # find total likes from all ip addresses
        total_likes_cursor = analytics_collection.aggregate([
            {"$match": {"key": "total_likes"}},
            {"$group": {"_id": None, "total": {"$sum": "$value"}}}
        ])
        total_likes = list(total_likes_cursor)
        if total_likes:
            return total_likes[0].get("total", 0)
        else:
            return 0
    except Exception as e:
        print(f"Error getting likes: {e}", flush=True)
        set_sentry_context(user_id=None, input=None, answer=None, message="get_likes error", error=str(e))
        return 0
    
def add_likes(ipaddr=None):
    try:
        ipaddr = ipaddr or "unknown_ip"
        analytics_collection.update_one(
            {"key": "total_likes", "ipaddr": ipaddr},
            {"$inc": {"value": 1}},
            upsert=True
        )
        print(f"########### Like added", flush=True)
        return True
    except Exception as e:
        print(f"Error adding like: {e}", flush=True)
        set_sentry_context(user_id=None, input=None, answer=None, message="add_likes error", error=str(e))
        return False

def check_user(user_id):
    print(f"########### Checking user: {user_id}", flush=True)
    daily_limit = 10
    user = user_collection.find_one({"user_id": user_id})
    if user:
        balance = user.get("chat_balance", daily_limit)
        userType = user.get("type", 'regular')
        is_using_test_account = user.get("is_using_test_account", True)
        last_balance_reset = user.get("last_balance_reset", datetime.now(tzn.utc))
        
        if last_balance_reset.tzinfo is None:
            last_balance_reset = last_balance_reset.replace(tzinfo=tzn.utc)
        
        print(f'########## checking user: {user_id}, balance: {balance}')
        
        # Convert current time to GMT+7
        gmt7_tz = tzn(timedelta(hours=7))
        current_time_gmt7 = datetime.now(gmt7_tz)
        last_reset_gmt7 = last_balance_reset.astimezone(gmt7_tz)
        
        # Check if it's a new day in GMT+7
        if current_time_gmt7.date() > last_reset_gmt7.date():
            # restore balance at the start of a new day
            print("########## restoring balance - new day in GMT+7")
            balance = daily_limit
            user_collection.update_one(
                {"user_id": user_id}, 
                {"$set": {
                    "chat_balance": daily_limit,
                    "last_balance_reset": datetime.now(tzn.utc)
                }}
            )

        return {"status": "existing", "user_id": user_id, "chat_balance": balance, "type": userType, "user_details": user, "is_using_test_account": is_using_test_account}
    else:
        current_time = datetime.now(tzn.utc)
        user_collection.insert_one({
            "user_id": user_id, 
            "timestamp": current_time.isoformat(), 
            "chat_balance": daily_limit, 
            "type": "regular", 
            "is_using_test_account": True,
            "last_balance_reset": current_time
        })
        print(f'########## creating new user: {user_id}, balance: {daily_limit}')
        set_sentry_context(user_id=user_id, input=None, answer=None, message="New User Added", error=None)
        return {"status": "new", "user_id": user_id, "user_details": user, "chat_balance": daily_limit, "type": "regular", "is_using_test_account": True}

def deduct_chat_balance(user, user_id):
    try:
        if user:
            print(f'########## deduct_chat_balance: {user}, type: {user["type"]}, balance: {user["chat_balance"]}')
            if user["type"] == 'regular' and user["chat_balance"] > 0:
                user_collection.update_one(
                    {"user_id": user_id},
                    {
                        "$inc": {"chat_balance": -1},
                        "$set": {"last_chat": datetime.now(tzn.utc)}
                    }
                )
                print(f"########### Balance deducted", flush=True)
                return True
        else:
            print(f"########### User not found: {user_id}", flush=True)
            return False
    except Exception as e:
        print(f"####### Error deducting chat balance: {str(e)}")
        set_sentry_context(user_id=user_id, input=None, answer=None, message="deduct_chat_balance error", error=str(e))
        return False

def check_user_balance(user):
    if user:
        balance = user["chat_balance"]
        print(f'########## check_user_balance: {user}, type: {user["type"]}, balance: {balance}')
        if user["type"] == 'regular' and balance > 0:
            return True
        elif user["type"] == 'unlimited':
            return True
        else:
            return False
    else:
        print(f"########### User not found: {user}", flush=True)
        return False
    
def check_timezone(user_id, cal_timezone=None):
    print(f"########### Checking timezone for user: {user_id}", flush=True)
    user = user_collection.find_one({"user_id": user_id})
    
    if user:
        is_using_test_account = user.get("is_using_test_account", False)
        if is_using_test_account:
            return "Asia/Jakarta"
        
        timezone = user.get("timezone")
        if timezone:
            return timezone
        elif cal_timezone:
            return cal_timezone
        else:
            return None
    else:
        return None

def add_update_timezone(user_id, timezone):
    try:
        user_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {"timezone": timezone}
                },
                upsert=True
            )
        return True
    except Exception as e:
        print(f"Error updating timezone for user {user_id}: {e}", flush=True)
        set_sentry_context(user_id=user_id, input=None, answer=None, message="add_update_timezone error", error=str(e))
        return False

def use_test_account(user_id):
    test_tokens = tokens_collection.find_one({"user_id": 'test_shared_calendar'})
    if not test_tokens:
        raise Exception("Test account not found in database.")

    test_access_token = test_tokens.get("access_token")
    test_refresh_token = test_tokens.get("refresh_token")
    test_expiry = test_tokens.get("expiry")

    tokens_collection.update_one(
        {"user_id": user_id},
        {"$set": {
            "access_token": test_access_token,
            "refresh_token": test_refresh_token,
            "scopes": SCOPES,
            "expiry": test_expiry,
            "is_using_test_account": True
        }},
    upsert=True)

    user_collection.update_one(
        {"user_id": user_id},
        {"$set": {
            "timezone": "Asia/Jakarta",
            "is_using_test_account": True
        }},
    upsert=True)

def check_user_active_email(user_id, user_email=None):
    print(f"########### Checking if user is whitelisted: {user_id}", flush=True)
    user = user_collection.find_one({"user_id": user_id})
    print(f"########### User: {user}", flush=True)

    if user:
        db_email = user.get("email", None)
        email_whitelist_status = user.get("is_email_whitelisted", False)
        is_email_whitelisted = bool(email_whitelist_status == True)

        if db_email == None:
            print(f"########## User {user_id} has no whitelisted email in database", flush=True)
            return False
        else:   
            if user_email == None:     
                if is_email_whitelisted == True:
                    print(f"########### User has email in database: {db_email}", flush=True)
                    return db_email
                else:
                    return False
            else:
                email = email_collection.find_one({"email": user_email})
                if email:
                    if (email.get("is_whitelisted", False) == True):
                        print(f"########### Email is whitelisted: {user_email}", flush=True)
                        return email

                user_and_email = bool(bool(user_email == db_email) and is_email_whitelisted)
                if user_and_email:
                    return user_email # email is already whitelisted
        
    return False

def add_user_whitelist_status(user_id, email):
    try:
        print(f"########### Adding user whitelist status: email: {email}", flush=True)
        email_collection.update_one(
            {"email": email},
            {"$set": {"user_id": user_id, "is_whitelisted": "Pending"}},
            upsert=True
        )
        user_collection.update_one(
            {"user_id": user_id},
            {"$set": {"email": email, "is_email_whitelisted": "Pending"}},
            upsert=True
        )
        return True
    except Exception as e:
        print(f"Error updating whitelist status for {email}: {e}", flush=True)
        set_sentry_context(user_id=user_id, input=None, answer=None, message="add_user_whitelist_status error", error=str(e))
        return False

def update_user_whitelist_status(email, status):
    try:
        print(f"########### Updating user whitelist status: {email}, status: {status}", flush=True)
        email_collection.update_one(
            {"email": email},
            {"$set": {"is_whitelisted": status}},
            upsert=True
        )
        user_collection.update_one(
            {"email": email},
            {"$set": {"is_email_whitelisted": status}},
            upsert=True
        )
        user = user_collection.find_one({"email": email})
        user_number = user.get("user_id")
        return user_number
    except Exception as e:
        print(f"Error updating whitelist status for {email}: {e}", flush=True)
        set_sentry_context(user_id=email, input=None, answer=None, message="update_user_whitelist_status error", error=str(e))
        return False

def update_send_whitelisted_message_status(user_number):
    user_collection.update_one(
        {"user_id": user_number},
        {"$set": {"whitelisted_message_sent": True}},
        upsert=True
    )
    return user_number

def send_test_calendar_message(resp, using_test_calendar, user_id):
    text = using_test_calendar
    resp.message(text)
    user_collection.update_one(
        {"user_id": user_id},
        {"$set": {"test_calendar_message": True}},
        upsert=True
    )

def update_is_using_test_account(user_id):
    user_collection.update_one(
        {"user_id": user_id},
        {"$set": {
            "is_email_whitelisted": False,
            "whitelisted_message_sent": False,
            "test_calendar_message": True,
            "is_using_test_account": True
        }}
    )

def update_send_test_calendar_message(resp, using_test_calendar, user_id):
    user = user_collection.find_one({"user_id": user_id})
    test_calendar_message = user.get("test_calendar_message", False)

    if not user or not test_calendar_message:
        sending = send_test_calendar_message(resp, using_test_calendar, user_id)
        return sending
    else:
        if test_calendar_message:
            last_chat = user.get("last_chat", datetime.now(tzn.utc))

            if last_chat.tzinfo is None:
                last_chat = last_chat.replace(tzinfo=tzn.utc)

            time_since_last_chat = datetime.now(tzn.utc) - last_chat
            print(f'########## time_since_last_chat: {time_since_last_chat}')

        if time_since_last_chat > timedelta(days=1) :
            # allow to send again
            print("########## resending test calendar message")
            user_collection.update_one({"user_id": user_id}, {"$set": {"test_calendar_message": False}})
            return False

    return test_calendar_message

def revoke_access_command(resp, user_id):
    user_email = user_collection.find_one({"user_id": user_id}).get("email", None)
    if (user_email):
        email_collection.delete_one(
            {"email": user_email})
        
    user_collection.update_one(
        {"user_id": user_id},
        {"$set": {
            "is_email_whitelisted": False,
            "whitelisted_message_sent": False,
            "test_calendar_message": True,
            "is_using_test_account": True
        },
        "$unset": {
            "email": ""
        }}
    )

    tokens_collection.delete_one(
        {"user_id": user_id}
    )
    resp.message("✅ You have been disconnected from your google account. You can re-connect by typing 'login'. You are now using our shared test calendar.")
    return str(resp)
    
def add_pending_auth(user_id, state, client_type):
    try:
        pending_auth_collection.update_one(
            {"state": state},
            {"$set": {"user_id": user_id, "created_at": datetime.now(), "client_type": client_type}},
            upsert=True
        )
        return True
    except Exception as e:
        print(f"Error adding pending auth for {user_id}: {e}", flush=True)
        set_sentry_context(user_id, None, None, f"Error in add_pending_auth function: Failed to add pending auth", e)
        return False

def get_pending_auth(state):
    try:
        pending_auth = pending_auth_collection.find_one_and_delete({"state": state})
        if pending_auth:
            return pending_auth
        else:
            return None
    except Exception as e:
        print(f"Error getting pending auth for {state}: {e}", flush=True)
        set_sentry_context(None, state, None, f"Error in get_pending_auth function: Failed to get pending auth", e)
        return None
    
def save_feedback(feedback, user_id):
    try:
        latest_conversations, user_latest_event_draft = get_latest_chat_and_draft_redis(user_id) 
        user_memory = {'user_id': user_id, 'latest_conversations': latest_conversations, 'latest_event_draft': user_latest_event_draft}
    except Exception as e:
        userMem = get_user_memory(user_id)
        _, user_memory = userMem

    userMemory = user_memory.copy()
    userMemory.pop("user_id", None) # ensure anonymity

    contain_feedback_keyword = 'feedback' in feedback.lower()
    feedback_content = feedback.lower().split('feedback')[1].strip() if contain_feedback_keyword else feedback.lower()

    feedback_collection.insert_one({
        "feedback": feedback_content,
        "context": userMemory,
        "timestamp": datetime.now()
    })
    print(f"########### Feedback saved successfully", flush=True)

def get_assistant_id():
    try:
        assistant = assistant_collection.find_one({"key": "assistant_id"})
        if assistant:
            return assistant.get("value", None)
        else:
            return None
    except Exception as e:
        print(f"Error getting assistant ID: {e}", flush=True)
        return None

def get_thread_id(user_id):
    try:
        thread = thread_collections.find_one({"user_id": user_id})
        if thread:
            thread_id = thread.get("thread_id", None)
            return thread_id
        else:
            return None
    except Exception as e:
        print(f"Error getting thread ID for {user_id}: {e}", flush=True)
        return None

def save_thread_id(user_id, thread_id):
    try:
        thread_data = {
            "user_id": user_id,
            "thread_id": thread_id,
            "created_at": datetime.now(tzn.utc)
        }
        thread_collections.update_one(
            {"user_id": user_id},
            {"$set": thread_data},
            upsert=True
        )
        print(f"########### Thread ID saved successfully for user: {user_id}", flush=True)
        return True
    except Exception as e:
        print(f"Error saving thread ID for {user_id}: {e}", flush=True)
        return False

def save_assistant_id(assistant_id):
    try:
        assistant_collection.update_one(
            {"key": "assistant_id"},
            {"$set": {"value": assistant_id}},
            upsert=True
        )
        print(f"########### Assistant ID saved successfully: {assistant_id}", flush=True)
        return True
    except Exception as e:
        print(f"Error saving assistant ID: {e}", flush=True)
        return False
