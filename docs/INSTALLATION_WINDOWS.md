# Windows Installation — Eggshell Backtester

This guide will help you set up the **Eggshell Backtester** locally on Windows.

## Prerequisites
- **Python 3.10 or higher**
- PowerShell or Command Prompt (CMD)

---

## 🛠️ Step-by-Step Setup

### 1. Clone the repository and submodules
Open your terminal (PowerShell or CMD) and run:
```powershell
git clone --recurse-submodules https://github.com/galgo2077/Eggshell-Backtester.git
cd Eggshell-Backtester
```

### 2. Create a virtual environment
```powershell
python -m venv venv
```

### 3. Activate the environment
- **PowerShell**:
  ```powershell
  .\venv\Scripts\Activate.ps1
  ```
- **CMD**:
  ```cmd
  .\venv\Scripts\activate.bat
  ```

### 4. Install dependencies
```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Configure API keys (optional)
Create a file named `.env` in the root directory and add:
```text
BINANCE_API_KEY=your_key_here
BINANCE_API_SECRET=your_secret_here
```

### 6. Launch the Application
```powershell
python src/main.py
```
