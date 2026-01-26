import os
from dotenv import load_dotenv

load_dotenv()


def get_config():
    """Load and validate configuration from environment variables."""
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")  # Optional for Claude Code
    allowed_users = os.getenv("ALLOWED_USER_IDS", "")
    working_directory = os.getenv("WORKING_DIRECTORY")

    if not telegram_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

    allowed_user_ids = set()
    if allowed_users:
        for user_id in allowed_users.split(","):
            user_id = user_id.strip()
            if user_id:
                allowed_user_ids.add(int(user_id))

    if not allowed_user_ids:
        raise ValueError("ALLOWED_USER_IDS must contain at least one user ID")

    return {
        "telegram_token": telegram_token,
        "anthropic_key": anthropic_key,  # Can be None
        "allowed_user_ids": allowed_user_ids,
        "working_directory": working_directory,
    }
