# Paired 16-bit and 19-bit output records from two ICM-42688-P MEMS gyroscopes across output-rate and sub-LSB bias-offset sweeps

Version {{VERSION}} · built {{BUILT}} · DOI {{DOI}}

{{N_RECORDS}} static-bench records from two ICM-42688-P MEMS gyroscopes (TDK
InvenSense). The sensors were stationary throughout: the board was clamped
and motionless, no rotation was applied, and no motion or attitude ground truth
is included.

Each record captures the device's 16-bit rate register alongside its extended
high-resolution output channel over the same physical samples, so the two
streams are digitisations of one shared input at resolutions differing by a
factor of eight. Samples are stored as raw integer codes with no scaling or
calibration applied, preserving the output code lattice that calibrated
floating-point datasets discard.

Totals: {{N_SAMPLES}} samples, {{HOURS}} hours, three axes per record.

---

## 1. Contents

| File | |
|---|---|
{{INVENTORY}}
| `summary.csv` | {{N_ROWS}} rows — one per record per axis. Configuration and moments only |
| `CODEBOOK.md` | column definitions, closed-form expressions for derived quantities |
| `read_sdat.py` | standalone reader and verifier; standard library + numpy |
| `MANIFEST-SHA256.txt` | SHA-256 of every file, and of every record inside every bundle |
| `LICENSE-DATA.txt` | CC-BY-4.0, covering the records and `summary.csv` |
| `LICENSE-CODE.txt` | MIT, covering `read_sdat.py` |

## 2. Quickstart

```bash
pip install numpy
unzip icm42688p-phase-sweep.zip -d records/

python read_sdat.py verify records/*.sdat     # CRC and continuity, per record
python read_sdat.py info   records/<one>.sdat # header and achieved rate
python read_sdat.py export records/<one>.sdat -o out.npz
```

`export` writes the decoded integer code arrays `gyro20`, `gyro16`, `accel20`,
`temp_raw`, `tmst_raw`, `tmst_us`, `block_index` and `block_t_us`, together with
`header_json`, so the exported file is self-describing. No scaling is applied;
`sensor.delta_mdps` in each header carries the scale factor for that record.

## 3. What is measured

| | |
|---|---|
| Part | ICM-42688-P (TDK InvenSense), two specimens, one SPI bus each |
| Full-scale range | ±2000 °/s — forced by the high-resolution mode |
| Register LSB | Δ = 61.035 m°/s |
| Reference lattice | Δ′ = Δ/8 = 7.629 m°/s |
| Output data rates | 25, 50, 100, 200, 500, 1000, 8000 Hz |
| Anti-alias filter | `585Hz_default` (87 records), `42Hz_floor` (7 records) |
| Logger | STM32F723ZET6, 32 MHz system clock, 8 MHz SPI, microSD |
| Supply | USB, all records |
| Motion | none — stationary, clamped, no applied rotation |
| Orientation | fixed for the whole campaign |

The system clock was held fixed and low across the campaign as an experimental
control so digital switching noise does not couple into the sensor and act as dither.

## 4. Word length and the 19-bit convention

The high-resolution FIFO field is 20 bits wide. Its least significant bit is
zero in all {{N_WORDS}} gyroscope words in this dataset, so 19 bits are
significant and the reachable lattice is Δ/8. Everything here is quoted on the
19-bit convention. The record headers carry `config.word_bits = 20`, which is
the field width, not the significant word length.

The register word is the reference word truncated by three bits,

```
gyro16 == gyro19 >> 3
```

which holds exactly in all {{N_WORDS}} words.

## 5. Characteristics a reuser should know

**Integrity.** All {{N_RECORDS}} records pass block-magic, sequence-continuity,
per-payload CRC-32, packet-header and timestamp-continuity checks. Zero FIFO
overflows and zero buffer-full events across the set.

A spectral line near 119 Hz is present in the records. Its origin has not
been identified. It aliases differently at each output rate, so it appears at a
different frequency and amplitude in each group. Measured, in units of Δ:

| Nominal ODR | Line frequency | Amplitude | Share of variance |
|---|---|---|---|
| 25 Hz | not detected | — | — |
| 50 Hz | 0–17.9 Hz | ≤ 0.07 Δ | 0–6 % |
| 100 Hz | 17.4–18.0 Hz | 0.18–0.24 Δ | 14–23 % |
| 200 Hz | 83.2–84.0 Hz | 0.06–0.76 Δ | 2–62 % |
| 500 Hz | 118.9–119.0 Hz | 0.83–1.15 Δ | 42–63 % |
| 1000 Hz | 118.4–119.4 Hz | 0.09–1.21 Δ | 5–52 % |
| 8000 Hz | 118.9–119.2 Hz | 0.84–1.21 Δ | 23–39 % |

Anyone treating these records as broadband noise should check the spectrum for
their rate first.

**Correlation between samples.** The anti-alias and user filter chains
correlate neighbouring samples at every rate. Estimators assuming independence
will be optimistic.

**Anti-alias filter records.** The seven `42Hz_floor` records vary the filter at
output rates of 50, 200 and 1000 Hz, each paired against default-filter records
at the same rate. Changing that filter also changes the line amplitude above and
the correlation between samples, so the setting is not a clean single-variable
axis. They are included for completeness.

**Temperature.** The die temperature is logged. `temp_span_mK` and
`temp_drift_mK` in `summary.csv` give the excursion and the end-to-end drift
per record; apply whatever criterion suits your purpose.

## 6. Record format

```
offset 0              4096 B  UTF-8 JSON header, space-padded
offset 4096 + 4096k           fixed 4 KiB blocks
  block                       32 B header + 4000 B payload + 64 B pad
```

Payload is the vendor's 20-byte FIFO Packet 4 verbatim (DS-000347 Rev. 1.6
§6.1), CRC-32 over every payload. The JSON header carries the firmware version
and build tag, board UID, clock tree, sensor part and slot, the full sensor
configuration and a verbatim readback of the configuration registers, so each
record is self-describing down to the register contents that produced it.

Filenames are `r<id>_<label>_<odr>.sdat`. `CODEBOOK.md` §4 maps labels to what
was varied.

## 7. Provenance

`summary.csv` is computed from the records in this deposit and from nothing
else. The bundled `read_sdat.py` is the reader used to produce it.

`MANIFEST-SHA256.txt` lists both the files as uploaded and each record inside
each bundle, so an unpacked archive can be checked record by record.

{{HEADER_NOTE}}

## 8. Citation

> Rhodes, J. ({{BUILT}}). *Paired 16-bit and 19-bit output records from two
> ICM-42688-P MEMS gyroscopes across output-rate and sub-LSB bias-offset
> sweeps* (Version {{VERSION}}) [Data set]. Zenodo.
> <https://doi.org/{{DOI}}>

## 9. Licence

Records and `summary.csv`: CC-BY-4.0 (`LICENSE-DATA.txt`).
`read_sdat.py`: MIT (`LICENSE-CODE.txt`).
