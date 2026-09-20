# Sheppard — a MEMS rate-gyroscope quantisation testbed

Hardware, firmware and host-side analysis for characterising quantisation in
MEMS gyroscopes that output a rate register rather than angle increments.

The instrument captures a gyroscope's standard 16-bit rate register alongside
its extended high-resolution FIFO channel over the same physical samples, so
the two streams are digitisations of one shared input and the finer channel can
serve as a reference for the coarser one. Records are written to SD in a
self-describing binary format and reduced by the Python tools in
`GMWM Software/tools/`.

The board is named after W. F. Sheppard, whose 1898 paper gave the $-c^2/12$
correction for the variance of grouped data
([DOI](https://doi.org/10.1112/plms/s1-29.1.353)).

## Data

The measurement records are not in this repository. They are archived as a
citable dataset:

> *Static-bench gyroscope records for rate-register quantisation analysis.*
> Zenodo. DOI: **(pending)**

`zenodo/` holds the build script and templates that assemble that deposit from
a local record directory. See `zenodo/RELEASE.md`.

## Hardware

| | |
|---|---|
| MCU | STM32F723ZET6, 32 MHz |
| Sensors | 2× ICM-42688-P, 1× ISM330DHCX, 1× BMI323, one SPI bus each |
| Storage | microSD on SDMMC2, exFAT |
| Host link | USB-C on OTG_HS, internal HS PHY |
| Power | 4S NiMH or USB-C |

The 32 MHz system clock is an experimental control, not a performance choice.
Digital switching noise acts as dither on the quantity under study, so clock
rates are held fixed across a campaign or logged as a treatment variable.

## Layout

```
GMWM Software/                 STM32CubeIDE firmware project
  Core/                          application sources
  tools/                         host-side Python (console, analysis, figures)
Array Electronics ICM42688P/   KiCad 10 project
zenodo/                        dataset deposit build system
```

## Running it

```
pip install pyserial numpy matplotlib
python "GMWM Software/tools/sheppard_console.py"
```

The console is a GUI with five tabs: a terminal, an SD card browser, a campaign
plan editor, an analysis runner, and a figure viewer. It finds the board by USB
ID rather than COM port and reconnects on its own when the board resets.

Everything it does is also available from the command line, and the panel prints
the exact command before it runs it, so a result in the GUI and a result in a
terminal are the same result.

```
python analyse.py summary <record-dir> -o summary.csv --fast
python figures.py summary.csv -o <figure-dir>
python sdat.py verify <record-dir>/*.sdat
```

## Record format

Each `.sdat` file opens with a 4 KiB UTF-8 JSON header carrying the firmware
version and build tag, board UID, clock tree, sensor part and slot, the full
sensor configuration and a verbatim readback of the configuration registers.
The payload is fixed 4 KiB blocks, each a 32-byte header plus the vendor's
20-byte FIFO packets, with CRC-32 over every payload.

`sdat.py` reads and verifies the format and depends only on the standard library
and numpy. It is documented in the dataset deposit, which ships a standalone
copy so the records can be read without this repository.

## Flashing without an ST-LINK

The board reflashes itself over the same USB-C cable that carries the console.

Run `sheppard_selftest.py` once before trusting the flasher. It feeds the board
bad data five ways and checks each one is refused with flash untouched. Nothing
in it can erase the board.

SWD recovery is always there:

```
STM32_Programmer_CLI -c port=SWD mode=UR -e all -w "Debug/GMWM STM32.elf" -v -rst
```

## Conventions

SI units throughout. The gyroscope's high-resolution FIFO field is 20 bits
wide, of which 19 are significant for the gyroscope at ±2000 °/s full scale —
the field's least significant bit is always zero. All resolutions in this
repository and in the dataset are quoted on the 19-bit convention, so the
reference lattice step is $\Delta' = \Delta/8$ and the register word is
`gyro19 >> 3`.

## Licence

MIT — see `LICENSE`. The dataset is licensed separately under CC-BY-4.0.
