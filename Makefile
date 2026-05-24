HUB      := ghcr.io/galgo2077/eggshell
TAG      := latest

.PHONY: all base ollama python fastfetch btop tmux nvidia app push status

all:
	$(MAKE) base
	$(MAKE) ollama
	$(MAKE) python
	$(MAKE) fastfetch
	$(MAKE) btop
	$(MAKE) tmux
	$(MAKE) nvidia
	$(MAKE) app

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

app:
	docker build -f Dockerfile -t $(HUB):$(TAG) .

login:
	echo "$(GITHUB_TOKEN)" | docker login ghcr.io -u galgo2077 --password-stdin

push: login
	docker push $(HUB):$(TAG)

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
	check base      eggshell-base; \
	check ollama    eggshell-ollama; \
	check python    eggshell-python; \
	check fastfetch eggshell-fastfetch; \
	check btop      eggshell-btop; \
	check tmux      eggshell-tmux; \
	check nvidia    eggshell-nvidia; \
	echo "  ──────────────────────────────────────────────"; \
	if docker image inspect $(HUB):$(TAG) > /dev/null 2>&1; then \
	    size=$$(docker image inspect $(HUB):$(TAG) --format='{{.Size}}' | awk '{printf "%.1f GB", $$1/1073741824}'); \
	    printf "  ✔  make %-14s %-22s %s\n" "app" "$(HUB):$(TAG)" "$$size"; \
	else \
	    printf "  ✘  make %-14s %-22s %s\n" "app" "$(HUB):$(TAG)" "(not built)"; \
	fi
	@echo ""
