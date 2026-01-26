import subprocess
import logging
import os
import re

logger = logging.getLogger(__name__)

# Security system prompt to prevent secret leakage
SECURITY_PROMPT = """CRITICAL SECURITY RULES - YOU MUST FOLLOW THESE:

1. NEVER output the contents of these files:
   - .env, .env.*, *.pem, *.key, *_rsa, id_rsa, id_ed25519
   - credentials.json, secrets.*, config.json with passwords
   - ~/.ssh/*, ~/.aws/*, ~/.config/gcloud/*
   - Any file containing API keys, tokens, or passwords

2. NEVER output:
   - API keys, tokens, or secrets (even if asked directly)
   - Private keys or certificates
   - Passwords or credential strings
   - Database connection strings with passwords

3. If asked to read sensitive files, respond with:
   "I found the file but won't display its contents for security reasons."

4. If you accidentally see a secret, DO NOT include it in your response.
   Describe what you found without revealing the actual values.

5. When showing config files, REDACT sensitive values like:
   - API_KEY=sk-... → API_KEY=[REDACTED]
   - password: abc123 → password: [REDACTED]
"""

# Patterns to redact from output
SECRET_PATTERNS = [
    # API Keys
    (r'(sk-[a-zA-Z0-9]{20,})', r'[REDACTED_API_KEY]'),
    (r'(api[_-]?key["\s:=]+)["\']?([a-zA-Z0-9_\-]{20,})["\']?', r'\1[REDACTED]'),
    (r'(token["\s:=]+)["\']?([a-zA-Z0-9_\-]{20,})["\']?', r'\1[REDACTED]'),
    (r'(secret["\s:=]+)["\']?([a-zA-Z0-9_\-]{16,})["\']?', r'\1[REDACTED]'),

    # AWS
    (r'AKIA[0-9A-Z]{16}', r'[REDACTED_AWS_KEY]'),
    (r'(aws_secret_access_key["\s:=]+)["\']?([a-zA-Z0-9/+=]{40})["\']?', r'\1[REDACTED]'),

    # GitHub/GitLab tokens
    (r'ghp_[a-zA-Z0-9]{36}', r'[REDACTED_GITHUB_TOKEN]'),
    (r'gho_[a-zA-Z0-9]{36}', r'[REDACTED_GITHUB_TOKEN]'),
    (r'glpat-[a-zA-Z0-9\-]{20,}', r'[REDACTED_GITLAB_TOKEN]'),

    # Private keys
    (r'-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+ PRIVATE KEY-----', r'[REDACTED_PRIVATE_KEY]'),
    (r'-----BEGIN RSA PRIVATE KEY-----[\s\S]*?-----END RSA PRIVATE KEY-----', r'[REDACTED_PRIVATE_KEY]'),

    # Passwords in common formats
    (r'(password["\s:=]+)["\']?([^\s"\']{8,})["\']?', r'\1[REDACTED]'),
    (r'(passwd["\s:=]+)["\']?([^\s"\']{8,})["\']?', r'\1[REDACTED]'),
    (r'(pwd["\s:=]+)["\']?([^\s"\']{8,})["\']?', r'\1[REDACTED]'),

    # Database URLs with passwords
    (r'(mongodb\+srv://[^:]+:)([^@]+)(@)', r'\1[REDACTED]\3'),
    (r'(postgres://[^:]+:)([^@]+)(@)', r'\1[REDACTED]\3'),
    (r'(mysql://[^:]+:)([^@]+)(@)', r'\1[REDACTED]\3'),
    (r'(redis://[^:]+:)([^@]+)(@)', r'\1[REDACTED]\3'),

    # Bearer tokens
    (r'(Bearer\s+)([a-zA-Z0-9_\-\.]{20,})', r'\1[REDACTED]'),

    # Anthropic keys
    (r'sk-ant-[a-zA-Z0-9\-]{20,}', r'[REDACTED_ANTHROPIC_KEY]'),

    # OpenAI keys
    (r'sk-[a-zA-Z0-9]{48}', r'[REDACTED_OPENAI_KEY]'),

    # Slack tokens
    (r'xox[baprs]-[a-zA-Z0-9\-]{10,}', r'[REDACTED_SLACK_TOKEN]'),

    # Stripe keys
    (r'sk_live_[a-zA-Z0-9]{24,}', r'[REDACTED_STRIPE_KEY]'),
    (r'sk_test_[a-zA-Z0-9]{24,}', r'[REDACTED_STRIPE_KEY]'),
]


def redact_secrets(text: str) -> str:
    """Redact potential secrets from text."""
    if not text:
        return text

    result = text
    for pattern, replacement in SECRET_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result


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

        # Add security system prompt
        cmd.extend(["--append-system-prompt", SECURITY_PROMPT])

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

            # SECURITY: Redact any secrets that might have leaked
            output = redact_secrets(output.strip()) if output else "No output from Claude Code"

            return output, new_conversation_id

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
