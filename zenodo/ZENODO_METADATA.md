# Zenodo metadata — paste-ready

Everything below goes into the Zenodo deposit form. Fields marked **required**
are the ones with a red star.

---

## Resource type **required**

`Dataset`

---

## Title **required**

```
Static-bench gyroscope records for rate-register quantisation analysis: paired 16-bit register and 19-bit FIFO streams from two ICM-42688-P specimens
```

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

Zenodo's description box is rich text. Paste this; the headings will carry
across.

```
94 records from two ICM-42688-P MEMS gyroscopes (TDK InvenSense) on a static
bench. Each record captures the device's standard 16-bit rate register
alongside its extended high-resolution FIFO channel over the same physical
samples, so the two streams are digitisations of one shared input at
resolutions differing by a factor of eight. 10,599,722 FIFO samples, 9.43
hours of logging, three axes per record.

CONTENTS

Records are supplied as four ZIP bundles grouped by what was varied: a phase
sweep of the device's user-offset trim register (50 records), an output-data-
rate sweep spanning 25 Hz to 8 kHz (14 records), trim-register calibration
ladders (22 records), and anti-alias filter variation (8 records). Also
included: summary.csv, giving per-record per-axis configuration and moments;
a standalone reader and verifier; a codebook defining every column and giving
closed-form expressions for the derived quantities; and a SHA-256 manifest
covering both the uploaded files and each record inside each bundle.

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

The high-resolution FIFO field is 20 bits wide; its least significant bit is
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

Search the licence box for "Attribution 4.0". The MIT licence on the reader is
stated in the description and in `LICENSE-CODE.txt`; Zenodo takes one licence
per record and CC-BY-4.0 is the right one for a dataset.

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

Add one at a time:

```
MEMS gyroscope
quantisation noise
Allan variance
angle random walk
inertial sensor calibration
ICM-42688-P
truncating quantiser
dither ratio
sensor characterisation
inertial measurement unit
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
read_sdat.py
sheppard-aaf-variation.zip
sheppard-odr-sweep.zip
sheppard-offset-calibration.zip
sheppard-phase-sweep.zip
summary.csv
```

Set the default preview file to `README.md` if Zenodo offers the choice.

---

## Visibility

`Public`. Do not tick "Apply an embargo".
