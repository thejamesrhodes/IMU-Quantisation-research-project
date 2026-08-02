# Sheppard — a MEMS rate-register quantisation testbed

Custom STM32F723 hardware, firmware and analysis for measuring output-register
quantisation noise in MEMS **rate** gyroscopes — the parts that report an
angular-rate register rather than an integrated angle increment.

![Status](https://img.shields.io/badge/status-pre--publication-orange)
![Preprint](https://img.shields.io/badge/preprint-not_yet_released-lightgrey)
![MCU](https://img.shields.io/badge/MCU-STM32F723-blue)
![KiCad](https://img.shields.io/badge/KiCad-10-blue)
![Analysis](https://img.shields.io/badge/analysis-Python_%2B_R-blue)

*This is a pre-publication research project. The preprint is **not yet released**;
the results, figures and numbers in this repository are working values — some
still gated on a repeat run — and are subject to change. Nothing here has been
peer-reviewed.*

---

## The claim under test

Rate-register quantisation is predicted to appear at a $-1/2$ Allan-deviation
slope and to be absorbed silently into the fitted angle random walk (ARW),
rather than appearing as the $-1$-slope angle-quantisation ("Q") term of IEEE
Std 952 — which describes a *different* output architecture, the angle-increment
parts (FOGs, RLGs). This holds regardless of the error's statistics: whether the
quantisation error is PQN-white, deadbanded, or dithered, it enters the *rate*
and therefore hides inside the fitted ARW instead of appearing as a separable Q.

If that is correct, fitted stochastic-noise parameters depend on the
configuration — output data rate (ODR), full-scale range (FSR), output word
length — at which they were measured, and the $\sqrt{\text{ODR}}$
bandwidth-transfer rule embedded in every mainstream IMU calibration toolchain,
where it is stated as a *condition* requiring ideal decimation rather than a
validated result, has never been checked for modern high-ODR consumer parts.

**Why this has gone unnoticed.** The transfer rule was safe for the parts it was
developed on. An MPU-6050-class gyro (≈5 mdps/√Hz, 2011) at ±2000 dps / 100 Hz
sits at a dither ratio $\rho = \sigma/\Delta \approx 0.58$, where the
pseudo-quantisation-noise (PQN) model is valid to ~2 %. The ICM-42688-P
(≈2.8 mdps/√Hz, 2020) sits at $\rho \approx 0.32$, where it is not.

> **The assumption did not fail because it was wrong when written. It failed
> because consumer MEMS gyros became quieter than ~4.3 mdps/√Hz, and nothing
> announced the crossing.**

The board is named after W. F. Sheppard, whose 1898 paper gave the $-c^2/12$
correction for the variance of grouped data
([DOI](https://doi.org/10.1112/plms/s1-29.1.353)) — the same $\Delta^2/12$ the
whole experiment turns on. The correction reappears in an unexpected place: the
20-bit reference stream is itself a quantiser, and Sheppard's correction must be
applied to it before it can serve as a reference at all (TN-23).

---

## What the project sets out to do

- Test whether the fitted stochastic-noise parameters of a MEMS IMU transfer
  across ODR and FSR, and return a single configuration-invariant parameter set
  that does.
- Establish that rate-register quantisation presents at the $-1/2$ slope and is
  absorbed into the fitted ARW, distinct from the IEEE-952 angle-quantisation
  term. *(This is the most robust claim in the project and is independent of the
  PQN-validity question.)*
- Derive the exact, parameter-free output-quantisation behaviour, governed by
  two quantities — the dither ratio $\rho = \sigma/\Delta$ and the sub-LSB bias
  phase $\mu \bmod \Delta$ — both measurable from a static code histogram with
  no additional hardware.
- Identify which requantisation architecture the output register implements
  (undithered/PQN, truncation, RPDF- or TPDF-dithered) from output data alone,
  validated against bit-exact software-dithered controls.
- Show that no mainstream toolchain (Kalibr, `allan_variance_ros`, …) models
  output-register quantisation or exposes $\rho$ or $\mu$, and document the
  effect size against configuration so a practitioner can locate their own.
- Publish the hardware, firmware, analysis code and a raw-integer-code,
  temperature-logged dataset — a dataset that, on the searches conducted, does
  not currently exist, because public IMU datasets are distributed as calibrated
  floats and the calibration destroys the code lattice.

---

## Project progress

| Item | Status |
| --- | --- |
| Data-logger PCB (4× IMU) brought up and logging | ✅ Complete |
| Firmware / unattended instrument | ✅ Complete |
| Analysis chain ($\sigma$, $\rho$, $\mu$, $\varphi$, $\eta$; Allan; GMWM) | ✅ Complete |
| Exact $\eta(\rho,\varphi)$ theory, closed form | ✅ Validated |
| Primary curve $\eta(\rho)$ | ✅ Measured over a decade of $\rho$ |
| Controlled phase sweep vs exact theory | ✅ 0.4 % of range, no free parameters, both specimens |
| Relevance evidence (toolchain guidance, default ODR/FSR) | 🚧 In progress |
| Software-dither sweep | 🚧 In progress |
| Manuscript | 🚧 Skeleton in `paper/` |
| Preprint | ⏳ Not yet released |

---

## Hardware

|           |                                                            |
| --------- | ---------------------------------------------------------- |
| MCU       | STM32F723ZET6, 32 MHz                                       |
| Sensors   | 2× ICM-42688-P, 1× ISM330DHCX, 1× BMI323, one SPI bus each |
| Storage   | microSD on SDMMC2, exFAT                                    |
| Host link | USB-C on OTG_HS, internal HS PHY                            |
| Power     | 4S NiMH or USB-C                                            |

The 32 MHz clock is a science parameter, not a performance choice. Digital
switching noise adds in quadrature at the register input and therefore *dithers*
the quantiser: more of it raises $\rho$ and abolishes the effect being measured.
It stays fixed across a campaign, or is logged as a treatment variable. For the
same reason the supply is recorded per record — battery is the worst case for
the 119 Hz contaminant line; a charger with the host powered off is quietest.

---

## Repository structure

```
GMWM Software/                 STM32CubeIDE firmware project + host Python
  Core/                          application sources
  tools/                         console, analysis, figures
GMWM Electronics/              KiCad 10 — data-logger PCB
Array Electronics ICM42688P/   KiCad 10 — ICM-42688-P board
Array Software ICM42688P/      firmware for the ICM-42688-P board
paper/                         LaTeX manuscript (skeleton)
Figures/                       generated — do not edit by hand
Test Datasets/                 records (gitignored; archived to Zenodo)
Misc/                          supporting material
TN-*.md                        technical notes
```

---

## Running it

```
pip install pyserial numpy matplotlib
python "GMWM Software/tools/sheppard_console.py"
```

The console is a GUI with five tabs: a terminal, the SD-card browser, the
campaign-plan editor, an analysis runner, and a figure viewer that renders the
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

---

## Flashing without an ST-LINK

The board reflashes itself over the same USB-C cable that carries the console.

Run `sheppard_selftest.py` once before trusting the flasher. It feeds the board
bad data five ways and checks each one is refused with flash untouched. Nothing
in it can erase the board.

SWD recovery is always there:

```
STM32_Programmer_CLI -c port=SWD mode=UR -e all -w "Debug/GMWM STM32.elf" -v -rst
```

---

## Technical notes

Start with **TN-16** if you are bringing up hardware — its bus↔chip-select
table and failure-mode list are most of the time it took to get the board alive.
**TN-20** is the campaign handover. **TN-21** through **TN-25** are the results:
the `OFFSET_USER` step size and the vernier phase ladder; the R2 estimator error
and the thermal environment; the phase sweep with the reference-truncation
correction; the third place that correction belonged; and the recovery,
derivation and measurement of the Bussgang gain $G(\rho)$.

> **Read TN-24 before quoting a number from any earlier note.** It found that
> the reference correction had been applied to only two of the three places it
> belongs, which left every $\eta$ in the campaign low by exactly $1/64$. Those
> earlier values are superseded.

---

## Pre-registration and exploratory findings

Which parts of this were fixed before the data and which were found by looking
at it is set out in `paper/sections/07_limitations.tex` and in the `\expl{}`
markers through the manuscript. Anything marked exploratory was found in the
residuals, not predicted — the reference-truncation correction of TN-23 above
all. Read that before citing any of it.

Run plans carry their reasoning in the file. Each `Test Datasets/plan_*.txt`
states what the run is for, what the expected outcome is, and what would change
my mind — written before the run rather than after.

---

## Status

94 records, two specimens, three axes. The register's architecture is identified
(truncation, bit-exact); $\eta(\rho)$ is measured over a decade of $\rho$; and a
controlled phase sweep tracks the exact theory to **0.4 % of its range with no
free parameters — on both specimens independently**. Repeatability is measured
at $\sigma_\eta = 0.0065$, so the theory is good to about twice the noise floor
of the apparatus.

The manuscript is a skeleton in `paper/`. The bench work the preprint needs is
done; what remains is desk work — the relevance evidence, the software-dither
sweep, and the writing.

---

## Preprint and data

The preprint is **not yet released**. A manuscript is in preparation in `paper/`
and is intended for submission to a measurement-science journal (IOP
*Measurement Science and Technology*); this section will carry the preprint DOI
when it is public. Campaign data is archived to Zenodo under its own DOI and is
not held in this repository.

---

## Conventions

SI units. LaTeX for maths. Campaign data goes to Zenodo with a DOI, not into
this repository.
