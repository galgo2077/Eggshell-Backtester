# Linux Installation — Eggshell Backtester

This guide will help you set up the **Eggshell Backtester** locally on Linux.

## Prerequisites
- **Python 3.10 or higher**
- A terminal (Bash, Zsh, etc.)

---

## 🛠️ Step-by-Step Setup

### 1. Clone the repository and submodules
```bash
git clone --recurse-submodules https://github.com/galgo2077/Eggshell-Backtester.git
cd Eggshell-Backtester
```

### 2. Create a virtual environment
```bash
python3 -m venv venv
```

### 3. Activate the environment
```bash
source venv/bin/activate
```

### 4. Install dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Configure API keys (optional)
Create a `.env` file in the root directory:
```bash
echo "BINANCE_API_KEY=your_key_here" > .env
echo "BINANCE_API_SECRET=your_secret_here" >> .env
```

### 6. Launch the Application
```bash
python src/main.py
```
