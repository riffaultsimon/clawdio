import subprocess
import logging
import os
import re
import json
from dataclasses import dataclass, field
from datetime import datetime

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


def format_tool_use(tool_name: str, tool_input: dict) -> str:
    """Format a tool use for display."""
    is_mcp = ":" in tool_name or tool_name.startswith("mcp_")

    icon = ""
    if is_mcp:
        icon = "🔌"
    elif tool_name in ("Bash", "bash", "run_command"):
        icon = "💻"
    elif tool_name in ("Read", "read_file"):
        icon = "📖"
    elif tool_name in ("Write", "write_file"):
        icon = "✏️"
    elif tool_name in ("Edit", "edit_file"):
        icon = "📝"
    elif tool_name in ("Glob", "glob"):
        icon = "🔍"
    elif tool_name in ("Grep", "grep"):
        icon = "🔎"
    elif tool_name.lower().startswith("web") or "search" in tool_name.lower():
        icon = "🌐"
    else:
        icon = "🔧"

    summary = ""
    if tool_name in ("Bash", "bash", "run_command"):
        cmd = tool_input.get("command", "")
        if len(cmd) > 60:
            cmd = cmd[:57] + "..."
        summary = f"`{cmd}`"
    elif tool_name in ("Read", "read_file"):
        path = tool_input.get("path", tool_input.get("file_path", ""))
        summary = f"`{path}`"
    elif tool_name in ("Write", "write_file", "Edit", "edit_file"):
        path = tool_input.get("path", tool_input.get("file_path", ""))
        summary = f"`{path}`"
    elif tool_name in ("Glob", "glob"):
        pattern = tool_input.get("pattern", "")
        summary = f"`{pattern}`"
    elif tool_name in ("Grep", "grep"):
        pattern = tool_input.get("pattern", "")
        summary = f"`{pattern}`"
    elif "query" in tool_input:
        query = tool_input.get("query", "")
        if len(query) > 50:
            query = query[:47] + "..."
        summary = f'"{query}"'
    elif "url" in tool_input:
        summary = tool_input.get("url", "")
    else:
        for key, value in tool_input.items():
            if isinstance(value, str) and len(value) < 50:
                summary = f"{key}: {value}"
                break

    return f"{icon} **{tool_name}** {summary}"


def extract_tools_recursive(obj, tool_uses: list, thinking_blocks: list):
    """Recursively extract tool uses and thinking from nested structures."""
    if isinstance(obj, dict):
        obj_type = obj.get("type", "")

        # Check for tool_use type
        if obj_type == "tool_use" or obj_type == "tool_call":
            tool_name = obj.get("name", obj.get("tool", obj.get("function", {}).get("name", "unknown")))
            tool_input = obj.get("input", obj.get("args", obj.get("arguments", obj.get("function", {}).get("arguments", {}))))
            if isinstance(tool_input, str):
                try:
                    tool_input = json.loads(tool_input)
                except:
                    tool_input = {"raw": tool_input}
            tool_uses.append(format_tool_use(tool_name, tool_input))

        # Check for thinking type
        elif obj_type == "thinking":
            thinking = obj.get("thinking", obj.get("content", ""))
            if thinking and len(thinking) > 10:
                if len(thinking) > 200:
                    thinking = thinking[:197] + "..."
                thinking_blocks.append(thinking)

        # Recurse into all values
        for key, value in obj.items():
            if key in ("tool_calls", "tools", "tool_use", "messages", "content", "blocks"):
                extract_tools_recursive(value, tool_uses, thinking_blocks)

    elif isinstance(obj, list):
        for item in obj:
            extract_tools_recursive(item, tool_uses, thinking_blocks)


def parse_json_output(output: str) -> tuple[str, list[str], list[str], str | None]:
    """
    Parse Claude Code JSON output to extract response, tool uses, thinking, and session ID.

    Returns:
        Tuple of (final_response, tool_uses, thinking_blocks, session_id)
    """
    tool_uses = []
    thinking_blocks = []
    final_response = ""
    session_id = None

    try:
        data = json.loads(output)

        # Log the top-level keys for debugging
        if isinstance(data, dict):
            logger.debug(f"JSON top-level keys: {list(data.keys())}")

            # Extract session_id
            session_id = data.get("session_id")

            # Extract server tool usage from usage.server_tool_use
            usage = data.get("usage", {})
            server_tool_use = usage.get("server_tool_use", {})

            web_search = server_tool_use.get("web_search_requests", 0)
            web_fetch = server_tool_use.get("web_fetch_requests", 0)

            if web_search > 0:
                tool_uses.append(f"🌐 **Web Search** ({web_search} request{'s' if web_search > 1 else ''})")
            if web_fetch > 0:
                tool_uses.append(f"📄 **Web Fetch** ({web_fetch} request{'s' if web_fetch > 1 else ''})")

        # Recursively extract tools and thinking from entire structure
        extract_tools_recursive(data, tool_uses, thinking_blocks)

        if isinstance(data, dict):
            if "result" in data:
                final_response = data["result"]
            elif "response" in data:
                final_response = data["response"]
            elif "content" in data:
                content = data["content"]
                if isinstance(content, str):
                    final_response = content
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                final_response += block.get("text", "")
                            elif block.get("type") == "tool_use":
                                tool_name = block.get("name", "unknown")
                                tool_input = block.get("input", {})
                                tool_uses.append(format_tool_use(tool_name, tool_input))
                            elif block.get("type") == "thinking":
                                thinking = block.get("thinking", "")
                                if thinking:
                                    if len(thinking) > 200:
                                        thinking = thinking[:197] + "..."
                                    thinking_blocks.append(thinking)

            if "messages" in data:
                for msg in data["messages"]:
                    if isinstance(msg, dict):
                        content = msg.get("content", [])
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict):
                                    if block.get("type") == "tool_use":
                                        tool_name = block.get("name", "unknown")
                                        tool_input = block.get("input", {})
                                        tool_uses.append(format_tool_use(tool_name, tool_input))
                                    elif block.get("type") == "thinking":
                                        thinking = block.get("thinking", "")
                                        if thinking and len(thinking) > 10:
                                            if len(thinking) > 200:
                                                thinking = thinking[:197] + "..."
                                            thinking_blocks.append(thinking)

    except json.JSONDecodeError:
        for line in output.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    event_type = event.get("type", "")

                    if event_type == "tool_use" or "tool" in event_type.lower():
                        tool_name = event.get("name", event.get("tool", "unknown"))
                        tool_input = event.get("input", event.get("args", {}))
                        tool_uses.append(format_tool_use(tool_name, tool_input))

                    elif event_type == "thinking" or "think" in event_type.lower():
                        thinking = event.get("thinking", event.get("content", ""))
                        if thinking and len(thinking) > 10:
                            if len(thinking) > 200:
                                thinking = thinking[:197] + "..."
                            thinking_blocks.append(thinking)

                    elif event_type in ("text", "result", "response", "message"):
                        text = event.get("text", event.get("content", event.get("result", "")))
                        if text:
                            final_response += text

                    elif event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            final_response += delta.get("text", "")

            except json.JSONDecodeError:
                if not final_response:
                    final_response = line

    if not final_response:
        final_response = output

    return final_response, tool_uses, thinking_blocks, session_id


@dataclass
class ConversationMessage:
    """A message in the conversation history."""
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Conversation:
    """Conversation history for a user."""
    messages: list[ConversationMessage] = field(default_factory=list)
    max_messages: int = 10  # Keep last N message pairs

    def add_user_message(self, content: str):
        self.messages.append(ConversationMessage(role="user", content=content))
        self._trim()

    def add_assistant_message(self, content: str):
        self.messages.append(ConversationMessage(role="assistant", content=content))
        self._trim()

    def _trim(self):
        """Keep only recent messages to avoid context overflow."""
        max_items = self.max_messages * 2  # pairs of user/assistant
        if len(self.messages) > max_items:
            self.messages = self.messages[-max_items:]

    def get_context(self) -> str:
        """Get conversation history as context string."""
        if not self.messages:
            return ""

        lines = ["Previous conversation:"]
        for msg in self.messages[:-1]:  # Exclude the current message
            prefix = "User" if msg.role == "user" else "Assistant"
            # Truncate long messages in history
            content = msg.content
            if len(content) > 500:
                content = content[:497] + "..."
            lines.append(f"{prefix}: {content}")

        return "\n".join(lines)

    def clear(self):
        self.messages = []


class Agent:
    def __init__(self, api_key: str = None, working_directory: str = None, skip_permissions: bool = True, verbose: bool = True):
        """
        Initialize the Claude Code agent.

        Args:
            api_key: Anthropic API key (optional, Claude Code can use its own config)
            working_directory: Directory to run Claude Code in (default: home directory)
            skip_permissions: Skip permission prompts for full system access (default: True)
            verbose: Show tool usage and thinking in responses (default: True)
        """
        self.api_key = api_key
        self.working_directory = working_directory or os.path.expanduser("~")
        self.skip_permissions = skip_permissions
        self.verbose = verbose
        self.conversations: dict[int, Conversation] = {}
        self.session_ids: dict[int, str] = {}  # user_id -> Claude Code session_id

    def _get_conversation(self, user_id: int) -> Conversation:
        """Get or create conversation for a user."""
        if user_id not in self.conversations:
            self.conversations[user_id] = Conversation()
        return self.conversations[user_id]

    def _run_claude_code(self, prompt: str, session_id: str = None) -> tuple[str, list[str], list[str], str | None]:
        """
        Run Claude Code with the given prompt.

        Args:
            prompt: The user's message/prompt
            session_id: Optional session ID to continue conversation

        Returns:
            Tuple of (response_text, tool_uses, thinking_blocks, new_session_id)
        """
        # Build the command
        cmd = ["claude", "-p", prompt, "--output-format", "json"]

        # Continue existing session if we have one
        if session_id:
            cmd.extend(["--continue", session_id])
            logger.info(f"Continuing session: {session_id[:8]}...")

        # Add security system prompt
        cmd.extend(["--append-system-prompt", SECURITY_PROMPT])

        # Skip permission prompts for full system access
        if self.skip_permissions:
            cmd.append("--dangerously-skip-permissions")

        # Set up environment
        env = os.environ.copy()
        if self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key

        logger.info(f"Running Claude Code...")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                cwd=self.working_directory,
                env=env,
            )

            output = result.stdout or ""
            if result.stderr:
                logger.warning(f"Claude Code stderr: {result.stderr}")

            if result.returncode != 0:
                error_msg = result.stderr or "Unknown error"
                return f"Error running Claude Code (exit code {result.returncode}):\n{error_msg}", [], [], None

            # Log first part of raw output for debugging
            logger.debug(f"Raw output (first 1000 chars): {output[:1000]}")

            # Parse JSON output for transparency and session ID
            response, tool_uses, thinking, new_session_id = parse_json_output(output)

            # SECURITY: Redact any secrets
            response = redact_secrets(response.strip()) if response else "No output from Claude Code"

            logger.info(f"Response length: {len(response)}, Tools used: {len(tool_uses)}, Session: {new_session_id[:8] if new_session_id else 'None'}...")

            return response, tool_uses, thinking, new_session_id

        except subprocess.TimeoutExpired:
            return "Error: Claude Code timed out after 5 minutes", [], [], None
        except FileNotFoundError:
            return "Error: Claude Code CLI not found. Make sure 'claude' is installed and in PATH.", [], [], None
        except Exception as e:
            logger.exception(f"Error running Claude Code: {e}")
            return f"Error running Claude Code: {str(e)}", [], [], None

    def process_message(self, user_id: int, message: str) -> list[tuple[str | None, bytes | None]]:
        """
        Process a user message through Claude Code.

        Args:
            user_id: The Telegram user ID (for conversation tracking)
            message: The user's message

        Returns:
            List of (text, image_bytes) tuples to send back
        """
        # Get existing session ID for this user
        session_id = self.session_ids.get(user_id)

        # Run Claude Code with session continuation
        response, tool_uses, thinking, new_session_id = self._run_claude_code(message, session_id)

        # Store new session ID for future messages
        if new_session_id:
            self.session_ids[user_id] = new_session_id

        # Build the formatted response
        parts = []

        # Add thinking summary if verbose
        if self.verbose and thinking:
            parts.append("🧠 **Thinking:**")
            for thought in thinking[:3]:
                parts.append(f"_{thought}_")
            parts.append("")

        # Add tool uses if verbose
        if self.verbose and tool_uses:
            parts.append("⚙️ **Actions:**")
            for tool in tool_uses[:10]:
                parts.append(f"  • {tool}")
            if len(tool_uses) > 10:
                parts.append(f"  _...and {len(tool_uses) - 10} more_")
            parts.append("")

        # Add separator if we had transparency info
        if parts:
            parts.append("───────────────")
            parts.append("")

        # Add the main response
        parts.append(response)

        formatted_response = "\n".join(parts)

        # Check for screenshots
        image_bytes = None
        image_match = re.search(r'screenshot[s]?\s+saved?\s+(?:to|at)\s+["\']?([^"\'>\s]+)', response or "", re.IGNORECASE)
        if image_match:
            image_path = image_match.group(1)
            try:
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
            except Exception as e:
                logger.warning(f"Could not read screenshot at {image_path}: {e}")

        return [(formatted_response, image_bytes)]

    def clear_conversation(self, user_id: int) -> None:
        """Clear conversation history for a user."""
        if user_id in self.conversations:
            self.conversations[user_id].clear()
        if user_id in self.session_ids:
            del self.session_ids[user_id]
            logger.info(f"Cleared session for user {user_id}")
