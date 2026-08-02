# Supersession register

**Last updated 30 July 2026.**

The corpus convention is an "Appendix Z" in each superseded note. No note ever
grew one, and four partial appendices would be four things to keep true instead
of one. This is that one thing: **every claim in the technical notes that a
later note has overturned, and what replaced it.**

Rule: if a number appears in a technical note and also here, **this file wins.**
Read it before quoting anything from TN-13 onwards.

---

## Z.1 — Every η in the campaign, superseded by TN-24 §3

**What was wrong.** `analyse.py` computed

$$\eta = \frac{\operatorname{Var}(Q) - \operatorname{Var}(x)}{\Delta^2/12}$$

but $\eta_{\text{exact}}$ is derived for a quantiser acting on a *continuous*
input, and $x$ is itself quantised on the $\Delta' = \Delta/8$ lattice. The
numerator needs $+\Delta'^2/12$, which is a constant $+(\Delta'/\Delta)^2 =
1/64 = 0.015625$ of η.

**Scope.** Every η, `eta_resid` and residual RMS quoted anywhere before
30 July 2026, in every note and every figure. There are no exceptions —
the term is a constant and applies to all 282 axis-measurements.

**Correction.** Add 0.015625 to any η quoted in TN-20, TN-21, TN-22 or TN-23.
Residual RMS values must be recomputed, not shifted, because the offset was
partly cancelling other error.

| Where | Was | Now |
|---|---|---|
| TN-23 §1, headline sweep residual RMS | 0.0179 | **0.0103** |
| TN-23 §4, out-of-sample ODR-axis improvement | 76% | recomputed, see TN-24 §3.4 |
| TN-20 §2.2, η range | as printed | +0.015625 each |
| all `fig*` residual panels | — | regenerated 30 July |

`summary_preTN24.csv` holds the pre-correction table byte-for-byte, and
`summary.csv` carries `eta_uncorr` alongside `eta` for every record.

---

## Z.2 — TN-21 §4, the per-part gain hypothesis. Withdrawn.

**Was:** the residual $\varepsilon = s - \tfrac12$ was attributed to per-axis
sensitivity trim, predicting that specimen 2 would show a *different*
$\varepsilon$.

**Now (TN-21 §9):** it does not. $s_2 = 0.499566 \pm 0.000026$ against
$s_1 = 0.499513 \pm 0.000073$ — agreement at 0.7σ. The between-axis spread
*within* specimen 2 ($9.1\times10^{-5}$) is larger than the between-part
difference. Prediction (a) is refuted; prediction (b) is untested and needs a
rate table.

---

## Z.3 — TN-23 §5, the step-size discrepancy. Resolved, and it was confounded.

**Was:** the ladder (0.499513, ODR 1000) and the vernier (0.499151, ODR 50)
disagreed at 4.9σ, cause unknown.

**Now (TN-24 §6):** the design was confounded — the two estimates differed in
*both* estimator and ODR. Completing the 2×2 shows the estimators agree at each
ODR (0.6σ and 0.1σ) and the ODRs disagree at 15σ.

$$s(50) = 0.499159 \pm 0.000013, \qquad s(1000) = 0.499504 \pm 0.000019$$

**The step size is ODR-dependent.** No consequence for the physics — φ is
measured per record, never computed from the step count — but a $k$-ladder is
ODR-specific, and any note treating $s$ as a single constant is wrong.
Mechanism unresolved: see Z.7.

---

## Z.4 — TN-20 §2.5 and §4.6, the 0.512 Δ step. Superseded by TN-21 §1.

One OFFSET_USER step is $0.4995\,\Delta$, not the datasheet's $0.512\,\Delta$,
which is excluded at 338σ. Consequently:

- TN-20 §4.6's "125 distinct phases" arithmetic (the inverse of 64 mod 125) has
  no analogue and is void.
- The degeneracy worry of TN-20 §2.5 is inverted: the ladder is a ~2050-point
  vernier, not a two-point one.
- `icm_offset_for_phase()` and the `phase` sequence directive implemented the
  0.512 premise. **Both removed from the firmware on 30 July 2026**; the
  directive is now refused rather than reinterpreted, so a stale plan fails
  loudly instead of running at the wrong phases.

---

## Z.5 — TN-20 §2.6, the R2 gate failures. Withdrawn by TN-22.

"Seven of fourteen gated records failed R2" was an artefact of evaluating the
gate on the sample **range** of the die temperature. The range is an
extreme-value statistic: at $6\times10^4$ samples it returns $\approx 8.5\,
\sigma_T$ and therefore measures the thermometer, not the temperature.
Measured on one record: range 823 mK, per-sample sensor noise 84 mK, actual
drift 103 mK. Re-evaluated on blocked linear drift, all eight gated records
pass.

**This is a deviation from the pre-registered rule and must be declared as
one** — it was changed after seeing records fail. The defence is that the
statistic was wrong on its own terms, independently of the outcome.

---

## Z.6 — TN-24 §7, the AAF ρ axis. A negative result, recorded so it is not repeated.

Varying the anti-alias filter at fixed ODR does move ρ (by 0.88×, 0.46×, 0.29×
at ODR 50, 200, 1000) but is **not usable as evidence**: the 119 Hz line
carries 34–62% of the variance in the default records at ODR 200 and 1000, and
the floor records leave samples correlated at $r_1 = 0.68$–$0.84$, inflating
SE(η) by 2.3–3.4×.

Superseded by the **software dither sweep** (TN-24 §11), which holds every one
of those confounds still by construction. Do not run more AAF records.

A prediction stated in `plan_night3.txt` before the run — that ρ would *rise*
at ODR 50 — was wrong. `aaf_floor` sets the anti-alias filter ahead of
decimation, not the ODR-tracking UI filter, so narrowing it lowers ρ at every
output rate. Recorded rather than quietly corrected.

---

## Z.7 — Open, not superseded: the mechanism of the ODR-dependent step

**[verify]** The step is 0.063–0.069% larger at ODR 1000 than at ODR 50. The
candidate mechanism is a decimation-chain DC gain that is not exactly unity and
not exactly equal at every output rate, with the offset injected upstream of
it.

**Partial test, from data already on disk (30 July).** A shared chain gain acts
on all three axes equally, so $s(1000)/s(50)$ should be axis-independent:

| axis | $s$ @ ODR 50 | $s$ @ ODR 1000 | ratio |
|---|---|---|---|
| X | 0.499116 | 0.499531 | 1.000832 |
| Y | 0.499170 | 0.499537 | 1.000736 |
| Z | 0.499281 | 0.499436 | 1.000310 |

Ratio SD is $2.8\times10^{-4}$, about 1.65× the per-axis scatter of $s$ itself.
That **weakly disfavours** a single shared gain but does not exclude it on three
axes.

**The check that settles it costs ten minutes and no bench time:** the
DS-000347 Rev 1.6 signal-path block diagram. A web search returned the block
order as *Gyro Only Decimation → AAF → UI Filter → Notch → Offset Registers*,
which if correct places OFFSET_USER **downstream** of decimation — in which case
a filter gain cannot scale it at all and the DC-gain hypothesis is dead, leaving
the 15σ effect unexplained. Read the diagram before writing either version
down.

---

## Z.8 — Corrections to Table 1 and Table 2

See `Table_Verification_30Jul2026.md`. Three corrections were made against
primary sources; rows 4–6 of Table 1 (GMWM/simts/wv, MATLAB Sensor Fusion,
NaveGo) and whether `imu_utils` fits Q internally remain **[verify]**.

---

## Z.9 — Documents referenced by the notes that no longer exist

`PREREGISTRATION.md` and `PREREG-02.md` were removed on 30 July. What they
carried now lives in:

- confirmatory-versus-exploratory status → the `\expl{}` markers in the
  manuscript and `paper/sections/07_limitations.tex`
- per-run expectations written before the run → the header of each
  `Test Datasets/plan_*.txt`

Any note pointing at those filenames should be read as pointing here.
