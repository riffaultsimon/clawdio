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
from .ollama_agent import OllamaAgent

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(
        self,
        token: str,
        agent: Agent,
        allowed_user_ids: set[int],
        ollama_agent: OllamaAgent = None,
    ):
        self.token = token
        self.agent = agent
        self.ollama_agent = ollama_agent
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

        ollama_status = ""
        if self.ollama_agent:
            ollama_status = (
                f"\n\nOllama Commands:\n"
                f"/ollama <msg> - Chat with {self.ollama_agent.model}\n"
                f"/ollama_models - List models\n"
                f"/ollama_model <name> - Switch model\n"
                f"/ollama_clear - Clear Ollama chat"
            )

        await update.message.reply_text(
            f"Hello {user_name}! I'm Clawdio, your remote assistant.\n\n"
            f"Claude Code commands:\n"
            f"- Just send a message for Claude Code\n"
            f"/clear - Reset Claude conversation\n"
            f"/status - Check Claude Code status"
            f"{ollama_status}"
        )

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /clear command to reset conversation history."""
        user_id = update.effective_user.id

        if not self._is_authorized(user_id):
            return

        self.agent.clear_conversation(user_id)
        await update.message.reply_text("Claude Code conversation cleared!")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /status command to check Claude Code availability."""
        user_id = update.effective_user.id

        if not self._is_authorized(user_id):
            return

        import subprocess
        status_parts = []

        # Check Claude Code
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                status_parts.append(
                    f"Claude Code: Available\n"
                    f"Version: {version}\n"
                    f"Working dir: {self.agent.working_directory}"
                )
            else:
                status_parts.append(f"Claude Code: Error\n{result.stderr}")
        except FileNotFoundError:
            status_parts.append("Claude Code: Not found")
        except Exception as e:
            status_parts.append(f"Claude Code: Error - {str(e)}")

        # Check Ollama
        if self.ollama_agent:
            models = self.ollama_agent.list_models()
            if "Error" in models:
                status_parts.append(f"\nOllama: Not running")
            else:
                status_parts.append(
                    f"\nOllama: Available\n"
                    f"URL: {self.ollama_agent.base_url}\n"
                    f"Active model: {self.ollama_agent.model}"
                )

        await update.message.reply_text("\n".join(status_parts))

    # ============ Ollama Commands ============

    async def ollama_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /ollama command to chat with Ollama."""
        user_id = update.effective_user.id

        if not self._is_authorized(user_id):
            return

        if not self.ollama_agent:
            await update.message.reply_text("Ollama is not configured.")
            return

        # Get the message after /ollama
        message_text = " ".join(context.args) if context.args else ""
        if not message_text:
            await update.message.reply_text(
                f"Usage: /ollama <your message>\n"
                f"Current model: {self.ollama_agent.model}"
            )
            return

        logger.info(f"Ollama message from user {user_id}: {message_text[:100]}...")

        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing"
        )

        processing_msg = await update.message.reply_text(
            f"Processing with Ollama ({self.ollama_agent.model})..."
        )

        try:
            response = self.ollama_agent.process_message(user_id, message_text)
            await processing_msg.delete()

            # Send response, splitting if too long
            max_length = 4096
            if len(response) <= max_length:
                await update.message.reply_text(response)
            else:
                for i in range(0, len(response), max_length):
                    chunk = response[i:i + max_length]
                    await update.message.reply_text(chunk)

        except Exception as e:
            logger.exception(f"Error processing Ollama message: {e}")
            try:
                await processing_msg.delete()
            except:
                pass
            await update.message.reply_text(f"Ollama error:\n{str(e)}")

    async def ollama_models_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /ollama_models command to list available models."""
        user_id = update.effective_user.id

        if not self._is_authorized(user_id):
            return

        if not self.ollama_agent:
            await update.message.reply_text("Ollama is not configured.")
            return

        models = self.ollama_agent.list_models()
        await update.message.reply_text(models)

    async def ollama_model_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /ollama_model command to switch models."""
        user_id = update.effective_user.id

        if not self._is_authorized(user_id):
            return

        if not self.ollama_agent:
            await update.message.reply_text("Ollama is not configured.")
            return

        model_name = " ".join(context.args) if context.args else ""
        if not model_name:
            await update.message.reply_text(
                f"Usage: /ollama_model <model_name>\n"
                f"Current model: {self.ollama_agent.model}\n\n"
                f"Use /ollama_models to see available models."
            )
            return

        result = self.ollama_agent.set_model(model_name)
        await update.message.reply_text(result)

    async def ollama_clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /ollama_clear command to reset Ollama conversation."""
        user_id = update.effective_user.id

        if not self._is_authorized(user_id):
            return

        if not self.ollama_agent:
            await update.message.reply_text("Ollama is not configured.")
            return

        self.ollama_agent.clear_conversation(user_id)
        await update.message.reply_text("Ollama conversation cleared!")

    # ============ Main Message Handler ============

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text messages (routes to Claude Code)."""
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

        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing"
        )

        processing_msg = await update.message.reply_text("Processing with Claude Code...")

        try:
            responses = self.agent.process_message(user_id, message_text)
            await processing_msg.delete()

            for text, image in responses:
                if image is not None:
                    await update.message.reply_photo(
                        photo=io.BytesIO(image),
                        caption="Screenshot"
                    )
                if text:
                    max_length = 4096
                    if len(text) <= max_length:
                        await update.message.reply_text(text)
                    else:
                        for i in range(0, len(text), max_length):
                            chunk = text[i:i + max_length]
                            await update.message.reply_text(chunk)

        except Exception as e:
            logger.exception(f"Error processing message: {e}")
            try:
                await processing_msg.delete()
            except:
                pass
            await update.message.reply_text(f"Sorry, an error occurred:\n{str(e)}")

    def run(self) -> None:
        """Start the bot."""
        logger.info("Starting Telegram bot...")

        self.application = Application.builder().token(self.token).build()

        # Claude Code handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("clear", self.clear_command))
        self.application.add_handler(CommandHandler("status", self.status_command))

        # Ollama handlers
        self.application.add_handler(CommandHandler("ollama", self.ollama_command))
        self.application.add_handler(CommandHandler("ollama_models", self.ollama_models_command))
        self.application.add_handler(CommandHandler("ollama_model", self.ollama_model_command))
        self.application.add_handler(CommandHandler("ollama_clear", self.ollama_clear_command))

        # Default message handler (Claude Code)
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        logger.info("Bot is running. Press Ctrl+C to stop.")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)
