import logging
import json
import httpx

logger = logging.getLogger(__name__)


class OllamaAgent:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.2"):
        """
        Initialize the Ollama agent.

        Args:
            base_url: Ollama API URL (default: http://localhost:11434)
            model: Model to use (default: llama3.2)
        """
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.conversations: dict[int, list] = {}  # user_id -> messages

    def _chat(self, messages: list[dict]) -> str:
        """
        Send a chat request to Ollama.

        Args:
            messages: List of message dicts with 'role' and 'content'

        Returns:
            The assistant's response text
        """
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }

        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data.get("message", {}).get("content", "No response from Ollama")

        except httpx.ConnectError:
            return f"Error: Cannot connect to Ollama at {self.base_url}. Is Ollama running?"
        except httpx.TimeoutException:
            return "Error: Ollama request timed out after 120 seconds"
        except httpx.HTTPStatusError as e:
            return f"Error: Ollama returned status {e.response.status_code}: {e.response.text}"
        except Exception as e:
            logger.exception(f"Error calling Ollama: {e}")
            return f"Error calling Ollama: {str(e)}"

    def process_message(self, user_id: int, message: str) -> str:
        """
        Process a user message through Ollama.

        Args:
            user_id: The Telegram user ID (for conversation tracking)
            message: The user's message

        Returns:
            The response text
        """
        # Get or create conversation history
        if user_id not in self.conversations:
            self.conversations[user_id] = []

        messages = self.conversations[user_id]
        messages.append({"role": "user", "content": message})

        # Call Ollama
        logger.info(f"Calling Ollama ({self.model}) with {len(messages)} messages...")
        response = self._chat(messages)

        # Add assistant response to history
        messages.append({"role": "assistant", "content": response})

        # Limit conversation history
        if len(messages) > 20:
            self.conversations[user_id] = messages[-20:]

        return response

    def clear_conversation(self, user_id: int) -> None:
        """Clear conversation history for a user."""
        if user_id in self.conversations:
            del self.conversations[user_id]

    def list_models(self) -> str:
        """List available Ollama models."""
        url = f"{self.base_url}/api/tags"

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url)
                response.raise_for_status()
                data = response.json()
                models = data.get("models", [])
                if not models:
                    return "No models found. Pull a model with: ollama pull llama3.2"
                model_names = [m.get("name", "unknown") for m in models]
                return "Available models:\n" + "\n".join(f"- {name}" for name in model_names)

        except httpx.ConnectError:
            return f"Error: Cannot connect to Ollama at {self.base_url}. Is Ollama running?"
        except Exception as e:
            return f"Error listing models: {str(e)}"

    def set_model(self, model: str) -> str:
        """Change the active model."""
        self.model = model
        return f"Switched to model: {model}"
