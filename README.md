# 🤖 Local Agentic Automation System

An AI-powered local computer automation CLI built with Python, LangChain, Groq, Typer, and Rich. It translates natural language requests into intelligent, secure local file system operations.

---

## 🌟 Key Features

- 🧠 **Natural Language Processing**: Translates conversational instructions (e.g., *"Show me PDFs from yesterday"*) into structured agent tool parameters.
- 📁 **Smart File Search**: Search files across `Downloads`, `Documents`, `Desktop`, or custom paths filtered by file extension and creation dates.
- 📆 **Relative Date Understanding**: Automatically converts natural relative date expressions (`today`, `yesterday`, `the day before yesterday`, `last week`, or specific date ranges) into concrete `YYYY-MM-DD` timestamps.
- 🛡️ **Safety & Security**: 
  - Destructive file actions require explicit user confirmation.
  - Path safety restriction prevents operations outside allowed directories (`Downloads`, `Documents`, `Desktop`).
  - Strict non-destructive execution policy by the LLM (the CLI application manages confirmation and deletion).
- 🎨 **Rich Terminal Interface**: Built with `Rich` and `Typer` to display styled panels, tables, status progress indicators, and help screens.

---

## 📋 Requirements

Before setting up the project, ensure your environment meets the following requirements:

- **Python**: Version `3.10` or higher
- **Groq API Key**: An active API key from [Groq Cloud Console](https://console.groq.com/)
- **Supported Operating Systems**: macOS, Linux, or Windows

### Python Dependencies
- `langchain-groq`: LangChain integration for Groq LLMs
- `langchain-core`: LangChain primitives and messaging abstractions
- `groq`: Official Python client for Groq API
- `python-dotenv`: Environment variable management
- `typer`: CLI command creation
- `rich`: Formatting, tables, and colors in the terminal

---

## 🚀 Download & Setup Instructions

Follow these steps to download, install, and configure the project:

### 1. Download / Clone the Repository

Clone the repository using Git:
```bash
git clone <repository-url>
cd "local system"
```
*(Or download and extract the ZIP file, then navigate to the extracted folder in your terminal).*

### 2. Set Up a Virtual Environment

Create and activate a virtual environment:

- **macOS / Linux**:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

- **Windows (Command Prompt)**:
  ```cmd
  python -m venv .venv
  .venv\Scripts\activate
  ```

- **Windows (PowerShell)**:
  ```powershell
  python -m venv .venv
  .venv\Scripts\Activate.ps1
  ```

### 3. Install Dependencies

Install the required Python packages:
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the root directory of the project:

```bash
touch .env
```

Add your Groq API Key to `.env`:
```env
GROQ_API_KEY=your_groq_api_key_here
```

---

## 💡 Usage Guide

The application provides a CLI interface powered by `Typer`.

### 1. Give Natural Language Tasks to the Agent

Run the `agent` command with your instruction in quotes:

```bash
# Search for files created yesterday
python3 -m app.main agent "Show me PDFs from yesterday"

# Search for Word documents in Downloads
python3 -m app.main agent "Find Word documents in Downloads"

# Search for text files on Desktop
python3 -m app.main agent "Find text files on my Desktop"

# Search within specific date ranges
python3 -m app.main agent "Find PDFs created between 2026-09-01 and 2026-09-25"
```

### 2. Safe Deletion Workflow

When requesting deletion through natural language, the agent finds matching files and requests approval before deleting:

```bash
python3 -m app.main agent "Delete the PDFs I downloaded yesterday"
```

1. Matching files are displayed in a formatted table.
2. A confirmation prompt asks: `Do you want to permanently delete ALL of these files? [y/N]`.
3. If confirmed (`y`), each file is deleted and verified. If cancelled (`N`), no files are touched.

### 3. Direct File Deletion Command

To delete a single specific file safely:

```bash
python3 -m app.main delete "~/Downloads/sample.pdf"
```

### 4. Check Capabilities & Help

You can query the agent about what it can do:

```bash
python3 -m app.main agent "What can you do for me?"
```

Or view the built-in CLI help guide:

```bash
# Show friendly interactive guide
python3 -m app.main help

# Show CLI options and commands
python3 -m app.main --help
```

---

## 📁 Project Architecture

```
local system/
├── .env                  # Environment variables (GROQ_API_KEY)
├── .gitignore            # Git ignore rules
├── requirements.txt      # Python dependencies
├── README.md             # Documentation
├── app/
│   ├── __init__.py
│   ├── main.py           # CLI entry point, UI rendering, and workflow control
│   ├── agent.py          # LangChain Groq agent setup and system prompt
│   ├── llm.py            # Standalone Groq tool choice utility
│   ├── policy.py         # Risk level evaluator for input requests
│   └── tools/
│       ├── __init__.py
│       ├── filesystem.py   # LangChain tool to search files by extension & creation date
│       └── file_actions.py # Helper functions for safe file path verification & deletion
└── tests/                # Test suite directory
```

---

## 🛡️ Safety & Guardrails

1. **Path Boundary Check**: Files can only be deleted if they reside within authorized directories (`Downloads`, `Documents`, `Desktop`).
2. **Explicit User Approval**: The agent never performs file deletions autonomously. High-risk actions always require user confirmation via terminal prompts.
3. **Verification**: After attempting deletion, the file's existence is re-checked to ensure successful removal.

---

## 📝 License

This project is open-source and available under the [MIT License](LICENSE).
