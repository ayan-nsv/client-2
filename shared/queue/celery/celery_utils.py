from shared.logger import log

logger = log.setup_logger("marketing-app")

def celery_on_message(body):
    logger.warn(body)

def background_on_message(task):
    logger.warn(task.get(on_message=celery_on_message, propagate=False))
