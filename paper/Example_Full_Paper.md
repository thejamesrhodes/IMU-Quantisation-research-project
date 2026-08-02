# EXAMPLE full-length paper — NOT the manuscript

**This is a worked example, written 30 July 2026 to show what a complete
version looks like end to end.** It is not `paper/main.tex` and must not be
pasted into it. Its purpose is threefold:

1. show the shape of a finished 7000-word measurement paper, so the target is
   concrete rather than notional;
2. carry every piece of corpus framing that TN-20…TN-24 dropped, in the place
   it belongs, so writing the real thing cannot lose it;
3. let you disagree with the argument order cheaply, before writing prose.

Numbers are real where they exist. `[EX]` marks a placeholder invented for the
example — never copy one. Margin notes in `> **Note.**` blocks explain *why* a
paragraph is where it is; those are for you, not for the paper.

Target: IOP *Measurement Science and Technology*. 10–12 pages, ~7000 words.

---

# Rate-Register Quantisation in MEMS Gyroscopes: Exact Statistics of an Unmeasured Term in Fitted Angle Random Walk

J. Rhodes

## Abstract

Stochastic calibration of a MEMS inertial measurement unit fits noise
parameters at one output data rate and transfers them to another by a
$\sqrt{\mathrm{ODR}}$ scaling of the fitted white-noise density. We show that no
mainstream calibration toolchain models the sensor's output-register
quantisation at all, and that the standards construct which would — the
IEEE-952 angle-quantisation term — describes a different output architecture.
In a gyroscope whose output is a *rate* register, the quantisation contribution
appears at the $-1/2$ Allan slope and is absorbed silently into the fitted angle
random walk. We derive its exact behaviour, governed by two parameters
measurable from a static record with no additional hardware, and test it on two
specimens of a low-noise consumer gyroscope. The register is identified
bit-exactly as a truncator. A controlled sub-code phase sweep moves the added
power over $\eta = -0.33$ to $+2.49$ **at fixed configuration**, tracking the
exact theory with a residual of 0.4% of that range and no free parameters. The
error is therefore not a bias to be corrected but a per-unit, sign-indefinite
lottery whose outcome depends on a sub-LSB bias phase that no existing tool
measures and that drifts with temperature.

> **Note.** Order is practice → gap → what was measured → result → consequence.
> The last sentence is the one that must survive: *sign-indefinite lottery*, not
> "systematically deflated" — see `CORPUS_AUDIT` item 1. Word count ≈195.

---

## 1. Introduction

Inertial navigation requires a stochastic model of its sensors. The standard
practice fits a small parameter set — angle random walk $N$, bias instability
$B$, rate random walk $K$ — to a static record via the Allan variance or a
wavelet-variance estimator, and supplies those parameters to a Kalman filter or
a visual–inertial estimator [Allan 1966; Riley 2008; Guerrier et al. 2013].

A calibration is performed once, at one configuration. The sensor is then
operated at another. The parameters are carried across by a bandwidth rule: the
white-noise density is treated as invariant, so the discrete-time variance
scales as $\sqrt{\mathrm{ODR}}$. **This is stated in the documentation of the
most widely used toolchain as a *condition* requiring ideal decimation, not as a
validated result**, and the same documentation recommends inflating the fitted
parameters by five to ten times to cover unmodelled error [Rehder et al. 2016;
Kalibr documentation].

Whether that rule holds for current high-ODR consumer parts appears not to have
been tested.

**The gap is architectural, not numerical.** A quantiser placed on the *rate*
output adds noise to the rate. In the Allan domain that is a $-1/2$ slope —
indistinguishable from angle random walk. The IEEE-952 quantisation term $Q$,
which practitioners might expect to cover this, is quantisation of the *angle*
and carries the distinct $-1$ slope; it describes fibre-optic and ring-laser
instruments that output angle increments. **For a rate-register part the term is
therefore unmodelled, and it lands where it cannot be separated from the
parameter it corrupts.** This holds whatever the quantisation error's statistics
— PQN-white, dead-banded or dithered — and is unaffected by everything else in
this paper.

> **Note.** This is claim 1 in the corpus survivability ranking (`Concept_Note`
> Z.3): phase-independent, ρ-independent, and it alone justifies the paper. It
> goes early and it goes plainly.

**Why the assumption survived until now.** The transfer rule and its embedded
quantisation model were safe for the parts on which they were developed. An
MPU-6050-class gyroscope (≈5 mdps/√Hz, 2011) at $\pm2000\,^\circ/\mathrm{s}$ and
ODR 100 Hz sits at a dither ratio $\rho = \sigma/\Delta \approx 0.58$, where the
classical model is valid to within 2%. The ICM-42688-P (2.8 mdps/√Hz, 2020) sits
at $\rho \approx 0.32$, where it is not.

> The assumption did not fail because it was wrong when written. It failed
> because consumer MEMS gyroscopes became quieter than about 4.3 mdps/√Hz, and
> nothing announced the crossing.

> **Note.** `Concept_Note` §3.4. Best paragraph in the corpus and currently in
> none of the working documents. It converts "someone made a mistake" into
> "a silent threshold was crossed", which is both truer and much easier for a
> referee to accept.

**Contributions.**

1. We show that register quantisation of a rate output presents at the $-1/2$
   Allan slope and is absorbed into fitted ARW, and that IEEE-952's $Q$ is the
   wrong architecture for it.
2. We survey six calibration toolchains and find that none models register
   quantisation and none exposes either parameter that governs it.
3. We give the exact added-power ratio $\eta(\rho,\varphi)$ for a truncating
   register with Gaussian input, requiring two measured parameters and no fit.
4. We identify the register architecture of a consumer part bit-exactly, and
   validate $\eta$ against a controlled phase manipulation on two specimens.

**What this paper is not about.** Scale factor, axis misalignment and
deterministic nonlinearity belong to a different calibration family —
deterministic, large-signal, multi-position, with IMU-TK as the standard open
tool [Tedaldi et al. 2014] — and are orthogonal to this work. We do not propose
a new theory of quantisation; the theory is Bennett's and Sripad and Snyder's,
and our contribution is to identify where it applies and to measure it. The
effect vanishes at high dither ratio, and we say where.

> **Note.** `Concept_Note` Z.6. Three sentences that stop three referee
> questions. They belong in the introduction, not buried in limitations.

---

## 2. Background and related work

### 2.1 Quantisation as an additive noise source

The pseudo-quantisation-noise (PQN) model treats the error of a uniform
quantiser of step $\Delta$ as uniform on $[-\Delta/2, \Delta/2)$ and independent
of the input, giving an added variance of exactly $\Delta^2/12$
[Bennett 1948; Widrow, Kollár & Liu 1996]. Sripad and Snyder [1977] give the
necessary and sufficient condition: the characteristic function of the input
must vanish at all non-zero multiples of $2\pi/\Delta$. For a Gaussian input of
standard deviation $\sigma$ this is approached exponentially in
$\rho = \sigma/\Delta$, and fails badly below $\rho \approx 0.5$
[Widrow & Kollár 2008, Ch. 5–6, 20].

> **Note.** Objections v2.1 is explicit that "this is Bennett with a gyroscope
> attached" must be pre-empted by citing Bennett *ourselves*, early and without
> being asked. Do not let this read as a literature summary — it is a concession
> made on our own initiative, and it is cheap because our contribution is the
> identification and the measurement, not the theory.

### 2.2 Why IEEE-952's $Q$ does not cover it

IEEE Std 952 defines a quantisation term $Q$ with a $-1$ Allan slope
[IEEE 2021]. That term models an instrument whose output is an *angle
increment*: the quantiser sits on the integrated quantity. Differentiating to
obtain rate produces the $-1$ slope. A rate register quantises the rate
directly, giving a $-1/2$ slope. The two are different architectures and the
standards construct does not transfer between them.

### 2.3 What the toolchains actually do

**Table 1** surveys six pipelines.

| Toolchain | √ODR transfer | Models register quantisation | Exposes $\rho$ or $\mu$ | Assumes PQN |
|---|---|---|---|---|
| Kalibr | yes, stated as a condition | no | no | n/a |
| `allan_variance_ros` | yes | no | no | n/a |
| `imu_utils` | yes | no | no | n/a `[verify]` |
| GMWM (`simts`/`wv`) | yes | no `[verify]` | no | n/a |
| MATLAB Sensor Fusion | yes | no `[verify]` | no | n/a |
| NaveGo | yes | no `[verify]` | no | n/a |

> **Note — the framing is non-negotiable.** `GMWM-to-Kalman-Q v1.2` Z.4: the
> surveyed pipelines **do not model register quantisation at all** — it is
> absent from the model set, not approximated within it. Never write "they adopt
> Δ²/12 and it is invalid". That is false and a referee will check in ten
> minutes. The "assumes PQN" column reads *n/a*, and that is the finding.

This is claim 2 of the paper and any reader can verify it in ten minutes,
independently of everything else here.

---

## 3. Theory

### 3.1 The quantiser and its two parameters

Let $v$ be the continuous rate at the register input and $\Delta$ the register
step. Work in units of $\Delta$, so the code lattice is the integers, and write
$u = v/\Delta$. A truncating register outputs $Q = \lfloor u \rfloor$.

Two dimensionless parameters govern everything:

$$\rho = \frac{\sigma}{\Delta} \quad\text{(dither ratio)}, \qquad
\varphi = \mu \bmod 1 \quad\text{(sub-code phase, referenced to a code edge)}$$

> **Note.** State the phase convention twice — here and in Table 2 — and give
> the relation to the corpus convention, $\varphi_{\mathrm{TN\text{-}14}} =
> \varphi - 1/2$. A silent convention change between a note and the paper is how
> sign errors enter.

### 3.2 The exact added power

Write the quantisation error in zero-mean form, $e = Q - u + 1/2$, so that
$Q = u + e - 1/2$. Then, exactly and with no model assumption,

$$\operatorname{Var}(Q) - \operatorname{Var}(u) = 2\operatorname{Cov}(u,e) + \operatorname{Var}(e)$$

PQN asserts $e$ is uniform and independent of $u$, giving
$\operatorname{Cov} = 0$, $\operatorname{Var}(e) = 1/12$, and hence an added
variance of exactly $\Delta^2/12$. Normalising the exact result by that
prediction defines

$$\eta \equiv \frac{\operatorname{Var}(Q) - \operatorname{Var}(u)}{\Delta^2/12}
= 12\left[2\operatorname{Cov}(u,e) + \operatorname{Var}(e)\right]$$

so $\eta = 1$ recovers the classical model, $\eta = 0$ means the register added
nothing, and $\eta < 0$ means it removed variance.

Expanding $e$ in its Fourier (sawtooth) series and taking a Gaussian input
collapses every term onto $g_k = \exp(-2\pi^2k^2\rho^2)$, giving a closed form
$\eta(\rho,\varphi)$ with two limits worth naming:

$$\eta \to -12\rho^2 \ \text{(mid-code)}, \qquad
\eta \to 3 - 12\rho^2 \ \text{(at a code edge)}$$

The zero crossing sits at $\rho_0 = 0.288814$; below it the register removes net
power. The minimum is near $\rho \approx 0.20$, where the output carries about
31% of the input power. Above $\rho \approx 0.62$ the classical model is valid
to within 2%.

> **Note.** $\rho_0 = 0.288814$ was verified to machine precision in the audit
> by independent routes. Quote it to six figures — it is one of the few numbers
> in the paper that is exact rather than measured, and precision signals that.

### 3.3 The gain, which is the other half

The register does not only add power; it applies a gain to the power already
there. The Bussgang gain $G(\rho,\varphi)$ spans $[0.75, 1.25]$ at the
configuration studied here, so at mid-code phase the physical noise is
*attenuated* to $G^2 = 56\%$ of its true in-band value.

**This is why the practitioner's defence fails.** The customary remedy for
uncertainty in a fitted noise density is to inflate it by five to ten times.
Inflation is a defence against an *under-estimate*. It is no defence at all
against a gain error: a conservative bound built on an attenuated estimate is
not conservative, and a deflated process-noise covariance produces an
optimistic, inconsistent filter [Sangsuk-Iam & Bullock 1990] — precisely the
failure mode the inflation practice was invented to prevent.

> **Note.** `Concept_Note` §8 and `CORPUS_AUDIT` items 2–3. **$G$ appears in no
> document written since TN-20.** If the paper reports $\eta$ and not $G$ it is
> telling half the story and it loses this paragraph, which is the strongest
> answer available to "practitioners inflate anyway, so who cares".

### 3.4 What follows for the transfer rule

The observed one-sided density at configuration $c$ carries

$$S_{\mathrm{obs}} = S_{\mathrm{unq}} + \eta\,\frac{\Delta^2}{6\,\mathrm{ODR}}$$

$\eta$ enters as a multiplier on the classical term, so $\eta = 1$ reduces the
expression to the textbook form. A parameter set fitted at one configuration and
transferred by the $\sqrt{\mathrm{ODR}}$ rule carries the calibration
configuration's $\eta$ into an operating configuration with a different one.

> **Note.** The corrected form. `GMWM-to-Kalman-Q v1.2` found the earlier
> worked example **double-counted the Bussgang gain**; the headline moved from
> "27% understatement, ×15 PQN error" to "**+4% overstatement, ×3.9**". Check
> `\arwSpan` in `numbers.tex` descends from the corrected figure.

**Figure 1** — $\eta(\rho)$ with the band swept by the unmeasured phase.

---

## 4. Instrumentation and statistical methods

*(This section exists in `paper/sections/04_method.tex` and is being written
there. The example does not duplicate it. Its order is: instrument → the
reference channel is itself a quantiser → phase manipulation → estimators →
choice of estimator and circularity → record selection.)*

Two points from this section are load-bearing later and are restated here so the
example reads continuously:

- $\sigma$ is estimated **only** from the 20-bit stream. The 16-bit code
  histogram would be cheaper but its likelihood presupposes the model under
  test, so it is used as an independent check and never as an estimator.
- The 20-bit reference is itself a truncating quantiser on a $\Delta/8$ lattice.
  Its own quantisation enters in three places — the phase, the width, and the
  numerator of $\eta$ — and all three carry the same $\Delta'^2/12$.

---

## 5. Results

### 5.1 The register is a truncator, bit-exactly

Comparing the native 16-bit register against the 20-bit word truncated in
software: **450 of 450 discriminating samples agree, across a 40× range of
output data rate, with none ambiguous.**

This needs no statistics. It also settles the architecture question outright, so
$\eta$ below is reported as a *validation* of an identified architecture rather
than as a selector between candidates.

> **Note.** This is the honest scope-down of rule R6, which asked for hypothesis
> selection by joint likelihood over $\{H_0\ldots H_3\}$. That pipeline does not
> exist and does not need to: a bit-exact comparison is stronger than a
> likelihood ratio. Say so explicitly rather than leaving R6 apparently unmet.

### 5.2 Added power against dither ratio

60 axis-measurements over 1.01 decades of $\rho$ on two specimens; residual RMS
against the exact theory 0.071.

> **Note.** This residual is six times the phase sweep's. §5.3's repeat records
> test whether that is measurement noise at high $\rho$ or model error. Do not
> write this subsection until that is known.

**Figure 2** — measured $\eta$ against $\rho$, both specimens, exact theory
overlaid, no fit.

### 5.3 Added power against phase: the causal manipulation

The sub-code phase was moved deliberately using the offset trim register, whose
step is $0.4995\,\Delta$ — within 0.1% of half a code, so that the *miss* from
one half precesses the phase and turns a coarse trim into a fine vernier.

96 measurements across two specimens, 16 step counts, three axes:

| | specimen 1 | specimen 2 |
|---|---|---|
| $\varphi$ span | 0.048 – 0.992 | 0.011 – 0.998 |
| $\eta$ span | −0.344 to +2.478 | −0.325 to +2.494 |
| residual RMS | **0.0103** | **0.0133** |
| residual / $\eta$ range | 0.37% | 0.47% |

Pooled residual 0.0119 over 96 measurements, mean $+0.0003$, **no free
parameters**.

The measured extremes match the closed-form limits: at $\rho = 0.203$ the theory
gives $-12\rho^2 = -0.49$ and $3 - 12\rho^2 = +2.51$.

**The sign of the error changes with phase at fixed configuration.** Two
identically configured units, of the same part number, on the same board, at the
same temperature, differ in added quantisation power by the full span of that
range because their sub-LSB bias phases differ.

> **Note.** This is the experimental confirmation of `Concept_Note` Z.2 and the
> reason the deflation claim was withdrawn. The consequence sentence belongs
> here, not only in §6: *this is a per-unit lottery, and its sign is not knowable
> without measuring $\varphi$*.

**Figure 3** — $\eta$ against $\varphi$, both specimens, exact theory, no fit.

### 5.4 Repeatability, and what the residual means

Sweep points repeated five hours later at a different die temperature give a
single-record repeatability of $\sigma_\eta = 0.0065$ `[EX: n = 6 pairs, ±32%;
supersede with the night-4 figure]`.

Between the two records $\varphi$ drifted by 0.14 of a code and $\eta$ moved by
**1.435**; the exact theory tracked that excursion to 0.008 with nothing
adjusted between them.

Against a residual of 0.0119 this gives $\chi^2_\nu \approx 3.3$, so the
residual is not yet consistent with measurement noise alone. One axis of one
specimen contributes disproportionately; excluding it gives 0.0091 and
$\chi^2_\nu \approx 2.0$, and that axis is also the least Gaussian (tail ratio
1.18 against 1.06–1.15). We report the full-sample figure as the result and the
exclusion as a sensitivity analysis.

> **Note.** Reporting order matters: headline over everything, then the
> concentration, then the sensitivity. Quoting 0.0091 as *the* result would be
> outcome-dependent exclusion, and a referee who spots it will disbelieve the
> rest of the section.

### 5.5 An independent channel: the code histogram

The 16-bit code histogram, never used to estimate any parameter, is predicted
from $(\rho,\varphi)$ measured on the 20-bit stream. Maximum discrepancy across
four phases: **0.005**, nothing fitted.

This is the IEEE Std 1241 code-density test under another name, which also
supplies a differential-nonlinearity check at no extra cost.

### 5.6 Varying $\rho$ at fixed configuration

Every $\rho$ above was set by the output data rate, so $\rho$ and ODR move
together and the $\eta(\rho)$ curve is open to the objection that it is a
decimation artefact. We break the confound by adding known Gaussian noise to the
20-bit stream and re-truncating: same record, same rate, same filter, same
spectral line, same correlation structure, and only $\rho$ changes.

Across 4704 simulated measurements spanning $\rho = 0.31$ to 3.24 the residual
is unbiased in every band. At matched $\rho$, across a 20× change in ODR, all
bands agree within $0.8\sigma$.

Because the dithered stream is genuinely continuous at the simulated quantiser's
input, this test uses **none** of the reference corrections of §4 — so the
theory's agreement here cannot be an artefact of them.

### 5.7 The Allan domain

No $-1$ slope term is present in any record. The short-$\tau$ slope is $-0.43$ to
$-0.60$ across 12 axis-records, consistent with the $-1/2$ family and
inconsistent with angle quantisation.

**Figure 4** — Allan deviation family with $-1/2$ and $-1$ references anchored
on the data.

---

## 6. Consequences for calibration practice

### 6.1 Where the calibration is performed

Kalibr and `allan_variance_ros` instruct users to take long static records at
low output data rate, to keep file sizes tractable, at the sensor's default full
scale. For any modern gyroscope below about 4.3 mdps/√Hz that is
$\rho \approx 0.3$.

> **GATE — do not write this subsection until the evidence exists.** The claim
> "the corner *is* the standard calibration configuration" is the paper's
> weakest structural point (`Concept_Note` Z.5) and is currently **uncited**.
> Required: verbatim Kalibr and `allan_variance_ros` guidance, plus the default
> ODR and FSR of the common drivers (ROS ICM/MPU drivers, PX4, VectorNav-class),
> plus a table of effect size against ODR at datasheet NBW so a reader can
> locate their own configuration. At ODR 200 Hz, $\rho = 0.468$ and $\eta =
> 0.84$ — an effect an order of magnitude smaller. **If the modal calibration
> ODR is 200 Hz rather than ≤100 Hz, this section shrinks accordingly and must
> say so.**

The calibration is therefore performed in the regime where the classical model
fails, and the resulting parameters are exported to operating configurations
(ODR 200–1000 Hz, $\rho > 0.6$) in which it holds.

### 6.2 What the error is, and what it is not

It is **not** a bias. Averaged over a uniform phase prior, $\mathbb{E}_\varphi[G]
= 1$ exactly: across an ensemble of units the classical model is unbiased, and
any claim that fitted ARW is systematically deflated is wrong.

It is a **per-unit, per-run lottery whose sign is not knowable without measuring
$\varphi$** — and $\varphi$ drifts with temperature, so it is not even fixed for
a given unit. No existing tool reports either $\rho$ or $\varphi$.

> **Note.** The most important paragraph in the paper to get right, and the one
> most likely to be got wrong from the recent notes alone. "On average it's
> fine" is a complete rebuttal of the bias claim and no rebuttal at all of this
> one: averaging does not rescue a practitioner who owns one sensor and runs one
> calibration.

Two further consequences follow, both testable:

- **Specimen scatter.** Units at the same nominal configuration carry different
  bias phases and therefore different effective ARW. Predicted scatter in fitted
  ARW exceeds the analogue part-to-part scatter.
- **Apparent bias instability.** A few mdps of thermal drift walks $\varphi$
  across a code during a long record, so $\eta$ and $G$ change slowly within it.
  In an Allan plot a slowly varying noise level is indistinguishable from bias
  instability. Some fraction of the reported bias instability of modern
  low-noise gyroscopes at high full scale may be a quantisation artefact of the
  temperature-driven phase rather than a physical $1/f$ process. `[speculation —
  label it as such]`

### 6.3 What can be corrected, and what cannot

With $\rho$ alone, **no reliable correction is possible** at the corner: the sign
is unknown, and correcting by the ensemble mean does nothing because that mean
is null. $\rho$ is necessary and not sufficient — itself a result worth stating.

With $\rho$ and $\varphi$ both measured — a ten-minute static record, no
additional hardware — correction is essentially exact, bounded by σ-pairing
systematics, phase drift within the record, and the memoryless assumption.

> The contribution is *"here is how to measure and correct a real per-unit
> unknown"*, not *"here is a universal correction factor"*. The smaller claim is
> the honest one and the publishable one.

---

## 7. Limitations

**One part, one full-scale setting, one configuration corner.** The effect
requires $\rho \lesssim 0.5$. We demonstrate it on two specimens of one part
number.

**The full-scale axis is unavailable, not merely unrun.** The 20-bit
high-resolution FIFO mode forces $\pm2000\,^\circ/\mathrm{s}$, so varying full
scale would remove the reference channel the method depends on. This is a
structural constraint of the instrument, not an omission.

**Exploratory elements, declared.** The reference-lattice correction was found by
fitting a free offset to a residual, not predicted in advance; its third
component was found in the residual left by the first two. What makes them
defensible is that the magnitudes are forced arithmetic — $1/16$ and $1/64$ from
$\Delta' = \Delta/8$ — and that they were validated on data they were not
derived from, including a second specimen.

**Deviation from the pre-specified thermal gate.** The gate was specified on the
sample range of die temperature and evaluated instead on blocked linear drift.
The change was made after records failed. The defence is that the range is an
extreme-value statistic — at $6\times10^4$ samples it returns ≈8.5$\sigma_T$ and
therefore measures the thermometer, not the temperature — and that this is true
independently of the outcome.

**Whiteness at high oversampling.** Kollár's criterion $\Delta/\sigma < 4.6
f_N/f_s$ is violated when a fixed anti-alias filter is combined with a high
output rate, and the quantisation error is then not white. Inter-rate
comparisons in this paper are restricted accordingly. `[check the ODR-8000
records are not used in a whiteness-assuming comparison]`

**Not tested here:** cross-vendor generality, a measurement uncertainty budget
to GUM, and the mechanism of the output-rate dependence of the trim register's
step size, which we report but do not explain.

---

## 8. Conclusion

Register quantisation of a rate output is absent from the model set of every
calibration toolchain surveyed, and the standards term that would cover it
describes a different architecture. We identified the register of a low-noise
consumer gyroscope bit-exactly as a truncator, derived the exact added-power
ratio from two measurable parameters, and confirmed it against a controlled
phase manipulation on two specimens to 0.4% of the measured range with no free
parameters.

The practical consequence is not a correction factor. It is that a widely used
calibration procedure has an unmeasured per-unit parameter with a
sign-indefinite effect, and that both numbers needed to determine it are
obtainable from a static record with no additional hardware.

---

## Data and code availability

All 94 records byte-for-byte, the HDF5 conversions and their converter, the
analysis code at its tagged commit, `summary.csv`, and a SHA-256 manifest.
`[EX: Zenodo DOI]` `[EX: repository URL]`

---

## Appendix A — Symbol conventions

> **Note.** Non-negotiable, per `Concept_Note` §3: Vaccaro & Zaki (2012) use $R$
> for ARW density and $Q$ for RRW, which clashes with IEEE-952's $Q$ and with
> the Kalman $Q$/$R$. A reader coming from either literature will misread the
> paper without this table.

| Symbol | Meaning | Note |
|---|---|---|
| $\Delta$ | register LSB | 61.035 mdps at ±2000 °/s |
| $\Delta'$ | reference-channel lattice | $\Delta/8$; 19 significant bits of a 20-bit field |
| $\rho$ | dither ratio $\sigma/\Delta$ | governs everything |
| $\varphi$ | sub-code phase, edge-referenced | $\varphi_{\mathrm{TN\text{-}14}} = \varphi - 1/2$ |
| $\eta$ | added power / $(\Delta^2/12)$ | $\eta = 1$ is PQN, not $\eta = 0$ |
| $G$ | Bussgang gain | $\mathbb{E}_\varphi[G] = 1$ exactly |
| $\kappa$ | architecture constant | 1 undithered, 2 RPDF, 3 TPDF |
| $Q$ | IEEE-952 angle quantisation | **not** our $\eta$; different architecture |

---

## Appendix B — the four architectures

| | Architecture | Total error variance | Distinguishing signature |
|---|---|---|---|
| H0 | undithered rounding | $\eta(\rho)\Delta^2/12$ | $\eta$ varies strongly with $\rho$ |
| H1 | non-subtractive RPDF, 1Δ p-p | ≈$\Delta^2/6$ | $\eta$ flat in $\rho$ |
| H2 | non-subtractive TPDF, 2Δ p-p | $\Delta^2/4$ exactly | $\eta$ flat in $\rho$ |
| H3 | truncation | as H0, plus a $-\Delta/2$ mean | $\eta$ varies; mean offset |

Only **non-subtractive** dither is available to a vendor, because the output must
lie on the integer code lattice and (code − dither) is not an integer. The
hypothesis space is therefore closed, which is what makes identification from
output data alone a measurement rather than an inference.

The cleanest discriminator is that H0/H3 predict $\eta$ *depends* on $\rho$
while H1/H2 predict it does not. Our §5.1 result settles it more directly still.

---

## Writing checklist

- [ ] The words "systematically deflated" appear **nowhere**
- [ ] "Per-unit, sign-indefinite" appears in the abstract and §6.2
- [ ] $G$ is reported, not only $\eta$
- [ ] The inflation-factor rebuttal is in §3.3 or §6
- [ ] Bennett, Sripad–Snyder and Widrow–Kollár are cited on our own initiative in §2
- [ ] Table 1 says pipelines do **not model** register quantisation — never "adopt Δ²/12"
- [ ] The phase convention is stated twice, with the TN-14 relation
- [ ] Every `\expl{}` element is declared exploratory in §7
- [ ] §6.1 is not written until the relevance evidence exists
- [ ] $\eta = 1$ is PQN is stated explicitly once, because $\eta = 0$ is the natural misreading
- [ ] `\arwSpan` traced to the corrected ×3.9, not the withdrawn ×15
