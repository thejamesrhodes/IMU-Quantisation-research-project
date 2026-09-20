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

Zenodo's description box is rich text. Paste this; the headings carry across.

```
THE SENSORS DO NOT MOVE. Every record is a stationary static-bench
measurement. The board was clamped and motionless throughout, no rotation was
applied, and the only quantities deliberately varied are the output data rate
and the sub-LSB bias offset. There is no motion, trajectory or attitude ground
truth in this dataset, and none is implied.

94 records from two ICM-42688-P MEMS gyroscopes (TDK InvenSense). Each record
captures the device's standard 16-bit rate register alongside its extended
high-resolution output channel over the same physical samples, so the two
streams are digitisations of one shared input at resolutions differing by a
factor of eight. 10,599,722 samples, 9.43 hours of logging, three axes per
record.

Samples are stored as raw integer codes. No scaling, calibration or conversion
to physical units has been applied, so the code lattice the two streams sit on
is intact and recoverable. This is the property that makes the dataset useful
for work on output quantisation, and the one that published IMU datasets
normally destroy by distributing calibrated floats.

CONTENTS

Records are supplied as four ZIP bundles grouped by what was varied: a sweep
of the device's user-offset trim register, which moves the bias within one
output code (50 records); an output-data-rate sweep spanning 25 Hz to 8 kHz
(14 records); trim-register calibration ladders (22 records); and anti-alias
filter variation (8 records). The two sweeps are independent axes, not a grid:
the offset sweep was run at fixed output rate, and the rate sweep at fixed
offset.

Also included: summary.csv, giving per-record per-axis configuration and
moments; a standalone reader and verifier; a codebook defining every column
and giving closed-form expressions for the derived quantities; and a SHA-256
manifest covering both the uploaded files and each record inside each bundle.

FORMAT AND PROVENANCE

Each record opens with a 4 KiB UTF-8 JSON header carrying the logger firmware
version and build tag, board identifier, clock tree, sensor part and slot, the
full sensor configuration, and a verbatim readback of the configuration
registers, so every record is self-describing down to the register contents
that produced it. The payload is the vendor's 20-byte FIFO packet verbatim
(DS-000347 Rev. 1.6 section 6.1) in fixed 4 KiB blocks with CRC-32 over every
payload. All 94 records pass block-magic, sequence-continuity, per-payload
CRC-32, packet-header and timestamp-continuity checks, with zero FIFO
overflows and zero buffer-full events.

The high-resolution output field is 20 bits wide; its least significant bit is
zero in all 31,799,166 gyroscope words in this dataset, so 19 bits are
significant and the reachable lattice is one eighth of the register LSB. The
register word equals the reference word shifted right by three bits, exactly,
in all 31,799,166 words.

SCOPE OF summary.csv

The table carries configuration read from the record headers and moments
computed from the records themselves. No column is fitted, corrected toward a
model, or compared against a prediction. Phase, dither ratio, added power and
quantiser gain are given in CODEBOOK.md as closed-form expressions over these
columns rather than as columns of their own, so that a user applies them
explicitly.

CHARACTERISTICS A REUSER SHOULD KNOW

A spectral line near 119 Hz is present in the records; its origin has not been
identified, and it aliases to a different frequency and amplitude at each
output rate. Measured amplitudes and variance shares per rate are tabulated in
README.md. The anti-alias and user filter chains correlate neighbouring
samples at every rate, so estimators assuming independence will be optimistic.
Die temperature is logged per record, with excursion and end-to-end drift in
summary.csv.

LICENCE

Records and summary.csv are CC-BY-4.0. The bundled reader read_sdat.py is MIT.
```

---

## Licence **required**

`Creative Commons Attribution 4.0 International` (CC-BY-4.0)

Search the licence box for "Attribution 4.0". Zenodo takes one licence per
record and CC-BY-4.0 is the right one for a dataset; the MIT licence on the
reader is stated in the description and in `LICENSE-CODE.txt`.

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
