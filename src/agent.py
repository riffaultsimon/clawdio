import subprocess
import logging
import os
import re
import json

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
    # Identify MCP tools (they usually have a server prefix)
    is_mcp = ":" in tool_name or tool_name.startswith("mcp_")

    icon = ""
    if is_mcp:
        icon = "🔌"  # MCP tool
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

    # Format the input summary
    summary = ""
    if tool_name in ("Bash", "bash", "run_command"):
        cmd = tool_input.get("command", "")
        # Truncate long commands
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
        # Generic: show first key-value pair
        for key, value in tool_input.items():
            if isinstance(value, str) and len(value) < 50:
                summary = f"{key}: {value}"
                break

    return f"{icon} **{tool_name}** {summary}"


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
        # Try to parse as a single JSON object first
        data = json.loads(output)

        # Handle different JSON structures
        if isinstance(data, dict):
            # Extract session ID (try various possible field names)
            session_id = (
                data.get("session_id") or
                data.get("sessionId") or
                data.get("session") or
                data.get("conversation_id") or
                data.get("conversationId") or
                data.get("conversation") or
                data.get("thread_id") or
                data.get("threadId") or
                data.get("id") or
                data.get("uuid")
            )

            # Log the keys for debugging if no session ID found
            if not session_id:
                logger.debug(f"JSON keys available: {list(data.keys())}")

            # Check for result field
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
                                    # Truncate long thinking
                                    if len(thinking) > 200:
                                        thinking = thinking[:197] + "..."
                                    thinking_blocks.append(thinking)

            # Check for messages array
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
        # Try parsing as newline-delimited JSON (stream format)
        for line in output.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    event_type = event.get("type", "")

                    # Extract session ID from any event
                    if not session_id:
                        session_id = (
                            event.get("session_id") or
                            event.get("sessionId") or
                            event.get("conversation_id") or
                            event.get("conversationId") or
                            event.get("id")
                        )

                    # Tool use events
                    if event_type == "tool_use" or "tool" in event_type.lower():
                        tool_name = event.get("name", event.get("tool", "unknown"))
                        tool_input = event.get("input", event.get("args", {}))
                        tool_uses.append(format_tool_use(tool_name, tool_input))

                    # Thinking events
                    elif event_type == "thinking" or "think" in event_type.lower():
                        thinking = event.get("thinking", event.get("content", ""))
                        if thinking and len(thinking) > 10:
                            if len(thinking) > 200:
                                thinking = thinking[:197] + "..."
                            thinking_blocks.append(thinking)

                    # Text/result events
                    elif event_type in ("text", "result", "response", "message"):
                        text = event.get("text", event.get("content", event.get("result", "")))
                        if text:
                            final_response += text

                    # Content delta events (streaming)
                    elif event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            final_response += delta.get("text", "")

            except json.JSONDecodeError:
                # Not JSON, might be plain text
                if not final_response:
                    final_response = line

    # If we still don't have a response, use the raw output
    if not final_response:
        final_response = output

    return final_response, tool_uses, thinking_blocks, session_id


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
        self.conversations: dict[int, str] = {}  # user_id -> conversation_id

    def _run_claude_code(self, prompt: str, conversation_id: str = None) -> tuple[str, str | None, list[str], list[str]]:
        """
        Run Claude Code with the given prompt.

        Args:
            prompt: The user's message/prompt
            conversation_id: Optional conversation ID to continue a session

        Returns:
            Tuple of (response_text, new_conversation_id, tool_uses, thinking_blocks)
        """
        # Build the command - use JSON format for transparency
        cmd = ["claude", "-p", prompt, "--output-format", "json"]

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
                return f"Error running Claude Code (exit code {result.returncode}):\n{error_msg}", None, [], []

            # Log raw output for debugging (first 500 chars)
            logger.debug(f"Raw Claude Code output: {output[:500]}...")

            # Parse JSON output for transparency and session ID
            response, tool_uses, thinking, new_session_id = parse_json_output(output)

            # Use new session ID if found, otherwise keep existing
            final_session_id = new_session_id or conversation_id

            # SECURITY: Redact any secrets
            response = redact_secrets(response.strip()) if response else "No output from Claude Code"

            logger.info(f"Session ID: {final_session_id}, Tools used: {len(tool_uses)}")
            if not final_session_id:
                logger.warning("No session ID found - conversation continuity may not work")

            return response, final_session_id, tool_uses, thinking

        except subprocess.TimeoutExpired:
            return "Error: Claude Code timed out after 5 minutes", None, [], []
        except FileNotFoundError:
            return "Error: Claude Code CLI not found. Make sure 'claude' is installed and in PATH.", None, [], []
        except Exception as e:
            logger.exception(f"Error running Claude Code: {e}")
            return f"Error running Claude Code: {str(e)}", None, [], []

    def process_message(self, user_id: int, message: str) -> list[tuple[str | None, bytes | None]]:
        """
        Process a user message through Claude Code.

        Args:
            user_id: The Telegram user ID (for conversation tracking)
            message: The user's message

        Returns:
            List of (text, image_bytes) tuples to send back
        """
        conversation_id = self.conversations.get(user_id)

        response, new_conversation_id, tool_uses, thinking = self._run_claude_code(message, conversation_id)

        if new_conversation_id:
            self.conversations[user_id] = new_conversation_id

        # Build the formatted response
        parts = []

        # Add thinking summary if verbose
        if self.verbose and thinking:
            parts.append("🧠 **Thinking:**")
            for thought in thinking[:3]:  # Max 3 thinking blocks
                parts.append(f"_{thought}_")
            parts.append("")

        # Add tool uses if verbose
        if self.verbose and tool_uses:
            parts.append("⚙️ **Actions:**")
            for tool in tool_uses[:10]:  # Max 10 tools shown
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
            del self.conversations[user_id]
