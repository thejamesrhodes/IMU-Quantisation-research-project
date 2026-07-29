# TN-22 — The R2 Estimator Error, and What the Thermal Environment Actually Needs

**Version 1.0 — 29 July 2026**
**Status:** rule R2 has been evaluated with the wrong statistic since the campaign began. This note corrects it, restates every gated record, and sizes the enclosure problem from the corrected numbers.
**Supersedes:** TN-20 §2.6 ("seven of fourteen gated records failed R2"). TN-14 §2.2 keeps its physics; its estimator needs specifying, which it never was.

**Tags:** **[fact]** · **[measured]** · **[inference]** · **[verify]**

---

## 1. The error

`analyse.py` reported the R2 thermal gate on

```python
span_mk = (t.max() - t.min()) * 1000.0
```

the **sample range** of the die temperature. That is an extreme-value statistic. For $N$ samples of a Gaussian it grows as roughly $8.5\sigma$ at $N \sim 6\times10^4$, so it measures **the thermometer's own noise**, not the temperature's drift.

**[measured]**, on `r358768_off_0a` (60 s, ODR 1000, 60 650 samples):

| quantity | value |
|---|---|
| raw range, as reported | **823 mK** |
| per-sample sensor noise $\sigma_T$ | 84 mK |
| expected range from noise alone, $8.5\sigma_T$ | 719 mK |
| **actual linear drift across the record** | **103 mK** |
| real wobble about the line | 27 mK |

Seven eighths of the reported "temperature span" was the sensor talking to itself.

There is a second, worse property. **The temperature channel is filtered with ODR**, so $\sigma_T$ measures 13 mK at ODR 25, 39 at 200, 84 at 1000 and 120 at 8000. A gate on the range therefore **tightens as ODR falls, for a reason that has nothing to do with temperature** — and low ODR is exactly where the paper's claims live.

**Fixed.** `drift_excursion()` in `analyse.py` blocks to 2 s means before fitting a line, so the trend is estimated from means rather than samples. `summary.csv` now carries `temp_drift_mK` (gated) and retains `temp_span_mK` (diagnostic only). Re-run `summary` **without** `--resume` to restate an existing folder.

---

## 2. Every gated record, restated

**[measured]** 28 July campaign night, gate values from TN-14 §2.2:

| record | gate | old range | old verdict | **true drift** | **new verdict** |
|---|---|---|---|---|---|
| s1_odr25 | 260 | 362 | FAIL | **54** | pass ×4.8 |
| s1_odr50 | 361 | 460 | FAIL | **123** | pass ×2.9 |
| s1_odr100 | 388 | 521 | FAIL | **154** | pass ×2.5 |
| s1_odr200 | 389 | 860 | FAIL | **376** | pass ×1.03 |
| s2_odr25 | 260 | 400 | FAIL | **76** | pass ×3.4 |
| s2_odr50 | 361 | 279 | pass | **7** | pass ×52 |
| s2_odr100 | 388 | 317 | pass | **24** | pass ×16 |
| s2_odr200 | 389 | 430 | FAIL | **127** | pass ×3.1 |

**Every gated record passes.** TN-20 §2.6's "seven of fourteen failed R2, the night is not admissible" is an artefact of the estimator, not a property of the night.

**This does not make the night admissible.** The ordering error it diagnosed was real — the ODR-8000 records drift at 13.5 K/h against 0.16 K/h for a settled ODR-25 record, a factor of 84 — and ascending order is still the right fix. But the low-ODR contrast points are far closer to usable than believed, and §3 gives the reason the ordering still matters.

---

## 3. The gate was bounding the wrong quantity

TN-14 §2.2 reasons temperature → phase through the ZRO tempco, $\mathrm{d}\mu/\mathrm{d}T = 5\ \text{mdps/K} / \Delta = 0.0819\ \Delta/\text{K}$. That chain is only as good as its middle term. Measuring $\mu$ directly skips it.

**[measured]** Within-record excursion of $\mu$ from the 19-bit stream, against TN-14's budget of $\delta\varphi \le 0.021\,\Delta$ at ODR 25:

| record | temp drift | phase that predicts | **measured $\mu$ drift (worst axis)** | ratio |
|---|---|---|---|---|
| s1_odr25 | 54 mK | 0.0044 Δ | 0.0171 | 3.9× |
| s2_odr25 | 76 mK | 0.0062 Δ | 0.2627 | **42×** |
| s2_odr50 | 7 mK | 0.0006 Δ | 0.1422 | **250×** |
| s1_odr200 | 376 mK | 0.0308 Δ | 0.2610 | 8.5× |

**The phase moves 4–250× more than the die temperature can explain.** Whatever is moving $\varphi$, it is mostly not the number the gate was watching.

`analyse.py` now reports `mu_drift_D` per axis. **R2 should be gated on it**, because it captures every cause of phase drift rather than the one TN-14 happened to model.

---

## 4. So what *is* moving the phase — and can an enclosure fix it?

The decisive test is the shape of the Allan deviation at long $\tau$. A deterministic ramp — temperature, stress relaxation, anything an enclosure addresses — appears at slope $+1$. Bias instability appears at slope $0$; rate random walk at $+\tfrac12$; white noise averages down at $-\tfrac12$.

**[measured]** 19-bit stream, $\tau$ up to $T/8$, slope over the last four points:

| record | X | Y | Z |
|---|---|---|---|
| s1_odr25 | −0.17 | +0.05 | −0.44 |
| s2_odr25 | −0.28 | −0.03 | −0.03 |
| s1_odr50 | −0.24 | −0.06 | +0.03 |
| s2_odr50 | −0.44 | −0.22 | −0.18 |

> **Not one axis of one record shows a $+1$ ramp. Every one flattens into bias instability or is still averaging down.**

There is **no deterministic thermal drift in the low-ODR records at all.** The $\mu$ excursion of §3 is flicker noise — a straight line fitted to a bias-instability process always returns a nonzero slope, and that is what was being measured.

The bias-instability floors, in Δ:

| | X | Y | Z |
|---|---|---|---|
| slot 1 | 0.009 | 0.015 | 0.006 |
| slot 2 | 0.010 | **0.042–0.051** | 0.021 |

**[inference]** Slot 2's Y axis has 4× the bias instability of everything else on the board, consistently across records and ODR. That is a per-unit property of that die, not an environment, and it is the single largest contributor to the §3 table.

---

## 5. What follows for the enclosure — and it is not what was expected

**The cardboard box is not the limiting factor.** The die-temperature drift is 7–376 mK against gates of 260–389 mK, the Allan curves show no thermal ramp, and the dominant phase-drift term is a property of one gyro die. **Buying thermal mass would improve a term that is already sub-dominant.**

Sized anyway, so the decision is on the record rather than on assertion. Board in a foam box, aluminium mass clamped to it, $\tau = RC$, ambient swing attenuated by $1/\sqrt{1+(2\pi\tau/T)^2}$:

| build | $C$ (J/K) | $R$ (K/W) | $\tau$ | 1 h cycle | 24 h | self-heat rise | 3τ settle |
|---|---|---|---|---|---|---|---|
| 1 kg Al, 50 mm PIR | 897 | 9.7 | 2.4 h | ×0.066 | ×0.85 | 2.4 K | 7 h |
| **3 kg Al, 50 mm PIR** | 2691 | 9.7 | 7.2 h | ×0.022 | ×0.47 | 2.4 K | **22 h** |
| 3 kg Al, 25 mm EPS | 2691 | 3.0 | 2.3 h | ×0.070 | ×0.86 | 0.8 K | 7 h |
| 6 kg Al, 50 mm PIR | 5382 | 9.7 | 14.5 h | ×0.011 | ×0.26 | 2.4 K | 43 h |

With 3 kg and 50 mm, a **1 K room swing** arrives at the die as:

| disturbance | amplitude at die | peak rate | vs the 780 mK/h gate |
|---|---|---|---|
| 30 min, fridge compressor | 11 mK | 88 mK/h | 8.9× margin |
| 1 h, boiler / central heating | 22 mK | 88 mK/h | 8.9× |
| 6 h, evening cool-down | 131 mK | 87 mK/h | 9.0× |
| 24 h, diurnal | 467 mK | 78 mK/h | 10× |

**[inference] Two things this table says that are easy to miss.**

1. **Insulation does not help with the disturbance that actually hurt.** The board's own dissipation is *inside* the box, so a power step from changing ODR is not attenuated — it is integrated, and a higher $R$ makes the resulting temperature step **larger**. The measured 13.5 K/h at ODR 8000 is a self-heating transient, and adding insulation makes it worse. Mass buys time, not rejection.
2. **A long $\tau$ raises the cost of every configuration change.** 3 kg in 50 mm foam takes 22 h to settle after a power step. Against TN-14 §5's finding that settling already dominates the wall clock (26 h of a 55 h budget), that is a serious trade, and it only pays if the board is held in one power state.

The disturbance that mass *does* kill is the fast one — draughts, doors, someone walking past — and that is exactly the disturbance the current cardboard box is worst at and the Allan curves say is not currently present at a level that matters.

---

## 6. Recommendation

**Do not build an enclosure this week.** The three free changes are worth more than any hardware:

| # | Change | Cost | Why |
|---|---|---|---|
| 1 | Gate R2 on `mu_drift_D`, not on temperature | done, §3 | The gate now watches the quantity it exists to bound |
| 2 | Re-run `summary` without `--resume` | 10 min | Restates every record on the corrected statistic |
| 3 | Ascending ODR, gated points first | already in `plan.txt` | Kills the only disturbance the data shows is real |

Then, in order of value per pound:

- **Seal the box and stop touching it.** Free. The 6156 mK/h drift in the `off_0a` record is a board handled minutes earlier; the settled ODR-25 record drifts at 162 mK/h. Handling dominates everything the enclosure would fix.
- **A single slab of aluminium or steel, board clamped to it, whole thing inside the existing cardboard.** £0–15. Removes thermal *gradients* across the package — which is the mechanism most likely to be behind slot 2's Y-axis behaviour, and which mean-temperature stability does not address at all. Gradients, not means, are what stress a MEMS die.
- **50 mm PIR offcut around it.** £10. Buys the ×0.022 rejection of hour-scale cycling, at the cost of a 22 h settle that only pays if the plan holds one power state.
- **Active control.** Not yet, and not without care: a PWM heater beside the analog chain is an EMI source, and TN-16 §7.4 already disconnects USB during science runs for exactly that reason. If it is ever built, it must be linear-drive or galvanically isolated. The one thing it does that mass cannot is reject the board's own power steps.

**[inference] The honest limit.** With the thermal term at 7–376 mK and the bias-instability term at 0.006–0.051 Δ, a perfect enclosure improves the worst axis by well under a factor of two. The route to a tighter phase is **shorter records or more of them**, not a colder room — and that is a campaign-design question for TN-14 §1.3, not a hardware one.

---

## 7. Actions

| # | Action | Priority |
|---|---|---|
| 1 | Appendix Z against TN-20 §2.6 — the night's R2 failures are withdrawn | **High** |
| 2 | TN-14 §2.2: specify the estimator, and restate R2 on $\mu$ drift | **High** |
| 3 | Re-run `summary` on the whole folder without `--resume`; regenerate `fig6_thermal_gate` | **High** |
| 4 | Characterise slot 2's Y axis: is the 4× bias instability stable across sessions? If so it is a specimen property and belongs in the systematics budget | Medium |
| 5 | Re-derive the TN-14 §2 smear analysis for *random* phase wander rather than a monotonic traverse — the current bias estimate $\tfrac12\lvert\partial\eta/\partial\varphi\rvert\,\delta\varphi$ assumes a ramp, and §4 shows there is not one | Medium |
| 6 | GUM budget: the corrected thermal contribution and the bias-instability contribution are now separately quantified and should enter as separate lines | Medium |

---

## 8. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 29 Jul 2026 | Initial issue. R2 estimator corrected from sample range to blocked linear drift; all eight gated records restated as passing; Allan-slope test shows no deterministic thermal ramp; bias instability identified as the dominant phase-drift term; enclosure options sized and deferred |
