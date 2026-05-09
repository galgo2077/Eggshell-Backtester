# 🐧 Linux Installation Guide: Eggshell Backtester

This guide will help you set up the **Eggshell Backtester** on Linux.

---

## 📋 Prerequisites
- **Python 3.10 or higher**
- A terminal (Bash, Zsh, etc.)

---

## 🛠️ Step-by-Step Setup

1. **Navigate to the project folder**:
   ```bash
   cd "Stategies testing"
   ```

2. **Create a virtual environment**:
   ```bash
   python3 -m venv venv
   ```

3. **Activate the environment**:
   ```bash
   source venv/bin/activate
   ```

4. **Install dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

5. **(Optional) Configure API Keys**:
   Create a `.env` file in the root directory:
   ```bash
   # For Binance data (default)
   echo "BINANCE_API_KEY=your_key_here" > .env
   echo "BINANCE_API_SECRET=your_secret_here" >> .env
   ```

6. **Launch the Application**:
   ```bash
   python Elliot/main.py
   ```

---

## 🚀 Running Modes

- **TUI Mode (Default)**: Launches the interactive dashboard.
  ```bash
  python Elliot/main.py
  ```
- **CLI Mode**: Runs a quick backtest in the terminal with prompts.
  ```bash
  python Elliot/main.py --cli
  ```
