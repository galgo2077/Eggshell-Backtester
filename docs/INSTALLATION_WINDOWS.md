# Windows Installation — Eggshell Backtester

## Option A · Docker (Recommended)

Includes Ollama AI, n8n automation, and reports server pre-configured.

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) with WSL2 backend enabled

### 1. Authenticate to GitHub Container Registry
```powershell
echo "YOUR_GITHUB_PAT" | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```
PAT needs `read:packages` scope.

### 2. Pull and run
```powershell
docker pull ghcr.io/galgo2077/eggshell:latest

docker run -it --rm `
  -e BINANCE_API_KEY=your_key `
  -e BINANCE_API_SECRET=your_secret `
  -p 5678:5678 `
  -p 8080:8080 `
  --privileged `
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
- PowerShell or Command Prompt

### Setup
```powershell
git clone --recurse-submodules https://github.com/galgo2077/Eggshell-Backtester.git
cd Eggshell-Backtester
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

### Configure API keys (optional)
Create `.env` in the root directory:
```text
BINANCE_API_KEY=your_key_here
BINANCE_API_SECRET=your_secret_here
```

### Launch
```powershell
python src/main.py
```
