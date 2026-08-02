# What the older corpus has that the newer documents lost

**30 July 2026.** Checked `Concept_Note_V2_3`, `00_CORPUS_INDEX_v2_0` and the
audit findings against TN-20…TN-24, `Preprint_Scaffold_v0_1.md`, `README.md`
and the `paper/` briefs.

The technical notes from TN-20 onwards are a *campaign log*. They record what
the instrument did. They do not carry the framing, and in several places the
framing is the thing that stops a claim being wrong. Nine items below; the
first three would each be a referee's first paragraph.

---

## ★★★ 1. "Fitted ARW is deflated" is WITHDRAWN. Nothing since TN-20 says so.

`Concept_Note v2.3 Z.2`:

> **Withdrawn:** "fitted ARW is systematically deflated."
> **Reason:** $\mathbb{E}_\mu[G] = 1$ **exactly** for a uniform phase prior
> (TN-12 v1.1 Appendix Z.1). Averaged over an ensemble of units, the classical
> model is **unbiased**. The previous claim was the $\mu = 0$ special case
> presented as a population result.

The replacement claim, which is stronger:

> The standard model is neither conservative nor accurate: it is a **per-unit,
> per-run gamble** whose outcome — including its **sign** — depends on an
> unmeasured sub-LSB bias phase that also **drifts with temperature**, and no
> existing tool measures either of the two numbers $(\rho, \mu \bmod \Delta)$
> that would tell a practitioner which regime their sensor is in.

**Why this matters now.** Our measured range, $\eta = -0.33$ to $+2.49$ at
*fixed configuration*, is the direct experimental confirmation of exactly this
— the sign flips with phase. But every recent document states the range without
stating what it means. Written carelessly, §6 will claim a systematic bias, a
referee will average over φ, and the paper loses its central consequence.

**Action: the phrase "per-unit, sign-indefinite lottery" must appear in the
abstract and in §6.** Never "systematically deflated" or "systematically
inflated".

---

## ★★★ 2. The Bussgang gain $G(\rho,\mu)$ has vanished entirely

Not one document since TN-20 mentions $G$. It is half the physics.

- $\eta$ = **power the register adds**
- $G$ = **gain the register applies to the signal already there**

At the ICM corner $G$ spans $[0.75, 1.25]$ over phase, i.e. $G^2 = 56\%$ at
$\mu = 0$: the physical noise is *attenuated*. That is a different failure from
adding the wrong amount of noise, and it drives the argument in item 3.

**Action: check whether `analyse.py` computes $G$ at all. If not, it should —
the data to do it is already on disk, and a paper about a quantiser that
reports only its added power is telling half the story.**

---

## ★★★ 3. The inflation-factor rebuttal — the strongest paragraph in the corpus

`Concept_Note v2.3 §8`, absent from every newer document:

> The ad-hoc 5–10× inflation is a defence against an *under-estimated* noise
> density. It is **no defence at all against a gain error.** … **A conservative
> bound built on a deflated estimate is not conservative.**

with the downstream consequence: a deflated $Q$ produces an *optimistic,
inconsistent* Kalman filter (Sangsuk-Iam & Bullock 1990) — precisely the
failure mode the inflation practice exists to prevent.

This pre-empts the single most likely referee objection ("practitioners inflate
by 10× anyway, so who cares"). Without it §6 has no answer.

---

## ★★ 4. The dated causal narrative — why nobody found this

`Concept_Note v2.3 §3.4`:

> The assumption did not fail because it was wrong when written. It failed
> because consumer MEMS gyros became quieter than ~4.3 mdps/√Hz, and nothing
> announced the crossing.

With the worked comparison: an MPU-6050-class part (≈5 mdps/√Hz, 2011) sits at
$\rho = 0.58$ where PQN is valid to 2%; the ICM-42688-P (2.8 mdps/√Hz, 2020)
sits at $\rho = 0.32$ where it is not.

This is the introduction's best paragraph and it is nowhere in `paper/`.

---

## ★★ 5. $\kappa \in \{1,2,3\}$ and the closed hypothesis space H0–H3

The scaffold mentions H0–H3 but no recent document carries the signature table
or $\kappa$. Worth keeping because it is what makes the architecture
identification a *measurement-science* contribution rather than a footnote:
$\kappa$ is a property of the silicon, identified from output data alone.

Also lost: **only non-subtractive dither is physically available to the
vendor** (the output must lie on the integer lattice), which is what closes the
hypothesis space. Without that sentence H0–H3 looks arbitrary.

---

## ★★ 6. Numbers that should be in Table 2 or the theory section

| Quantity | Value | Source |
|---|---|---|
| deadband zero | $\rho_0 = 0.288814$ | audit, verified to machine precision |
| η minimum | $\rho \approx 0.20$, output carries 31% of input power | Concept §7 |
| PQN valid within 2% | $\rho \gtrsim 0.62$ | Concept §3.1 |
| at $\mu \approx \Delta/4$ | exact theory mimics PQN to <1% | index, finding 1 |
| Sripad–Snyder autocorrelation | matches Widrow & Kollár Eq. 20.24 verbatim | audit |
| SE(ρ) from code-density MLE | 0.0012 | audit |

The $\mu \approx \Delta/4$ line is important and slightly awkward: there is a
phase at which the classical model is *right*. Say it before a referee does.

---

## ★★ 7. Kollár's whiteness criterion — a live constraint on our own comparisons

$\Delta/\sigma < 4.6\,f_N/f_s$. At a fixed AAF with ODR swept to 8 kHz this is
violated by 66×, and the quantisation error is not white but concentrated at
low frequency (simulated LF/HF ratio 680:1). The corpus resolution was to
restrict the primary inter-ODR difference test to **ODR 100 vs 200–400 Hz**.

**We have ODR-8000 records in the campaign.** Check they are not being used in
a whiteness-assuming comparison anywhere.

---

## ★ 8. The "what this paper is not about" list

`Concept_Note v2.3 Z.6`. Scale factor, axis misalignment and deterministic
nonlinearity belong to a different calibration family (IMU-TK, Tedaldi et al.
2014) — one sentence in the introduction stops a referee asking why IMU-TK is
missing from the toolchain survey.

Also there: DNL is **not** orthogonal, and the code-density histogram procedure
already collected **is** the IEEE Std 1241-2010 linearity test. Free citation,
free falsifier (F4).

---

## ★ 9. References — `references.bib` is far short of the corpus list

The Concept Note carries ~45 references. Two still need resolving before
submission:

- **Vardeman (2005)** 'Sheppard's correction for variances and the
  "quantization noise model"', IEEE TIM — **volume/pages [verify]**
- **Kollár (1994)** 'Bias of mean value and mean square value measurements
  based on quantized data', IEEE TIM — **volume/pages [verify]**

And three were never retrieved: Han & Wang (2011); El-Sheimy, Hou & Niu (2008);
Kohl, Györfi & Wagner (2022).

---

## Resolved by this audit — an open item closes

**Hi-res mode forces FSR = ±2000 dps.** `00_CORPUS_INDEX` finding 5 and
`Concept_Note` note 5 both state it, sourced to TN-13 v1.1 read against
DS-000347. My `[verify]` flag in `SESSION_HANDOVER.md` and
`Preprint_Scaffold_v0_1.md` can be **downgraded from unverified to sourced** —
the FSR axis is structurally unavailable, not merely unrun, and §7 can say so.

---

## Stale generated values

`paper/numbers.tex` still carries superseded macros:

| Macro | Value | Problem |
|---|---|---|
| `\stepSizeSweep` | 0.499151 | superseded by the 2×2, TN-24 §6 |
| `\refImprovement` | 76% | pre-TN-24; recompute |
| `\arwSpan` | ×4.7 | check against the corrected ×3.9 / +4% of the double-count erratum |

The last one matters: `GMWM-to-Kalman-Q v1.2` corrected the headline from
"27% understatement / ×15" to "**+4% overstatement / ×3.9**". If `\arwSpan`
descends from the old figure it is wrong.
