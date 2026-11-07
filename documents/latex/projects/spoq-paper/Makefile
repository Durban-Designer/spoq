.PHONY: all pdf clean
all: pdf

pdf:
	mkdir -p output
	cd src && pdflatex -interaction=nonstopmode -halt-on-error -output-directory=../output main.tex
	cd output && BIBINPUTS=../src: bibtex main
	cd src && pdflatex -interaction=nonstopmode -halt-on-error -output-directory=../output main.tex
	cd src && pdflatex -interaction=nonstopmode -halt-on-error -output-directory=../output main.tex

clean:
	rm -rf output
