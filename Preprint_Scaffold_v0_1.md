# Preprint scaffold v0.1 — 30 July 2026

**Purpose:** a section-by-section frame for the first preprint, with each claim tied to the data that supports it and the figure that shows it. Prose is deliberately not written; what is written is the *argument order*, the *evidence*, and the *gaps*.

**Reading order for this document:** §0 first — it is the honest readiness answer and it changes what you do next.

---

## 0. Is there enough? Yes, with two conditions, and one of them is cheap

Critical Analysis v2.1 Z.1 set three conditions for publishability. Their status:

| # | Condition (Critical Analysis Z.1) | Status |
|---|---|---|
| a | *"hardware must deliver a decisive result — either the memoryless-rounder assumption is confirmed, or an architecture is identified; **either outcome publishes**"* | **MET, decisively.** V0.4 identified truncation bit-exactly: 450 of 450 discriminating samples across a 40× ODR range, zero ambiguous |
| b | *"the practice-evidence gap must be closed or the consequences section overreaches"* | **NOT MET.** Concept Note Z.5's relevance evidence is still uncited. Desk work, no hardware |
| c | *"claims stay phase-conditional throughout"* | Achievable — it is a writing discipline, not a measurement |

**What exists now:** 49 records, 147 axis-measurements, two specimens, three axes.

| Evidence | Scale | Quality |
|---|---|---|
| Architecture identification | 450/450 discriminating samples, three ODR | Bit-exact, no statistics needed |
| ODR axis, η(ρ) | 42 axis-measurements, ρ over 1.01 decades, 2 specimens | residual RMS 0.067 against exact theory |
| **Controlled phase sweep, η(φ)** | **48 measurements, φ from 0.05 to 0.99, η from −0.344 to +2.478** | **residual RMS 0.0179, zero free parameters** |
| Code histograms | 4 phases | max discrepancy 0.005, nothing fitted |
| Allan slopes | 4 records | no −1 term anywhere; −½ family confirmed |

That is a real measurement paper. **The core is publishable now.** Two things gate it, and only one is expensive.

**Gate 1 — relevance evidence (cheap, do it first).** Concept Note Z.5 names this the paper's weakest structural point: the claim *"the corner is the standard calibration configuration"* is uncited. Needed: verbatim Kalibr and `allan_variance_ros` guidance, and the default ODR/FSR of the common drivers. Half a day at a desk. Without it, §7 overreaches and a referee will say so.

**Gate 2 — rule R6 (must be either met or explicitly scoped down).** TN-14 §6 R6 requires hypothesis selection by joint likelihood over {H0…H3} on (code histogram, η̂, software sweep), *"never on a single summary statistic"*. That pipeline does not exist. Two honest options:

- **(i) Build it** — the code-histogram half is validated (max discrepancy 0.005) and the software dither sweep re-uses existing 19-bit records, so this is analysis work, not bench work. A few days.
- **(ii) Scope down** — state in the paper that architecture identification rests on the *bit-exact* V0.4 comparison rather than on likelihood, that η is reported as a *validation* of the identified architecture rather than as a selector, and that R6 is therefore not invoked. This is defensible **because V0.4 is bit-exact** and needs no statistics at all.

Option (ii) is honest, costs nothing, and is arguably stronger. **Recommended for the preprint; build (i) for the journal version.**

**What is missing but does not block a preprint:** slot-2 phase sweep (one night, and it would materially strengthen §5); FSR axis; thermal ramp as a second phase axis; cross-vendor probe; GUM budget; the 4.9σ step-size discrepancy (TN-23 §5, touches no physics).

---

## 1. Title, venue, format

**Title (Critical Analysis Z.4 recommendation, unchanged — it survives every experimental branch):**

> **Rate-Register Quantisation in MEMS Gyroscopes: Exact Statistics of an Unmeasured Term in Fitted Angle Random Walk**

**Venue.** Preprint first. arXiv `eess.SP` needs an endorser; engrXiv needs none but its deposits are permanent, which makes later arXiv cross-posting of the *same* PDF inadvisable. Decide before posting, not after.

**Format.** Two-column IEEE or single-column MST style — pick the target journal's now, because it sets the figure aspect ratios. Target **10–12 pages**. Critical Analysis Z.2 warns the real risk is depth, not niche: full phase-dependent derivations and the H0–H3 tables go to **supplementary material**, and the main text keeps one theory section, one procedure section, one results section, one consequences section.

---

## 2. Section frame

Word budgets assume ~7000 words of main text.

### Abstract (~200 words)
Order: practice → gap → what was measured → result → consequence. Lead with the transfer rule, not with quantisation theory — the reader must know what breaks before they care why.
Must contain: "truncating rate register", "−½ slope", "two measured parameters", "no free parameters", and one number. Suggested number: **η measured from −0.344 to +2.478 at fixed configuration**, or **×4.7 in fitted ARW**.

### 1. Introduction (~900 words)
1. Stochastic IMU calibration fits N, B, K and transfers them across configuration by a √ODR rule.
2. That rule is stated as a *condition* in Kalibr's own documentation, not a validated result. **[needs verbatim quote — Gate 1]**
3. The standards construct that would model register quantisation — IEEE-952's Q — describes angle-increment outputs, a different architecture.
4. So for a rate register the term is unmodelled, and lands on the −½ family where it is absorbed into fitted ARW.
5. Contributions, four bullets, matching Concept Note Z.3's survivability ranking.

Explicitly **not** claimed (one sentence each, and they must be in the introduction, not buried): this is not a new quantiser theory; scale factor and misalignment are a different calibration family (IMU-TK); the effect vanishes at high ρ.

### 2. Background and related work (~800 words)
Bennett 1948, Sripad–Snyder 1977, Widrow–Kollár 2008 cited **as the foundation, on our own initiative** — Objections Z.2 is explicit that the "this is Bennett with a gyroscope attached" objection must be pre-empted by citing Bennett ourselves.
IEEE-952 Q and why it is the wrong architecture. Then **Table 1**, the toolchain survey.

> **Table 1** — from GMWM-to-Kalman-Q v1.2 §3, with its Z.4 correction. Columns: toolchain | √ODR transfer | models register quantisation | exposes ρ or μ | assumes PQN. Rows: Kalibr, allan_variance_ros, imu_utils, GMWM (simts/wv), MATLAB Sensor Fusion, NaveGo.
> **The framing must be Z.4's:** the pipelines *do not model register quantisation at all* — absent from the model set, not approximated within it. Do **not** write "they adopt Δ²/12 and it is invalid". That is false and a referee will check.

### 3. Theory (~1200 words)
Only what the results need. Everything else to supplementary.
- Truncating quantiser, sawtooth series, η = 12[2 Cov(u,e) + Var(e)]
- Gaussian input ⇒ everything collapses onto g_k = exp(−2π²k²ρ²)
- η(ρ, φ), the two limits (−12ρ² mid-code, 3−12ρ² at an edge)
- **Symbol conventions table.** Non-negotiable: Vaccaro & Zaki (2012) use R for ARW density and Q for RRW, clashing with IEEE-952 Q and Kalman Q/R.
- State the φ convention *twice* — edge-referenced, and φ_TN-14 = φ − ½.

**Figure 1** ← `fig1_eta_vs_rho.png` — η(ρ) with the all-phase band.

### 4. Instrument and method (~1000 words)
Board, two ICM-42688-P, 32 MHz deliberately (a science parameter — clock noise is dither), SD-logged, battery, USB disconnected during science runs.
Rule R3 stated structurally: σ comes **only** from the 19-bit stream; the 16-bit histogram is a test statistic, never an estimator. This is the anti-circularity defence and it belongs in the method, prominently.

**§4.x — the reference channel is a quantiser too. This is a genuine methods contribution and should be its own subsection.**
The 20-bit field truncates on a 0.125 Δ lattice, so φ read from it is low by 1/16 Δ and σ² carries Δ′²/12. Sheppard's correction, applied to the instrument's own reference.
**Figure 2** ← `fig8_reference_truncation.png`
**Label this EXPLORATORY** — see §4 of this scaffold.

**§4.y — the vernier.** OFFSET_USER steps 0.4995 Δ; the miss from ½ is what makes it sweep. A coarse trim register turned into a fine phase control.
**Figure (supplementary)** ← `fig9_vernier.png`

### 5. Results (~1400 words)
Order matters — architecture first, because everything downstream is conditional on it.

**5.1 Architecture identification.** V0.4: `gyro16 == gyro20 >> 4` exactly, 450/450 discriminating samples over 25/100/1000 Hz. Truncation, not rounding. Bit-exact, no statistics.
**5.2 η against ρ.** ODR axis, two specimens. **Figure 1**.
**5.3 η against φ — the causal manipulation.** One specimen, one configuration; the only change is a trim register. **Figure 3** ← `fig7_phase_sweep.png`. Residual RMS 0.0179, no free parameters.
**5.4 Independent channel.** Code occupancy to 0.005. **Figure (supplementary)** ← `fig15_code_histograms.png`
**5.5 The Allan domain.** **Figure 4** ← `fig10_allan_family.png`. The −1 slope is absent.

### 6. Consequences (~1000 words) — **gated on Gate 1**
**6.1** Fitted ARW at fixed configuration. **Figure 5** ← `fig11_arw_consequence.png`, ×4.7.
**6.2** Transfer across configuration. **Figure 6** ← `fig16_transfer_three_worlds.png`. Three worlds; the PQN-aware world is still wrong and below 69 Hz returns a negative density.
**Figure (supplementary)** ← `fig17_transfer_surface.png`
**6.3** Effect size vs ODR table, so a reader can locate their own configuration — Concept Note Z.5 asks for exactly this.

### 7. Limitations (~500 words)
Concede these **before** a referee raises them (Objections Z.1, Z.2):
- E_μ[G] = 1 exactly. Averaged over units the classical model is unbiased. The error is a per-unit, sign-indefinite gamble — which is *worse* for someone who owns one sensor.
- Two specimens, one part number, one FSR, one phase-swept specimen.
- Bias instability limits within-record phase stability to 0.006–0.051 Δ.
- The 4.9σ step-size discrepancy, unresolved.
- Bandwidth and register failures both present in raw data; §6 separates them.

### 8. Conclusion (~250 words)

---

## 3. Figure budget

Main text **six**. Everything else supplementary.

| Fig | File | Carries |
|---|---|---|
| 1 | `fig1_eta_vs_rho.png` | η(ρ), all-phase band |
| 2 | `fig8_reference_truncation.png` | the methods result |
| 3 | `fig7_phase_sweep.png` | **the causal manipulation** |
| 4 | `fig10_allan_family.png` | **the architectural claim** |
| 5 | `fig11_arw_consequence.png` | the per-unit consequence |
| 6 | `fig16_transfer_three_worlds.png` | the transfer consequence |

Supplementary: 9, 12, 13, 14, 15, 17, 18, and 2/3/4 as diagnostics.

fig5 is no longer generated — it showed the inconclusive 28 July trio and fig12
replaces it.

**Check before F10 carries its caption:** the $-\tfrac12$ vs $-1$ claim is a
SHORT-$\tau$ statement, and the figure currently annotates the long-$\tau$
slope. Measured short-$\tau$ slopes are $-0.43$ to $-0.60$ across twelve
axis-records, so the claim holds — but the figure should fit and report the
range it is actually arguing from.

**Before submission:** regenerate at the journal's column width with a serif font matching the body text, and check every figure is legible in greyscale.

---

## 4. Pre-registration

Superseded — see `PREREGISTRATION.md`. Short version: formal pre-registration
is not a norm in metrology and the ceremony is not worth it here. What the
paper needs is the confirmatory/exploratory split and the deviations table,
both of which live in that file. `PREREG-02.md` is a run plan for the
remaining nights, kept because writing the decision rule down beforehand is
what stops you fooling yourself, not because anyone will check it.


## 5. Data and code availability

Zenodo deposit, cited by DOI:
- `.sdat` records byte-for-byte (49 files) — the primary record, so every published number is re-derivable from the instrument's own output
- HDF5 conversions plus the converter
- `analyse.py`, `figures*.py`, `offset_fit.py`, `sdat.py`, and the firmware at its tagged commit
- `summary.csv`
- SHA-256 manifest

**Add to `analyse.py` before the deposit:** a `--version` that prints the git commit, and write it into `summary.csv`. A deposited CSV with no provenance is a deposited CSV nobody can use.

---

## 6. Order of work

| # | Task | Cost | Blocks |
|---|---|---|---|
| 1 | **Relevance evidence** (Gate 1) | half a day, desk | §6 entirely |
| 2 | Decide R6: build or scope down (Gate 2) | 0 or ~3 days | §5.1's framing |
| 3 | `PREREG-02.md` + git tag + Zenodo | 2 hours | every future run |
| 4 | Slot-2 phase sweep | one night | §5.3 generality |
| 5 | Draft §3 and §4 | — | they are the most stable sections |
| 6 | Deviations table | 1 hour | §7 credibility |
| 7 | Symbol conventions table | 1 hour | reviewer goodwill |

**Do 1 and 3 first.** One unblocks a third of the paper for half a day's desk work; the other stops the same problem recurring on every night from here on.
