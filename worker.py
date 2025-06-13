from helperFiles.redis_helper import r_worker
from rq import Worker, Queue

if __name__ == "__main__":
    worker = Worker(queues=["kalenda"], connection=r_worker)
    worker.work()