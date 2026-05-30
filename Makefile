HUB        := ghcr.io/galgo2077/eggshell
TAG        := latest

# Per-interval cache-bust timestamps (floor-rounded to interval boundary)
BUILD_DATE_1D  := $(shell date +%Y-%m-%d)
BUILD_DATE_4H  := $(shell date +%Y%m%d%H | awk '{y=substr($$0,1,4);mo=substr($$0,5,2);d=substr($$0,7,2);h=substr($$0,9,2)+0;printf "%s-%s-%s-%02d",y,mo,d,int(h/4)*4}')
BUILD_DATE_1H  := $(shell date +%Y-%m-%d-%H)
BUILD_DATE_15M := $(shell date +%Y%m%d%H%M | awk '{y=substr($$0,1,4);mo=substr($$0,5,2);d=substr($$0,7,2);h=substr($$0,9,2);m=substr($$0,11,2)+0;printf "%s-%s-%s-%s-%02d",y,mo,d,h,int(m/15)*15}')

.PHONY: all base ollama python fastfetch btop tmux nvidia gpu-benchmark models \
        systemd source data app eggshell push status gpu-benchmark-run run stop exec

# ── Full chain ────────────────────────────────────────────────────────────────
all:
	$(MAKE) base
	$(MAKE) ollama
	$(MAKE) python
	$(MAKE) fastfetch
	$(MAKE) btop
	$(MAKE) tmux
	$(MAKE) nvidia
	$(MAKE) gpu-benchmark
	$(MAKE) models
	$(MAKE) systemd
	$(MAKE) source
	$(MAKE) data
	$(MAKE) app

# ── Infrastructure layers ─────────────────────────────────────────────────────
base:
	docker build -f docker/Dockerfile.base -t eggshell-base:$(TAG) .

ollama:
	docker build -f docker/Dockerfile.ollama -t eggshell-ollama:$(TAG) .

python:
	docker build -f docker/Dockerfile.python -t eggshell-python:$(TAG) .

fastfetch:
	docker build -f docker/Dockerfile.fastfetch -t eggshell-fastfetch:$(TAG) .

btop:
	docker build -f docker/Dockerfile.btop -t eggshell-btop:$(TAG) .

tmux:
	docker build -f docker/Dockerfile.tmux -t eggshell-tmux:$(TAG) .

nvidia:
	docker build -f docker/Dockerfile.nvidia -t eggshell-nvidia:$(TAG) .

gpu-benchmark:
	docker build -f docker/Dockerfile.gpu_benchmark -t eggshell-gpu-benchmark:$(TAG) .

models:
	docker build -f docker/Dockerfile.models -t eggshell-models:$(TAG) .

# ── App layers ────────────────────────────────────────────────────────────────
systemd:
	docker build -f docker/Dockerfile.systemd -t eggshell-systemd:$(TAG) .

source:
	docker build -f docker/Dockerfile.source -t eggshell-source:$(TAG) .

data:
	docker build -f docker/Dockerfile.data \
	    --build-arg BUILD_DATE_1D=$(BUILD_DATE_1D) \
	    --build-arg BUILD_DATE_4H=$(BUILD_DATE_4H) \
	    --build-arg BUILD_DATE_1H=$(BUILD_DATE_1H) \
	    --build-arg BUILD_DATE_15M=$(BUILD_DATE_15M) \
	    -t eggshell-data:$(TAG) .

app:
	docker build -f Dockerfile -t $(HUB):$(TAG) .

eggshell:
	$(MAKE) source
	$(MAKE) data
	$(MAKE) app

# ── Container ops ─────────────────────────────────────────────────────────────
run:
	docker rm -f eggshell 2>/dev/null || true
	docker run -d --name eggshell \
	    --gpus all \
	    -e NVIDIA_VISIBLE_DEVICES=all \
	    -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
	    -p 11435:11434 \
	    -p 8081:8080 \
	    $(HUB):$(TAG)

exec:
	docker exec -it eggshell bash

stop:
	docker stop eggshell && docker rm eggshell

gpu-benchmark-run:
	docker run --rm --gpus all \
	    -e NVIDIA_VISIBLE_DEVICES=all \
	    -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
	    eggshell-gpu-benchmark:$(TAG) gpu-benchmark

# ── Registry ──────────────────────────────────────────────────────────────────
login:
	echo "$(GITHUB_TOKEN)" | docker login ghcr.io -u galgo2077 --password-stdin

push: login
	docker push $(HUB):$(TAG)

# ── Status ────────────────────────────────────────────────────────────────────
status:
	@echo ""
	@echo "  make target        image                  size"
	@echo "  ──────────────────────────────────────────────"
	@check() { \
	    target=$$1; img=$$2; \
	    if docker image inspect $$img:$(TAG) > /dev/null 2>&1; then \
	        size=$$(docker image inspect $$img:$(TAG) --format='{{.Size}}' | awk '{printf "%.1f GB", $$1/1073741824}'); \
	        printf "  ✔  make %-14s %-22s %s\n" "$$target" "$$img" "$$size"; \
	    else \
	        printf "  ✘  make %-14s %-22s %s\n" "$$target" "$$img" "(not built)"; \
	    fi; \
	}; \
	check base          eggshell-base; \
	check ollama        eggshell-ollama; \
	check python        eggshell-python; \
	check fastfetch     eggshell-fastfetch; \
	check btop          eggshell-btop; \
	check tmux          eggshell-tmux; \
	check nvidia        eggshell-nvidia; \
	check gpu-benchmark eggshell-gpu-benchmark; \
	check models        eggshell-models; \
	echo "  ──────────────────────────────────────────────"; \
	check systemd       eggshell-systemd; \
	check source        eggshell-source; \
	check data          eggshell-data; \
	echo "  ──────────────────────────────────────────────"; \
	if docker image inspect $(HUB):$(TAG) > /dev/null 2>&1; then \
	    size=$$(docker image inspect $(HUB):$(TAG) --format='{{.Size}}' | awk '{printf "%.1f GB", $$1/1073741824}'); \
	    printf "  ✔  make %-14s %-22s %s\n" "app" "$(HUB):$(TAG)" "$$size"; \
	else \
	    printf "  ✘  make %-14s %-22s %s\n" "app" "$(HUB):$(TAG)" "(not built)"; \
	fi
	@echo ""
