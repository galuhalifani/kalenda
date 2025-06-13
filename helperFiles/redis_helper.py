import redis
import json
import os
from authorization.creds import REDIS_HOST, REDIS_PASSWORD, REDIS_PORT, redis_encryption_non_admin, redis_encryption_all, no_redis_encryption
from helperFiles.helpers import send_error_whatsapp_message, extract_phone_number
from helperFiles.sentry_helper import set_sentry_context
from datetime import datetime, timezone as tzn, timedelta
from cryptography.fernet import Fernet
import os
from authorization.creds import ADMIN_NUMBER

r = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    ssl=True,
    decode_responses=True
)

r_worker = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    ssl=True,
    decode_responses=False  # must be False for RQ
)

CLEAN_ADMIN_NUMBER = extract_phone_number(ADMIN_NUMBER)

def is_not_user_admin(key):
    # return False # allow debug for beta testing
    if redis_encryption_all:
        return True
    elif redis_encryption_non_admin:
        user_id = key.split(':')[1] if ':' in key else None
        if user_id and user_id != CLEAN_ADMIN_NUMBER:
            return True
        return False
    elif no_redis_encryption:
        return False
    else:
        return False

def is_encrypted(value):
    return isinstance(value, str) and value.startswith("RENC_v")

def add_secure(key, value, ttl=None):
    from authorization.auth import encrypt_token
    try:
        if not isinstance(value, str):
            value = json.dumps(value)

        if is_not_user_admin(key): 
            encrypted = encrypt_token(value, True)
            if ttl:
                r.set(key, encrypted, ex=ttl)
            else:
                r.set(key, encrypted)
        else:
            if ttl:
                r.set(key, value, ex=ttl)
            else:
                r.set(key, value)

    except Exception as e:
        print(f"❌ Error adding secure value for key {key}: {e}", flush=True)
        set_sentry_context(None, None, None, f"Encryption failed in add_secure for key '{key}'. Falling back to plaintext storage.", e)
        r.set(key, value)

def get_secure(key):
    from authorization.auth import decrypt_token
    try:
        encrypted = r.get(key)
        
        if encrypted:
            if is_encrypted(encrypted):
                print(f"########### Decrypting value for key: {key}", flush=True)
                decrypted = decrypt_token(encrypted, True)
                print(f"########### Decrypted value for key: {key}", flush=True)
            else:
                decrypted = encrypted

            try:
                return json.loads(decrypted)
            except json.JSONDecodeError:
                return decrypted
        return None
    except Exception as e:
        print(f"❌ Error retrieving secure value for key {key}: {e}", flush=True)
        set_sentry_context(None, None, None, f"Encryption failed in get_secure for key '{key}'. Falling back to plaintext storage.", e)
        return r.get(key)

def ping_redis():
    try:
        response = r.ping()
        return {"status": "ok", "redis": response}, 200
    except ConnectionError as e:
        return {"status": "error", "message": str(e)}, 500

#### Redis Chat Functions ####

def add_user_chat_redis(user_id, input, answer, user_chats:list=[], update=True):
    """
    Add a new conversation to a user's memory or create a new memory entry.
    example chat:
    [
        {
            "userMessage": "hello",
            "aiMessage": "hi",
            "timestamp": "2025-06-12T08:15:00+07:00"
        }
    ]
    """
    print(f"########### Adding memory for user: {user_id}", flush=True)
    max_chat_stored = 3
    try:
        # Replace newlines and multiple spaces with a single space, then strip trailing spaces
        answer = ' '.join(answer.split())
        key = f"chat:{user_id}"
        chats = user_chats

        if not user_chats:
            chats = get_secure(key)
            # chats = r.get(key)
        
        if chats:
            if isinstance(chats, str):
                chats = json.loads(chats)
            
            if len(chats) > max_chat_stored:
                chats.pop(0)
                print(f"########### Memory limit reached for user: {user_id}. Oldest message removed.", flush=True)
            chats.append({
                "userMessage": input,
                "aiMessage": answer,
                "timestamp": str(datetime.now(tzn.utc))
            })
        else:
            chats = [{
                "userMessage": input,
                "aiMessage": answer,
                "timestamp": str(datetime.now(tzn.utc))
            }]

        if update:
            update_user_memory_redis(key, chats)
            print(f"✅ Memory updated for user: {user_id}", flush=True)
        
        return chats
    except Exception as e:
        print(f"❌ Error updating memory for user {user_id}: {e}", flush=True)
        set_sentry_context(user_id, input, answer, f"Error in add_user_chat_redis function: Failed to update memory", e)
        return []

def get_user_chat_redis(user_id) -> list:
    """
    Retrieve a user's memory from Redis.
    example chat:
    [
        {
            "userMessage": "hello",
            "aiMessage": "hi",
            "timestamp": "2025-06-12T08:15:00+07:00"
        }
    ]
    """
    try:
        key = f"chat:{user_id}"
        memory = get_secure(key)
        # memory = r.get(key)
        
        if memory:
            if isinstance(memory, str):
                memory = json.loads(memory)

            return memory
        else:
            return []
    except Exception as e:
        print(f"❌ Error retrieving memory for user {user_id}: {e}", flush=True)
        set_sentry_context(user_id, None, None, f"Error in get_user_chat_redis function: Failed to retrieve memory", e)
        return []

def delete_user_chat_redis(user_id, chats:list=[], update=True):
    """
    Delete a user's chat from Redis.
    """
    now = datetime.now(tzn.utc)
    try:
        key = f"chat:{user_id}"
        user_chats = chats
        
        if not chats:
            user_chats = get_secure(key)
            # user_chats = r.get(key)

        if user_chats:
            if isinstance(user_chats, str):
                user_chats = json.loads(user_chats)

            index_to_remove = []
            for index, chat in enumerate(user_chats):
                print(f"Checking chat {index} for user {user_id}: chat: {chat}", flush=True)
                ts = chat.get('timestamp')
                if not ts:
                    continue
                
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    except ValueError:
                        continue
                
                # check if this conversation is older than 24 hours
                if ts < (now - timedelta(hours=24)):
                    index_to_remove.append(index)

            # Remove chats in reverse order to avoid index shifting
            for index in reversed(index_to_remove):
                user_chats.pop(index)

            if update:
                update_user_memory_redis(key, user_chats)
            
            return user_chats
    except Exception as e:
        print(f"❌ Error deleting chat memory for user {user_id}: {e}", flush=True)
        set_sentry_context(user_id, None, None, f"Error in delete_user_chat_redis function: Failed to delete chat memory", e)
        return []

def add_and_delete_user_chat_redis(user_id, input, answer):
    """
    Add a new conversation to a user's memory and delete old conversations if necessary.
    """
    try:
        chats_after_delete = delete_user_chat_redis(user_id)
        add_user_chat_redis(user_id, input, answer, chats_after_delete, update=True)
        print(f"✅ Memory added and old conversations deleted for user: {user_id}", flush=True)
    except Exception as e:
        print(f"❌ Error in add_and_delete_user_chat_redis for user {user_id}: {e}", flush=True)
        set_sentry_context(user_id, input, answer, f"Error in add_and_delete_user_chat_redis function: Failed to add and delete user memory", e)

#### Redis Draft Functions ####

def get_latest_draft_redis(user_id) -> dict:
    """
    Retrieve the latest event draft for a user from Redis.
    """
    try:
        key = f"draft:{user_id}"
        draft = get_secure(key)
        # draft = r.get(key)
        
        if draft:
            if isinstance(draft, str):
                draft = json.loads(draft)
            return draft
        else:
            return {}
    except Exception as e:
        print(f"❌ Error retrieving latest draft for user {user_id}: {e}", flush=True)
        set_sentry_context(user_id, None, None, f"Error in get_latest_draft_redis function: Failed to retrieve latest draft", e)
        return {}
    
def add_event_draft_redis(user_id, draft:dict):
    """
    Add or update an event draft for a user in Redis.
    """
    try:
        key = f"draft:{user_id}"
        draft['timestamp'] = str(datetime.now(tzn.utc))
        add_secure(key, draft, ttl=60*60*24)  # store draft for 24 hours
        # r.set(key, json.dumps(draft))
        print(f"✅ Draft added/updated for user: {user_id}", flush=True)
        return draft
    except Exception as e:
        print(f"❌ Error adding/updating draft for user {user_id}: {e}", flush=True)
        set_sentry_context(user_id, None, None, f"Error in add_event_draft_redis function: Failed to add/update draft", e)

def delete_user_draft_redis(user_id):
    """
    Delete a user's event draft from Redis.
    """
    try:
        key = f"draft:{user_id}"
        r.delete(key)
        print(f"✅ Draft deleted for user: {user_id}", flush=True)
    except Exception as e:
        print(f"❌ Error deleting draft for user {user_id}: {e}", flush=True)
        set_sentry_context(user_id, None, None, f"Error in delete_user_draft_redis function: Failed to delete draft", e)

#### Redis Combination Functions ####

def get_latest_chat_and_draft_redis(user_id):
    """
    Retrieve the latest chat and event draft for a user from Redis.
    """
    try:
        chat = get_user_chat_redis(user_id)
        draft = get_latest_draft_redis(user_id)
        return chat, draft
    except Exception as e:
        print(f"❌ Error retrieving chat and draft for user {user_id}: {e}", flush=True)
        set_sentry_context(user_id, None, None, f"Error in get_latest_chat_and_draft_redis function: Failed to retrieve chat and draft", e)
        return [], {}
    
def clear_all_user_memories_redis():
    """
    Clear all user memories from Redis.
    """
    try:
        keys = r.keys("chat:*")
        if keys:
            r.delete(*keys)
            print("✅ All user memories cleared", flush=True)
        else:
            print("ℹ️ No user memories to clear", flush=True)
    except Exception as e:
        print(f"❌ Error clearing all user memories: {e}", flush=True)
        set_sentry_context(None, None, None, f"Error in clear_all_user_memories_redis function: Failed to clear all user memories", e)
    
def update_user_memory_redis(key, chats):
    """
    Update a user's chat memory with a new conversation.
    """
    try:
        add_secure(key, chats)
    except Exception as e:
        print(f"❌ Error in update_user_memory_redis for key {key}: {e}", flush=True)
        set_sentry_context(None, None, None, f"Error in update_user_memory_redis function: Failed to update user chat for key {key}", e)