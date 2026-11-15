.PHONY: build clean

build:
	latexmk -xelatex main.tex
	cp build/main.pdf main.pdf

clean:
	latexmk -C || true
	rm -rf build
