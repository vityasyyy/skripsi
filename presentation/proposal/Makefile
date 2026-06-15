.PHONY: build clean notes watch

build:
	latexmk -xelatex main.tex

notes:
	latexmk -xelatex main-notes.tex

watch:
	latexmk -xelatex -pvc main.tex

clean:
	rm -rf build/
