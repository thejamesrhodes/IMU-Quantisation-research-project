# Sheppard — MEMS rate-register quantisation testbed

Hardware, firmware and analysis for an experiment on quantisation noise in
MEMS gyroscopes that report **rate registers** rather than angle increments.

The central claim under test: rate-register quantisation noise presents at a
$-\tfrac{1}{2}$ Allan deviation slope and is silently absorbed into fitted
angle random walk, rather than appearing as the canonical $-1$ slope
angle-quantisation term of IEEE-952 — which belongs to FOG/RLG
angle-increment architectures. If so, fitted stochastic parameters are
configuration-dependent, and the $\sqrt{\text{ODR}}$ bandwidth-transfer rule
embedded in standard IMU calibration toolchains has never been validated for
current high-ODR parts.

The board is named after **W. F. Sheppard**, whose 1898 paper gave the
$-c^2/12$ correction for the variance of grouped data
([DOI 10.1112/plms/s1-29.1.353](https://doi.org/10.1112/plms/s1-29.1.353)) —
the same $\Delta^2/12$ that the whole experiment turns on.

---

## Hardware

| | |
|---|---|
| MCU | STM32F723ZET6, LQFP144, 32 MHz (deliberately low — see below) |
| Sensors | 2× ICM-42688-P, 1× ISM330DHCX, 1× BMI323, one SPI bus each |
| Storage | microSD on SDMMC2, exFAT |
| Host link | USB-C on OTG_HS with the internal HS PHY |
| Power | 4S NiMH or USB-C |

**The clock rate is a science parameter, not a performance choice.** 32 MHz
minimises digital switching noise into the analog chain. Board noise acts as
dither: excess σ raises ρ and abolishes the effect under study. It must stay
fixed across a campaign or be logged as a treatment variable.

## Repository layout

```
GMWM Software/           STM32CubeIDE firmware project
  Core/Inc, Core/Src       application sources
  USB_DEVICE/              composite CDC device, self-flasher transport
  tools/                   host-side Python
Array Electronics ICM42688P/   KiCad 10 project
TN-*.md                  technical notes
```

## Firmware

Built with STM32CubeIDE. The `.ioc` is the source of truth for the pin map
and peripheral configuration.

Notable modules:

| File | Role |
|---|---|
| `sheppard_config.h` | every compile-time switch, in one place, so one file describes the build that produced a dataset |
| `console.c` | transport-independent console: CDC primary, USART1 mirror, extensible command table |
| `fwupdate.c` | self-flasher — receives a new image over CDC, verifies it, rewrites flash from a routine executing in RAM |
| `boot_ctrl.c` | backup-register boot protocol |
| `usbd_composite.c` | USB class driver wrapping the stock CDC class |

### Flashing without an ST-LINK

The board reflashes itself over the same USB-C cable that carries the
console. See **TN-17A** for the procedure and **TN-17** for why it works this
way — in short, the F72x ROM bootloader's DFU is reachable only on OTG_FS,
which is not routed to the connector.

```
pip install pyserial
python "GMWM Software/tools/sheppard_console.py"
```

`sheppard_console.py` is a GUI that finds the board by USB ID, gives you a
terminal, and flashes it. `sheppard_flash.py` and `sheppard_selftest.py` do
the same jobs from the command line.

**Run the self-test once before trusting the flasher.** It feeds the board
deliberately bad data five ways and confirms each is refused with flash
untouched. Nothing in it can erase the board.

Recovery is always available over SWD:

```
STM32_Programmer_CLI -c port=SWD mode=UR -e all -w "Debug/GMWM STM32.elf" -v -rst
```

## Technical notes

| Note | Subject |
|---|---|
| TN-16 | Firmware bring-up reference — as-built record, failure modes, register maps, measured true ODR |
| TN-17 | USB-C firmware update: design and rationale |
| TN-17A | USB-C firmware update: setup and use |

TN-16 is the one to read first. Its §1.2 bus↔chip-select table and §3
failure-mode list represent most of the time spent getting the board alive.

## Conventions

- Claims in the notes are tagged **[fact]**, **[measured]**, **[inference]**
  or **[verify]**. `[verify]` means load-bearing and not yet confirmed against
  a primary source — treat accordingly.
- SI units. LaTeX for mathematics.
- Campaign data belongs in Zenodo with a DOI, not in this repository.

## Status

Bring-up complete: four IMUs identified and configured, SD/exFAT verified,
cross-vendor physical validation, first noise baseline, USB firmware update
working. Data collection is the next phase.
