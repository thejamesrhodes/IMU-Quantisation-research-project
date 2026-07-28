# TN-19 — Bring-up Findings, 27–28 July 2026

**Status:** working notes for the manuscript. Everything here is fresh from hardware or from DS-000347 **Rev 1.6** read directly. The corpus was built against **v1.2, marked pre-production**, which is why several items below contradict it.
**Purpose:** capture the reasoning while it is fresh. Several of these change documents the campaign design rests on.

**Tags:** **[fact]** datasheet or recomputed · **[measured]** observed on Sheppard · **[inference]** reasoned from sourced facts · **[verify]** not yet confirmed.

---

## 1. V0.4 answered: the 16-bit register is a truncation, not a rounder

**[measured]** The 16-bit gyro register equals bits **[19:4]** of the 20-bit hi-res FIFO word — a plain arithmetic right shift, i.e. floor, not round-to-nearest.

| ODR | discriminating axis-samples | floor | round | neither |
|---|---|---|---|---|
| 25 Hz | 188 | 188 | 0 | 0 |
| 100 Hz | 162 | 162 | 0 | 0 |
| 1000 Hz | 100 | 100 | 0 | 0 |
| **total** | **450** | **450** | **0** | **0** |

"Discriminating" means the discarded low nibble was ≥ 8, so floor and round give different answers. Spanning a 40× range of ODR.

Independent corroborations from the same data:
- Every 20-bit value was **even**, confirming the datasheet's "gyro LSB always zero". The chain closes: field = 2·v₁₉, register = field ≫ 4 = v₁₉ ≫ 3, and 131 = 8 × 16.4 LSB/dps.
- At ODR 8000 Hz the comparison degrades exactly as predicted from read skew (~30 µs gap between two sequential SPI transfers against a 125 µs period ⇒ ~24%), with the harness reporting 71 FIFO-backlog events. A property of the test, not the silicon.

### Two consequences

**Engineering.** Rule R1 — simultaneous 16-bit and 19-bit capture over the same physical samples — is now satisfiable **by construction**: log the FIFO alone and derive the 16-bit stream in software, bit-exactly. The dual-path subsystem is deleted, and ODR 8000 becomes a single burst-read stream.

**Theoretical, and this one needs adjudicating.** TN-13 Appendix Z.4 anticipated it: *"if the 16-bit register were the high bits, it would be a truncation of the 19-bit word (H3-flavoured), not a rounding"*, and warned that "high bits = register" and "register is a memoryless rounder" are **different hypotheses**. It is the former.

A truncator is a uniform quantiser whose decision boundaries sit half an LSB from a mid-tread rounder's. Since TN-12 makes η a function of (ρ, μ mod Δ), truncation enters as a **fixed half-LSB shift in φ** — the framework applies unchanged, but any phase quoted against a mid-tread assumption carries that offset. **[inference]**

> **For the manuscript:** the architecture under test is a *truncating* rate register. That is arguably a cleaner story than a rounder — truncation has a deterministic −Δ/2 mean offset that a rounder does not — but every φ in the corpus needs the convention stated explicitly.

---

## 2. Three datasheet corrections

**[fact, DS-000347 Rev 1.6]**

| # | Item | Corpus said | Rev 1.6 says |
|---|---|---|---|
| 1 | `GYRO_ACCEL_CONFIG0` reset value | TN-13 Z.1: BW = 0 default is `[verify]`, "on the critical path" | **`0x11`** — UI_FILT_BW defaults to **1**, not 0 |
| 2 | AAF power-on bandwidth | TN-16 §5.1: "default ≈258 Hz" | **585 Hz** (`GYRO_CONFIG_STATIC3` reset `0x0D` = DELT 13) |
| 3 | AAF floor triple | TN-16 open item 1: 1/1/15 for 42 Hz, `[verify]`, High priority | **Confirmed.** §5.3 table row: 42 Hz ↔ DELT 1, DELTSQR 1, BITSHIFT 15 |

Also recorded: gyro ODR power-on default is **1 kHz** (`GYRO_ODR = 0110`), and the ODR code map is confirmed (`0011` = 8 kHz, `1010` = 25 Hz, `1111` = 500 Hz).

### Why #1 matters beyond bookkeeping

TN-13's premise — "the sensor's **default** ODR-tracking decimation" — is false. Only `BW = 0` tracks ODR; the factory default is `BW = 1`, where Z.1 shows the noise bandwidth is ODR-independent below 200 Hz and **there is no ρ sweep at all**.

The firmware writes `0x00` explicitly, so the campaign is safe. But the *relevance* argument may be strengthened rather than weakened: if a practitioner takes the part at its defaults, the noise bandwidth does **not** scale with ODR, so the √ODR transfer rule embedded in the calibration toolchains is violated by the **hardware default**, not merely by an unusual configuration. **[inference — this is an argument for the Concept Note, not something bring-up settles.]**

---

## 3. The signal chain behaves exactly as modelled

**[measured]** σ from the 19-bit stream, AAF at the 42 Hz floor, `UI_FILT_BW = 0`, n = 3000 per point, gyro axes pooled.

Solving σ_a from the 25 Hz point, where the datasheet UI table gives NBW = 13.0 Hz:

$$\sigma_a = \frac{8.85\ \text{mdps}}{\sqrt{13.0\ \text{Hz}}} = 2.46\ \text{mdps}/\sqrt{\text{Hz}}$$

| ODR (Hz) | σ (mdps) | ρ | implied NBW | UI table | AAF |
|---|---|---|---|---|---|
| 25 | 8.85 | 0.145 | 13.0 | 13.0 | 42 |
| 50 | 11.1 | 0.182 | 20.4 | 26.0 | 42 |
| 100 | 13.3 | 0.218 | 29.5 | 52.0 | 42 |
| 200 | 14.8 | 0.242 | 36.3 | 104 | 42 |
| 500 | 16.1 | 0.265 | 43.3 | 260 | 42 |
| 1000 | 16.7 | 0.274 | 46.9 | 519 | 42 |

Implied bandwidth rises with the UI filter at low ODR and saturates at the AAF floor, sitting between `min(UI, AAF)` and their harmonic combination — as two cascaded second-order sections should. **σ_a = 2.46 mdps/√Hz, better than the 2.8 datasheet figure.**

**This is Experiment 1's configuration (fixed AAF), not M1.** A harness defect — the "native AAF" mode skipped the AAF writes rather than restoring the default, inheriting the 42 Hz floor set at boot — meant both runs were identical. Fixed; both modes now write the registers explicitly.

**But M1's core worry is already largely answered.** TN-13 §5 case (b) predicted σ pinned near σ_a√42 ≈ 18 mdps at *every* low ODR. At 25 Hz that would be ~16 mdps. It measured **8.85**, with implied NBW **13.0 Hz — the UI table value to three figures**. The low-ODR decimation path bandlimits. Case (a) holds, and the low-ODR axis is real.

---

## 4. The bench is far quieter than the §11 baseline — the gating question may be settled

**[measured]** ρ = **0.218** at ODR 100 Hz, AAF 42 Hz.
**[measured, TN-16 §11.1]** the same configuration previously read **1.79 LSB**.

That is **8.2× lower**. TN-16 §11.4 set the gate: *"σ must fall ≈5.6× (≈15 dB) from current bench conditions before the ICM enters the under-dithered regime."*

On this reading the gate is **met and exceeded**. Against TN-12/TN-13's predicted ρ = 0.331 at ODR 100, the measurement sits **below** prediction — inside the under-dithered regime where η departs materially from 1 and there is an effect to measure. §11.4's conclusion, *"no effect to measure on this bench"*, would be reversed.

**Do not bank this yet.** Two differences from the comparison:
1. **Estimator.** TN-16's figure was n = 6–16 samples taken 1 s apart on the **16-bit register** — a marginal-distribution estimate with 18–32% standard error. This is n = 3000 contiguous on the **19-bit stream**.
2. **Environment.** TN-16's bench was "board on a running PC, no isolation mass, USB-tethered".

Either could account for a large part of 8×. The comparison is **suggestive, not established** — but it is the most encouraging number the project has produced, and it should be re-measured properly under rule R3 with a recorded run before anything is claimed.

**Still outstanding before any exact-theory table is applied: rule R4, screening the 19-bit spectrum for coherent lines.** A mains harmonic, switching spur or structural resonance in band destroys the Gaussianity on which every closed-form $A_k = e^{-2\pi^2k^2\rho^2}$ depends, making the tables *wrong* rather than imprecise. Nothing has screened for this yet; it needs a recorded run and an FFT.

---

## 5. Open items this creates

| Item | Priority | Note |
|---|---|---|
| Re-run M1 with the AAF at 585 Hz | **High** | Completes M1; the last gate on the campaign matrix |
| Screen the 19-bit spectrum for coherent lines (R4) | **High** | Mandatory pre-condition, still unmet; needs Stage B |
| Re-measure ρ under R3 with a recorded run | **High** | §4 is suggestive only |
| State the truncation φ convention across the corpus | **High** | §1; affects every quoted phase |
| **Measure the true settle time** | **High — schedule** | TN-14 §5: settling is 26 h of the 55 h wall clock and is "the single biggest lever". Assumed 15 min, never measured |
| Appendix Z entries against TN-13 Z.1 and TN-16 §5.1, open item 1 | Medium | §2 |
| Whether the BW = 1 default strengthens the relevance claim | Medium | §2; a Concept Note argument |

---

## 6. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 28 Jul 2026 | Initial issue. V0.4 answered; three datasheet corrections; signal-chain validation; bench noise 8× below the §11 baseline |
