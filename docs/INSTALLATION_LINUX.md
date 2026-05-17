# Linux Installation — Eggshell Backtester

## Option A · Docker (Recommended)

Includes Ollama AI, n8n automation, and reports server pre-configured.

### Prerequisites
- Docker Engine installed and running

### 1. Authenticate to GitHub Container Registry
```bash
echo "YOUR_GITHUB_PAT" | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```
PAT needs `read:packages` scope.

### 2. Pull and run
```bash
docker pull ghcr.io/galgo2077/eggshell:latest

docker run -it --rm \
  -e BINANCE_API_KEY=your_key \
  -e BINANCE_API_SECRET=your_secret \
  -p 5678:5678 \
  -p 8080:8080 \
  --privileged \
  ghcr.io/galgo2077/eggshell:latest
```

### 3. Launch backtester inside container
```bash
eggshell
```

Services started automatically by systemd:
| Service | URL |
|---|---|
| Ollama AI | `http://localhost:11434` |
| n8n workflows | `http://localhost:5678` |
| Reports browser | `http://localhost:8080` |

---

## Option B · Local Python

### Prerequisites
- Python 3.10+
- Terminal (Bash/Zsh)

### Setup
```bash
git clone --recurse-submodules https://github.com/galgo2077/Eggshell-Backtester.git
cd Eggshell-Backtester
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Configure API keys (optional)
```bash
echo "BINANCE_API_KEY=your_key_here" > .env
echo "BINANCE_API_SECRET=your_secret_here" >> .env
```

### Launch
```bash
python src/main.py
```
