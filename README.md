# Clawdio

Remote Claude Code assistant via Telegram. Control your Mac Mini from your phone by chatting with Claude Code.

## How It Works

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  You        │────▶│  Telegram API    │────▶│  Mac Mini   │
│  (Phone)    │◀────│  (Cloud)         │◀────│  (Clawdio)  │
└─────────────┘     └──────────────────┘     └─────────────┘
                                                    │
                                              ┌─────┴─────┐
                                              │  Claude   │
                                              │  Code     │
                                              └───────────┘
```

You send a message on Telegram → Clawdio receives it → Runs Claude Code with your message → Sends the response back to you.

**No inbound ports or tunnels needed.** The bot connects outbound to Telegram's servers using long polling.

## Prerequisites

- **Python 3.11+**
- **Claude Code CLI** installed and authenticated on your Mac Mini
  ```bash
  npm install -g @anthropic-ai/claude-code
  claude  # Follow auth prompts
  ```
- **Telegram account**

## Setup

### 1. Create a Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** (looks like `123456789:ABCdefGHI...`)

### 2. Get Your Telegram User ID

1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. It will reply with your user ID (a number like `123456789`)

### 3. Clone and Configure

```bash
git clone https://github.com/riffaultsimon/clawdio.git
cd clawdio

# Install dependencies
pip install -r requirements.txt

# Create your config file
cp .env.example .env
```

Edit `.env` with your values:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
ALLOWED_USER_IDS=your_telegram_user_id

# Optional: set working directory for Claude Code
# WORKING_DIRECTORY=/Users/you/projects
```

### 4. Run the Bot

```bash
python -m src
```

You should see:
```
Starting Clawdio - Remote Claude Code Assistant
Configuration loaded. Allowed users: {123456789}
Claude Code agent initialized (working dir: /Users/you)
Starting Telegram bot...
Bot is running. Press Ctrl+C to stop.
```

## Usage

Open your Telegram bot and start chatting:

- `/start` - Welcome message and capabilities
- `/status` - Check if Claude Code is available
- `/clear` - Reset conversation history
- **Any message** - Sent to Claude Code for processing

### Example Commands

```
"What files are in my home directory?"
"Show me the contents of ~/.zshrc"
"Create a Python script that prints hello world"
"What's using port 3000?"
"Open Safari"
```

Claude Code has full access to your system - it can read/write files, run shell commands, search code, and more.

### Ollama Commands (Local LLMs)

For simpler tasks, you can use local models via Ollama. Conversations are maintained per user, so the model remembers context across messages until you clear it.

- `/ollama <message>` - Chat with the local model (maintains conversation history)
- `/ollama_mode` - Toggle Ollama as default (all messages go to Ollama instead of Claude)
- `/ollama_models` - List available models
- `/ollama_model <name>` - Switch to a different model
- `/ollama_clear` - Clear Ollama conversation history

## Using Ollama (Optional)

Run local LLMs for tasks that don't need Claude Code's full capabilities. Ollama conversations maintain context per user (up to 20 messages), so you can have back-and-forth discussions without repeating yourself.

### 1. Install Ollama

```bash
# macOS
brew install ollama

# Or download from https://ollama.com
```

### 2. Pull a Model

```bash
ollama pull gemma3:1b
# Or other models: llama3.2, mistral, codellama, phi3, etc.
```

### 3. Start Ollama

```bash
ollama serve
```

### 4. Configure (Optional)

In `.env`:
```env
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:1b
```

Now use `/ollama What is the capital of France?` in Telegram!

Example multi-turn conversation:
```
You: /ollama What is the capital of France?
Bot: The capital of France is Paris.

You: /ollama What's its population?
Bot: Paris has a population of about 2.1 million...

You: /ollama_clear
Bot: Ollama conversation cleared.
```

**Ollama Mode**: Use `/ollama_mode` to make Ollama the default - all your messages will go to Ollama without needing the `/ollama` prefix. Toggle it again to switch back to Claude Code.

## Enabling Web Search (Optional)

Claude Code doesn't have built-in web search. To add it, configure an MCP (Model Context Protocol) server.

### Option 1: Brave Search

1. Get a free API key at https://brave.com/search/api/ (2,000 queries/month free)

2. Copy the example config to Claude Code's settings:
   ```bash
   cp claude-settings.json.example ~/.claude/settings.json
   ```

3. Edit `~/.claude/settings.json` and replace `your_brave_api_key_here` with your actual key

4. Restart Clawdio

### Option 2: Tavily Search

1. Get a free API key at https://tavily.com/

2. Create `~/.claude/settings.json`:
   ```json
   {
     "mcpServers": {
       "tavily": {
         "command": "npx",
         "args": ["-y", "tavily-mcp"],
         "env": {
           "TAVILY_API_KEY": "your_tavily_api_key"
         }
       }
     }
   }
   ```

3. Restart Clawdio

Now you can ask Claude Code to search the web!

## Running as a Service (Optional)

To keep Clawdio running in the background on macOS:

### Using launchd

Create `~/Library/LaunchAgents/com.clawdio.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.clawdio</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-m</string>
        <string>src</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/clawdio</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/clawdio.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/clawdio.error.log</string>
</dict>
</plist>
```

Then:
```bash
launchctl load ~/Library/LaunchAgents/com.clawdio.plist
```

## Security

- **User whitelist**: Only Telegram users in `ALLOWED_USER_IDS` can use the bot
- **No inbound connections**: Bot polls Telegram servers outbound only
- **Secrets in .env**: Never committed to git (in .gitignore)

**Warning**: Claude Code has full system access. Only add your own Telegram user ID to the whitelist.

## License

MIT
