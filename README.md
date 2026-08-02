# Sheppard — MEMS rate-register quantisation testbed

Hardware, firmware and analysis for an experiment on quantisation noise in MEMS
gyroscopes that output **rate registers** rather than angle increments.

The claim under test is that rate-register quantisation shows up at a $-1/2$
Allan slope and gets absorbed into fitted angle random walk, rather than
appearing as the $-1$ slope angle-quantisation term in IEEE-952 — which belongs
to FOG and RLG parts that output angle increments. If that's right, fitted noise
parameters depend on the configuration they were measured at, and the
$\sqrt{\text{ODR}}$ transfer rule built into every IMU calibration toolchain has
never been checked for modern high-ODR parts.

The board is named after W. F. Sheppard, whose 1898 paper gave the $-c^2/12$
correction for the variance of grouped data
([DOI](https://doi.org/10.1112/plms/s1-29.1.353)). That's the same
$\Delta^2/12$ the whole experiment turns on. It also turned up in an unexpected
place: the 20-bit reference stream is itself a quantiser, and needs Sheppard's
correction applied to it before it can be used as a reference at all (TN-23).

## Hardware

| | |
|---|---|
| MCU | STM32F723ZET6, 32 MHz |
| Sensors | 2× ICM-42688-P, 1× ISM330DHCX, 1× BMI323, one SPI bus each |
| Storage | microSD on SDMMC2, exFAT |
| Host link | USB-C on OTG_HS, internal HS PHY |
| Power | 4S NiMH or USB-C |

The 32 MHz clock is a science parameter, not a performance choice. Digital
switching noise acts as dither: more of it raises $\rho$ and abolishes the
effect being measured. It stays fixed across a campaign or gets logged as a
treatment variable.

## Layout

```
GMWM Software/          STM32CubeIDE firmware project
  Core/                   application sources
  tools/                  host-side Python (console, analysis, figures)
Array Electronics ICM42688P/   KiCad 10 project
paper/                  LaTeX manuscript
Figures/                generated — do not edit by hand
Test Datasets/          records (gitignored; they go to Zenodo)
TN-*.md                 technical notes
```

## Running it

```
pip install pyserial numpy matplotlib
python "GMWM Software/tools/sheppard_console.py"
```

The console is a GUI with five tabs: a terminal, the SD card browser, the
campaign plan editor, an analysis runner, and a figure viewer that renders the
plots in-app. It finds the board by USB ID rather than COM port and reconnects
on its own when the board resets.

Everything it does is also available from the command line, and the panel prints
the exact command before it runs it, so a result in the GUI and a result in a
terminal are the same result.

```
python analyse.py summary "../../Test Datasets" -o "../../Test Datasets/summary.csv" --fast
python figures.py "../../Test Datasets/summary.csv" -o "../../Figures"
python offset_fit.py "../../Test Datasets" --glob "*ph_k*.sdat"
```

## Flashing without an ST-LINK

The board reflashes itself over the same USB-C cable that carries the console.
TN-17A is the procedure, TN-17 is why it works that way — briefly, the F72x ROM
bootloader only exposes DFU on OTG_FS, which isn't routed to the connector.

Run `sheppard_selftest.py` once before trusting the flasher. It feeds the board
bad data five ways and checks each one is refused with flash untouched. Nothing
in it can erase the board.

SWD recovery is always there:

```
STM32_Programmer_CLI -c port=SWD mode=UR -e all -w "Debug/GMWM STM32.elf" -v -rst
```

## Technical notes

TN-16 first if you're bringing up hardware — its bus↔chip-select table and
failure-mode list are most of the time it took to get the board alive. TN-20 is
the campaign handover. TN-21 through TN-24 are the results: the OFFSET_USER step
size and the vernier phase ladder, the R2 estimator error, the phase sweep with
the reference-truncation correction, and the third place that correction
belonged.

**Read TN-24 before quoting a number from any earlier note.** It found that
the reference correction had been applied to two of the three places it
belongs, which left every $\eta$ in the campaign low by exactly $1/64$. All
of them are superseded.

## Conventions

Claims in the notes are tagged **[fact]**, **[measured]**, **[inference]** or
**[verify]**. `[verify]` means load-bearing and not yet checked against a primary
source — treat it accordingly.

SI units. LaTeX for maths. Campaign data goes to Zenodo with a DOI, not into
this repository.

## Method notes

Which parts of this were fixed before the data and which were found by looking
at it is set out in `paper/sections/07_limitations.tex` and in the `\expl{}`
markers through the manuscript. Anything marked exploratory was found in the
residuals, not predicted — the reference-truncation correction of TN-23 above
all. Read that before citing any of it.

Run plans carry their reasoning in the file. `Test Datasets/plan_*.txt` each
state what the run is for, what the expected outcome is, and what would change
my mind, written before the run rather than after.

## Status

94 records, two specimens, three axes. The architecture is identified
(truncation, bit-exact), $\eta(\rho)$ is measured over a decade of $\rho$, and
a controlled phase sweep tracks the exact theory to **0.4% of its range with no
free parameters — on both specimens independently**. Repeatability is measured
at $\sigma_\eta = 0.0065$, so the theory is good to about twice the noise floor
of the apparatus.

Manuscript is a skeleton in `paper/`. The bench work the preprint needs is
done; what is left is desk work — the relevance evidence, the software dither
sweep, and writing it.
