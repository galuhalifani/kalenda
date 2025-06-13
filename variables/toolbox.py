tools = [
    {
        "type": "function",
        "function": {
            "name": "save_event_to_draft",
            "description": "Save a draft event for the user to review",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string"},
                },
                "required": ["instruction"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_confirmed_event_to_calendar",
            "description": "Save a confirmed event to the user's calendar",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string"},
                },
                "required": ["instruction"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_upcoming_events",
            "description": "Fetch upcoming events for a user",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string"},
                },
                "required": ["instruction"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_timezone",
            "description": "Update user's timezone",
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                },
                "required": ["answer"]
            }
        }
    }
]