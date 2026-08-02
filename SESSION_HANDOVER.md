# Session handover — 30 July 2026 (post night 3)

Everything below is on disk. Read TN-24 first.

## Night 3 ran clean and changed the headline

45/45 records, no CRC failures, no overflows, every gated record passed R2.
Full analysis in **TN-24**. Four things came out of it:

**1. The reference correction belonged in three places and had been applied to
two.** η's numerator needs $+\Delta'^2/12$ as well as ρ and φ needing their
corrections, because η must be referred to the *continuous* rate and $x$ is
itself quantised. Missing it made every η in the campaign low by exactly
$(\Delta'/\Delta)^2 = 1/64 = 0.015625$.

Fixed in `analyse.py`; `eta_uncorr` retained in `summary.csv` for audit;
`summary_preTN24.csv` kept byte-for-byte; all figures and `numbers.tex`
regenerated.

| | before | after |
|---|---|---|
| slot-1 sweep | 0.0179 | **0.0103** |
| slot-2 sweep | 0.0208 | **0.0133** |
| both, n=96 | 0.0194 | **0.0119** |

The magnitude is *predicted*, not fitted — six independent groups agree with
1/64 to within 1.1σ. It was found in a residual, which must be declared, but
nothing was tuned.

**2. The sweep replicates on specimen 2.** φ 0.011–0.998, η −0.325 to +2.494,
residual 0.47% of range. The k list needed no change and that was a
prediction: specimen 2's vernier period (2305 steps) exceeds the register
ceiling (2047), so coverage comes from the three axes' differing intrinsic
phases filling each other's gaps.

**3. Repeatability now measured: σ_η = 0.0065 per record.** Best sentence in
the campaign: between two records five hours apart, φ drifted 0.14 of a code
and η moved by **1.435**, and the theory tracked it to 0.008 with nothing
adjusted. But the residual (0.0119) is ~1.8× the repeatability, so χ²ᵥ ≈ 3.4 —
not yet consistent with noise. With n=6 pairs that could be 1.3 to 8; six more
pairs (90 min) would settle it.

**4. Step size is ODR-dependent at 15σ**, and the estimator hypothesis is
dead — ladder and vernier agree to <1σ at both rates.

| | ODR 50 | ODR 1000 |
|---|---|---|
| ladder (μ) | 0.499189 ± 0.000049 | 0.499513 ± 0.000073 |
| vernier (φ) | 0.499157 ± 0.000013 | 0.499503 ± 0.000020 |

s(1000)/s(50) = 1.000690. Touches no physics — φ is measured per record — but
it means a k-ladder is ODR-specific.

**Negative results worth as much as the positive ones:**

- **The AAF ρ axis does not work.** My pre-run prediction (ρ would rise at ODR
  50) was wrong — `aaf_floor` sets the anti-alias filter ahead of decimation,
  not the ODR-tracking UI filter, so ρ fell everywhere. Worse, where ρ moves
  usefully the 119 Hz line carries 34–62% of the variance in the default
  records, and the floor records have r₁ = 0.68–0.84 sample correlation
  inflating SE(η) 2.3–3.4×. **Don't run more AAF records.** The right
  instrument is the software dither sweep — no bench time, already required by
  rule R6.
- **The 119 Hz line is not the residual source.** Two independent tests: direct
  correlation r = 0.014, and the Gaussian-plus-tone model predicts a negative
  slope against (η_exact − 1) where the measured slope is +0.0016 ± 0.0012.
  Gaussianity is safe at ODR 50.
- **The leftover residual is one axis.** Five of six axis-groups sit at
  0.006–0.014; slot-2 Y is 0.0207. Refit without it before believing the weak
  φ correlation (r = −0.26).

## Methods section reordered

`04_method.tex` now follows apparatus → procedure → reduction → selection:

| | was | now |
|---|---|---|
| 4.1 | Instrument | Instrument |
| 4.2 | Estimators | **The reference channel is itself a quantiser** |
| 4.3 | Circularity | **Phase manipulation** |
| 4.4 | Reference channel | Estimators |
| 4.5 | Phase manipulation | Choice of estimator, and circularity |
| 4.6 | — | **Record selection** (new) |

Two reasons this mattered rather than being tidying:

- **§4.2 had to move above the estimators.** The equations are written in terms
  of $x$, and $x$ is not the continuous input. In the old order a reader met
  the definitions, computed from them, and only two subsections later learned
  they needed correcting — which is the circularity charge arriving by the back
  door, because it looks as though the correction was applied because it
  helped.
- **§4.6 is new.** It was paragraph 4 of a comment block stranded under the
  circularity subsection, which was the wrong home: exclusions are not part of
  choosing an estimator, and they belong last, as the final filter between
  instrument and results. It now has a genuinely strong opening — night 3
  excluded nothing.

`\eqref{eq:quantities}` has been corrected: all three expressions now carry the
reference-lattice term, and the η one is new. Your sentence "$x$ is the
quantity $Q$ is a quantisation of" was directly contradicted by §4.2, so I
changed it to "$x$ is a finer quantisation of the same continuous rate $v$" —
check you're happy with that wording, it's your prose.

Build verified: no undefined references or citations, 11 pages. (`siunitx`
isn't in the sandbox so the check used a stub; the real build is on your
machine.)

## Done since (all TN-24 actions bar one)

- **Software dither sweep** — `software_dither.py`. 4704 simulated
  measurements, ρ 0.31–3.24, unbiased throughout, and **at matched ρ across a
  20× ODR change all five bands agree within 0.8σ**. The ρ↔ODR confound is
  closed and the R6 software-sweep leg is discharged. Crucially it uses none of
  the reference corrections, so the theory's agreement is not an artefact of
  them. TN-24 §11.
- **No phase-shaped residual** — it was one axis. Dropping slot-2 Y takes
  r(φ) from −0.264 to −0.139 and every covariate below significance; RMS
  0.0119 → 0.0091, χ²ᵥ 3.34 → 1.98. Likely non-Gaussianity: slot-2 Y has the
  highest tail ratio (1.18). **Headline stays 0.0119 over all 96** — quoting
  0.0091 would be outcome-dependent exclusion. TN-24 §9.
- **Supersession register** — `SUPERSEDED.md`, Z.1–Z.9, plus a banner at the
  head of TN-20/21/22/23. Written as one register rather than four Appendix Z
  sections, because four partial appendices are four things to keep true.
- **`phase` directive removed from the firmware** — `icm_offset_for_phase()`
  deleted with the reasoning left at its old site; the directive is now
  *refused*, not reinterpreted, so a stale plan fails loudly. Needs a reflash
  to take effect; nothing depends on it.
- **fig8 rebuilt as three panels** — nothing corrected / φ and ρ corrected /
  all three. Both specimens marked and superimposed in panel 1, which is the
  point. Panel 2 carries the predicted −1/64 line.
- **ODR DC-gain hypothesis narrowed** — per-axis ratios 1.000832 / 1.000736 /
  1.000310, SD 1.65× the per-axis scatter of s, which weakly disfavours a
  shared chain gain. The DS-000347 signal-path block diagram settles it in ten
  minutes: if OFFSET_USER sits downstream of decimation the hypothesis is dead.
- **`plan_night4.txt` written** — 32 records, 7 h 18 min, 6 settings × 4
  replicates round-robin plus 8 high-ρ repeats. Pins σ_η to ±10%.

## Known defects

1. ~~`icm_offset_for_phase()` assumes 0.512 Δ/step~~ — **fixed 30 July**, both
   the function and the directive. Needs a reflash to take effect.
2. **The Arm dialog contradicts the firmware** — says "battery boot" and "will
   not run while USB is connected"; `seq_autorun_if_armed()` tests
   *enumeration*, not VBUS, and runs happily on a charger. One-line fix in
   `sheppard_console.py`. Powering from a charger is what the plans assume.
3. **FSR axis is unavailable, not merely unrun** — no FSR field in the sequence
   format, `fs_sel` hard-coded, hi-res mode appears to force ±2000 dps. State
   as a limitation in §7. **[verify]** against DS-000347 Rev 1.6.

## Housekeeping

- Two zero-byte junk files in the repo root, `cd` and `git`, from a mistyped
  command.
- 326 PNGs in `Figures/`. Most are diagnostics; `git rm --cached` the tracked
  ones and gitignore the directory — `\graphicspath` reads them from disk, so
  the manuscript doesn't need them committed.
- LaTeX build artefacts in `paper/` want gitignoring (`main.aux`, `.fdb_latexmk`,
  `.fls`, `.log`, `.out`, `.synctex.gz`, `.bbl`, `.blg`).
- `paper/.latexmkrc` **does** exist — an earlier handover said it was missing,
  which was wrong; it's a dotfile and `ls` hid it.

## Open technical items

- `fig8_reference_truncation` needs three traces now: uncorrected, two-place,
  three-place.
- `fig10` reports the long-τ Allan slope but the −½ vs −1 claim is a short-τ
  statement. Claim holds (−0.43 to −0.60); the figure should fit the range it
  argues from.
- Table 1 rows 4–6 unverified: GMWM, MATLAB Sensor Fusion, NaveGo, and whether
  `imu_utils` fits Q internally.
- **[verify]** the ODR-dependent DC-gain hypothesis (TN-24 §6) against the
  filter specification.
