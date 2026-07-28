# TN-18 — Datalogger Architecture and Delivery Plan

> ## Findings, 28 July 2026 — Stage A on hardware
>
> **1. The 16-bit register is bits [19:4] of the hi-res fine word. Truncation, not rounding.** [measured]
> 20/20 packets at ODR 100 Hz on slot 1, register triple matching `gyro >> 4`
> exactly, including at least five samples where floor and round differ
> (20-bit 44 → 2 not 3; −18 → −2 not −1; 14 → 0 not 1; −22 → −2 not −1;
> 10 → 0 not 1). Every 20-bit value was even, independently confirming the
> datasheet's "LSB always zero" and closing the sensitivity chain:
> field = 2 × v₁₉, register = field ≫ 4 = v₁₉ ≫ 3, and 131 = 8 × 16.4 LSB/dps.
> **Consequences in §1 below — this is the favourable branch and it deletes a
> subsystem.** Still provisional: reads were sequential, not synchronised.
>
> **2. `GYRO_ACCEL_CONFIG0` reset value is `0x11`, so UI_FILT_BW defaults to 1,
> not 0.** [fact, DS-000347 Rev 1.6 §14.40]
> This closes the `[verify]` in TN-13 Appendix Z.1 that it calls "on the
> critical path", and closes it unfavourably: at the power-on default the
> noise bandwidth is ODR-independent below 200 Hz, so **there is no ρ sweep**.
> TN-13's phrase "the sensor's default ODR-tracking decimation" is wrong —
> nothing about the default tracks ODR. The firmware writes `0x00` explicitly,
> so the campaign is safe, but see §7.6.

**Version 1.0 — 27 July 2026**
**Status:** plan of record for the campaign firmware. Nothing here is built yet.
**Derived from:** TN-14 §6 (rules R1–R8), Hardware Design Notes v1.3 Appendix Z, TN-13 v1.1 + Appendix Z, TN-12 v1.1, TN-16 (as-built firmware state), TN-17/17A (USB update path).

**Decisions taken at the 27 July interview:**
- First build targets the **gating measurements plus the run sequencer** — the same state machine that answers M1 and V0.4 goes on to run the campaign.
- All runs on the **Sheppard board**. Specimen count revisited separately (§7.1).
- **DMA and a properly sized ring buffer from the start**, designed for the ODR 8000 Hz control point.
- Record format chosen in §4 and justified there.

---

## 1. The one fork that could delete a subsystem

**V0.4 must be answered before the general dual-path architecture is designed, not after.**

Rule R1 demands the 16-bit register stream and the 20-bit hi-res FIFO stream over the *same physical samples*. How expensive that is depends entirely on an undocumented fact:

> DS-000347 §6.1 states hi-res packets carry 20-bit fields and that gyro data is 19 significant bits. **Nowhere does it state that the 16-bit register value equals the high-order bits of the 20-bit word.** (TN-13 Appendix Z.4)

Two outcomes, with very different costs:

| V0.4 result | Consequence |
|---|---|
| **16-bit register = high bits of the fine word** | The register path is redundant. Log the FIFO only and derive the 16-bit stream in software, bit-exactly. R1 is satisfied by construction, ODR 8000 becomes one burst-read stream, and an entire subsystem is deleted |
| **Not the high bits** | Genuine dual-path needed at every ODR: 8000 register reads/s *and* FIFO bursts, both timestamped and paired. Substantially more work, and the ODR 8000 point becomes the binding engineering constraint |

There is a second entanglement TN-13 Z.4 flags and which the plan must respect: *if* the register is the high bits, it is a **truncation** of the fine word, not a rounding — and "high bits = register" and "register is a memoryless rounder" are **different hypotheses**. V0.4 scores against **five** outcomes: {rounding, truncation, RPDF, TPDF, neither}.

**Consequence for the schedule:** V0.4 needs only one ICM, one ODR (100 Hz), watermark = 1 so every sample generates one FIFO packet and one register read, and a few minutes of data. It does *not* need DMA, the sequencer, the thermal gate, or the SD stall measurement. **It should be run as early as physically possible**, because a positive result removes work from every stage that follows.

Test **M1** (does σ fall as √ODR under `GYRO_UI_FILT_BW = 0`, or plateau near $\sigma_a\sqrt{42} \approx 18$ mdps) has the same property: one ICM, 19-bit only, six ODR points, ~2 h. It decides whether the low-ODR axis — the paper's primary evidential channel — exists at all.

---

## 2. Requirements traceability

Every firmware feature below exists because a numbered rule demands it. Anything not traceable to this table is scope creep.

| Rule | Requirement | Firmware feature | Stage |
|---|---|---|---|
| **R1** / Z.1 | Simultaneous 16-bit + 19-bit over the same samples | `sampler`: paired capture, index alignment, gap detection | C |
| **R2** / Z.2 | Die temperature every record, ≥1 Hz; per-ODR thermal gate | `health`: temp logging, gate evaluation, record excision flag | D |
| **R3** | σ from the 19-bit stream only | Analysis-side. Firmware must never emit a derived σ | — |
| **R4** | Screen the 19-bit spectrum for coherent lines | Analysis-side. Firmware must deliver ungapped records | — |
| **R5** | PSD predictions from measured $S_x$ | Analysis-side | — |
| **R6** | Likelihood over {H0…H3} at measured $(\hat\rho,\hat\mu)$ | Analysis-side | — |
| **R7** | Falsifiers F1–F4 recorded as framework-breaking | Analysis-side | — |
| **R8** / Z.3 | FIFO watermark changeable 4× at fixed ODR | `imu_icm42688`: watermark as a run parameter | D |
| TN-06 v1.2 | **Raw integer codes, never scaled floats** | `record`: integer-only encoding + read-back acceptance test | B |
| TN-06 v1.2 | Per-block metadata: sensitivity, FSR, word length, ODR, filters | `record`: register **read-back** snapshot per block, not intended values | B |
| Z.4 | OFFSET_USER swept, 12 steps | `imu_icm42688`: offset as a run parameter | E |
| Z.5 | Thermal ramp, 0.5–2 K/h, ~6 h | No firmware work — a well-logged uncontrolled drift suffices | — |
| Z.7 | Unattended overnight, SD primary, USB disconnected | `runctl`: autostart, no console dependency, resumable | D |
| TN-16 §10.5 | `f_measured`, `n_gaps`, `ts_first/last` per record | `record` header; `timebase` supplies the ticks | B |
| TN-16 §10.3 | µs timestamps captured **in the ISR** | `timebase`: TIM2 + 64-bit extension | A |
| TN-16 open 7 | Worst-case SD write latency → ring sizing | `storage`: instrumented write path | B |
| TN-16 open 8 | No DMA anywhere | `bus`: SPI-DMA from the start | A |

---

## 3. Module architecture

Existing and unchanged: `sheppard_config`, `console`, `boot_ctrl`, `fwupdate`, `usbd_composite`.

```
timebase.c/h     TIM2 free-running 1 MHz, 64-bit extension, ISR capture,
                 tick -> RTC wall-clock mapping, per-record f_measured
bus.c/h          SPI abstraction: per-slot handle, CS discipline, DMA
                 transfer with completion callback, blocking fallback
imu.h            vtable: configure / read_regs / read_fifo / set_offset /
                 set_watermark / read_temp / whoami
  imu_icm42688.c   bank switching, AAF + UI filters, hi-res FIFO, OFFSET_USER,
                   watermark, INT routing
  imu_ism330dhcx.c secondary (stage E)
  imu_bmi323.c     secondary (stage E)
sampler.c/h      INT ISR -> DMA burst -> lock-free ring; sample indexing;
                 gap detection; pairing of register and FIFO streams
record.c/h       .sdat writer: 4 KiB JSON header, packed fixed-width binary,
                 per-block register read-back, running CRC
storage.c/h      FATFS writer task, file rotation, worst-case stall
                 instrumentation, free-space guard
runctl.c/h       declarative run table; state machine
                 IDLE -> CONFIGURE -> SETTLE -> RECORD -> VERIFY -> next
health.c/h       thermal gate, battery ADC, card detect, abort conditions
main.c           wiring only
```

A campaign becomes data, not code:

```c
static const run_step_t campaign_odr_axis[] = {
  { .slot = SLOT_ICM1, .odr_hz = 25,   .fsr_dps = 2000, .path = PATH_DUAL,
    .ui_bw = 0, .watermark = 1, .settle_s = 900, .record_s = 1200,
    .gate_mk = 260, .label = "odr25" },
  { .slot = SLOT_ICM1, .odr_hz = 50,   /* ... */ .record_s = 600,  .gate_mk = 361 },
  { .slot = SLOT_ICM1, .odr_hz = 100,  /* ... */ .record_s = 300,  .gate_mk = 388 },
  { .slot = SLOT_ICM1, .odr_hz = 200,  /* ... */ .record_s = 500,  .gate_mk = 389 },
  { .slot = SLOT_ICM1, .odr_hz = 500,  /* ... */ .record_s = 120,  .gate_mk = 0   },
  { .slot = SLOT_ICM1, .odr_hz = 1000, /* ... */ .record_s = 228,  .gate_mk = 0   },
  { .slot = SLOT_ICM1, .odr_hz = 8000, /* ... */ .record_s = 1464, .gate_mk = 0   },
};
```

Durations are TN-14 §1.3 verbatim. Gates are TN-14 §2.2 verbatim. `gate_mk = 0` means inactive, per the ODR ≥ 500 row.

---

## 4. Record format

You asked for whatever is standard for academic use and Zenodo deposit. There is no single answer, because the instrument's needs and the archive's needs differ. The standard practice is **two formats and a documented converter**, and that is what this specifies.

### 4.1 On the device — `.sdat`

```
offset 0      4096 B   UTF-8 JSON header, space-padded to 4 KiB
offset 4096   ...      packed fixed-width binary sample records
```

- **4 KiB header, block-aligned.** SD writes are 512-byte blocks and FATFS clusters here are 256 sectors; starting the payload on a 4 KiB boundary avoids a read-modify-write on the first data write. The header is also readable with `head -c 4096`, so a record is never opaque.
- **Single file.** Header and data cannot be separated in an archive, which a sidecar permits and which is a real failure mode for deposited datasets.
- **Raw integer codes only** (TN-06 v1.2). No scaling, no floats, anywhere in the payload. Sensitivity lives in the header; the multiplication happens in analysis.
- **Register read-back, not intent.** The header records what was read back out of the sensor after configuration — `GYRO_CONFIG0`, `GYRO_ACCEL_CONFIG0`, the AAF triple, `OFFSET_USER`, watermark — because TN-16 §5.4 asks for exactly this and because a write that silently failed is otherwise invisible.

Header fields, minimum set:

```json
{
  "format": "sdat/1", "run_id": "...", "label": "odr25",
  "board_uid": "...", "fw_version": "0.2.0", "fw_build_tag": "...",
  "fw_build_time": "...", "opt_level": "-O0",
  "sensor": {"part": "ICM-42688-P", "slot": 1, "whoami": 71},
  "config": {"odr_nominal_hz": 25, "fsr_dps": 2000, "word_bits": 16,
             "ui_filt_bw": 0, "aaf": {"delt": 1, "deltsqr": 1, "bitshift": 15},
             "offset_user_lsb": 0, "fifo_watermark": 1,
             "sensitivity_lsb_per_dps": 16.4},
  "registers_readback": {"0x4F": "0x08", "0x52": "0x00", "...": "..."},
  "timing": {"f_nominal_hz": 25, "f_measured_hz": null,
             "f_measure_method": "tim2_regression", "n_samples": 0,
             "n_gaps": 0, "ts_first_us": 0, "ts_last_us": 0},
  "thermal": {"gate_mk": 260, "t_start_c": null, "t_end_c": null,
              "drift_k_per_h": null, "gate_pass": null},
  "clock": {"sysclk_hz": 32000000, "hse": "24MHz bypass"},
  "power": "battery", "usb_connected": false,
  "rtc_start_utc": "2026-08-15T02:14:07Z"
}
```

The `timing` and `thermal` blocks are filled in at record close, which means the header is rewritten once at the end — cheap, and it keeps everything in one place.

### 4.2 For the archive — HDF5 plus the raw files

Deposit **both**:

1. The `.sdat` files byte-for-byte. This is the primary record and it makes the whole chain auditable — a reviewer can re-derive every published number from the instrument's own output.
2. **HDF5** per record, generated by a converter that is itself deposited. HDF5 is the de facto standard for archived scientific array data, reads natively in Python, MATLAB and R, carries metadata as attributes, and compresses well.
3. A **SHA-256 manifest** over everything, so the deposit is verifiable.

Rationale for not writing CSV: at 0.92 GB raw it becomes roughly 5 GB, it is materially slower to write — which eats the SD stall margin at ODR 8000 — and float formatting is the most likely route to violating the raw-integer-codes rule that TN-06 calls the single most important firmware constraint.

Rationale for not writing HDF5 on the device: it is not realistically writable from an STM32, and attempting it would put a complex library on the critical write path.

---

## 5. Staged delivery

Each stage ends with a stated acceptance test. Nothing proceeds on "it seems to work".

### Stage A — timebase and bus
`timebase.c/h`, `bus.c/h`, ICM FIFO configuration and read.

- TIM2 at 1 MHz with a 64-bit software extension (a 12 h bias-instability record of TN-13 block 10 wraps the 32-bit counter ten times — the current TN-16 §10.3 note assumes 20-minute records and does not cover this)
- Timestamp captured in the ISR, not the main loop
- SPI-DMA burst read with completion callback
- Hi-res FIFO enabled, packets read and decoded

**Acceptance:** hi-res packets decode to plausible gyro values that agree with a simultaneous register read to within one 16-bit LSB; TIM2 timestamps are monotonic across a deliberate 90-minute run.

### Stage B — storage and record format
`record.c/h`, `storage.c/h`.

- `.sdat` writer with the §4.1 header
- Ring buffer between sampler and writer
- **Worst-case single-write latency instrumented and reported** (TN-16 open item 7)

**Acceptance:** a 20-minute record at ODR 100 with zero gaps; read back on a PC and confirm every gyro sample is an exact multiple of one LSB; worst-case stall reported and the ring sized at $t_{\text{stall,max}} \times f_\text{ODR} \times b_\text{sample}$ with ≥3× margin.

### Stage C — V0.4 and M1
`sampler.c/h` paired capture, minimal: ODR 100, watermark 1, one ICM.

**This is the stage that answers §1.** Deliberately kept small.

**Acceptance:** V0.4 scored against all five outcomes {rounding, truncation, RPDF, TPDF, neither}; M1 reports σ at ODR 25/50/100/200/500 from the 19-bit stream and states whether it falls as √ODR.

**Decision gate.** The general dual-path architecture is designed *after* this reports, not before.

### Stage D — sequencer and unattended operation
`runctl.c/h`, `health.c/h`.

- Run table, settle/record/verify state machine
- Thermal gate per R2, with automatic excision flagging
- FIFO watermark as a run parameter (R8)
- Autostart on power-up with no console attached; survive a full unattended night

**Acceptance:** the seven-point ODR axis runs end to end unattended on battery, USB disconnected, producing seven valid records with gate results recorded.

### Stage E — remaining axes
OFFSET_USER ladder (12 steps), FSR axis, secondary sensors (TN-13 blocks 6–7), long BI/RRW records.

---

## 6. Schedule

Today is 27 July. The holiday window is 29 July to mid-August. The data deadline is 30 August. The board is already alive, ahead of the mid-August arrival the corpus assumed.

The real constraint is therefore **firmware complete by ~14 August**, leaving two weeks for 55 h of wall-clock logging — TN-14's >2× margin holds.

| Window | Target |
|---|---|
| **27–28 July** | Stage A, and Stage C if A goes well. Even a partial result on V0.4 is worth more than anything else that could be built in two days, because it may delete work |
| 29 July – mid Aug | Away. If Stage B is reachable before leaving, set a long unattended M1 record running |
| mid Aug – 22 Aug | Stages B, D, E |
| 22–30 Aug | Campaign logging |

The two days before the holiday should be spent on the thing that can invalidate the design, not the thing that is most satisfying to build.

---

## 7. Open decisions

### 7.1 Specimen count
TN-13 block 8 and TN-14 §5 assume **four ICM specimens**. Sheppard carries **two**. Options: a second board, or TN-14's degradation ladder item 1 — drop to two specimens, which it states "loses specimen-scatter evidence; keeps every central claim". Not urgent, but it changes the campaign budget by 5.6 h logging and 13 h settling. **Decide before the campaign is frozen.**

### 7.2 AAF setting for the regime sweep
TN-13 specifies `GYRO_UI_FILT_BW = 0` for Experiment 2 but **never pins the AAF setting**. The present `icm_configure_matched()` forces the 42 Hz floor, which is correct for the cross-vendor comparison (TN-16 §5.4) and possibly wrong for the ODR sweep: TN-13 §5 notes the AAF alone cannot bandlimit below Nyquist at ODR ≤ 50. M1 may settle it empirically. **Must be decided before the sweep is frozen**, and whichever is chosen must be recorded in every header.

### 7.3 Is `GYRO_UI_FILT_BW = 0` the power-on default?
Marked **[verify]** in TN-13 Appendix Z.1 and described there as on the critical path. The current firmware writes `GYRO_ACCEL_CONFIG0 = 0x00` explicitly, which sets it — so the campaign is safe either way, but the question should be answered and recorded.

### 7.4 Interrupt routing for paired capture
Only **INT1 per slot is routed** on Sheppard (TN-16 §1.2). The ICM can drive both data-ready and FIFO-watermark onto INT1, but distinguishing them requires reading `INT_STATUS` — an SPI transaction, forbidden in the ISR by TN-16 §9.3. Watermark = 1 sidesteps this for V0.4 by making the two events coincide. **A general solution is needed only if V0.4 says the register path cannot be dropped**, which is the §1 fork. Add INT2 routing to the rev-B list regardless.

### 7.6 UI filter default, and what it means for the relevance claim
The power-on default is `GYRO_ACCEL_CONFIG0 = 0x11`, i.e. UI_FILT_BW = 1 on
both channels [fact, DS Rev 1.6 §14.40]. Three consequences:

1. **Operationally safe.** The firmware programs `0x00` explicitly, so the
   regime sweep exists. But it is not free, and any build that fails to write
   it produces a flat σ and no sweep — a silent failure that looks like a null
   result. `icm_configure()` verifies the write; keep it that way, and log the
   read-back in every record header.
2. **TN-13 needs correcting.** Its premise, "the sensor's default ODR-tracking
   decimation", is false. Z.1 already flagged that only BW = 0 tracks ODR; this
   confirms BW = 0 is not the default. An Appendix Z entry is warranted.
3. **It may strengthen the relevance argument rather than weaken it.** The
   corpus's ★★ action is to establish the default ODR/FSR of common drivers
   because it "gates the relevance claim". If a practitioner takes the part at
   its defaults, the noise bandwidth does *not* scale with ODR — so the
   √ODR transfer rule embedded in the toolchains is violated by the hardware
   default, not merely by an unusual configuration. **This is an interpretive
   question for the Concept Note, not something Stage A settles**, and it
   should be argued rather than assumed.

### 7.5 DMA stream allocation
The `.ioc` currently configures no DMA at all. SPI1/4/5 all sit on DMA2 and contend. Only one sensor logs at a time in the campaign, so contention is not expected to bind — but the allocation must be checked in CubeMX before Stage A, and it is a regeneration hazard once set.

---

## 8. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 27 Jul 2026 | Initial issue. Records the 27 July scope decisions, the V0.4 architectural fork, requirements traceability from R1–R8, module set, `.sdat` format, five-stage delivery with acceptance tests, and five open decisions |
