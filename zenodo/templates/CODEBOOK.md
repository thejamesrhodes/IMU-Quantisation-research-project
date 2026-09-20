# Codebook

Version {{VERSION}} · built {{BUILT}} · DOI {{DOI}}

`summary.csv` has {{N_ROWS}} rows, one per record per gyroscope axis, and
{{N_RECORDS}} distinct records, all taken with the sensors stationary. Every
column is either configuration read from the record header or a moment computed
from that record's own samples. No column is fitted, corrected toward a model,
or compared against a prediction.

Quantities derived from these columns are given in §3 as explicit expressions,
so that a reader applies them rather than inheriting them.

Formulas are written in plain text and are directly usable in Python or any
spreadsheet. `mod` is the non-negative remainder, `sqrt` the square root,
`floor` rounding toward negative infinity, and `^` exponentiation.

---

## 1. Conventions

| Symbol | Definition | Value |
|---|---|---|
| Δ | 16-bit rate-register LSB | 61.035 m°/s at ±2000 °/s |
| Δ′ | reference-lattice step | Δ/8 = 7.629 m°/s |
| v | continuous rate at the quantiser input | — |
| x | reference stream, 19-bit | in units of Δ |
| Q | register stream, 16-bit | in units of Δ |
| φ | sub-code bias phase | in units of Δ |
| ρ | dither ratio | dimensionless |
| η | normalised added power | dimensionless |
| G | quantiser gain | dimensionless |

All `*_lsb` and `*_lsb2` columns are in units of Δ and Δ² respectively. To
convert to physical units multiply by Δ or Δ²; `sensor.delta_mdps` in each
record header carries the value that record was taken at.

**Word length.** The device's high-resolution FIFO field is 20 bits wide. The
field's least significant bit is zero in all {{N_WORDS}} gyroscope words in this
dataset, so 19 bits are significant and the reachable lattice is Δ/8. All
resolutions here are quoted on the 19-bit convention:

```
x  = Δ' * gyro19          with Δ' = Δ/8
gyro16 = gyro19 >> 3
```

The second identity holds bit-exactly in all {{N_WORDS}} words, so the register
is a truncation of the reference and not a rounding of it:

```
Q(v) = Δ * floor(v / Δ)
```

**Phase reference.** φ is edge-referenced: φ = 0 at a code boundary,
φ = 0.5 at mid-code.

**Detrending.** Every moment column is computed on the record after removal of
a least-squares straight line, so that bench temperature drift during a record
does not enter the variance. The first-moment column `mean_ref_lsb` is computed
on the undetrended stream.

---

## 2. Columns

### 2.1 Identity

| Column | Definition |
|---|---|
| `file` | record filename |
| `label` | run label from the record header |
| `specimen` | sensor slot, 1 or 2; distinct physical parts of the same type |
| `axis` | `X`, `Y` or `Z` |

### 2.2 Configuration, read verbatim from the record header

| Column | Definition | Units |
|---|---|---|
| `odr_nominal_hz` | commanded output data rate | Hz |
| `odr_measured_hz` | rate measured by the logger's own timer over the record | Hz |
| `aaf` | anti-alias filter setting | — |
| `offset_user_steps` | value written to the device's user-offset trim register | steps |
| `power` | supply during the record | — |

### 2.3 Extent and integrity

| Column | Definition |
|---|---|
| `n_samples` | FIFO samples in the record |
| `minutes` | `n_samples / odr_measured_hz / 60` |
| `verify` | `ok` if block magic, sequence continuity, CRC-32 over every payload, packet-header sanity and timestamp continuity all pass |
| `fifo_overflows` | device-reported FIFO overflow count |
| `ring_full` | logger-reported buffer-full count |
| `temp_span_mK` | `1000 * (max(T) - min(T))` over the record, from the device's own die sensor |
| `temp_drift_mK` | `1000 * abs(mean(T, last 5%) - mean(T, first 5%))` |

`verify` is `ok` for every row in this release.

### 2.4 Moments

`Var` and `Cov` are sample estimators with denominator `n - 1`. A tilde denotes
the detrended stream.

| Column | Definition |
|---|---|
| `mean_ref_lsb` | `mean(x)`, undetrended |
| `var_ref_lsb2` | `Var(x~)` |
| `var_reg_lsb2` | `Var(Q~)` |
| `cov_lsb2` | `Cov(Q~, x~)` |

### 2.5 Descriptive

| Column | Definition |
|---|---|
| `tail_ratio` | `std(x~) / (1.4826 * MAD(x~))`. The constant is the Gaussian consistency factor. Values materially above 1 indicate the tails carry disproportionate weight — a transient during the record rather than wide noise. |
| `n_codes` | distinct 16-bit register codes occupied by the axis over the record |

---

## 3. Derived quantities

Each expression is exact given the definitions in §1 and the model of the
reference channel in §3.1. Nine significant figures are carried in the moment
columns so that these reproduce to more places than are useful.

### 3.1 The reference channel is itself a quantiser

x is not v. It is v truncated onto the Δ′ lattice. Where the input is well
dithered relative to the step - Sripad and Snyder (1977) give the necessary and
sufficient condition - the first two moments of a truncating quantiser of step
s relate to those of its input as [Sheppard 1898; Widrow & Kollár 2008, ch. 4]:

```
mean(x) = mean(v) - Δ'/2
Var(x)  = Var(v)  + Δ'^2 / 12
```

Vardeman (2005) sets out the relationship between Sheppard's correction and
the quantisation-noise model directly.

With Δ′ = Δ/8, in units of Δ:

```
Δ'/2     = 1/16  = 0.0625
Δ'^2/12  = 1/768 = 0.00130208333
```

### 3.2 Sub-code phase

```
phi = (mean_ref_lsb + 1/16) mod 1
```

Without the `1/16` the result is the phase of the reference lattice rather
than of the continuous input.

### 3.3 Dither ratio

```
rho = sqrt(var_ref_lsb2 - 1/768)
```

This is the standard deviation of v in units of Δ.

### 3.4 Added power

Normalised by the ideal quantiser variance Δ²/12:

```
eta = 12 * (var_reg_lsb2 - var_ref_lsb2) + 1/64
```

equivalently `(Var(Q) - Var(v)) / (Δ^2 / 12)`.

`eta = 1` recovers the classical additive model, in which the quantiser adds
Δ²/12 [Widrow & Kollár 2008, ch. 4]. `eta = 0` does not.

### 3.5 Gain

```
G = cov_lsb2 / (var_ref_lsb2 - 1/768)
```

equivalently `Cov(Q, v) / Var(v)`.

This uses `Cov(Q, x)` in place of `Cov(Q, v)`, which neglects `Cov(Q, x - v)`.
The reference lattice is eight times finer than the register, so on these
records the reference channel's own error is uncorrelated with the input to
well below the precision carried here.

### 3.6 Worked example

Taking row 1 of `summary.csv` and working in units of Δ:

```python
import csv

r  = next(csv.DictReader(open("summary.csv")))
m  = float(r["mean_ref_lsb"])
vx = float(r["var_ref_lsb2"])
vq = float(r["var_reg_lsb2"])
cv = float(r["cov_lsb2"])

phi = (m + 1/16) % 1
rho = (vx - 1/768) ** 0.5
eta = 12 * (vq - vx) + 1/64
G   = cv / (vx - 1/768)
```

---

## 4. Record families

Record filenames are `r<id>_<label>_<odr>.sdat`. Labels group as follows.

| Prefix or suffix | Bundle | What was varied |
|---|---|---|
| `ph_k`, `s2ph_k`, `c1_k`, `s1rep_k` | phase-sweep | `offset_user_steps`, at fixed rate and filter |
| `*_odr*` | odr-sweep | output data rate |
| `off*`, `c2_*`, `p2cal_*` | offset-calibration | `offset_user_steps` in ladders, for trim-register characterisation |
| `aaf*`, `*_fl` | aaf-variation | anti-alias filter, at 50, 200 and 1000 Hz |

The `*_fl` records vary the anti-alias filter at output rates of 50, 200 and
1000 Hz, each paired against default-filter records at the same rate. Changing
that filter also changes the amplitude of the spectral line described in
`README.md` §5 and alters the correlation between successive samples, so the
setting is not a clean single-variable axis. They are included for
completeness.

---

## 5. Record header fields

Each `.sdat` file opens with a 4 KiB UTF-8 JSON header. `read_sdat.py info`
prints it. Register names and the FIFO packet layout follow the device
datasheet (TDK InvenSense DS-000347 Rev. 1.6). Fields of note:

| Path | Meaning |
|---|---|
| `sensor.delta_mdps` | Δ in m°/s for that record |
| `sensor.hires_lsb_per_dps` | reference-channel scale, `1/Δ'` |
| `config.word_bits` | the FIFO field width, 20. See §1 on the 19-bit convention |
| `config.offset_user_steps` | trim-register value |
| `registers_readback` | verbatim configuration-register contents |
| `fw.version`, `fw.tag`, `fw.built` | logger firmware provenance |
| `clock.sysclk_hz` | logger system clock, held fixed as an experimental control |

---

## 6. References

- Sheppard, W. F., 'On the Calculation of the most Probable Values of
  Frequency-Constants, for Data arranged according to Equidistant Divisions of
  a Scale', *Proceedings of the London Mathematical Society*, s1-29 (1898),
  353–380 <https://doi.org/10.1112/plms/s1-29.1.353>
- Sripad, A., and D. Snyder, 'A Necessary and Sufficient Condition for
  Quantization Errors to be Uniform and White', *IEEE Transactions on
  Acoustics, Speech, and Signal Processing*, 25 (1977), 442–448
  <https://doi.org/10.1109/TASSP.1977.1162977>
- Widrow, B., and I. Kollár, *Quantization Noise: Roundoff Error in Digital
  Computation, Signal Processing, Control, and Communications* (Cambridge
  University Press, 2008) <https://doi.org/10.1017/CBO9780511754661>
- Vardeman, S. B., 'Sheppard's Correction for Variances and the "Quantization
  Noise Model"', *IEEE Transactions on Instrumentation and Measurement*, 54
  (2005), 2117–2119 <https://doi.org/10.1109/TIM.2005.853348>
- TDK InvenSense, *ICM-42688-P Datasheet*, DS-000347 Rev. 1.6 — FIFO packet
  structure (§6.1), register map, temperature scaling
