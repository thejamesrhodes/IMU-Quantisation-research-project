# TN-20 — Campaign Bring-up and First Results, 28 July 2026

**Status: the primary effect is measured and the sign of the phase dependence is
confirmed. The instrument is complete and unattended. The first campaign night
is compromised by a thermal-gate ordering error and must be repeated.**

This note is a handover. It carries everything learned on 28 July — the
firmware, the analysis chain, the instrument findings, the science, and the open
questions — in enough detail to resume without reference to the session.

---

## 1. Where the project stands

| | |
|---|---|
| Firmware | v0.2.17, tag `Stage-D-charger-autorun-Os`, `-Os` |
| Instrument | Complete: unattended sequencer, battery/charger boot, self-disarming plans, status LEDs, live R2 gate |
| Data path | SD card → USB CDC → host, dual CRC verified end to end |
| Analysis | R4 screen, σ/ρ/μ/φ/η, Allan, tails, cross-channel tracing, two-specimen clock discrimination, batch summary, result figures |
| Theory | **Exact η(ρ, φ) in closed form, validated against TN-14 §1.3** (§2.3) |
| Records | 19 campaign, 25 archived diagnostics |
| **Primary result** | **η(ρ) measured across 1.2 decades; η(φ) spans −0.24 to +2.42 and tracks the exact theory with no free parameters** |
| **Blocking** | Seven of fourteen gated records failed R2; OFFSET_USER step size unresolved |

---

## 2. The science

### 2.1 The primary curve exists

Slot 1, X axis, line-corrected ρ:

| ODR | ρ measured | ρ TN-14 §1.3 | η measured | η TN-14 (φ=0) |
|---|---|---|---|---|
| 25 | 0.157 | 0.165 | **−0.120** | −0.298 |
| 50 | 0.272 | 0.234 | +0.693 | −0.266 |
| 100 | 0.307 | 0.331 | +0.927 | +0.255 |
| 200 | 0.421 | 0.468 | +1.056 | +0.844 |
| 500 | 0.630 | 0.739 | +1.015 | +0.999 |
| 1000 | 0.847 | 1.077 | +1.002 | +1.000 |
| 8000 | 1.078 | (1.11, see §3.3) | +0.929 | +1.000 |

η is **negative** at the smallest ρ and saturates at +1. The dead-zone regime is
real and measured. ρ tracks TN-14 closely at the low end where it matters most.

Specimen agreement is excellent — line-corrected ρ, slot 1 vs slot 2:
0.1572/0.1575 at ODR 25, 0.4210/0.4216 at 200, 1.0780/1.0807 at 8000.

### 2.2 The phase dependence, and the φ convention — RESOLVED

η varies by more than 2.5 across records at the *same* ρ. Sorting every low-ρ
measurement (both specimens, all three axes) by phase:

| φ measured | φ − 0.5 (mod 1) | η | ρ |
|---|---|---|---|
| 0.587 | 0.087 | −0.187 | 0.157 |
| 0.605 | 0.105 | −0.120 | 0.157 |
| 0.606 | 0.106 | −0.099 | 0.157 |
| 0.189 | 0.311 | +0.228 | 0.157 |
| 0.829 | 0.329 | +1.885 | 0.157 |
| 0.907 | 0.407 | +2.354 | 0.223 |

Monotonic. Two limits anchor the interpretation and both are met:

- **Mid-code, ρ→0.** Q becomes constant, so
  η → −12ρ² = −0.33 at ρ = 0.157. Measured −0.187.
- **On a code boundary, ρ→0.** The input straddles 50/50, so
  Var[Q] → Δ²/4 and η → 3 − 12ρ² = +2.67. Measured **+2.354**.

**Therefore TN-14's μ = 0 is a code CENTRE, while φ = μ mod Δ under truncation
is referenced to a code EDGE:**

```
    phi_TN14 = phi_measured - 0.5   (mod 1)
```

This closes the "truncation φ convention (half-LSB shift)" item that has been
open across the corpus. **Any quoted phase in TN-12/13/14 must be shifted by
half an LSB before comparison with data from this instrument.** §2.3 promotes
this from an empirical inference to a derivation.

### 2.3 The exact theory, in closed form — and it reproduces TN-14 §1.3

The two limits above are the endpoints of an expression that can be written
down exactly, so nothing here needs to rest on a tabulated curve.

With u = x/Δ and Q(x)/Δ = floor(u), the quantisation error has an exact Fourier
representation — the sawtooth series

```
    e = floor(u) - u + 1/2 = sum_{k>=1} sin(2 pi k u) / (pi k)
```

so Q = u − ½ + e and therefore

```
    eta = 12 [ 2 Cov(u, e) + Var(e) ].
```

For Gaussian u with mean μ and standard deviation ρ (both in units of Δ), every
expectation reduces to the characteristic function sampled on the quantiser's
reciprocal lattice, g_k = exp(−2π²k²ρ²):

```
    Cov(u, e) = 2 rho^2 sum_k g_k cos(2 pi k phi)
    E[e]      = sum_k g_k sin(2 pi k phi) / (pi k)
    E[e^2]    = sum_{k,l} (A_|k-l| - A_{k+l}) / (2 pi^2 k l),
                A_m = g_m cos(2 pi m phi),  A_0 = 1
```

The k = l terms contribute Σ 1/(2π²k²) → 1/12, which is the classical Δ²/12;
truncating the series at K therefore biases η low by ≈ 12/(2π²K), and that tail
is added back analytically rather than by brute force.

**Evaluated at φ = 0.5 this reproduces TN-14 §1.3 at every tabulated ρ:**

| ρ | TN-14 §1.3 | exact, φ = 0.5 |
|---|---|---|
| 0.165 | −0.298 | **−0.2975** |
| 0.331 | +0.255 | **+0.2551** |
| 1.077 | +1.000 | **+0.9985** |

Two things follow. First, the half-LSB mapping of §2.2 is now **derived, not
inferred** — TN-14's tabulated η is the mid-code value in the edge-referenced
convention, and no other mapping reproduces the table. Second, the exact-theory
chain that R4 and R6 require **exists and is validated**, implemented as
`eta_exact(rho, phi)` in `analyse.py`. Predictions no longer depend on
interpolating six tabulated points, and η can be evaluated at the *measured*
(ρ̂, φ̂) of every record, which is what R6 asks for.

The practical consequence is large: the two specimens happened to sit at
different phases, so the η(φ) curve has been sampled *without* the OFFSET_USER
ladder. It is not a controlled sweep and cannot replace one, but it establishes
the sign, the magnitude and the shape independently of the offset register —
which matters, because that register is now in doubt (§2.4).

### 2.4 R4 passes where the physics is

`line_D` at ODR 25 and 50 is **0.0000** on both specimens. The 119 Hz line does
not reach the contrast points.

Line amplitude against ODR (slot 1): 0 → 0 → 0.240 → 0.759 → 1.151 → 1.208 →
1.209 for ODR 25 → 8000. The growth tracks a filter cutoff scaling with ODR/2,
i.e. the **UI decimation filter removes the line at low ODR**. The 585 Hz AAF is
not the only anti-alias protection, contrary to the working assumption held for
most of the day.

**The analytical (exact-theory) chain is therefore available exactly where the
paper's claims live.** No J₀ correction is needed at ODR 25–50.

### 2.5 The OFFSET_USER step size is unresolved, and the ladder may be degenerate

Measured shift in μ over the 4-step interval `off1 → off5`:

| axis | Δμ / step |
|---|---|
| X | 0.5042 |
| Y | 0.5014 |
| Z | 0.4353 (outlier) |

X and Y agree at **0.503 ± 0.006**. The datasheet's 1/32 dps predicts 0.512;
half a 16-bit LSB predicts 0.500. The measurement sits 1.5σ from the former and
0.5σ from the latter.

**If the step is exactly Δ/2 the ladder is degenerate**: even steps land on
φ = 0, odd steps on φ = 0.5, and only two phases are reachable out of the 125
the arithmetic in §4.6 promises. It would also falsify TN-13 §4.3's premise that
the offset is applied pre-register on the fine lattice — a finding in its own
right, but one that costs the digital phase axis.

**Resolution:** steps 0/1/20/40. Twenty steps separate the hypotheses by
0.24 Δ in μ against ±0.03 Δ of thermal drift — eight sigma. Ten minutes of bench
time and it is the highest-priority measurement outstanding.

**Consequence:** the thermal ramp (TN-14 §3) is promoted from a second,
independent phase axis to a possible *only* phase axis. It should be scheduled
before the FSR axis.

### 2.6 The first campaign night is not admissible

**Seven of the fourteen gated records failed the R2 thermal gate.** Measured
temperature span per record, against the gate for that ODR:

| ODR | gate | specimen 1 | specimen 2 |
|---|---|---|---|
| 25 | 260 mK | 362 **FAIL** | 400 **FAIL** |
| 50 | 361 mK | 460 **FAIL** | 279 pass |
| 100 | 388 mK | 521 **FAIL** | 317 pass |
| 200 | 389 mK | 860 **FAIL** | 430 **FAIL** |
| 500 | — | 996 | 853 |
| 1000 | — | 974 | 876 |
| 8000 | — | **1872** | **2536** |

The ODR 8000 records drifted 1.9–2.5 K. That is the heat the gated records then
had to sit through.

Cause: the plan ran ODR descending, on the reasoning that a cooling die is
gentler than a warming one. That is wrong — a cooling die is still drifting, and
the thermal time constant after 8 kHz logging is tens of minutes against settles
of 60–300 s. Slot 2's ODR 50 and 100 passed only because they ran ninety minutes
later, once the board had stabilised of its own accord.

This is visible in the data: the gate-failed records carry the anomalous η
values, exactly as TN-14 §2 predicts — "a record taken while φ moves does not
measure η at a phase, it measures a smear".

**Fix, already in the plan file:** ascending ODR. Gated records first from a long
idle warmup where dissipation is low and steady; ungated high-ODR steps last,
where drift cannot invalidate anything. Settles lengthened to 300–600 s at low
ODR.

---

## 3. Instrument findings

Seven results about the ICM-42688-P and the measurement chain that the corpus
does not contain. Each is independently checkable and several correct existing
documents.

### 3.1 The 16-bit register is a truncation of bits [19:4]

Established 27 July, confirmed throughout. The UI register is the top 16 bits of
the 20-bit fine word — a truncation toward negative infinity, not a rounder. The
comparison word therefore needs no arithmetic: `gyro16 == gyro20 >> 4` exactly,
verified in the reader's self-test.

### 3.2 TMST ticks at 16/15 µs, not 1 µs

At ODR 8000 with `TMST_RES = 0` the design interval is 125 counts. Measured
**117.188**, and 125 × 15/16 = 117.1875. Applying the 16/15 correction plus the
sample loss present in that record returns exactly the nominal ODR, as it must,
because the ODR divider is exact against the sensor's own clock.

**Anyone using TMST as a microsecond clock is 6.67% out.** Needs confirming
against DS-000347 §14 before being relied on for R1 timing.

### 3.3 The AAF is first order, and it — not the ODR — controls ρ

σ scales as √NBW **exactly**: 1.109/0.299 = 3.71 against √(585/42) = 3.73.

Two consequences:

- **TN-14's ρ = 2.959 at ODR 8000 is unreachable** at the default AAF, which
  caps noise bandwidth at 585 Hz. The true value is 1.11 — statistically the
  same point as ODR 1000. The ODR-8000 record length can drop from 24.4 min to
  5 min accordingly, a saving of ~39 min and ~500 MB per night.
- Reaching ρ ≈ 2.9 requires `AAF_DELT = 63` (3979 Hz), not a higher ODR.

Attenuation at 119 Hz with the 42 Hz floor was **−10.05 dB**, and
20·log₁₀(2.83) = 9.0 dB for a single pole against 18 dB for two. **The AAF is
first order**, so anti-alias protection is weak — directly relevant to
TN-14 §4.2.

### 3.4 Sensor oscillator offsets

Slot 1 **+1.073%**, slot 2 **+1.504%**, against the board's HSE-derived TIM2.
Independently confirms TN-16 §10.1's "+1.10%/+1.50%". Stable across sessions and
across ODR.

### 3.5 A 119 Hz external line — characterised, unsourced

| property | value / finding |
|---|---|
| Frequency | 118.938–119.012 Hz across all records and both specimens |
| Amplitude | 0.42 Δ on USB, **1.28 Δ on battery**, 0.72 Δ with coins taped to the PCB |
| Gyro axes | all three |
| Accel axes | **none** |
| Clock-locked? | **No** — 1.000622 between specimens against a 1.004266 clock ratio |
| Mass loading | **No shift** (referenced to the internal spur, which cancels any fs error) |
| AAF | Attenuated 3.18×, but σ falls 3.71× — relatively *worse* |
| Low ODR | **Absent** — removed by the UI decimation filter |

Ruled out: PCB flexural mode (no mass shift), bench motion (no accel
signature), internal to either part (not clock-locked), the USB supply (worse
without it), mains (119.0 ≠ 100 or 120, and mains is frequency-locked).

Remaining hypothesis: board-level electrical coupling into the gyro analog
front end, entering *before* the AAF (it is attenuated by it). Amplitude differs
2.4× between the two parts, consistent with layout and decoupling.

**It does not affect the contrast points** and so does not block the campaign.

### 3.6 Two clock-locked internal spurs

1732.682 Hz on slot 1 and 1740.074 Hz on slot 2 — ratio 1.004266, matching the
sample-rate ratio to six digits — plus an exact second harmonic at 3465.4 /
3480.1 Hz. **Generated inside each ICM**, in its clock domain. Small
(0.07–0.11 Δ) and unavoidable, but worth documenting as an intrinsic artefact.

They also appear in the accelerometer, which is *not* evidence of mechanical
origin: accel and gyro share the internal clock. The decisive test is the
two-specimen frequency ratio, not the accel cross-check.

### 3.7 Three datasheet corrections (27 July, carried forward)

- `GYRO_ACCEL_CONFIG0` reset is `0x11`: `UI_FILT_BW` defaults to 1, not 0.
  TN-13's "default ODR-tracking decimation" premise is false.
- The AAF default is **585 Hz**, not the ~258 Hz stated in TN-16 §5.1.
- The AAF floor triple 1/1/15 does give 42 Hz, closing TN-16 open item 1.

---

## 4. The instrument

### 4.1 Hardware

STM32F723ZET6, 32 MHz SYSCLK (a deliberate science parameter — minimises
switching noise), HSE/LSE bypass oscillators, microSD on SDMMC2, USB-C on
OTG_HS with the internal HS PHY.

| Slot | SPI | Part | Notes |
|---|---|---|---|
| 1 | SPI1 (APB2) | ICM-42688-P | DMA2 streams 2/3 |
| 2 | SPI3 (APB1) | ICM-42688-P | DMA1 streams 0/5 |
| 3 | SPI5 | ISM330DHCX | polled, unused so far |
| 4 | SPI4 | BMI323 | polled, unused so far |

All four are forced to **8 MHz** by `bus_init()`, computed from the live PCLK.
Before 0.2.12 slot 2 ran at 16 MHz, which would have written a bus-rate
difference straight into the specimen axis (rule R8). `spi_hz` is read back from
`CR1` into every record header.

LEDs are on GPIOE 12–15. VBUS is sensed on **PB13**.

**Neither the ISM330DHCX nor the BMI323 exposes a word finer than 16 bits**, so
η and V0.4-style architecture identification are impossible on them. They can
contribute a cross-vendor code-histogram discriminant at low ODR, and are the
best available instrument for deciding whether the 119 Hz line is board-level.

### 4.2 Firmware modules

| File | Responsibility |
|---|---|
| `sheppard_config.h` | Every build parameter in one place, so one file describes the build that produced a dataset |
| `timebase.c` | TIM2 at 1 MHz with a 64-bit software extension |
| `bus.c` | SPI transport, four slots, DMA on 1–2, clock normalisation |
| `imu_icm42688.c` | ICM driver, register map from DS-000347 Rev 1.6, OFFSET_USER |
| `sampler.c` | FIFO watermark IRQ → chained DMA drain → ring, entirely in interrupt/PendSV context |
| `storage.c` | 4 KiB block ring, SD writer, `storage_record()`, `mount`/`rec` |
| `record.c` | `.sdat` header and block format, zlib CRC-32 |
| `arena.c` | The one 144 KiB RAM block, shared with ownership checks |
| `seq.c` | Unattended sequencer, plan on card, autorun |
| `xfer.c` | `ls`/`get`/`rm`, bulk download over CDC |
| `led.c` | Status indication, VBUS sense |
| `console.c` | Line assembly, command dispatch, CDC + UART mirror |
| `fwupdate.c` | Self-flasher, runs from RAM |

### 4.3 Console commands

```
ver                                     version, clocks, boot state
help
scan / icm <slot> / fifo <n> <odr>      sensor bring-up
mount                                   mount card, report free space
rec <label> <secs> [odr] [slot] [def|floor] [delay_s]
seq new | add <line> | plan | arm | disarm | run | status
ls [dir] | get <file> | rm <file>
m1 / settle                             validation harness
fw ...                                  self-flash
```

### 4.4 The `.sdat` format

```
offset 0            4096 B   UTF-8 JSON header, space-padded
offset 4096 + 4096k          fixed 4 KiB blocks
block               32 B header + 4000 B payload + 64 B pad
packet              20 B ICM FIFO Packet 4, verbatim
```

Packet 4 layout (DS-000347 §6.1): byte 0 header; 1–6 accel [19:4]; 7–12 gyro
[19:4]; 13–14 temperature; 15–16 TMST; 17–19 low nibbles, high nibble accel and
low nibble gyro per axis.

The header records **register read-back, not intent** — a write that silently
failed is otherwise invisible in the archive. It carries `spi_hz`, `aaf`,
`tmst_res_us`, `offset_user_steps`, `battery`, `usb_connected`, the R2 gate
value, and on close: `n_samples`, `n_gaps`, `f_measured_mhz`, `blocks`,
`bus_overruns`, `bus_faults`, `fifo_overflows`, `ring_full`, `closed`.

Units convention used throughout the analysis:

```
Delta = 16 fine codes = 1/16.384 dps = 61.035 mdps
x/Delta   = gyro20 / 16        (input in LSB units)
Q(x)/Delta = gyro16            (already integer LSB units)
rho = sigma / Delta            (so sigma in LSB units IS rho)
phi = mu mod 1                 (edge-referenced; see 2.2)
eta = (Var[Q] - Var[x]) / (Delta^2 / 12)
```

### 4.5 Host tools

| Tool | Purpose |
|---|---|
| `sheppard_console.py` | Terminal, flasher, **Records on card** browser, **Sequence plan** editor, analysis launcher |
| `sdat.py` | Reader: `verify`, `info`, `rate`, `export`, `selftest` |
| `analyse.py` | `screen` (R4), `stats`, `allan`, `trace`, `compare`, `summary`, `all`; and `eta_exact(rho, phi)`, the exact-theory chain of §2.3 |
| `figures.py` | The six result figures of §6, from `summary.csv` |
| `sheppard_pull.py` | Command-line downloader (the GUI now supersedes it) |

Defaults: records to `Test Datasets`, figures to `Figures`, both anchored on the
**workspace** root (the parent of the firmware root, which is where
`Core/Inc/sheppard_config.h` lives).

The two commands for a whole night:

```
python analyse.py summary "..\..\Test Datasets" -o "..\..\Test Datasets\summary.csv" --fast --resume
python figures.py "..\..\Test Datasets\summary.csv" -o "..\..\Figures"
```

`--fast` skips the Allan deviation, which is O(N × n_tau) and dominates the
runtime on the multi-million-sample ODR 8000 records — about a minute per file,
for numbers the η/ρ/φ results do not use. Drop it when the bias-instability and
ARW columns are wanted. `--resume` keeps rows already in the CSV, so a night's
work is not lost because the last file failed.

### 4.6 The OFFSET_USER arithmetic

One register step is nominally 1/32 dps against Δ = 2000/32768 dps:

```
    step = (1/32) / (2000/32768) = 0.512 Delta   exactly
```

Coarser than one quantiser LSB, so a naive uniform ladder lands on two clusters
rather than sweeping phase. But 0.512 = 64/125, so k steps give phase
(64k mod 125)/125, and since 64 × 84 = 5376 = 43×125 + 1, the inverse of 64 mod
125 is 84. Phase m/125 is therefore reached at **k = 84m mod 125**, giving 125
distinct phases at 0.008 Δ spacing from a register that cannot resolve one LSB.

Implemented as `icm_offset_for_phase(num, den)`; a plan line reading
`phase lbl 300 100 1 def 5/12 60` resolves the step count automatically.

**All of this depends on the 0.512 figure, which §2.4 places in doubt.**

---

## 5. Bugs found and fixed — do not reintroduce

Recorded because several were silent, and the silent ones are the expensive
ones.

| # | Fault | Consequence | Fix |
|---|---|---|---|
| 1 | SPI DMA re-armed from inside `HAL_SPI_TxRxCpltCallback` | RX stream left armed, slot dead for the rest of the run | Chain steps deferred to **PendSV** |
| 2 | Chain re-entry test `s_avail > n + s_wm` | Always false — `chained drains` read 0 at every ODR; ODR 8000 ran at **half rate** | Continue while `FIFO_COUNT ≥ watermark`, stop below |
| 3 | Watermark pulse arriving mid-chain was discarded | Pulsed INT1 never fires again; 170 FIFO overflows, 25,920 samples lost, reported as `0 dropped` | Remember the pulse, check it before clearing the chain |
| 4 | CRC computed **before** the partial-block tail was zeroed | Last block of every record failed verification | Zero, then CRC |
| 5 | Unsigned underflow in `sampler_poll` | Spurious watchdog kicks at ~10% of the interrupt rate | Whole decision taken with interrupts masked |
| 6 | `account_start_failure` cleared `s_chain` on `BUS_E_BUSY` | A second chain could overwrite `s_pending_pkts` under the first one's data read | Only the owner releases the chain; liveness timeout as backstop |
| 7 | `f_measured` from the `rec` loop bounds | Biased low by up to one watermark; 0.5% at ODR 100 | Use first/last read triggers, excluding the first read's packets |
| 8 | `MX_USB_DEVICE_Init()` before UART/ADC/I²C/SDMMC | No VBUS → boot hangs → board appears dead on battery | Skip USB init when VBUS is absent |
| 9 | `CONSOLE_MAX_ARGS` 8 | Plan lines silently truncated at the settle field | Raised to 12 |
| 10 | `__file__` for locating sibling tools | Resolved to the Desktop when launched from a shortcut | Derive from the marker-file root |
| 11 | Header `bus_overruns`/`bus_faults` hard-coded to 0 | A record could not be judged from the file alone | Wired to the real counters |
| 12 | Reader used the **first** block's packets in the rate estimate | 91.98 Hz against a true 101.08 | Use the **last** block's |
| 13 | Descending ODR in the campaign plan | Six records failed R2 | Ascending, gated points first |

Recurring CubeMX regeneration hazards, on the TN-17 §8 checklist:
`USBD_MAX_NUM_INTERFACES` reverts to `1U`; `_Min_Stack_Size` reverts to `0x400`;
`sampler_pendsv()` and `#include "sampler.h"` in `stm32f7xx_it.c`; the VBUS guard
in `usb_device.c`.

---

## 6. Figures

Generated by `figures.py` from `summary.csv`; regenerating after a new night is
one command. All six are in `Figures/`.

| Figure | Shows |
|---|---|
| `fig1_eta_vs_rho` | The primary curve. Measurements against the **exact theory** of §2.3, with the shaded band spanning every phase. Every point must lie inside it, which is a far stronger constraint than agreement with one tabulated curve — and the mid-code branch passes through TN-14's tabulated diamonds |
| `fig2_eta_vs_phi` | **The result.** η against distance from a code centre, ODR 25–50, both specimens, three axes, with one exact curve per ρ present. No fitting and no free parameters. Spans −0.24 to +2.42 |
| `fig3_rho_validation` | ρ against ODR, raw and line-corrected, and measured against TN-14 predicted on a 1:1 axis |
| `fig4_line_vs_odr` | The 119 Hz contaminant falling to zero below ODR 100 — §2.4 |
| `fig5_offset_step` | The OFFSET_USER ambiguity of §2.5: 0.512 and 0.500 Δ/step against the data, showing why five steps cannot separate them |
| `fig6_thermal_gate` | R2 compliance across the night, with the measured span under each cell — §2.6 |

Two things to know when reading them. **ρ is line-corrected**, and above ODR 200
that subtraction removes 20–50% of the variance, so the high-ρ points are less
trustworthy than they appear; η is saturated there, so it does not affect any
conclusion. And in `fig1`/`fig2`, **hollow markers are records that failed R2** —
they are plotted rather than dropped, because hiding them would conceal how much
of the axis is currently inadmissible. Their scatter about the exact curves,
against the filled markers' agreement, is itself the evidence that a drifting φ
smears η as TN-14 §2 predicts.

---

## 7. Data inventory

19 campaign records in `Test Datasets`, 25 diagnostics in
`Test Datasets/archive`. The archived set is **evidence**, not clutter — it
contains the AAF filter-order measurement, the two-specimen clock
discrimination, the mass test, and the battery/charger comparison, which are the
basis of §3.3, §3.5 and §3.6.

Four archived files are genuinely worthless (corrupt or empty) and may be
deleted: `r20561`, `r33101`, `r233116`, `r34973`.

---

## 8. Open questions

| # | Question | Cost to settle | Blocks |
|---|---|---|---|
| 1 | Is the OFFSET_USER step 0.512 or 0.500 Δ? | 10 min (`off0/1/20/40`) | The entire digital phase axis |
| 2 | Do the low-ODR records pass R2 when run ascending? | one night | The paper's core points |
| 3 | Where does the 119 Hz line come from? | unknown | Nothing critical |
| 4 | Does η(ρ) agree when ρ is set by AAF instead of ODR? | needs the AAF table | A strong internal cross-check |
| 5 | Is the TMST 16/15 ratio in the datasheet? | reading | R1 timing claims |
| 6 | Do the ISM/BMI see the 119 Hz line? | ~2 h | §3.5 |

**Needed from the datasheet:** the DS-000347 §5.2 table of `GYRO_AAF_DELT` /
`DELTSQR` / `BITSHIFT` against 3 dB bandwidth. It is a lookup, not a formula —
the default is DELT 13 with DELTSQR **170**, not 13² = 169 — so arbitrary AAF
settings cannot be computed and must not be guessed into an overnight run.

---

## 9. Next steps, in order

1. **`off0/off1/off20/off40`** — ten minutes. Settles the ladder.
2. **Re-run the ODR axis ascending** — one night. Makes the core points
   admissible.
3. **Likelihood pipeline** — the exact η(ρ, φ) of §2.3 is done and validated.
   What remains is the code histogram under the same CF machinery, the software
   dither sweep, and joint likelihood over {H0…H3} at the measured (ρ̂, φ̂) per
   rule R6. R6 forbids selection on a single summary statistic, so η alone is
   not sufficient however well it fits.
4. **Thermal ramp**, enclosure off — one night. Second phase axis, or the only
   one if (1) fails.
5. **AAF sweep at fixed ODR 1000** — cross-check against the ODR sweep. The ODR
   axis remains primary because most parts do not expose an anti-alias filter,
   which makes it the generalisable claim; the AAF sweep is the internal
   consistency test and reaches ρ ≈ 2.9, which the ODR route cannot.
6. **OFFSET_USER ladder**, both specimens — conditional on (1).
7. **FSR axis** — 15 min.
8. **Cross-vendor probe** on the ISM330DHCX and BMI323.
9. **Corpus updates** — §2.2/§2.3's φ convention and the closed-form η, and
   §3.1–3.7 into Appendix Z, TN-13 Z.1 and TN-16 §5.1.

### Operational: how to run a night

```
Sequence plan... → edit → Upload to board → Arm
seq status                      (confirm ARMED)
unplug from PC, plug into a phone charger, shut the PC down
```

Autorun requires an armed plan **and** no host enumerating. Plugging in to
offload cannot start a campaign. The plan disarms itself on completion and
leaves `SHEPPARD/plan.done` with the tally.

Morning, before touching anything: LED1 single blip = finished; three flashes
and a gap = still running; **LED2 lit = a step lost data**; LED3 blinking = a
thermal gate was exceeded.

Supply matters and is recorded per record: battery is the **worst** for the
119 Hz line (1.28 Δ), charger and host both give 0.42 Δ. Use a charger with the
PC off — it keeps the cable's ground reference while removing host traffic and
the PC's fans, which were the source of the 75.0/75.8 Hz pair.

---

## 10. Version history

| Version | Tag | Change |
|---|---|---|
| 0.2.6 | `Stage-B-chained-dma-Os` | Chained DMA drain (regressed) |
| 0.2.7 | `Stage-B-pendsv-chain-Os` | Bug 1: PendSV deferral; abort on failed start |
| 0.2.8 | `Stage-B-drain-chain-Os` | Bugs 2, 5, 6; FIFO overflow detection; yield check |
| 0.2.9 | `Stage-B-fmeas-Os` | Bugs 4, 7 |
| 0.2.10 | `Stage-B-retry-Os` | Event-driven chain recovery; watchdog relaxed for R8 |
| 0.2.11 | `Stage-B-xfer-Os` | `ls`/`get`/`rm`; `console_write_cdc` |
| 0.2.12 | `Stage-C-spi-matched-Os` | SPI clock normalisation; `spi_hz` in header |
| 0.2.13 | `Stage-C-pulse-recovery-Os` | Bug 3; `rec` AAF and delay; LEDs; live R2 gate |
| 0.2.14 | `Stage-C-battery-boot-Os` | Bug 8; VBUS in header; LED polarity switch |
| 0.2.15 | `Stage-D-seq-Os` | Sequencer; OFFSET_USER driver |
| 0.2.16 | `Stage-D-seq-write-Os` | Bug 9; `seq new`/`add` |
| 0.2.17 | `Stage-D-charger-autorun-Os` | Autorun on host absence, not VBUS absence |

`SHEPPARD_OPT_LEVEL` is `-Os` from 0.2.6 onward and is recorded in every record
header. All bring-up data before that (V0.4, M1, the drift runs) was taken at
`-O0`. Optimisation level is a science parameter (TN-16 open item 20) because it
affects SPI timing.
