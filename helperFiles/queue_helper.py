from rq import Queue
from helperFiles.redis_helper import r_worker
from helperFiles.sentry_helper import set_sentry_context

q = Queue("kalenda", connection=r_worker)

def safe_enqueue(func, *args, **kwargs):
    try:
        print("Adding interaction to queue")
        return q.enqueue(func, *args, **kwargs)
    except Exception as e:
        print("RQ failed, running locally")
        set_sentry_context(None, None, None, f"Error in adding interaction to queue -- running locally", e)
        return func(*args, **kwargs)
