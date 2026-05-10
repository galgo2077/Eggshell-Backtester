# 🪟 Windows Installation Guide: Eggshell Backtester

This guide will help you set up the **Eggshell Backtester** on Windows.

---

## 📋 Prerequisites
- **Python 3.10 or higher**
- PowerShell or Command Prompt (CMD)

---

## 🛠️ Step-by-Step Setup

1. **Open your terminal** and navigate to the project folder:
   ```powershell
   cd "Stategies testing"
   ```

2. **Create a virtual environment**:
   ```powershell
   python -m venv venv
   ```

3. **Activate the environment**:
   - **PowerShell**:
     ```powershell
     .\venv\Scripts\Activate.ps1
     ```
   - **CMD**:
     ```cmd
     .\venv\Scripts\activate.bat
     ```

4. **Install dependencies**:
   ```powershell
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

5. **(Optional) Configure API Keys**:
   Create a file named `.env` in the root directory and add:
   ```text
   # For Binance data (default)
   BINANCE_API_KEY=your_key_here
   BINANCE_API_SECRET=your_secret_here
   ```

6. **Launch the Application**:
   ```powershell
   python Elliot/main.py
   ```

---

## 🚀 Running Modes

- **TUI Mode (Default)**: Launches the interactive dashboard.
  ```powershell
  python Elliot/main.py
  ```
- **CLI Mode**: Runs a quick backtest in the terminal with prompts.
  ```powershell
  python Elliot/main.py --cli
  ```
