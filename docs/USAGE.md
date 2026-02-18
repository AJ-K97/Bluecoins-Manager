# Bluecoins Manager V2 - Usage Guide

This guide explains how to set up and use the Bluecoins Manager, including the AI and Telegram features.

## 1. 🛠️ Installation & Setup

### A. Database (PostgreSQL)
We use Docker to run the database without messing up your system libraries.

1.  **Install Docker**: [Get Docker Desktop](https://www.docker.com/products/docker-desktop/) or `sudo apt install docker.io docker-compose`.
2.  **Start Database**:
    ```bash
    docker-compose up -d
    ```
    This starts a PostgreSQL container and a PGAdmin container (web interface).

### B. Local AI (Ollama)
We use Ollama to run the Llama 3 model locally.

1.  **Install Ollama**: [Download from ollama.com](https://ollama.com/) or:
    ```bash
    curl -fsSL https://ollama.com/install.sh | sh
    ```
2.  **Pull the Model**:
    ```bash
    ollama pull llama3
    ```
3.  **Ensure it's running**:
    ```bash
    ollama serve
    ```
4.  **(Optional) Use Ollama on another machine**:
    - On the main PC (the machine running Ollama), expose Ollama on LAN:
      ```bash
      OLLAMA_HOST=0.0.0.0:11434 ollama serve
      ```
    - On this Bluecoins machine, set `OLLAMA_HOST` in `.env`:
      ```bash
      OLLAMA_HOST=http://<MAIN_PC_LAN_IP>:11434
      ```
    - Ensure firewall allows TCP `11434` on the main PC.

### C. Telegram Bot
1.  Open Telegram and chat with **@BotFather**.
2.  Send command `/newbot`.
3.  Follow the prompts. You'll get an **API Token**.
4.  Create a `.env` file in the project folder (copy from `.env.example`):
    ```bash
    cp .env.example .env
    nano .env
    ```
5.  Paste your token: `TELEGRAM_BOT_TOKEN=123456:ABC-DEF...`

## 2. 🚀 Running the Bot

To start the bot, run:
```bash
python3 -m src.bot
```
The bot will listen for messages. Send it a CSV file (e.g., `HSBC_Statement.csv`) and it will:
1.  Parse the file.
2.  Categorize transactions using history and AI.
3.  Save them to the database.

## 3. 🖥️ Using the CLI

### A. Interactive Wizard (Recommended) 🪄
Simply run `python3 main.py` without arguments to launch the interactive menu.
```bash
python3 main.py
```
This will guide you through:
-   Importing transactions (with file pickers!)
-   **Review & Verify** new transactions (Line-by-line approval)
-   **Managing Transactions** (View recent, Edit Category, Delete)
-   **Exporting** to Bluecoins CSV (Filtered by account/date)
-   Managing accounts

### B. Command Mode
You can also use the command line directly.

**Manage Accounts:**
```bash
# List accounts
python3 main.py account --list

# Add a bank
python3 main.py account --add "My Bank"
```

**Import CSV manually:**
```bash
python3 main.py convert --bank HSBC --input path/to/file.csv --account "My Bank" --output results.csv
```
This will also trigger the AI categorization for any unknown transactions!

## 4. 🧠 Local LLM Pipeline (Private + Incremental)

For a complete runbook on building a local model workflow that learns from your transactions and custom skills, see:

- `docs/LOCAL_LLM_PIPELINE.md`

Quick command examples:
```bash
# Build/update embedding index from your transactions
python3 main.py llm reindex

# Rebuild category intent memory used by categorizer
python3 main.py llm rebuild-category-understanding

# Add a custom behavioral rule
python3 main.py llm skill-add --name "review-first" --instruction "If uncertain, recommend review." --priority 10

# Ask questions using your indexed local data
python3 main.py llm ask --query "What are my top spending categories this month?"

# Export verified examples for periodic LoRA fine-tuning
python3 main.py llm export-finetune

# List resettable tables
python3 main.py db list-tables

# Reset only specific tables (dependency-checked)
python3 main.py db reset --tables ai_memory llm_finetune_examples

# Queue operations (conservative auto-categorization policy)
python3 main.py queue list
python3 main.py queue stats
python3 main.py queue recalc --since 2026-01-01
python3 main.py queue review
```

## 5. 📊 Benchmarking Categorization Quality

For a full benchmark workflow (CSV import, interactive row-by-row labeling, scoring 0-100, memory score tracking), see:

- `docs/BENCHMARK_GUIDE.md`
