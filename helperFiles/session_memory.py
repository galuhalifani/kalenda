from datetime import datetime, timedelta, timezone as tzn

## DEPRECATED: This file is no longer used in the current implementation.

latest_event_draft = [{
    "user_id": "id123",
    "details": {
        "name": 'test event',
        "start_date": '2025-06-12T08:15:00+07:00',
        "end_date": '2025-06-12T09:00:00+07:00',
        "location": 'Jakarta',
        "description": 'No description',
        "reminder": None,
        "participants": [],
        "status": 'draft'
    }
}]

session_memories = [{
    "user_id": "id123",
    "latest_conversations": [
        {
            "userMessage": "hello",
            "aiMessage": "hi",
            "timestamp": "2025-06-12T08:15:00+07:00"
        }
    ],
    "latest_event_draft": {
        "name": 'test event',
        "start_date": '2025-06-12T08:15:00+07:00',
        "end_date": '2025-06-12T09:00:00+07:00',
        "location": 'Jakarta',
        "description": 'No description',
        "reminder": None,
        "participants": [],
        "status": 'draft'
    }
}]

max_chat_stored = 3

def add_user_memory(user_id, input, answer):
    """
    Add a new conversation to a user's memory or create a new memory entry.
    """
    print(f"########### Adding memory for user: {user_id}", flush=True)
    try:
        global session_memories
        index, memory = get_user_memory(user_id)
        if memory:
            if 'latest_conversations' not in memory:
                session_memories[index]['latest_conversations'] = []
            else:
                if len(memory['latest_conversations']) > max_chat_stored:
                    session_memories[index]['latest_conversations'].pop(0)

            session_memories[index]['latest_conversations'].append({
                "userMessage": input,
                "aiMessage": answer,
                "timestamp": datetime.now(tzn.utc)
            })
            print(f"########### Memory appended", flush=True)
        else:
            session_memories.append({
                "user_id": user_id,
                "latest_conversations": [{
                    "userMessage": input,
                    "aiMessage": answer,
                    "timestamp": datetime.now(tzn.utc)
                }],
                "latest_event_draft": {}
            })
    except Exception as e:
        print(f"########### Error adding memory: {e}", flush=True)

def get_user_memory(user_id):
    try:
        for index, memory in enumerate(session_memories):
            if memory['user_id'] == user_id:
                return index, memory
        return None, None
    except Exception as e:
        print(f"########### Error getting user memory: {e}", flush=True)
        return None, None

def delete_user_memory(user_id):
    """
    Check if any conversation for this user is older than 24 hours.
    If yes, delete all memory for this user.
    """
    try:
        _, memory = get_user_memory(user_id)

        if not memory or not memory.get('latest_conversations'):
            return

        now = datetime.now(tzn.utc)
        should_delete = False
        
        # Check each conversation timestamp
        for conversation in memory['latest_conversations']:
            ts = conversation.get('timestamp')
            if not ts:
                continue
                
            # Convert string timestamp to datetime if needed
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                except ValueError:
                    continue
                    
            # Check if this conversation is older than 24 hours
            if ts < (now - timedelta(hours=24)):
                should_delete = True
                break
        
        # Delete memory if any conversation is older than 24 hours
        if should_delete:
            print(f"########### Memory expired for user: {user_id}", flush=True)
            global session_memories
            session_memories = [m for m in session_memories if m['user_id'] != user_id]
            print(f"########### Memory deleted for user: {user_id}", flush=True)
        else:
            print(f"########### Memory still valid for user: {user_id}", flush=True)
    except Exception as e:
        print(f"########### Error deleting user memory: {e}", flush=True)

def get_latest_memory(user_id):
    try:
        _, memory = get_user_memory(user_id)
        if memory:
            print(f"########### Memory found for user: {user_id} -- memory: {memory}", flush=True)
            latest_draft = memory.get('latest_event_draft', {})
            latest_draft_status = latest_draft.get('status') if latest_draft else None
            user_latest_event_draft = latest_draft if latest_draft_status == 'draft' else {}
            print(f"########### User latest event draft: {user_latest_event_draft}", flush=True)
            latest_conversations = memory.get('latest_conversations', [])
            print(f"########### User latest conversations: {latest_conversations}", flush=True)
            return latest_conversations, user_latest_event_draft
        print(f"########### No memory found for user: {user_id}", flush=True)
        return [], {}
    except Exception as e:
        print(f"########### Error getting latest memory: {e}", flush=True)
        return [], {}
