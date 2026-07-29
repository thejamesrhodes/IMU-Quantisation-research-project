# paper/

The manuscript. Nothing here is written yet: the sections are stubs carrying
the argument order and the evidence each one has to cite.

## Build

    cd paper
    python "../GMWM Software/tools/make_numbers.py" "../Test Datasets/summary.csv" -o numbers.tex
    latexmk -pdf main.tex

`latexmk -C` cleans.

## The two rules

**1. No number is typed into the prose.** `numbers.tex` is generated from
`summary.csv`; write `\phaseResidRMS{}` and let the build fill it in. If a
macro is missing the build fails, which is correct — the alternative is a
stale number that compiles quietly. Regenerate after every `analyse.py` run.

**2. Figures are referenced, not copied.** `\graphicspath` points at
`../Figures/`, where `figures.py` writes them. Rerunning the figures updates
the PDF on the next build. Do not copy a PNG in here; the copy will go stale
and you will not notice.

## Journal class — you probably don't need it

MST takes a single PDF at submission and IOP say plainly that their class file
is not required: *"it is not essential to use this class file or to format your
article in the same style."* So `article` is a legitimate submission format, and
switching is a five-minute job at the end if you want to.

If you do switch: download `iopart.cls` from IOP, put it beside `main.tex`, use
`\documentclass[12pt]{iopart}` with `\bibliographystyle{iopart-num}`. IEEE TIM
is `\documentclass[journal]{IEEEtran}`, which ships with TeX Live. TIM is
two-column, so that one does change figure sizing.

## Writing on a machine without TeX

LaTeX source is plain text. Edit the files in `sections/` in any editor,
anywhere, offline — you only need TeX to see the PDF, and that can wait until
you are back at a machine that has it. Commit as you go; push when you have
signal.

## Draft markers

`\todo{}` red, `\gap{}` orange for missing evidence, `\expl{}` blue for
anything found by looking at the data rather than predicted in advance. All
three must be gone before submission — grep for them.
