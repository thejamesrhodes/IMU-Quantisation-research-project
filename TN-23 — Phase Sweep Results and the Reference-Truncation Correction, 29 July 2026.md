# TN-23 — The Controlled Phase Sweep, and Sheppard's Correction Applied to the Reference Channel

**Version 1.0 — 29 July 2026**
**Status:** the causal phase manipulation is delivered, and it exposed a systematic error in every phase quoted by the project to date.
**Supersedes:** the residual quality of TN-20 §2.2 and fig2. TN-21 §1's step size is contradicted by this run and the discrepancy is open (§5).

**Tags:** **[fact]** · **[measured]** · **[inference]** · **[verify]**

---

## 1. What was run, and the headline

`plan_phase.txt`: specimen 1, ODR 50 Hz, AAF default, sixteen 600 s records at OFFSET_USER step counts 0 to 1920 in strides of 128, **run in bit-reversed order** so that phase and clock time are decorrelated (corr = −0.02 by design). Plus a five-record slot-2 step-size calibration.

**[measured]** The sweep covers φ from 0.02 to 0.99 — essentially the full period — and η spans **−0.344 to +2.477**, the full theoretical range, from a register whose step is 0.4995 Δ.

After the correction of §3, the exact theory tracks all 48 measurements with **residual RMS 0.0179**, which is **0.6% of the η range**, with **zero free parameters**.

---

## 2. The correction, and how it was found

The first pass gave residual RMS **0.393** — 14% of the η range, and far too large. Two hypotheses were tested and rejected before the right one was found, which is worth recording because both were plausible:

| hypothesis | test | result |
|---|---|---|
| phase smear during the record (TN-14 §2) | predict η averaged over the phases each record actually visited, in 10 s blocks | **0% improvement**; residual is *anti*-correlated with within-record phase wander (r = −0.17) |
| ρ mis-estimated | free scale on ρ | RMS 0.393 → 0.392. ρ is nearly unidentifiable from these data |
| **a phase offset** | free offset on φ | **RMS 0.393 → 0.025**, offset **+0.0623 Δ** |

The residual was never scatter. Plotted against φ it is a smooth, sign-changing curve — the signature of a phase error, not of noise (F8, left panel).

**+0.0623 is 1/16 Δ to 0.3%.**

---

## 3. The mechanism: the reference stream is a quantiser too

**[fact]** The reference is not the continuous input. It is the 20-bit hi-res field divided by 16, and TN-19 §1 established two things about that field: the register is a **truncation**, and the gyro LSB of the field is **always zero**. So the reachable lattice of $x = \text{gyro20}/16$ has spacing

$$\Delta' = \tfrac{2}{16}\,\Delta = 0.125\,\Delta,$$

**[measured]** confirmed directly — every `gyro20` value in every record is even, and the minimum spacing between distinct values is 0.1250 Δ.

**[inference]** A truncating quantiser has a deterministic mean error of $-\Delta'/2$. Therefore

$$\mathbb{E}[x_\text{meas}] = \mathbb{E}[x_\text{true}] - \tfrac{\Delta'}{2}, \qquad \varphi_\text{true} = \varphi_\text{meas} + \tfrac{1}{16},$$

and its variance carries $\Delta'^2/12$ of its own quantisation noise, so

$$\sigma^2_\text{true} = \sigma^2_\text{meas} - \frac{\Delta'^2}{12}.$$

> That second expression is **Sheppard (1898) applied to the instrument's own reference channel** — the correction the board is named after, needed one level below where anyone had been looking for it. The reference stream was being treated as ground truth when it is a quantiser in its own right, only a better-dithered one.

**Result with both corrections and no free parameters:**

| | free parameters | residual RMS |
|---|---|---|
| as published | 0 | 0.3932 |
| $\varphi + 1/16$ | 0 | 0.0252 |
| $+$ Sheppard on $\rho$ | 0 | **0.0179** |
| best 2-parameter fit, for comparison | 2 | 0.0160 |

The principled correction recovers essentially everything a free fit could.

**Out-of-sample validation. [measured]** Both corrections were derived from the 29 July phase sweep at ODR 50. Applied unchanged to the 28 July ODR axis — a different night, different configurations, no shared records — the residual falls from RMS **0.282 to 0.067, a 76% improvement**. The record TN-20 §2.2 highlighted as η = +1.885 moves from a residual of +0.744 to −0.023.

**Independent channel. [measured]** The output code histograms at four phases across the sweep match the predicted occupancy

$$P(j) = \Phi\!\left(\frac{j + 1 - \mu_c}{\rho}\right) - \Phi\!\left(\frac{j - \mu_c}{\rho}\right)$$

to a **maximum discrepancy of 0.005** in fractional occupancy, with nothing fitted (F15). The histogram is a distributional statistic and shares no algebra with η, so this is a genuinely separate confirmation and goes directly to rule R6's demand that a hypothesis never be selected on a single summary statistic.

---

## 4. What this changes in the corpus

**[inference]** Every phase the project has quoted from measured data is low by 1/16 Δ, and every ρ is high by the reference stream's own quantisation noise. This is a second convention error stacked on the first: TN-20 §2.2 corrected the **16-bit** truncation convention (φ_TN-14 = φ_meas − 0.5); this corrects the **19-bit reference's own** truncation, which nobody had accounted for because the reference was assumed to be the input.

`analyse.Stats` now emits `phi_ref`, `rho_ref`, `eta_exact` and `eta_resid` alongside the raw values, so both are auditable and anything computed before today can still be reproduced.

The manuscript gains a methods point that is worth stating plainly: **a reference channel used to test a quantiser must itself be corrected as a quantiser.** It is not an exotic requirement, and it is exactly the correction the 1898 paper gives — but it is invisible if the reference is described as "the unquantised input", which is how TN-12 through TN-14 describe it throughout.

---

## 5. Open: the two step-size measurements disagree

**[measured]** The sweep measures its own step size from μ, which does not wrap:

| source | configuration | $s$ (Δ/step) |
|---|---|---|
| dedicated ladder (TN-21) | ODR 1000, k = 0…2000, bracketed | 0.499513 ± 0.000073 |
| **this sweep** | ODR 50, k = 0…1920, uniform | **0.499151 ± 0.000013** |

They differ by 3.6 × 10⁻⁴, which is **4.9 σ**, and 0.68 Δ of phase at k = 1920.

Three checks, all negative: adding a time regressor moves $s$ by less than 10⁻⁶ (so it is not the night's drift); adding a temperature regressor likewise; and the sweep's three axes agree to 5 × 10⁻⁵, where the ladder's spread across axes was 2.5 × 10⁻⁴. On conditioning alone the sweep is the better measurement, but that is not a reason to discard the other.

**[verify] The discriminating test is the same k set at two ODRs**, one night, ~1 h. Until it is run, neither number should be quoted as *the* step size.

**This does not touch any physics.** φ is measured per record, never commanded, so a wrong $s$ costs only the accuracy of the *predicted* phase — which the design already treats as unreliable (plan_phase.txt steps uniformly in k for exactly this reason). F9 fits $s$ from the data it plots and shows both values.

---

## 6. Figures

Fifteen now, `figures.py` + `figures_new.py`. Suggested split for MST, which tolerates roughly 10–12 pages:

**Main text (5).**

| # | Figure | Why it earns the space |
|---|---|---|
| F10 | Allan slopes | The paper's strongest claim (Concept Note Z.3 #1): quantisation on the −½ family, no −1 term. Reference slopes anchored *on* the data so only the slope is being compared |
| F7 | Controlled phase sweep | The causal manipulation. Answers Objection #14 part 2 — φ manipulated, not observed |
| F8 | Reference truncation | The methods result, and the most transferable thing in the paper |
| F11 | Consequence for fitted ARW | The "so what", in practitioner units: **×4.7 in fitted ARW** across the phase, at one configuration on one sensor |
| F1 | η vs ρ | The ODR axis, with the exact-theory band |

**Supplementary (10).** F9 vernier · F15 code histograms · F14 residual anatomy · F12 offset linearity · F13 R2 estimator · F2 F3 F4 F5 F6 as before.

F5 (`fig5_offset_step`) is now obsolete — it shows the inconclusive 28 July trio — and should be dropped in favour of F12.

---

## 7. Actions

| # | Action | Priority |
|---|---|---|
| 1 | Same k set at ODR 50 and ODR 1000 to settle §5 | **High**, 1 h |
| 2 | Appendix Z against TN-12/13/14 and TN-20: every measured φ is low by 1/16 Δ, every ρ high by Δ′²/12 | **High** |
| 3 | Slot-2 phase sweep — the sweep is currently one specimen | **High**, one night |
| 4 | The likelihood pipeline (R6) can now use the code histogram: §3 shows it matches to 0.005 with no fit | Medium |
| 5 | Re-examine whether the reference-truncation correction changes the TN-14 §1.3 predicted table, which was computed for an ideal continuous input | Medium |
| 6 | Manuscript §5.1: the DNL / IEEE-1241 check now has a validated histogram model to work against | Medium |

---

## 8. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 29 Jul 2026 | Initial issue. Controlled phase sweep delivered, η spanning −0.344 to +2.477 across the full period; reference-stream truncation identified as a +1/16 Δ phase error and Δ′²/12 variance error; residual RMS 0.393 → 0.0179 with no free parameters; 76% out-of-sample improvement on the ODR axis; code histograms match to 0.005; step-size discrepancy with TN-21 recorded as open |
