# Codebook

Version {{VERSION}} · built {{BUILT}} · DOI {{DOI}}

`summary.csv` has {{N_ROWS}} rows, one per record per gyroscope axis, and
{{N_RECORDS}} distinct records, all taken with the sensors stationary. Every
column is either configuration read from the record header or a moment computed
from that record's own samples. No column is fitted, corrected toward a model,
or compared against a prediction.

Quantities derived from these columns are given in §3 as closed-form
expressions, so that a reader applies them explicitly rather than inheriting
them.

---

## 1. Conventions

| Symbol | Definition | Value |
|---|---|---|
| $\Delta$ | 16-bit rate-register LSB | $\SI{61.035}{\milli\degree\per\second}$ at $\pm\SI{2000}{\degree\per\second}$ |
| $\Delta'$ | reference-lattice step | $\Delta/8 = \SI{7.629}{\milli\degree\per\second}$ |
| $v$ | continuous rate at the quantiser input | — |
| $x$ | reference stream, 19-bit | $\Delta$ |
| $Q$ | register stream, 16-bit | $\Delta$ |

All `*_lsb` and `*_lsb2` columns are in units of $\Delta$ and $\Delta^2$. To
convert to physical units multiply by $\Delta$ or $\Delta^2$; `delta_mdps` in
each record header carries the value that record was taken at.

**Word length.** The device's high-resolution FIFO field is 20 bits wide. The
field's least significant bit is zero in all {{N_WORDS}} gyroscope words in this
dataset, so 19 bits are significant and the reachable lattice is $\Delta/8$.
All resolutions here are quoted on the 19-bit convention:

$$x = \Delta' \, \texttt{gyro19}, \qquad \Delta' = \Delta/8, \qquad
\texttt{gyro16} = \texttt{gyro19} \gg 3 .$$

The right-hand identity holds bit-exactly in all {{N_WORDS}} words, so the
register is a truncation of the reference and not a rounding of it:

$$Q(v) = \Delta \left\lfloor v/\Delta \right\rfloor .$$

**Phase reference.** $\varphi$ is **edge**-referenced: $\varphi = 0$ at a code
boundary, $\varphi = 1/2$ at mid-code.

**Detrending.** Every moment column is computed on the record after removal of
a least-squares straight line, so that bench temperature drift during a record
does not enter the variance. First-moment columns (`mean_ref_lsb`) are computed
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

### 2.2 Configuration — read verbatim from the record header

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
| `minutes` | $n_\text{samples} / f_\text{measured} / 60$ |
| `verify` | `ok` if block magic, sequence continuity, CRC-32 over every payload, packet-header sanity and timestamp continuity all pass |
| `fifo_overflows` | device-reported FIFO overflow count |
| `ring_full` | logger-reported buffer-full count |
| `temp_span_mK` | $10^3\,(\max T - \min T)$ over the record, from the device's own die sensor |
| `temp_drift_mK` | $10^3\,\lvert \bar T_\text{last 5\%} - \bar T_\text{first 5\%} \rvert$ |

`verify` is `ok` for every row in this release.

### 2.4 Moments

$\operatorname{Var}$ and $\operatorname{Cov}$ are sample estimators with
denominator $n-1$. $\tilde{x}$ denotes the detrended stream.

| Column | Definition |
|---|---|
| `mean_ref_lsb` | $\mathbb{E}[x]$, undetrended |
| `var_ref_lsb2` | $\operatorname{Var}(\tilde{x})$ |
| `var_reg_lsb2` | $\operatorname{Var}(\tilde{Q})$ |
| `cov_lsb2` | $\operatorname{Cov}(\tilde{Q}, \tilde{x})$ |

### 2.5 Descriptive

| Column | Definition |
|---|---|
| `tail_ratio` | $\sigma / \sigma_\text{robust}$, where $\sigma_\text{robust} = 1.4826\,\mathrm{MAD}(\tilde{x})$. The factor is the Gaussian consistency constant. Values materially above 1 indicate the tails carry disproportionate weight — a transient during the record rather than wide noise. |
| `n_codes` | distinct 16-bit register codes occupied by the axis over the record |

---

## 3. Derived quantities

Each expression below is exact given the definitions in §1 and the model of
the reference channel in §3.1. Nine significant figures are carried in the
moment columns so that these reproduce to more places than are useful.

### 3.1 The reference channel is itself a quantiser

$x$ is not $v$. It is $v$ truncated onto the $\Delta'$ lattice, so for a
truncating quantiser of step $s$ acting on an input dithered well relative to
$s$ [Sheppard 1898; Widrow & Kollár 2008, ch. 4]:

$$\mathbb{E}[x] = \mathbb{E}[v] - \tfrac{1}{2}\Delta', \qquad
\operatorname{Var}(x) = \operatorname{Var}(v) + \frac{\Delta'^2}{12} .$$

With $\Delta' = \Delta/8$, in units of $\Delta$:

$$\tfrac{1}{2}\Delta' = \tfrac{1}{16}, \qquad
\frac{\Delta'^2}{12} = \frac{1}{768} .$$

### 3.2 Sub-code phase

$$\varphi = \left( \texttt{mean\_ref\_lsb} + \tfrac{1}{16} \right) \bmod 1 .$$

Without the $\tfrac{1}{16}$ the result is the phase of the *reference lattice*
rather than of the continuous input.

### 3.3 Dither ratio

$$\rho = \frac{\sqrt{\operatorname{Var}(v)}}{\Delta}
       = \sqrt{\,\texttt{var\_ref\_lsb2} - \tfrac{1}{768}\,} .$$

### 3.4 Added power

Normalised by the ideal quantiser variance $\Delta^2/12$:

$$\eta \equiv \frac{\operatorname{Var}(Q) - \operatorname{Var}(v)}{\Delta^2/12}
 = 12\left( \texttt{var\_reg\_lsb2} - \texttt{var\_ref\_lsb2} \right)
   + \tfrac{1}{64} .$$

$\eta = 1$ recovers the classical additive model, in which the quantiser adds
$\Delta^2/12$ [Widrow & Kollár 2008, ch. 4]. $\eta = 0$ does not.

### 3.5 Gain

$$G \equiv \frac{\operatorname{Cov}(Q, v)}{\operatorname{Var}(v)}
 = \frac{\texttt{cov\_lsb2}}{\texttt{var\_ref\_lsb2} - \tfrac{1}{768}} .$$

This uses $\operatorname{Cov}(Q,x)$ in place of $\operatorname{Cov}(Q,v)$, which
neglects $\operatorname{Cov}(Q, x - v)$. The reference lattice is eight times
finer than the register, so on these records the reference channel's own error
is uncorrelated with the input to well below the precision carried here.

### 3.6 Worked example

Taking row 1 of `summary.csv` and working in units of $\Delta$:

```python
import csv
r = next(csv.DictReader(open("summary.csv")))
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
| `aaf*`, `*_fl` | aaf-variation | anti-alias filter at fixed output rate |

The `*_fl` records vary the anti-alias filter while holding the output rate
fixed. Changing that filter also changes the amplitude of the spectral line
described in `README.md` §5 and alters the correlation between successive
samples, so the setting is not a clean single-variable axis. They are included
for completeness.

---

## 5. Record header fields

Each `.sdat` file opens with a 4 KiB UTF-8 JSON header. `read_sdat.py info`
prints it. Fields of note:

| Path | Meaning |
|---|---|
| `sensor.delta_mdps` | $\Delta$ in m°/s for that record |
| `sensor.hires_lsb_per_dps` | reference-channel scale, $1/\Delta'$ |
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
- Widrow, B., and I. Kollár, *Quantization Noise: Roundoff Error in Digital
  Computation, Signal Processing, Control, and Communications* (Cambridge
  University Press, 2008)
- Vardeman, S. B., 'Sheppard's Correction for Variances and the "Quantization
  Noise Model"', *IEEE Transactions on Instrumentation and Measurement*, 54
  (2005), 2117–2119
- IEEE Std 952-2020, *IEEE Standard Specification Format Guide and Test
  Procedure for Single-Axis Interferometric Fiber Optic Gyros*
- TDK InvenSense, *ICM-42688-P Datasheet*, DS-000347 Rev. 1.6 — FIFO packet
  structure (§6.1), register map, temperature scaling
