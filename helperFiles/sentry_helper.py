from sentry_sdk import set_user, set_context, capture_message, capture_exception

def set_sentry_context(user_id=None, input=None, answer=None, message=None, error=None):
    """
    Set the Sentry context for the user.
    """
    if user_id:
        set_user({"id": user_id})
    if input:
        set_context("input", {"message": input})
    if answer:
        set_context("output", {"message": answer})
    if message:
        capture_message(message)
    if error:
        capture_exception(error)
