import subprocess
import logging
import os
import json
import re

logger = logging.getLogger(__name__)


class Agent:
    def __init__(self, api_key: str = None, working_directory: str = None, skip_permissions: bool = True):
        """
        Initialize the Claude Code agent.

        Args:
            api_key: Anthropic API key (optional, Claude Code can use its own config)
            working_directory: Directory to run Claude Code in (default: home directory)
            skip_permissions: Skip permission prompts for full system access (default: True)
        """
        self.api_key = api_key
        self.working_directory = working_directory or os.path.expanduser("~")
        self.skip_permissions = skip_permissions
        self.conversations: dict[int, str] = {}  # user_id -> conversation_id

    def _run_claude_code(self, prompt: str, conversation_id: str = None) -> tuple[str, str | None]:
        """
        Run Claude Code with the given prompt.

        Args:
            prompt: The user's message/prompt
            conversation_id: Optional conversation ID to continue a session

        Returns:
            Tuple of (response_text, new_conversation_id)
        """
        # Build the command
        cmd = ["claude", "-p", prompt, "--output-format", "text"]

        # Skip permission prompts for full system access
        if self.skip_permissions:
            cmd.append("--dangerously-skip-permissions")

        # Continue conversation if we have an ID
        if conversation_id:
            cmd.extend(["--continue", conversation_id])

        # Set up environment
        env = os.environ.copy()
        if self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key

        logger.info(f"Running Claude Code: {' '.join(cmd[:4])}...")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",  # Replace undecodable chars instead of crashing
                timeout=300,  # 5 minute timeout
                cwd=self.working_directory,
                env=env,
            )

            output = result.stdout or ""
            if result.stderr:
                logger.warning(f"Claude Code stderr: {result.stderr}")

            # Try to extract conversation ID from output for continuation
            # Claude Code may output session info we can parse
            new_conversation_id = conversation_id  # Keep existing if we can't find new one

            if result.returncode != 0:
                error_msg = result.stderr or "Unknown error"
                return f"Error running Claude Code (exit code {result.returncode}):\n{error_msg}", None

            return output.strip() if output else "No output from Claude Code", new_conversation_id

        except subprocess.TimeoutExpired:
            return "Error: Claude Code timed out after 5 minutes", None
        except FileNotFoundError:
            return "Error: Claude Code CLI not found. Make sure 'claude' is installed and in PATH.", None
        except Exception as e:
            logger.exception(f"Error running Claude Code: {e}")
            return f"Error running Claude Code: {str(e)}", None

    def process_message(self, user_id: int, message: str) -> list[tuple[str | None, bytes | None]]:
        """
        Process a user message through Claude Code.

        Args:
            user_id: The Telegram user ID (for conversation tracking)
            message: The user's message

        Returns:
            List of (text, image_bytes) tuples to send back
        """
        # Get existing conversation ID if any
        conversation_id = self.conversations.get(user_id)

        # Run Claude Code
        response, new_conversation_id = self._run_claude_code(message, conversation_id)

        # Store conversation ID for continuation
        if new_conversation_id:
            self.conversations[user_id] = new_conversation_id

        # Check if response contains any image references (screenshots)
        # Claude Code might save screenshots to files
        image_bytes = None
        image_match = re.search(r'screenshot[s]?\s+saved?\s+(?:to|at)\s+["\']?([^"\'>\s]+)', response or "", re.IGNORECASE)
        if image_match:
            image_path = image_match.group(1)
            try:
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
            except Exception as e:
                logger.warning(f"Could not read screenshot at {image_path}: {e}")

        return [(response, image_bytes)]

    def clear_conversation(self, user_id: int) -> None:
        """Clear conversation history for a user."""
        if user_id in self.conversations:
            del self.conversations[user_id]
