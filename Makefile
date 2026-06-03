# Skripsi Makefile
# Supports local compilation (requires texlive) and Docker compilation

.PHONY: help proposal skripsi clean proposal-docker skripsi-docker shell

help:
	@echo "Skripsi - Build Options"
	@echo "========================="
	@echo ""
	@echo "Local Compilation (requires texlive):"
	@echo "  make proposal          - Compile content/proposal/main.tex"
	@echo "  make skripsi           - Compile content/skripsi/main.tex"
	@echo "  make clean             - Remove build artifacts"
	@echo "  make all               - Compile both proposal and skripsi"
	@echo ""
	@echo "Docker Compilation (no texlive required):"
	@echo "  make proposal-docker   - Compile proposal in Docker container"
	@echo "  make skripsi-docker    - Compile skripsi in Docker container"
	@echo "  make all-docker        - Compile both in Docker"
	@echo "  make shell             - Open interactive shell in container"

proposal:
	cd content/proposal && \
		pdflatex -interaction=nonstopmode main.tex && \
		bibtex main && \
		pdflatex -interaction=nonstopmode main.tex && \
		pdflatex -interaction=nonstopmode main.tex

skripsi:
	cd content/skripsi && \
		pdflatex -interaction=nonstopmode main.tex && \
		bibtex main && \
		pdflatex -interaction=nonstopmode main.tex && \
		pdflatex -interaction=nonstopmode main.tex

clean:
	find content -name "*.aux" -o -name "*.log" -o -name "*.out" -o -name "*.toc" -o -name "*.lof" -o -name "*.lot" -o -name "*.fls" -o -name "*.fdb_latexmk" -o -name "*.synctex.gz" -o -name "*.bbl" -o -name "*.blg" -o -name "*.glo" | xargs rm -f 2>/dev/null || true

DOCKER_IMAGE := skripsi-latex
DOCKER_TAG := latest

build-docker:
	docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) -f docker/Dockerfile .

proposal-docker: build-docker
	docker run --rm -v $(PWD)/content:/workspace/content $(DOCKER_IMAGE):$(DOCKER_TAG) sh -c "cd /workspace/content/proposal && pdflatex -interaction=nonstopmode main.tex && bibtex main && pdflatex -interaction=nonstopmode main.tex && pdflatex -interaction=nonstopmode main.tex"

skripsi-docker: build-docker
	docker run --rm -v $(PWD)/content:/workspace/content $(DOCKER_IMAGE):$(DOCKER_TAG) sh -c "cd /workspace/content/skripsi && pdflatex -interaction=nonstopmode main.tex && bibtex main && pdflatex -interaction=nonstopmode main.tex && pdflatex -interaction=nonstopmode main.tex"

shell: build-docker
	docker run --rm -it -v $(PWD)/content:/workspace/content $(DOCKER_IMAGE):$(DOCKER_TAG) sh

all: proposal skripsi

all-docker: proposal-docker skripsi-docker