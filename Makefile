# Skripsi Makefile
# Supports local compilation (requires texlive) and Docker compilation

.PHONY: help proposal skripsi skripsi-diagrams presentation presentation-diagrams presentation-skripsi presentation-skripsi-diagrams clean clean-proposal clean-skripsi clean-presentation clean-presentation-skripsi proposal-docker skripsi-docker presentation-docker presentation-diagrams-docker presentation-skripsi-docker presentation-skripsi-diagrams-docker shell test-experiments lint-experiments coverage-experiments check-experiments

help:
	@echo "Skripsi - Build Options"
	@echo "========================="
	@echo ""
	@echo "Local Compilation (requires texlive):"
	@echo "  make proposal          - Compile content/proposal/main.tex"
	@echo "  make skripsi           - Compile content/skripsi/main.tex"
	@echo "  make skripsi-diagrams  - Render skripsi diagrams from local Mermaid sources (requires mmdc 11.15+ and Chrome)"
	@echo "  make presentation      - Compile diagrams then presentation/proposal/main.tex (xelatex)"
	@echo "  make presentation-skripsi - Compile diagrams then presentation/skripsi/main.tex (xelatex)"
	@echo "  make presentation-diagrams - Compile only presentation diagrams"
	@echo "  make presentation-skripsi-diagrams - Compile only skripsi presentation diagrams"
	@echo "  make clean             - Remove build artifacts"
	@echo "  make all               - Compile proposal, skripsi, and both presentations"
	@echo ""
	@echo "Docker Compilation (no texlive required):"
	@echo "  make proposal-docker   - Compile proposal in Docker container"
	@echo "  make skripsi-docker    - Compile skripsi in Docker container"
	@echo "  make presentation-docker - Compile presentation in Docker container"
	@echo "  make presentation-skripsi-docker - Compile skripsi presentation in Docker container"
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
		makeindex -s nomencl.ist -o main.nls main.nlo && \
		pdflatex -interaction=nonstopmode main.tex && \
		pdflatex -interaction=nonstopmode main.tex && \
		pdflatex -interaction=nonstopmode main.tex && \
		pdflatex -interaction=nonstopmode main.tex

skripsi-diagrams:
	cd content/skripsi/diagrams/src && ./render.sh

presentation-diagrams:
	cd presentation/proposal/diagrams && \
		for f in *.tex; do xelatex -interaction=nonstopmode -halt-on-error "$$f" || exit 1; done

presentation: presentation-diagrams
	cd presentation/proposal && \
		latexmk -xelatex main.tex

presentation-skripsi-diagrams:
	cd presentation/skripsi/diagrams && \
		for f in *.tex; do xelatex -interaction=nonstopmode -halt-on-error "$$f" || exit 1; done

presentation-skripsi: presentation-skripsi-diagrams
	cd presentation/skripsi && \
		latexmk -xelatex main.tex && \
		cp build/main.pdf main.pdf

clean: clean-proposal clean-skripsi clean-presentation clean-presentation-skripsi

clean-proposal:
	cd content/proposal && rm -f *.aux *.log *.out *.toc *.lof *.lot *.fls *.fdb_latexmk *.synctex.gz *.bbl *.blg *.glo || true

clean-skripsi:
	cd content/skripsi && rm -f *.aux *.log *.out *.toc *.lof *.lot *.fls *.fdb_latexmk *.synctex.gz *.bbl *.blg *.glo *.gls *.nlo *.nls main.ist || true

clean-presentation:
	cd presentation/proposal/diagrams && rm -f *.aux *.log *.out *.fls *.fdb_latexmk *.synctex.gz || true
	cd presentation/proposal && latexmk -C || true

clean-presentation-skripsi:
	cd presentation/skripsi/diagrams && rm -f *.aux *.log *.out *.fls *.fdb_latexmk *.synctex.gz || true
	cd presentation/skripsi && latexmk -C || true
	rm -rf presentation/skripsi/build

DOCKER_IMAGE := skripsi-latex
DOCKER_TAG := latest

build-docker:
	docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) -f docker/Dockerfile .

proposal-docker: build-docker
	docker run --rm -v $(PWD)/content:/workspace/content $(DOCKER_IMAGE):$(DOCKER_TAG) sh -c "cd /workspace/content/proposal && pdflatex -interaction=nonstopmode main.tex && bibtex main && pdflatex -interaction=nonstopmode main.tex && pdflatex -interaction=nonstopmode main.tex"

skripsi-docker: build-docker
	docker run --rm -v $(PWD)/content:/workspace/content $(DOCKER_IMAGE):$(DOCKER_TAG) sh -c "cd /workspace/content/skripsi && pdflatex -interaction=nonstopmode main.tex && bibtex main && makeindex -s nomencl.ist -o main.nls main.nlo && pdflatex -interaction=nonstopmode main.tex && pdflatex -interaction=nonstopmode main.tex && pdflatex -interaction=nonstopmode main.tex && pdflatex -interaction=nonstopmode main.tex"

presentation-diagrams-docker: build-docker
	docker run --rm -v $(PWD)/presentation:/workspace/presentation $(DOCKER_IMAGE):$(DOCKER_TAG) sh -c 'cd /workspace/presentation/proposal/diagrams && for f in *.tex; do xelatex -interaction=nonstopmode -halt-on-error "$$f" || exit 1; done'

presentation-docker: presentation-diagrams-docker
	docker run --rm -v $(PWD)/presentation:/workspace/presentation $(DOCKER_IMAGE):$(DOCKER_TAG) sh -c "cd /workspace/presentation/proposal && latexmk -xelatex main.tex"

presentation-skripsi-diagrams-docker: build-docker
	docker run --rm -v $(PWD)/presentation:/workspace/presentation $(DOCKER_IMAGE):$(DOCKER_TAG) sh -c 'cd /workspace/presentation/skripsi/diagrams && for f in *.tex; do xelatex -interaction=nonstopmode -halt-on-error "$$f" || exit 1; done'

presentation-skripsi-docker: presentation-skripsi-diagrams-docker
	docker run --rm -v $(PWD)/presentation:/workspace/presentation $(DOCKER_IMAGE):$(DOCKER_TAG) sh -c "cd /workspace/presentation/skripsi && latexmk -xelatex main.tex"

shell: build-docker
	docker run --rm -it -v $(PWD)/content:/workspace/content $(DOCKER_IMAGE):$(DOCKER_TAG) sh

all: proposal skripsi presentation presentation-skripsi

all-docker: proposal-docker skripsi-docker presentation-docker presentation-skripsi-docker

# Experiment apparatus verification (dry-run/offline only; no cluster access)
test-experiments:
	python3 -m unittest discover -s experiments/tests -v
	python3 -m unittest discover -s experiments/sensitivity -p 'test_*.py' -v

lint-experiments:
	uv run --with-requirements experiments/requirements-dev.txt ruff check experiments
	uv run --with-requirements experiments/requirements-dev.txt ruff format --check experiments
	cd experiments && uv run --with-requirements requirements-dev.txt mypy
	shellcheck experiments/scripts/*.sh
	bash -n experiments/scripts/*.sh

coverage-experiments:
	uv run --with-requirements experiments/requirements-dev.txt coverage run --rcfile=experiments/.coveragerc -m unittest discover -s experiments/tests
	uv run --with-requirements experiments/requirements-dev.txt coverage run -a --rcfile=experiments/.coveragerc -m unittest discover -s experiments/sensitivity -p 'test_*.py'
	uv run --with-requirements experiments/requirements-dev.txt coverage report --rcfile=experiments/.coveragerc --fail-under=100

check-experiments: test-experiments lint-experiments coverage-experiments
