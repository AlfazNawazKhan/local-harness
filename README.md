# LordBlack Harness

A fully local, privacy-first AI orchestration platform that lets you run local LLMs through LM Studio, Ollama, or llama.cpp with persistent memory and optional external API delegation.

![LordBlack Harness Interface](docs/screenshot-main.png)

## What is this?

LordBlack Harness gives local language models:
- **Persistent Memory** — A searchable knowledge store so models don't exhaust their context window
- **External API Delegation** — Local models can call Claude, GPT, or OpenRouter for specific sub-tasks (opt-in only)
- **Local-to-Local Chat** — Two local models can converse (e.g., planner + worker)
- **Folder Access Control** — Grant models access to specific folders, not your whole filesystem
- **Agent Builder** — Define and host your own AI agents locally

**Everything works completely offline** once models are loaded. Cloud APIs are an enhancement, never a dependency.

---

## Hardware Requirements

Designed for low-end laptops:
- **CPU**: Intel i3 class or better
- **RAM**: 4–8 GB minimum (more RAM = larger context windows)
- **GPU**: Optional (integrated graphics work fine)
- **Storage**: Depends on model sizes (typically 4–20 GB per quantized model)

---

## Software Prerequisites

1. **Python 3.9+** — Backend runtime
2. **A local LLM server** (choose one):
   - **[LM Studio](https://lmstudio.ai/)** (recommended for beginners) — GUI app with built-in model downloader
   - **[Ollama](https://ollama.ai/)** — CLI-based, auto-downloads models on first use
   - **llama.cpp** — Advanced users, requires manual model setup

---

## Installation

### 1. Download the Project

```bash
git clone https://github.com/yourusername/lordblack-harness.git
cd lordblack-harness
```

Or download as ZIP and extract.

### 2. Install Python Dependencies

```bash
python -m venv venv

# On Linux/Mac:
source venv/bin/activate

# On Windows:
venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Set Up Your Local LLM Server

#### Option A: LM Studio (Easiest)

1. Download and install [LM Studio](https://lmstudio.ai/)
2. Open LM Studio → Click "Developer" tab (left sidebar)
3. Click "Start Server" button
4. Note the server URL shown: `http://localhost:1234/v1`
5. Go to "Model" tab → Download a model (e.g., Qwen 2.5 7B Instruct, Gemma 2 9B)

**Screenshot Guide:**
```
LM Studio Developer Mode:
┌─────────────────────────────┐
│ 🟢 Server Ready             │
│ http://localhost:1234/v1    │
│ [Stop Server]               │
└─────────────────────────────┘
```

#### Option B: Ollama

1. Install [Ollama](https://ollama.ai/)
2. Pull a model: `ollama pull qwen2.5:7b`
3. Ollama runs automatically at `http://localhost:11434`

### 4. Launch LordBlack Harness

```bash
python app.py
```

This will:
- Start the FastAPI backend
- Open your browser to `http://localhost:8000`

If the browser doesn't open automatically, visit `http://localhost:8000` manually.

---

## First-Run Setup

### Step 1: Connect to Your Local Model

1. Click **Settings** (gear icon, top right)
2. Navigate to **"Model & API Integrations"** tab
3. Under **"LM Studio / Local Hub"**:
   - Enter server URL: `http://localhost:1234/v1` (LM Studio) or `http://localhost:11434` (Ollama)
   - Click **"Connect"**
   - Wait for **"Detection active: Found X models"** message
4. Select your preferred model from the detected list
5. Click **"Save"**

### Step 2: Add Memory (Optional)

1. In the main workspace, click **"Memory"** panel (left sidebar)
2. Click **"Upload Files"** or **"Add Entry"**
3. Add markdown/text files containing project docs, notes, or reference material
4. The system will automatically chunk and index them for retrieval

### Step 3: Grant Folder Access (Optional)

1. Click **"File Access"** panel (left sidebar)
2. Click **"Grant New Folder"**
3. Select a folder you want the model to read/write
4. Toggle individual files in/out of context as needed

### Step 4: Configure External APIs (Optional)

Only if you want local models to delegate tasks to Claude/GPT/OpenRouter:

1. Settings → **"Cloud API Providers"**
2. For each provider you want to enable:
   - Enter your API key
   - Click **"Verify"** to test connection
   - Toggle **"Enable Delegation"**
3. **Privacy Note**: External models cannot access your memory store (enforced by routing layer)

---

## Usage

### Basic Chat

1. Type in the chat box at the bottom
2. Toggle **"RAG Memory"** to enable memory retrieval for this conversation
3. Toggle **"Agentic Mode"** to allow external API delegation
4. Press **Enter** or click **"Send"**

Watch the **"AI Activity"** trace (right sidebar) to see:
- Input parsing
- Routing decision (local vs. external)
- Memory search results
- External API calls (if any)
- Response extraction

### Building an Agent

1. Settings → **"Node Networks"** tab (agent builder dashboard)
2. Click **"New Agent"**
3. Define:
   - **Name**: e.g., "CodeReviewer"
   - **System Prompt**: Instructions for this agent
   - **Assigned Model**: Which local model powers it
   - **Allowed Tools**: Memory, File Access, External API
   - **Trigger**: Manual chat, scheduled, or exposed endpoint
4. Click **"Host Locally"**
5. Agent becomes available at: `http://localhost:8000/agents/<name>`

---

## Troubleshooting

### "Connection Failed" When Connecting to LM Studio

**Problem**: Can't connect to `http://localhost:1234/v1`

**Solutions**:
1. Make sure LM Studio is running and server is started (Developer tab)
2. Check firewall isn't blocking localhost connections
3. Try different port: some LM Studio versions use `:1234`, others `:8080`
4. Verify no other app is using port 1234: `lsof -i :1234` (Mac/Linux) or `netstat -ano | findstr :1234` (Windows)

### "No Models Detected"

**Problem**: Connected to LM Studio/Ollama but no models appear

**Solutions**:
1. **LM Studio**: Download a model via the "Model" tab first
2. **Ollama**: Run `ollama list` to verify models exist; if empty, run `ollama pull llama3.2`
3. Restart LordBlack Harness after downloading models

### Slow Responses / Out of Memory

**Problem**: App crashes or takes minutes to respond

**Solutions**:
1. Use a smaller model (e.g., 3B instead of 7B parameters)
2. Reduce context window in Settings → General → "Max Context Tokens"
3. Close other applications consuming RAM
4. Disable "Agentic Mode" if not needed (prevents external API latency)

### Memory Search Not Working

**Problem**: RAG Memory toggle is on but model doesn't seem to retrieve context

**Solutions**:
1. Verify memory files were uploaded successfully (check Memory panel)
2. Ensure embedding model is configured: Settings → General → "Embedding Method"
   - Default: "MiniLM ONNX" (small local model)
   - Fallback: "Keyword Search" (for very low-RAM devices)
3. Try increasing "Top-K Chunks" in Settings (retrieve more context per query)

---

## Privacy & Security

**What stays on your device**:
- All chat history
- All memory files and embeddings
- All folder contents you grant access to
- API keys (stored encrypted at rest)

**What can leave your device** (only if you explicitly enable it):
- Prompts sent to external APIs (Claude, GPT, OpenRouter)
- **Never** raw memory content — enforced at routing layer

**Telemetry**: None. Zero. Zilch.

See [PRIVACY.md](PRIVACY.md) for full details.

---

## Project Structure

```
lordblack-harness/
├── app.py                    # Main launcher script
├── requirements.txt          # Python dependencies
├── README.md                 # This file
├── PRIVACY.md                # Privacy policy
├── LICENSE                   # MIT License
│
├── lordblack/                # Core application package
│   ├── __init__.py
│   ├── config.py             # Configuration management
│   ├── system_stats.py       # CPU/RAM monitoring
│   │
│   ├── services/             # Business logic
│   │   ├── providers.py      # LocalModelProvider abstraction (LM Studio, Ollama, llama.cpp)
│   │   ├── memory.py         # Chunking, embedding, retrieval
│   │   ├── cloud.py          # External API clients (OpenRouter, Anthropic, OpenAI)
│   │   ├── pipeline.py       # Request routing, activity tracing
│   │   ├── agents.py         # Agent builder and hosting
│   │   ├── fileaccess.py     # Folder permission management
│   │   ├── secure_store.py   # Encrypted API key storage
│   │   └── activity.py       # Live trace logging
│   │
│   ├── routers/              # FastAPI route handlers
│   │   ├── chat.py           # Main chat endpoint
│   │   ├── memory_api.py     # Memory CRUD operations
│   │   ├── cloud_api.py      # External API settings
│   │   ├── agents_api.py     # Agent management
│   │   ├── files.py          # File tree browsing
│   │   └── system.py         # Health checks, stats
│   │
│   ├── web/                  # Frontend (static files)
│   │   ├── index.html        # Main UI
│   │   ├── css/
│   │   │   └── styles.css    # Dark theme styling
│   │   └── js/
│   │       ├── app.js        # Main application logic
│   │       ├── chat.js       # Chat interface
│   │       ├── memory.js     # Memory panel
│   │       └── settings.js   # Settings screen
│   │
│   └── data/                 # Local database and uploads
│       ├── memory.db         # SQLite memory store
│       ├── config.json       # User preferences
│       └── uploads/          # Uploaded memory files
│
├── docs/                     # Additional documentation
│   ├── screenshots/
│   └── api-reference.md
│
└── tests/                    # Test suite
    ├── test_memory.py
    ├── test_providers.py
    └── test_pipeline.py
```

---

## Configuration Reference

Key settings (edit via UI or `lordblack/data/config.json`):

| Setting | Default | Description |
|---------|---------|-------------|
| `provider_type` | `"lmstudio"` | Active local runtime: `lmstudio`, `ollama`, or `llamacpp` |
| `provider_url` | `"http://localhost:1234/v1"` | Local server endpoint |
| `default_model` | *(auto-detected)* | Primary model for chat |
| `embedding_method` | `"minilm-onnx"` | Memory search: `"minilm-onnx"` or `"keyword"` |
| `max_context_tokens` | `4096` | Context window size (reduce for low-RAM) |
| `memory_top_k` | `5` | Number of chunks retrieved per query |
| `internet_enabled` | `false` | Global toggle for external API calls |
| `cloud_providers` | `{}` | Dict of enabled external APIs and keys |

---

## Development

### Running in Dev Mode

```bash
export LORDBLACK_DEBUG=1
python app.py
```

Enables hot-reload and verbose logging.

### Testing

```bash
pytest tests/
```

### Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

MIT License — See [LICENSE](LICENSE) for details.

---

## Support & Community

- **GitHub Issues**: [Report bugs](https://github.com/yourusername/lordblack-harness/issues)
- **Discussions**: [Community forum](https://github.com/yourusername/lordblack-harness/discussions)
- **Documentation**: [Full docs site](https://yourusername.github.io/lordblack-harness/)

---

## Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) — Lightweight async backend
- [SQLite](https://sqlite.org/) — Zero-config database
- [ONNX Runtime](https://onnxruntime.ai/) — Small embedding model inference
- LM Studio, Ollama, llama.cpp — Local model runtimes

Special thanks to the open-source LLM community for making local AI accessible.
