import io
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from .agent import Agent

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, token: str, agent: Agent, allowed_user_ids: set[int]):
        self.token = token
        self.agent = agent
        self.allowed_user_ids = allowed_user_ids
        self.application = None

    def _is_authorized(self, user_id: int) -> bool:
        """Check if a user is authorized to use the bot."""
        return user_id in self.allowed_user_ids

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command."""
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name

        if not self._is_authorized(user_id):
            logger.warning(f"Unauthorized access attempt from user {user_id}")
            await update.message.reply_text(
                f"Sorry, you are not authorized to use this bot.\n"
                f"Your user ID is: {user_id}"
            )
            return

        logger.info(f"User {user_id} ({user_name}) started the bot")
        await update.message.reply_text(
            f"Hello {user_name}! I'm Clawdio, your remote Claude Code assistant.\n\n"
            f"I run Claude Code on your Mac Mini with full system access. "
            f"Claude Code can:\n"
            f"- Read and edit files\n"
            f"- Run shell commands\n"
            f"- Search your codebase\n"
            f"- Help with coding tasks\n"
            f"- And much more!\n\n"
            f"Just tell me what you need!\n\n"
            f"Commands:\n"
            f"/clear - Reset conversation\n"
            f"/status - Check Claude Code status"
        )

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /clear command to reset conversation history."""
        user_id = update.effective_user.id

        if not self._is_authorized(user_id):
            return

        self.agent.clear_conversation(user_id)
        await update.message.reply_text("Conversation cleared. Starting fresh!")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /status command to check Claude Code availability."""
        user_id = update.effective_user.id

        if not self._is_authorized(user_id):
            return

        import subprocess
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                await update.message.reply_text(
                    f"Claude Code is available!\n"
                    f"Version: {version}\n"
                    f"Working directory: {self.agent.working_directory}"
                )
            else:
                await update.message.reply_text(
                    f"Claude Code returned an error:\n{result.stderr}"
                )
        except FileNotFoundError:
            await update.message.reply_text(
                "Claude Code CLI not found. Make sure 'claude' is installed and in PATH."
            )
        except Exception as e:
            await update.message.reply_text(f"Error checking status: {str(e)}")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text messages."""
        user_id = update.effective_user.id
        message_text = update.message.text

        if not self._is_authorized(user_id):
            logger.warning(f"Unauthorized message from user {user_id}: {message_text[:50]}...")
            await update.message.reply_text(
                f"Sorry, you are not authorized to use this bot.\n"
                f"Your user ID is: {user_id}"
            )
            return

        logger.info(f"Message from user {user_id}: {message_text[:100]}...")

        # Send typing indicator
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing"
        )

        # Send a "processing" message since Claude Code can take a while
        processing_msg = await update.message.reply_text("Processing with Claude Code...")

        try:
            # Process the message through Claude Code
            responses = self.agent.process_message(user_id, message_text)

            # Delete the processing message
            await processing_msg.delete()

            # Send all responses
            for text, image in responses:
                if image is not None:
                    # Send screenshot as photo
                    await update.message.reply_photo(
                        photo=io.BytesIO(image),
                        caption="Screenshot"
                    )
                if text:
                    # Send text response, splitting if too long
                    max_length = 4096  # Telegram's max message length

                    if len(text) <= max_length:
                        await update.message.reply_text(text)
                    else:
                        # Split into chunks
                        for i in range(0, len(text), max_length):
                            chunk = text[i:i + max_length]
                            await update.message.reply_text(chunk)

        except Exception as e:
            logger.exception(f"Error processing message: {e}")
            try:
                await processing_msg.delete()
            except:
                pass
            await update.message.reply_text(
                f"Sorry, an error occurred:\n{str(e)}"
            )

    def run(self) -> None:
        """Start the bot."""
        logger.info("Starting Telegram bot...")

        # Create application
        self.application = Application.builder().token(self.token).build()

        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("clear", self.clear_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        # Start polling
        logger.info("Bot is running. Press Ctrl+C to stop.")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)
