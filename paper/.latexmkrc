# latexmk configuration. `latexmk -pdf main.tex` does everything: reruns for
# cross-references, runs BibTeX when the .bib changes, and stops when the
# output is stable.
$pdf_mode = 1;
$bibtex_use = 2;              # run bibtex, and clean the .bbl on -C
$clean_ext = 'synctex.gz run.xml bbl';
# Figures live outside this directory on purpose -- they are build output of
# figures.py, and copying them here would create a second copy that goes
# stale. main.tex sets \graphicspath accordingly.
