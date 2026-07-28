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

## 5. Firmware fault: an SPI DMA transfer must not be re-armed from its own completion callback

Recorded because it is a silent, total data-loss mode that presented as a plausible-looking short record rather than as an error, and because the same trap exists on every ST HAL SPI/DMA path in this project.

**Symptom.** After the sampler was changed from a fixed-length read to a chained drain (read `FIFO_COUNT`, then read exactly that many packets), `rec smoke 20 100` — a configuration that had previously produced 2020 samples with zero drops — returned:

```
rec: irq 1, reads 0/0, ring-full 0, busy 50, faults 50, wdog 49
  chained drains 0
  gaps 20 packets (1% of expected)
  0 samples, 0 blocks, 0 dropped, 0 B
```

**Diagnosis from the counters alone.** The two failure paths in the sampler have distinguishable arithmetic signatures:

- count read succeeds, data-read *start* fails → `finish()` runs `on_data(FAULT)` (faults +1, lost +10 packets), then the caller adds `bus_busy` +1 and lost +10 → **(1, 1, 20 packets)**
- count-read *start* fails → `on_count(FAULT)` (faults +1), caller adds `bus_busy` +1 → **(1, 1, 0 packets)**

Totals of 50 faults, 50 busy and 20 lost packets therefore decompose uniquely as **one** of the first kind followed by **49** of the second. One interrupt plus 49 watchdog kicks is exactly 50 chain starts. So the first chained start failed, and every attempt thereafter failed instantly and identically — the slot was dead, not merely unlucky.

**Mechanism.** `HAL_SPI_TransmitReceive_DMA()` arms the RX stream first, then the TX stream. TX and RX are separate NVIC lines at equal priority — for SPI1, DMA2_Stream2 is IRQ 58 (RX) and DMA2_Stream3 is IRQ 59 (TX). Equal priority means no preemption, and the NVIC serves the lower number first, so the RX completion handler runs while the TX handler is **still pending**. `hdmatx->State` is therefore still `HAL_DMA_STATE_BUSY`, and `HAL_DMA_Start_IT()` refuses (`stm32f7xx_hal_dma.c` sets `State = BUSY` at start and only clears it in the IRQ handler; the TC interrupt is enabled unconditionally, so this is purely an ordering effect, not a missing interrupt).

The damage is in the HAL's failure path: having already armed RX, it returns on the TX failure **without un-arming it**. `hdmarx->State` stays `BUSY` for the rest of the run, so every subsequent `HAL_SPI_TransmitReceive_DMA()` on that slot fails at the first `HAL_DMA_Start_IT()`. One badly-timed re-arm bricks the peripheral until reset.

Note that `hspi->State` is *not* the culprit: `SPI_DMATransmitReceiveCplt()` sets `HAL_SPI_STATE_READY` at line 3285, before invoking the user callback at line 3311. The obvious hypothesis — that the SPI state machine is still busy — is wrong, and checking it in the source rather than assuming it is what pointed at the DMA streams.

**Fix, two parts.**

1. *Structural.* Each chain step is deferred to **PendSV** rather than issued from the bus completion callback. PendSV tail-chains only once every pending interrupt has been serviced, which is precisely the condition the HAL requires; and because it is an exception rather than main-loop code, it still preempts thread mode, so the drain continues through a 33 ms `f_write` stall. That was the entire reason for not putting the chain in the main loop, and it is preserved. PendSV is set to priority 15 in `sampler_start()`.
2. *Defensive.* `bus_xfer_async()` now calls `HAL_SPI_Abort()` whenever a DMA start fails, returning both streams and the SPI state machine to `READY`. Whatever the cause, a failed start now costs one read instead of the remainder of the record.

A separate accounting bug was found in the same decomposition: a failed start was charged to `s_lost_packets` twice, once in the completion callback and once in the caller. That is the phantom "20 packets" above, and it is now charged in one place only.

**Generalisation.** Any callback in this firmware that runs from a HAL DMA completion — bus, storage, or future sensor drivers — must not start a new DMA transfer on the same peripheral. Defer it.

### 5.1 The chain condition was dead code, and the loss was invisible

With the PendSV fix in place, ODR 100 and 1000 recorded cleanly. ODR 8000 delivered **235,733 of 480,000 samples — 49% — while reporting `0 dropped, gaps 0`.** `f_measured` read 3928.859 Hz against a nominal 8000.

The chain re-entry test was

```c
if (s_avail > (uint16_t)(n + s_wm))
```

where `n` is `s_avail` truncated to a packet boundary. It therefore asked whether `s_avail > s_avail + watermark`, which is never true — `chained drains` read 0 at *every* ODR, and the drain had been doing one read per interrupt throughout. At ODR 100 and 1000 one read per interrupt is sufficient, so the fault was invisible. At ODR 8000 the read leaves the FIFO above the watermark, the pulsed interrupt has no upward crossing to fire on, and the stream survives only on watchdog kicks — 55 reads per second against the 160 required.

The test is now inverted and moved to `on_count()`: **continue while `FIFO_COUNT ≥ watermark`, stop below it.** Only below the watermark is a further pulse guaranteed, so that is the only safe place to stop.

Two further faults were found in the same output.

**Spurious watchdog kicks from an unsigned underflow.** `busy` equalled `wdog` exactly at both ODR 100 (20/20) and ODR 1000 (117/117) — a ratio of 9.9% and 9.6% of interrupts respectively, which is the signature of a per-interrupt race rather than a timing threshold. `sampler_poll()` read `now`, then `s_last_int_us`; an interrupt landing between the two makes `last` later than `now`, and `now - last` underflows to ≈2⁶⁴. The kick then collides with the chain the interrupt just started. The whole decision is now taken with interrupts masked, which also fixes the non-atomic 64-bit read.

**A refused start stole the chain flag.** `account_start_failure()` cleared `s_chain` on `BUS_E_BUSY`, i.e. while a transfer was genuinely in flight, allowing a second chain to overwrite `s_pending_pkts` and `s_avail` underneath the first one's data read — the byte count copied into the ring would then be wrong. This is the likely origin of the 94 reads that were started but never completed in the ODR 8000 run. `s_chain` is now released only by its owner, with a liveness timeout in `sampler_poll()` as the backstop.

**Reporting.** A run that loses half its samples must not report success. Three changes:

- `FIFO_COUNT` at or above 2000 B means the 2048-byte FIFO wrapped and samples were overwritten. This is now counted (`overflows`) and written to the `.sdat` header as `integrity.fifo_overflows`.
- The header's `bus_overruns` and `bus_faults` were hard-coded to zero. They now carry the real sampler counters, so a record can be judged from the file alone.
- `rec` compares delivered samples against `secs × nominal ODR` and prints **`DATA LOSS … RECORD NOT ADMISSIBLE`** below 98%. The threshold sits outside the ~1% oscillator offset of TN-16 §10.1 and far inside any real loss.

The watchdog period is additionally clamped to half the FIFO fill time (12.8 ms at ODR 8000), since the previous 20 ms floor guaranteed an overflow before the watchdog could notice a missed pulse.

---

## 6. Open items this creates

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

## 7. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 28 Jul 2026 | Initial issue. V0.4 answered; three datasheet corrections; signal-chain validation; bench noise 8× below the §11 baseline |
| 1.1 | 28 Jul 2026 | Added §5, the SPI DMA re-arm fault and the PendSV chain fix (fw 0.2.7, tag `Stage-B-pendsv-chain-Os`) |
| 1.2 | 28 Jul 2026 | Added §5.1: dead chain condition, watchdog underflow, stolen chain flag, and the yield/overflow reporting that would have caught the 49% ODR 8000 run (fw 0.2.8, tag `Stage-B-drain-chain-Os`) |
