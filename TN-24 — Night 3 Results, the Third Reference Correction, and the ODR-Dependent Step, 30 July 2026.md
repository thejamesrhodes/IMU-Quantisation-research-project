# TN-24 — Night 3: the third reference correction, replication on specimen 2, and an ODR-dependent step size

**Version 1.0 — 30 July 2026**
**Status:** the headline result is replicated on a second specimen, and a constant systematic in every η in the campaign is identified and removed.
**Supersedes:** TN-23 §3 (the correction was two-thirds complete). Every η, η_resid and residual RMS quoted in TN-20, TN-21, TN-22 and TN-23 is superseded — see §3.4.
**Depends on:** `plan_night3.txt`, 45 records, 138 axis-measurements.

**Tags:** **[fact]** datasheet or recomputed · **[measured]** observed on Sheppard · **[inference]** reasoned from sourced facts · **[verify]** not yet confirmed.

---

## 1. The results in one line each

1. **[measured]** TN-23's reference-truncation correction belongs in **three** places and had been applied to two. The third is a pure constant, $(\Delta'/\Delta)^2 = 1/64 = 0.015625$ of $\eta$, and correcting it cuts the phase-sweep residual by **39%**.
2. **[measured]** The phase sweep replicates on specimen 2: residual RMS **0.0133** against slot 1's **0.0103**, over $\varphi = 0.011$–$0.998$ and $\eta = -0.325$ to $+2.494$, with no free parameters.
3. **[measured]** An independent repeatability estimate now exists: $\sigma_\eta = 0.0065$ per record. The theory is good to roughly **twice** the repeatability, not to it — §5.
4. **[measured]** The step size is **ODR-dependent** at 15σ. The two estimators agree at each ODR; the two ODRs disagree. TN-21 §10's 2×2 is resolved, and the answer is the column, not the row.
5. **[measured]** The anti-alias-filter ρ axis **does not work** as intended. A negative result, §7.

---

## 2. What ran, and whether to trust it

`plan_night3.txt` executed complete: 45 of 45 records, 6 h 58 min, no operator intervention.

| Check | Result |
|---|---|
| CRC / `verify` | 45/45 ok |
| FIFO overflows | 0 |
| Ring buffer full | 0 |
| R2 thermal gate | every gated record passed (48/48 sweep, 6/6 repeat, 15/15 ladder, 12/12 gated Block B) |
| Median thermal drift | 76 mK (Block A), 22 mK (C2), 237 mK (Block B) against a 361 mK gate |

**[inference]** A selection subsection that excludes nothing is the strongest version of that subsection there is, and this is the first night of the campaign that earns it. The 30-minute warmup and the ascending-ODR ordering are doing the work that TN-20 §2.6 identified.

---

## 3. The third place the reference correction belongs

**3.1 How it was found. [measured]**

The slot-2 sweep residual decomposed into a constant and a scatter, and the constant dominated:

| | RMS | constant offset | scatter | offset share of MS |
|---|---|---|---|---|
| slot 1 | 0.0179 | −0.0147 | 0.0103 | 67% |
| slot 2 | 0.0208 | −0.0159 | 0.0134 | 59% |
| pooled | 0.0194 | −0.0153 | 0.0119 | 62% |

Two independent specimens agreeing on a constant offset of −0.0153 is not scatter. −0.0153 is $1/64$ to within 2%.

**3.2 Why $1/64$. [fact]**

$\eta_{\text{exact}}(\rho,\varphi)$ is derived for a quantiser acting on a **continuous** input. So η must be referred to the variance of the unobserved continuous rate $v$, not to that of $x$ — and $x$ is itself a quantisation of $v$ on the $\Delta' = \Delta/8$ lattice:

$$\eta = \frac{\operatorname{Var}(Q) - \operatorname{Var}(v)}{\Delta^2/12},
\qquad \operatorname{Var}(v) = \operatorname{Var}(x) - \frac{\Delta'^2}{12}$$

$$\Rightarrow\quad \eta = \frac{\operatorname{Var}(Q) - \operatorname{Var}(x)}{\Delta^2/12} + \left(\frac{\Delta'}{\Delta}\right)^{2}, \qquad \left(\frac{\Delta'}{\Delta}\right)^{2} = \frac{1}{64} = 0.015625$$

`analyse.py` computed the first term only. **Every η in the campaign was low by exactly 0.015625.**

**[fact]** The substitution for $\operatorname{Var}(v)$ is exact, not approximate. The reference lattice is 8× finer, so $\rho' = 8\rho = 1.6$–$2.0$ on these records and the Gaussian collapse factor $\exp(-2\pi^2\rho'^2)$ is of order $10^{-22}$. The same theory that predicts a 250% departure from PQN for the register predicts none whatever for the reference. That is a consistency check on the theory, not an excuse for the correction.

**3.3 The magnitude is predicted, not fitted. [measured]**

This matters for how it is written up. It was *found* in a residual — that is exploratory and must be declared — but $1/64$ is forced arithmetic. Fitting a free constant to each group independently and comparing with $1/64$:

| group | n | fitted constant | vs $1/64$ |
|---|---|---|---|
| slot-1 sweep, ODR 50 | 48 | $0.01466 \pm 0.00149$ | −0.6σ |
| slot-2 sweep, ODR 50 | 48 | $0.01593 \pm 0.00194$ | +0.2σ |
| slot-1 repeats, ODR 50 | 6 | $0.01982 \pm 0.00395$ | +1.1σ |
| ladder, ODR 50 | 15 | $0.01545 \pm 0.00323$ | −0.1σ |
| vernier, ODR 1000 | 48 | $0.01332 \pm 0.00379$ | −0.6σ |
| offset ladder, ODR 1000 | 36 | $0.01569 \pm 0.00467$ | +0.0σ |

Six groups, two specimens, two ODRs, two estimators — all within 1.1σ of a number with no free parameters.

**3.4 Effect on the campaign. [measured]**

| group | n | RMS before | RMS after | change |
|---|---|---|---|---|
| slot-1 sweep | 48 | 0.0179 | **0.0103** | −43% |
| slot-2 sweep | 48 | 0.0208 | **0.0133** | −36% |
| both sweeps | 96 | 0.0194 | **0.0119** | −39% |
| slot-1 repeats | 6 | 0.0217 | 0.0098 | −55% |
| ladder, ODR 50 | 15 | 0.0196 | 0.0121 | −38% |
| vernier, ODR 1000 | 48 | 0.0292 | 0.0261 | −11% |
| AAF floor | 18 | 0.0869 | 0.0814 | −6% |
| ODR axis, both slots | 60 | 0.0675 | 0.0632 | −6% |
| **everything** | 282 | 0.0391 | 0.0352 | −10% |

The post-correction means are $+0.0010$, $-0.0003$, $+0.0002$ on the clean ODR-50 groups: the systematic is gone, not reduced.

**[inference]** The groups that improve least are the high-ρ ones, and that is expected rather than troubling. Where $\rho \gtrsim 1$, $\eta_{\text{exact}} \to 1$, the whole dynamic range of η collapses, and a 0.0156 constant is a small part of a residual already dominated by other error. The correction is a fixed absolute shift; its *relative* importance is largest exactly where the physics is most visible.

**3.5 Code and reproducibility.**

`analyse.py` now adds `REF_STEP**2/12` to η's numerator and retains the old value as `eta_uncorr`, which is written to `summary.csv` alongside `eta`. `summary_preTN24.csv` is the pre-correction table, kept byte-for-byte. Every figure and `numbers.tex` has been regenerated. **The analysis was re-run on 30 July and the correction applied to all 94 records, including those already reported in TN-20 to TN-23 — not only to the new ones.** That belongs in the paper's record-selection subsection.

---

## 4. Replication on specimen 2

**[measured]** 16 step counts × 3 axes, ODR 50, bit-reversed in $k$, all passing R2.

| | slot 1 (night 2) | slot 2 (night 3) |
|---|---|---|
| n | 48 | 48 |
| φ span | 0.048 – 0.992 | 0.011 – 0.998 |
| ρ span | 0.185 – 0.224 | 0.200 – 0.253 |
| η span | −0.344 to +2.478 | −0.325 to +2.494 |
| residual RMS | **0.0103** | **0.0133** |
| residual / η range | 0.37% | 0.47% |

**[measured] The k list needed no modification, and that was a prediction.** Specimen 2's vernier period is $1/\varepsilon_2 = 2305$ steps, *longer* than the 2047-step register ceiling, so one sweep in even $k$ reaches only 0.83 of a period per axis — a 0.167 hole. The three axes' differing intrinsic phases fill it: predicted union span 0.007–0.969 with largest gap 0.056, measured 0.011–0.998. **[inference]** The edge region, where η peaks at $3 - 12\rho^2$, is therefore reachable *only* through the axis offsets. No axis may be dropped in analysis, and that is a methods constraint rather than a convenience.

---

## 5. Repeatability, and the honest reading

**[measured]** Two slot-1 sweep points were repeated five hours later at a different die temperature.

| k | axis | φ then | φ now | Δφ | η then | η now | Δη | Δresidual |
|---|---|---|---|---|---|---|---|---|
| 0 | X | 0.5534 | 0.5855 | +0.032 | −0.273 | −0.224 | +0.049 | −0.0130 |
| 0 | Y | 0.7654 | 0.9069 | +0.142 | 0.710 | 2.146 | **+1.435** | −0.0077 |
| 0 | Z | 0.9915 | 0.9620 | −0.030 | 2.474 | 2.408 | −0.067 | −0.0066 |
| 896 | X | 0.8167 | 0.8226 | +0.006 | 1.345 | 1.394 | +0.049 | +0.0004 |
| 896 | Y | 0.0484 | 0.1147 | +0.066 | 2.467 | 1.921 | −0.545 | −0.0225 |
| 896 | Z | 0.9271 | 0.8662 | −0.061 | 2.245 | 1.788 | −0.457 | +0.0025 |

$\text{SD}[\Delta\text{residual}] = 0.0091 \Rightarrow \sigma_\eta = 0.0091/\sqrt2 = \mathbf{0.0065}$ per record.

**[inference] This is the strongest single sentence available from the campaign.** Between two records five hours apart, φ drifted by up to 0.14 of a code and η moved by **1.435**, and the exact theory tracked that change to 0.008. Nothing was adjusted between the two records; nothing was fitted. A theory that follows a 1.4-unit excursion to 0.6% of it is doing more than fitting a curve.

**But the residual is not yet consistent with measurement noise, and the note must say so.**

$$\text{residual RMS } 0.0119 \quad\text{vs}\quad \sigma_\eta = 0.0065
\;\Rightarrow\; \chi^2_\nu = 3.35,
\quad \sqrt{0.0119^2 - 0.0065^2} = 0.0100 \text{ unexplained}$$

**[verify]** With $n = 6$ pairs, $\sigma_\eta$ carries about ±32% of its own, so $\chi^2_\nu$ lies somewhere between roughly 1.3 and 8. The honest statement is *"the residual is about twice the measured repeatability, on an error estimate that is itself only good to a third"* — suggestive of remaining structure, not decisive. **More pairs are cheap and would settle it: six more repeats is 90 minutes.**

---

## 6. The step size is ODR-dependent

**[measured]** TN-21 §10's 2×2, completed:

| | ODR 50 | ODR 1000 |
|---|---|---|
| **ladder**, from μ | $0.499189 \pm 0.000049$ | $0.499513 \pm 0.000073$ |
| **vernier**, from φ | $0.499157 \pm 0.000013$ | $0.499503 \pm 0.000020$ |

**Rows agree; columns differ.**

| comparison | difference | significance |
|---|---|---|
| ladder − vernier, at ODR 50 | $+3.2\times10^{-5} \pm 5.1\times10^{-5}$ | 0.6σ |
| ladder − vernier, at ODR 1000 | $+1.0\times10^{-5} \pm 7.6\times10^{-5}$ | 0.1σ |
| ODR 1000 − ODR 50, ladder | $+3.24\times10^{-4} \pm 8.8\times10^{-5}$ | 3.7σ |
| ODR 1000 − ODR 50, vernier | $+3.46\times10^{-4} \pm 2.4\times10^{-5}$ | 14.5σ |
| **ODR 1000 − ODR 50, pooled** | $+3.45\times10^{-4} \pm 2.3\times10^{-5}$ | **15.0σ** |

$$s(50) = 0.499159 \pm 0.000013, \qquad s(1000) = 0.499504 \pm 0.000019,
\qquad \frac{s(1000)}{s(50)} = 1.000690$$

**The estimator hypothesis is dead.** The two estimators — one reading μ directly, one reading the precession of a wrapped φ over 1920 steps — agree to better than 1σ at both rates. The vernier's unwrapping was not the problem.

**[inference]** The step is 0.069% larger at ODR 1000 than at ODR 50. The natural mechanism is a DC gain in the decimation chain that is not exactly unity and not exactly the same at every output rate: a fixed digital offset injected upstream of that gain would read as a slightly different number of Δ at each ODR. That is speculation until checked against the filter specification, and it is **[verify]**, not a finding.

**Two consequences, and only the first is about this paper.**

- **Method.** A $k$-ladder designed at one ODR does not sweep the same phases at another. The vernier is ODR-specific. This belongs in §4.3 of the manuscript.
- **Physics.** None. φ is measured per record from the 20-bit mean and never computed from the step count. The register's job is to *move* the phase, not to place it. This is rule R6 earning its keep, and it is worth saying so explicitly, because a referee who thinks φ was commanded will ask exactly this question.

---

## 7. The AAF ρ axis does not work — a negative result

**[measured]** The intent was to vary ρ at *fixed* ODR, breaking the ρ↔ODR confound. Mechanically it does:

| ODR | ρ ratio, floor / default | spread across 6 axis-records |
|---|---|---|
| 50 | 0.881 | 0.677 – 1.005 |
| 200 | 0.464 | 0.341 – 0.563 |
| 1000 | 0.290 | 0.237 – 0.351 |

**The prediction stated in `plan_night3.txt` before the run was wrong.** It predicted ρ would *rise* at ODR 50, on the reasoning that the default UI filter tracks ODR while `floor` is a fixed 42 Hz. ρ fell at every ODR. **[inference]** The reason is that `aaf_floor` sets the *anti-alias* filter, which acts at the internal sample rate ahead of decimation, not the ODR-tracking UI filter — so narrowing it removes noise at every output rate. The prediction confused two filters. Recording that plainly is worth more than quietly correcting it.

**But the axis is not usable as evidence, for two independent reasons.**

1. **The coherent line is confounded with the filter.** In the *default* records the 119 Hz line carries 34–62% of the total variance at ODR 200 and 1000, falling to 2.5–10% at the floor. A default/floor pair at those rates compares two ρ values *and* two line amplitudes, and η's closed form assumes a Gaussian input. At ODR 50 the line is absent from both sides — but there ρ moves by only 12%, which is too little to be a ρ axis.
2. **Sample correlation at the narrow setting.** The successive-difference ratio $\sigma_{\text{diff}}/\sigma$ falls to 0.40–0.57 on the ODR-1000 floor records, implying $r_1 = 0.68$–$0.84$ and an AR(1) variance inflation $C = (1+r_1)/(1-r_1) = 5$–$12$. SE(η) is inflated 2.3× to 3.4×. The observed residual RMS of 0.067 at ODR 1000 is consistent with that inflation and carries little information.

Residual RMS on the floor records: 0.063 (ODR 50), 0.107 (ODR 200), 0.067 (ODR 1000) — five to nine times the sweep.

**[inference] The right instrument for this job is software dither, not the filter.** Adding known Gaussian noise to the 20-bit stream and re-truncating varies ρ at fixed ODR, fixed filter, fixed line amplitude and fixed correlation structure — every confound above is held still by construction. It is pure analysis on records already on disk, it costs no bench time, and it is already named in rule R6 as the "software sweep". **This should be the next analysis task, and it supersedes any further AAF runs.**

---

## 8. What is left in the residual

**[measured]** After the §3 correction, the pooled sweep residual is 0.0119 RMS with mean $+0.0003$. Regressing it on every available covariate:

| covariate | r | t |
|---|---|---|
| φ | −0.264 | −2.7 |
| ρ (= σ/Δ) | −0.234 | −2.3 |
| tail ratio | −0.230 | −2.3 |
| codes | −0.145 | −1.4 |
| η_exact | +0.139 | +1.4 |
| thermal drift | −0.110 | −1.1 |
| **line amplitude** | **−0.014** | **−0.1** |
| **line % of variance** | **+0.014** | **+0.1** |

**[measured] The 119 Hz line is not responsible, and this is a clean negative result.** Two tests agree. First, the direct correlation is 0.014 — indistinguishable from zero. Second, a Gaussian-plus-tone input has characteristic function $\Phi_{\text{gauss}}(u)J_0(uA)$, which *reduces* the collapse factors and therefore pulls η *toward* 1 — predicting a residual that slopes negatively against $(\eta_{\text{exact}} - 1)$. The measured slope is $+0.0016 \pm 0.0012$: wrong sign, and not significant. **The Gaussian assumption is safe at ODR 50.**

**[measured] The leftover is concentrated on one axis of one specimen.**

| | X | Y | Z |
|---|---|---|---|
| slot 1 | 0.0135 | 0.0094 | 0.0067 |
| slot 2 | 0.0083 | **0.0207** | 0.0057 |

Five of six axis-groups sit at 0.006–0.014, straddling the 0.0065 repeatability. Slot-2 Y is the outlier at 0.0207, and it is also the axis with the largest σ. **[inference]** That pattern points to a per-axis effect rather than a phase-shaped or theory-shaped one, and it is consistent with the φ correlation above being an artefact of one axis rather than a real phase dependence. **[verify]** Refit with slot-2 Y excluded and see whether the φ correlation survives; if it does not, there is no phase-shaped residual left to explain.

---

## 9. There is no phase-shaped residual — it was one axis

**[measured]** §8's φ correlation ($r = -0.264$, $t = -2.7$) does not survive removing slot-2 Y:

| set | n | resid RMS | $r(\varphi)$ | $t$ | $\chi^2_\nu$ |
|---|---|---|---|---|---|
| all | 96 | 0.0119 | −0.264 | −2.7 | 3.34 |
| without slot-2 Y | 80 | 0.0091 | −0.139 | −1.2 | 1.98 |
| without all Y axes | 64 | 0.0091 | −0.095 | −0.8 | 1.95 |

Every covariate drops below significance, not only φ. The "without all Y" row is the defensible one because its exclusion rule does not reference the outcome, and it gives the same answer.

**[inference] The likely cause is non-Gaussianity, and it is measurable.** The tail ratio $\sigma/\sigma_{\text{robust}}$ is highest on slot-2 Y (median 1.183) against 1.06–1.15 for the other five axis-groups. η_exact assumes a Gaussian input, so the residual tracking departure from Gaussianity is the expected failure mode rather than a mystery. **[verify]** Confirm with a direct normality statistic per axis, and consider whether a pre-specified Gaussianity criterion belongs alongside R2 and R4.

**How this must be reported.** The headline stays **0.0119 over all 96 measurements**. Quoting 0.0091 as the result would be outcome-dependent exclusion, which is exactly the discipline R2/R4 exist to enforce. The correct form is: *headline 0.0119; one axis of one specimen contributes disproportionately; sensitivity analysis without it gives 0.0091*.

---

## 10. Is the ODR effect a shared chain gain? Narrowed, not settled

**[measured]** A decimation-chain DC gain acts on all three axes equally, so $s(1000)/s(50)$ should be axis-independent:

| axis | $s$ @ ODR 50 | $s$ @ ODR 1000 | ratio |
|---|---|---|---|
| X | 0.499116 | 0.499531 | 1.000832 |
| Y | 0.499170 | 0.499537 | 1.000736 |
| Z | 0.499281 | 0.499436 | 1.000310 |

Mean ratio 1.000626. Ratio SD is $2.8\times10^{-4}$, about 1.65× the per-axis relative scatter of $s$ itself ($1.7\times10^{-4}$). **[inference]** That weakly disfavours a single shared gain, but three axes cannot exclude it.

**[verify] The check that settles it needs no bench time: the DS-000347 Rev 1.6 signal-path block diagram.** A search returned the block order as *Gyro Only Decimation → AAF → UI Filter → Notch → Offset Registers*. If that ordering is right, OFFSET_USER is applied **downstream** of decimation, a filter gain cannot scale it at all, and the DC-gain hypothesis is dead — leaving a 15σ effect with no mechanism, which is a more interesting position than the one currently written down. Read the diagram before committing to either version.

---

## 11. The software dither sweep — the ρ↔ODR confound is closed

**[measured]** `software_dither.py` adds synthetic Gaussian noise of known SD $d$ to the 20-bit stream and truncates the sum on the register lattice. 4704 simulated measurements from 14 records, $d$ from $0.25\,\Delta$ to $3\,\Delta$, 8 independent realisations per (record, axis, $d$).

**Why this is an independent test and not a restatement.** $u = x + n$ is genuinely the continuous input to the simulated quantiser, so ρ and φ are read straight off $u$ with **no Sheppard term and no half-lattice phase offset**. None of the §3 correction machinery is used. If the software sweep agrees with η_exact, that agreement cannot be an artefact of the corrections.

**Residual, by ρ band, pooled over ODR:**

| ρ band | n | η range | resid RMS | resid mean |
|---|---|---|---|---|
| 0.25–0.40 | 576 | +0.145 to +1.860 | 0.0137 | −0.0005 |
| 0.40–0.60 | 864 | +0.669 to +1.353 | 0.0201 | −0.0000 |
| 0.60–0.90 | 600 | +0.877 to +1.083 | 0.0303 | +0.0004 |
| 0.90–1.40 | 913 | +0.859 to +1.113 | 0.0344 | −0.0000 |
| 1.40–2.20 | 1038 | +0.754 to +1.275 | 0.0675 | −0.0008 |
| 2.20–3.20 | 702 | +0.629 to +1.327 | 0.1026 | +0.0020 |

Unbiased across the whole range. The growing RMS is estimator variance, not model error — the simulation's own spread across realisations is 0.029 median, comparable to the pooled residual of 0.055.

**The confound test. [measured]** Matching ρ across a 20× change in ODR:

| ρ band | resid, ODR 50 | resid, ODR 1000 | difference |
|---|---|---|---|
| 0.71–0.95 | $-0.0010 \pm 0.0055$ | $-0.0021 \pm 0.0060$ | $-0.0012 \pm 0.0081$ |
| 0.95–1.27 | $+0.0009 \pm 0.0049$ | $+0.0002 \pm 0.0028$ | $-0.0007 \pm 0.0056$ |
| 1.27–1.69 | $-0.0029 \pm 0.0093$ | $-0.0018 \pm 0.0049$ | $+0.0010 \pm 0.0105$ |
| 1.69–2.25 | $-0.0001 \pm 0.0095$ | $-0.0031 \pm 0.0078$ | $-0.0031 \pm 0.0123$ |
| 2.25–3.00 | $+0.0083 \pm 0.0156$ | $-0.0063 \pm 0.0114$ | $-0.0146 \pm 0.0193$ |

**All five bands agree within 0.8σ.** Mean difference −0.0037, RMS 0.0067, largest $|t| = 0.8$.

**[inference] The objection is answered.** At matched ρ, η does not depend on ODR — so the η(ρ) curve is not a decimation or filter artefact. Every confound the AAF attempt failed to hold still (§7) is held still here by construction: same record, same ODR, same filter, same line, same correlation structure, same die temperature, and the only thing changing is ρ by a known amount.

This also discharges the R6 "software dither sweep" leg, which had never existed.

**Limitation to state.** The sweep starts at $d = 2\Delta' = 0.25\,\Delta$, because below that the $\Delta'$ lattice of $x$ survives into $u$ and the Gaussian assumption is violated by construction rather than by the instrument. The region $\rho < 0.3$ is covered by the hardware sweep instead.

---

## 12. Actions

| # | Action | State |
|---|---|---|
| 1 | Supersession register for TN-20/21/22/23 | **DONE** — `SUPERSEDED.md`, Z.1–Z.9, plus a banner at the head of each affected note. Written as one register rather than four Appendix Z sections, because four partial appendices are four things to keep true |
| 2 | Software dither sweep | **DONE** — `software_dither.py`, §11. Confound closed, R6 leg discharged |
| 3 | More repeat pairs to pin $\sigma_\eta$ | **PLANNED** — `plan_night4.txt`, 32 records, 7 h 18 min. 6 settings × 4 replicates round-robin gives 54 dof, so $\sigma_\eta$ to ±10% instead of ±32%. Needs a night |
| 4 | Refit without slot-2 Y | **DONE** — §9. No phase-shaped residual survives; likely non-Gaussianity |
| 5 | Manuscript: one Δ′²/12 in three places | **DONE** — `04_method.tex` §4.2 brief rewritten around the three places, and `\eqref{eq:quantities}` now carries all three terms |
| 6 | `fig8` three traces | **DONE** — three panels, both specimens marked, panel 2 carries the predicted −1/64 line. Panels 2–3 use a zoomed shared axis because panel 1's 0.38 RMS otherwise makes the last two visually identical |
| 7 | Do not run more AAF records | **CLOSED** — §7 supersedes; recorded in `SUPERSEDED.md` Z.6 |
| 8 | **[verify]** the ODR DC-gain hypothesis | **NARROWED** — §10. Per-axis ratio test weakly disfavours a shared gain; the block diagram settles it in ten minutes |
| 9 | Delete `icm_offset_for_phase()` and the `phase` directive | **DONE** — function removed with the reasoning left at its old site; the directive is now *refused* rather than reinterpreted, so a stale plan fails loudly. Needs a reflash to take effect |

**Remaining, in priority order:** action 3 (one night), action 8 (ten minutes at
the datasheet), the Gaussianity statistic of §9, and the relevance evidence for
manuscript §6 — which is the only item that actually gates the preprint.

---

## 10. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 30 Jul 2026 | Initial issue. Third reference correction identified (+1/64, predicted not fitted, validated on six groups); sweep replicated on specimen 2 at 0.0133; repeatability σ_η = 0.0065 established; step size shown ODR-dependent at 15σ with the estimator hypothesis excluded; AAF ρ axis recorded as a negative result and superseded by software dither; 119 Hz line excluded as a residual source by two independent tests |
