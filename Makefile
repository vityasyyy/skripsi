# UGM Thesis LaTeX Template - Makefile
# Supports local compilation (requires texlive)

.PHONY: help proposal skripsi clean

help:
	@echo "UGM Thesis LaTeX Template - Build Options"
	@echo "========================================="
	@echo ""
	@echo "Local Compilation (requires texlive):"
	@echo "  make proposal          - Compile template/proposal/main.tex"
	@echo "  make skripsi           - Compile template/skripsi/main.tex"
	@echo "  make clean             - Remove build artifacts"
	@echo ""
	@echo "CI/All:"
	@echo "  make all               - Compile both proposal and skripsi"

proposal:
	cd template/proposal && \
		pdflatex -interaction=nonstopmode main.tex && \
		bibtex main && \
		pdflatex -interaction=nonstopmode main.tex && \
		pdflatex -interaction=nonstopmode main.tex

skripsi:
	cd template/skripsi && \
		pdflatex -interaction=nonstopmode main.tex && \
		bibtex main && \
		pdflatex -interaction=nonstopmode main.tex && \
		pdflatex -interaction=nonstopmode main.tex

clean:
	find template -name "*.aux" -o -name "*.log" -o -name "*.out" -o -name "*.toc" -o -name "*.lof" -o -name "*.lot" -o -name "*.fls" -o -name "*.fdb_latexmk" -o -name "*.synctex.gz" -o -name "*.bbl" -o -name "*.blg" -o -name "*.glo" | xargs rm -f 2>/dev/null || true

all: proposal skripsi