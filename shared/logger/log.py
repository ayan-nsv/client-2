
import logging
import re


class RedactingFilter(logging.Filter):
    """Redact secrets and customer-contact fields from log messages."""

    _TOKEN_PATTERNS = [
        # Authorization/Bearer style headers and values
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-\._~\+/]+=*"),
        re.compile(r'(?i)\b(Authorization)\b(\s*[:=]\s*)(["\']?)[^,"\'}\s]+(?:\s+[^\s,"\'}]+)?\3'),
        # Key/value fields
        re.compile(
            r'(?i)\b('
            r'access_token|refresh_token|long_lived_token|x-api-key|api_key|client_secret|'
            r'customer_name|customer_phone|customer_number|to_email|owner_email|'
            r'phone_number|phone|email|password|secret'
            r')\b(\s*[:=]\s*)(["\']?)([^,"\'}\]]*)\3'
        ),
    ]
    _PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d{7,15}(?!\w)")
    _EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b")

    def _redact(self, text: str) -> str:
        redacted = text
        redacted = self._TOKEN_PATTERNS[0].sub("Bearer [REDACTED]", redacted)
        redacted = self._TOKEN_PATTERNS[1].sub(r"\1\2\3[REDACTED]\3", redacted)
        redacted = self._TOKEN_PATTERNS[2].sub(r"\1\2\3[REDACTED]\3", redacted)
        redacted = self._PHONE_PATTERN.sub("[REDACTED_PHONE]", redacted)
        redacted = self._EMAIL_PATTERN.sub("[REDACTED_EMAIL]", redacted)
        return redacted

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            redacted = self._redact(msg)
            if redacted != msg:
                record.msg = redacted
                record.args = ()
        except Exception:
            # Never block logging due to redaction errors.
            pass
        return True


def _attach_redaction_filter(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())

def setup_logger(name: str = "app", level=logging.INFO):
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:  # Prevent adding duplicate handlers
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    _attach_redaction_filter(logger)
    _attach_redaction_filter(logging.getLogger())

    logger.propagate = False  
    return logger
