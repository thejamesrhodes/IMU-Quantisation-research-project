# Zenodo metadata — paste-ready

DOI reserved: **10.5281/zenodo.22860516**

Everything below goes into the Zenodo deposit form. Fields marked **required**
are the ones with a red star.

---

## Resource type **required**

`Dataset`

---

## Title **required**

```
Paired 16-bit and 19-bit output records from two ICM-42688-P MEMS gyroscopes across output-rate and sub-LSB bias-offset sweeps
```

17 words, 124 characters.

---

## Creators **required**

| Field | Value |
|---|---|
| Family name | `Rhodes` |
| Given names | `James` |
| Identifier | your ORCID |
| Affiliation | `Independent researcher` |
| Role | leave blank |

---

## Publication date **required**

Today's date. Zenodo prefills it.

---

## Description **required**

Zenodo's description box is rich text. Paste this. 279 words, inside the 120-280
typical of Zenodo dataset records.

```
This dataset contains 94 static-bench records from two ICM-42688-P MEMS
gyroscopes (TDK InvenSense). The sensors were stationary throughout: the board
was clamped and motionless, no rotation was applied, and no motion or attitude
ground truth is included.

Each record captures the device's 16-bit rate register alongside its extended
high-resolution output channel over the same physical samples, so the two
streams are digitisations of one shared input at resolutions differing by a
factor of eight. Samples are stored as raw integer codes, with no scaling or
calibration applied, preserving the output code lattice that calibrated
floating-point datasets discard. Totals: 10,599,722 samples, 9.43 hours, three
axes per record.

Two quantities were varied, on independent axes rather than as a grid: the
output data rate (25 Hz to 8 kHz), and the device's user-offset trim register,
which moves the sensor bias within a single output code.

Contents: four record bundles (offset sweep, output-rate sweep, trim-register
calibration, anti-alias filter variation); summary.csv, giving per-record
per-axis configuration and moments; a standalone Python reader and verifier; a
codebook defining every column and giving closed-form expressions for derived
quantities; and a SHA-256 manifest.

Format: each record carries a 4 KiB JSON header with firmware version, clock
and sensor configuration and a verbatim configuration-register readback,
followed by 4 KiB data blocks holding the vendor's FIFO packets with CRC-32
over every payload. All 94 records pass integrity verification.

Notes: a spectral line near 119 Hz is present and aliases to a different
frequency at each output rate; measured amplitudes are tabulated in README.md.
The filter chains correlate neighbouring samples at every rate. Die
temperature is logged per record.

Licence: records and summary.csv are CC-BY-4.0; the bundled reader is MIT.
```

---

## Licences **required** — add both

Zenodo supports several licences on one record, and documents exactly this case
("software under the MIT license, but documentation under CC-BY"). This deposit
is mixed, so declare both rather than picking one:

| Licence | Covers |
|---|---|
| `Creative Commons Attribution 4.0 International` | the record bundles and `summary.csv` |
| `MIT License` | `read_sdat.py` |

CC-BY-4.0 is Zenodo's default and is already selected. Click **Edit** beside it
to confirm, then **Add standard** and search `MIT` for the second. Zenodo uses
the SPDX list, so the entries are `cc-by-4.0` and `mit`.

Watch for near-identical entries in the picker — several Creative Commons
variants differ only by version or by `-NC` / `-SA` suffixes.

---

## Copyright

Optional free-text field, separate from the licence. It names the rights
holder; the licence says what others may do. Worth filling here precisely
because the deposit is mixed-licence — one unambiguous statement of who holds
the rights removes any question about which file belongs to whom.

```
Copyright (c) 2026 James Rhodes. Records and summary.csv licensed CC-BY-4.0; read_sdat.py licensed MIT.
```

---

## References

Optional list of free-text references, rendered as a References block on the
record page. Add one per entry.

These are exactly the five cited in `CODEBOOK.md` — the datasheet defines the
packet structure and register names, and the other four define the quantiser
relations used in §3. Nothing is listed that the deposit does not use. All
DOIs verified against Crossref.

```
TDK InvenSense (2020). ICM-42688-P Datasheet, DS-000347 Rev. 1.6.
```

```
Sheppard, W. F. (1898). On the Calculation of the most Probable Values of Frequency-Constants, for Data arranged according to Equidistant Divisions of a Scale. Proceedings of the London Mathematical Society, s1-29, 353-380. https://doi.org/10.1112/plms/s1-29.1.353
```

```
Sripad, A., & Snyder, D. (1977). A Necessary and Sufficient Condition for Quantization Errors to be Uniform and White. IEEE Transactions on Acoustics, Speech, and Signal Processing, 25(5), 442-448. https://doi.org/10.1109/TASSP.1977.1162977
```

```
Widrow, B., & Kollar, I. (2008). Quantization Noise: Roundoff Error in Digital Computation, Signal Processing, Control, and Communications. Cambridge University Press. https://doi.org/10.1017/CBO9780511754661
```

```
Vardeman, S. B. (2005). Sheppard's Correction for Variances and the "Quantization Noise Model". IEEE Transactions on Instrumentation and Measurement, 54(5), 2117-2119. https://doi.org/10.1109/TIM.2005.853348
```

**Not included: IEEE Std 952.** It was in an earlier draft of the codebook and
is now removed from both. It specifies test procedures for interferometric
fibre-optic gyroscopes — a different output architecture from the part in this
dataset — and nothing in the deposit uses it. Listing it would suggest the
records relate to that standard.

---

## Version

```
1.0.0
```

---

## Language

```
English
```

---

## Keywords

Data-descriptive terms first, so the deposit is findable by people who are not
already thinking about quantisation. Add one at a time:

```
MEMS gyroscope
inertial measurement unit
raw sensor data
uncalibrated data
static bench measurement
ICM-42688-P
sensor characterisation
Allan variance
output data rate
quantisation noise
angle random walk
truncating quantiser
```

---

## Related works

Leave empty for now. Metadata stays editable indefinitely, so the manuscript
and the code repository go in later:

| Relation | Identifier | Resource type |
|---|---|---|
| `is supplemented by` | repository URL | Software |
| `is supplement to` | manuscript DOI, once it has one | Publication |

---

## Files

All eleven files from `zenodo\build\`:

```
CODEBOOK.md
LICENSE-CODE.txt
LICENSE-DATA.txt
MANIFEST-SHA256.txt
README.md
icm42688p-aaf-variation.zip
icm42688p-odr-sweep.zip
icm42688p-offset-calibration.zip
icm42688p-phase-sweep.zip
read_sdat.py
summary.csv
```

Set the default preview file to `README.md` if Zenodo offers the choice.

---

## Visibility

`Public`. Do not tick "Apply an embargo".

---

## Citation this produces

> Rhodes, J. (2026). *Paired 16-bit and 19-bit output records from two
> ICM-42688-P MEMS gyroscopes across output-rate and sub-LSB bias-offset
> sweeps* (Version 1.0.0) [Data set]. Zenodo.
> <https://doi.org/10.5281/zenodo.22860516>
