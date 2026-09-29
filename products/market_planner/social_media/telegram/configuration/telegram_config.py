"""Configuration constants for Telegram bot."""

import os


def get_bot_token():
    """Get BOT_TOKEN from environment variable. Raises error if not set."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")
    return token


# Telegram Bot Configuration
# Note: BOT_TOKEN is now accessed via get_bot_token() function for lazy evaluation
# This prevents validation errors at import time when env var is not set

BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "marketiing_pandeybot")

# Approval Configuration
DEFAULT_WAIT_TIME = 7200  # 2 hours in seconds

