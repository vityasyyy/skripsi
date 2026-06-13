# Skripsi Makefile
# Supports local compilation (requires texlive) and Docker compilation

.PHONY: help proposal skripsi presentation clean clean-proposal clean-skripsi clean-presentation proposal-docker skripsi-docker presentation-docker shell

help:
	@echo "Skripsi - Build Options"
	@echo "========================="
	@echo ""
	@echo "Local Compilation (requires texlive):"
	@echo "  make proposal          - Compile content/proposal/main.tex"
	@echo "  make skripsi           - Compile content/skripsi/main.tex"
	@echo "  make presentation      - Compile presentation/proposal/main.tex (xelatex)"
	@echo "  make clean             - Remove build artifacts"
	@echo "  make all               - Compile proposal, skripsi, and presentation"
	@echo ""
	@echo "Docker Compilation (no texlive required):"
	@echo "  make proposal-docker   - Compile proposal in Docker container"
	@echo "  make skripsi-docker    - Compile skripsi in Docker container"
	@echo "  make presentation-docker - Compile presentation in Docker container"
	@echo "  make all-docker        - Compile all in Docker"
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

presentation:
	cd presentation/proposal && \
		latexmk -xelatex main.tex

clean: clean-proposal clean-skripsi clean-presentation

clean-proposal:
	cd content/proposal && rm -f *.aux *.log *.out *.toc *.lof *.lot *.fls *.fdb_latexmk *.synctex.gz *.bbl *.blg *.glo || true

clean-skripsi:
	cd content/skripsi && rm -f *.aux *.log *.out *.toc *.lof *.lot *.fls *.fdb_latexmk *.synctex.gz *.bbl *.blg *.glo || true

clean-presentation:
	cd presentation/proposal && latexmk -C || true

DOCKER_IMAGE := skripsi-latex
DOCKER_TAG := latest

build-docker:
	docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) -f docker/Dockerfile .

proposal-docker: build-docker
	docker run --rm -v $(PWD)/content:/workspace/content $(DOCKER_IMAGE):$(DOCKER_TAG) sh -c "cd /workspace/content/proposal && pdflatex -interaction=nonstopmode main.tex && bibtex main && pdflatex -interaction=nonstopmode main.tex && pdflatex -interaction=nonstopmode main.tex"

skripsi-docker: build-docker
	docker run --rm -v $(PWD)/content:/workspace/content $(DOCKER_IMAGE):$(DOCKER_TAG) sh -c "cd /workspace/content/skripsi && pdflatex -interaction=nonstopmode main.tex && bibtex main && pdflatex -interaction=nonstopmode main.tex && pdflatex -interaction=nonstopmode main.tex"

presentation-docker: build-docker
	docker run --rm -v $(PWD)/presentation:/workspace/presentation $(DOCKER_IMAGE):$(DOCKER_TAG) sh -c "cd /workspace/presentation/proposal && latexmk -xelatex main.tex"

shell: build-docker
	docker run --rm -it -v $(PWD)/content:/workspace/content $(DOCKER_IMAGE):$(DOCKER_TAG) sh

all: proposal skripsi presentation

all-docker: proposal-docker skripsi-docker presentation-docker