import logging
import sys

from .config import get_config
from .agent import Agent
from .ollama_agent import OllamaAgent
from .telegram_bot import TelegramBot
from .avatar_gui import AvatarWindow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


def main():
    """Main entry point for Clawdio."""
    logger.info("Starting Clawdio - Remote Claude Code Assistant")

    try:
        # Load configuration
        config = get_config()
        logger.info(f"Configuration loaded. Allowed users: {config['allowed_user_ids']}")

        # Initialize the Claude Code agent
        agent = Agent(
            api_key=config["anthropic_key"],
            working_directory=config["working_directory"],
        )
        logger.info(f"Claude Code agent initialized (working dir: {agent.working_directory})")

        # Initialize Ollama agent
        ollama_agent = OllamaAgent(
            base_url=config["ollama_url"],
            model=config["ollama_model"],
        )
        logger.info(f"Ollama agent initialized (model: {ollama_agent.model})")

        # Initialize and start the avatar GUI
        avatar = AvatarWindow()
        avatar.start()
        logger.info("Avatar GUI started")

        # Initialize and run the Telegram bot
        bot = TelegramBot(
            token=config["telegram_token"],
            agent=agent,
            allowed_user_ids=config["allowed_user_ids"],
            ollama_agent=ollama_agent,
            avatar=avatar,
        )

        # Run the bot (this blocks until stopped)
        try:
            bot.run()
        finally:
            avatar.stop()

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
