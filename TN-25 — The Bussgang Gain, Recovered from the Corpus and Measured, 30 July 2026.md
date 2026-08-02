# TN-25 — The Bussgang gain: recovered from the corpus, derived, and measured

**Version 1.0 — 30 July 2026**
**Status:** a governing quantity the campaign had never computed is now measured across the whole dataset, and it confirms the corpus claim that the calibration error is a per-unit lottery rather than a bias.
**Arises from:** `CORPUS_AUDIT_30Jul2026.md` items 1–3. Nothing between TN-20 and TN-24 mentions $G$.
**Depends on:** no new records. Analysis only, on the 94 already held.

**Tags:** **[fact]** · **[measured]** · **[inference]** · **[verify]**

---

## 1. What was missing

`Concept_Note v2.3` §3.1 defines the observation model with **two** quantiser
effects, not one:

$$S_{\rm obs}(f;c) = G(\rho,\varphi)^2\,|H(f;A)|^2\,S_{\rm phys}(f;\theta) + S_n(f;\rho,\varphi,S_x)$$

- $\eta$ — the power the register **adds**
- $G$ — the gain the register applies to the power **already there**

Every document from TN-20 onwards reports $\eta$ and none mentions $G$. The
campaign has been measuring half the effect.

---

## 2. Closed form

**[fact]** Same Fourier route as $\eta$. With $Q = u + e - \tfrac12$ and the
sawtooth $e = \sum_k \sin(2\pi k u)/(\pi k)$,

$$G \equiv \frac{\operatorname{Cov}(Q,u)}{\operatorname{Var}(u)} = 1 + \frac{\operatorname{Cov}(u,e)}{\operatorname{Var}(u)}$$

Stein's lemma gives $\mathbb{E}[(u-\mu)\sin(2\pi k u)] = \sigma^2\,2\pi k\,g_k\cos(2\pi k\mu)$, so every term collapses onto the same $g_k$ as $\eta$:

$$\boxed{\;G(\rho,\varphi) = 1 + 2\sum_{k\ge1} g_k \cos(2\pi k\varphi), \qquad g_k = e^{-2\pi^2k^2\rho^2}\;}$$

**Two consequences follow immediately.**

**2.1 $\mathbb{E}_\varphi[G] = 1$ exactly.** Every cosine integrates to zero over
a uniform phase prior. Averaged across an ensemble of units the classical model
is *unbiased* — which is precisely why `Concept_Note v2.3 Z.2` withdrew "fitted
ARW is systematically deflated" and replaced it with the per-unit,
sign-indefinite claim. The derivation above is the analytical basis for that
withdrawal, reproduced independently here.

**2.2 The formula reproduces the corpus figure.** At $\rho = 0.33$ the closed
form gives $G \in [0.767, 1.233]$ against the corpus's quoted $[0.75, 1.25]$.
Independent confirmation that the recovered framing is the right one.

---

## 3. Measured

**[measured]** $G = \operatorname{Cov}(Q,x)/(\operatorname{Var}(x) - \Delta'^2/12)$ on all 94 records. $\operatorname{Cov}(Q, e_{\rm ref})$ is negligible: the reference is well dithered at $\rho' = 8\rho$, so its error is independent at the $10^{-22}$ level.

Phase sweep, 96 axis-measurements, both specimens, $\rho \approx 0.21$:

| | value |
|---|---|
| $G$ measured | **0.135 – 2.179** |
| $G$ closed form | 0.124 – 2.099 |
| residual RMS | 0.0377 (1.9% of range) |
| residual mean | $+0.0316$ |
| $G^2$ at the mid-code floor | **0.018** |

Whole campaign, 282 axis-measurements: $G$ from 0.095 to 2.179.

**3.1 A sixteen-fold span in gain at fixed configuration. [measured]** Two
identically configured specimens of the same part, on the same board, at the
same temperature, differ in the gain applied to their own noise by 16×, purely
through their sub-LSB bias phases.

**3.2 The physical noise is attenuated to 1.8% at mid-code. [measured]** This is
far more dramatic than the corpus corner ($G^2 = 56\%$ at $\rho = 0.33$),
because our sweep sits at $\rho = 0.21$ where the collapse factors are larger.

**3.3 $\mathbb{E}_\varphi[G] = 1$ confirmed on our own data. [measured]**

$$\overline{G} = 1.0584 \pm 0.0647 \quad\Rightarrow\quad 0.9\sigma\ \text{from unity}$$

Specimen 1: $0.977 \pm 0.095$. Specimen 2: $1.140 \pm 0.087$. Both consistent
with 1.

**[verify]** The sweep's $\varphi$ sampling is near-uniform but not exactly so,
so this is an approximation to the uniform-prior average rather than the average
itself. Reweighting by the sampling density would tighten it.

---

## 4. Why this changes what the paper can say

**[inference]** The strongest paragraph in the corpus depends on $G$ and could
not be written from the campaign notes alone:

> The customary 5–10× inflation of a fitted noise density is a defence against
> an *under-estimate*. It is no defence at all against a **gain** error. A
> conservative bound built on an attenuated estimate is not conservative, and a
> deflated process-noise covariance produces an optimistic, inconsistent filter
> (Sangsuk-Iam & Bullock 1990) — the exact failure mode the inflation practice
> exists to prevent.

With $G^2 = 0.018$ measured at mid-code, that argument now has a number behind
it rather than a projection.

**And it fixes the framing risk.** $\eta$ alone invites "the register adds the
wrong amount of noise", which averages away. $G$ with $\mathbb{E}_\varphi[G] = 1$
forces the correct statement: **not a bias, a lottery**.

---

## 5. Open: a $+0.03$ constant in the $G$ residual

**[verify]** The residual mean is $+0.0316$ against an RMS of $0.0377$ — mostly a
constant, which is the same signature that led to the $\eta$ correction of
TN-24 §3. Candidates not yet eliminated:

1. a missing reference-lattice term in $\operatorname{Cov}(Q,x)$, parallel to
   the one $\eta$ needed — note that $Q = \lfloor x \rfloor$ **exactly** (the
   cascade identity), so $Q$ is a deterministic function of $x$ and
   $\operatorname{Cov}(Q, e_{\rm ref})$ may not vanish as assumed in §3;
2. the detrending, which removes a component from both streams;
3. genuine model error, $G$ being more tail-sensitive than $\eta$.

Candidate 1 is the most likely and is checkable analytically in an hour. Until
it is settled, quote $G$ to two decimals and describe the agreement as "1.9% of
range", not as exact.

---

## 6. Also checked, from the same corpus recovery

**6.1 The deadband zero. [measured]** $\rho_0 = 0.288814$ is the mid-code zero.
Our sweep sits at $\bar\rho = 0.2124$, below it, so mid-code $\eta$ must be
negative and edge $\eta$ positive:

| region | n | $\eta$ range | mean | closed form at $\bar\rho$ |
|---|---|---|---|---|
| mid-code, $0.40 < \varphi < 0.60$ | 18 | $-0.328$ to $-0.176$ | $-0.253$ | $-12\rho^2 = -0.541$ |
| edge, $\varphi < 0.1$ or $> 0.9$ | 24 | $+2.045$ to $+2.510$ | $+2.294$ | $3-12\rho^2 = +2.459$ |

Sign structure confirmed. The binned means sit inside the closed-form extremes
because the bins are wide and the extremes are reached only at exactly
$\varphi = 0.5$ and $\varphi = 0$.

**6.2 Kollár's whiteness criterion — and it is not the records we expected.
[measured]** $\Delta/\sigma < 4.6\,f_N/f_s$ with $f_N = 2B_{\rm eff}$.

The corpus warning concerns a **fixed** anti-alias filter with ODR swept
upward, giving a large oversampling ratio. Our design tracks the filter to ODR,
so the ODR-8000 records are comfortable ($\rho = 0.97$–$1.38$).

**62 axis-measurements violate the criterion, and they are the ODR-50 phase
sweep records** — marginally, $1/\rho \approx 4.8$–$5.4$ against a bound of
$4.78$. Low $\rho$ is what does it, not oversampling.

**[inference] This does not touch the variance results.** $\eta$ and $G$ are
second-moment statements and require no whiteness assumption. What the criterion
governs is whether the added error is *spectrally flat*, which matters for two
downstream claims: that the contribution appears at a $-1/2$ Allan slope, and
that the transfer relation $S_{\rm obs} = S_{\rm unq} + \eta\Delta^2/(6\,\rm ODR)$
distributes it evenly in frequency.

**The defence is that we measured the slope rather than assuming it** — $-0.43$
to $-0.60$ over 12 axis-records. State the criterion, state that it is marginal,
and point at the measurement. A referee who knows Widrow & Kollár Ch. 20 will
check this, and finding it acknowledged is worth more than finding it absent.

**6.3 `\arwSpan` is not traceable. [verify]** `make_numbers.py` sets it by hand
as $\times 4.7$, tagged "F11", and it is in the `HAND` set rather than computed
from data. `GMWM-to-Kalman-Q v1.2` corrected this headline from "27%
understatement / ×15" to **"+4% overstatement / ×3.9"**. Until the provenance of
4.7 is established it must not appear in the abstract.

---

## 7. Actions

| # | Action | Priority |
|---|---|---|
| 1 | Settle the $+0.03$ constant in the $G$ residual — §5 candidate 1 first | **High** |
| 2 | Trace `\arwSpan` to fig11's computation or recompute from the corrected transfer relation | **High** |
| 3 | Add $G$ to the manuscript: theory §3.3, results as its own subsection, and the inflation rebuttal in §6 | **High** |
| 4 | A $G(\varphi)$ figure alongside the $\eta(\varphi)$ one — the 16× span is the most striking single plot available | Medium |
| 5 | Reweight the $\mathbb{E}_\varphi[G]$ test by the sampling density | Medium |
| 6 | State the whiteness criterion in limitations with the measured-slope defence | Medium |

---

## 8. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 30 Jul 2026 | Initial issue. $G$ derived, added to `analyse.py` as `gain`/`gain_exact`/`gain_resid`, and measured over 282 axis-measurements. $\mathbb{E}_\varphi[G] = 1$ confirmed at 0.9σ. Deadband sign structure confirmed. Whiteness criterion found marginal on the ODR-50 sweep, not on ODR-8000. `\arwSpan` flagged as untraceable |
