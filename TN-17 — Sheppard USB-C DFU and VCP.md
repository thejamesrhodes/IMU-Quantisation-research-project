# TN-17 — Sheppard USB-C Firmware Update and Virtual COM Port

**Version 1.1 — 26 July 2026**
**Status:** stage 1 (composite CDC) verified on hardware. Self-flasher written, awaiting first test.
**Purpose:** remove the ST-LINK from the edit–build–flash loop, so one USB-C cable carries both the diagnostic console and firmware updates.

**Changes from v1.0:** architecture changed from a resident DFU loader to an in-application self-flasher (§3, §7) after stage-1 testing showed the composite CDC path working and made the cost of the loader look disproportionate. DFU run-time interface compiled out (§3.4). Acceptance tests rewritten (§6). Records the stage-1 results.

**Relates to:** TN-16 §7 (USB CDC), §3.10 (regeneration collateral), §8 (RTC and backup registers), open items 17, 19, 20.

---

## Tag legend

| Tag | Meaning |
|---|---|
| **[fact]** | Confirmed against a datasheet, application note, or vendor source in this repository |
| **[measured]** | Directly observed on the Sheppard board |
| **[inference]** | Reasoned from sourced facts; not directly confirmed |
| **[verify]** | Load-bearing and **not** confirmed — check before relying on it |

---

## 1. Two constraints that shape everything

### 1.1 The ROM bootloader is unreachable

**The STM32F72x/F73x ROM system bootloader exposes USB DFU only on the full-speed peripheral (OTG_FS, PA11/PA12).** Sheppard routes USB-C to PB14/PB15 — OTG_HS with the internal HS PHY (TN-16 §1.3; `GMWM STM32.ioc` records `PB14.Mode=Internal_Phy_Device`). PA11 and PA12 are unallocated on the MCU but are not connected to the connector.

[fact] — AN2606 peripheral table for STM32F72xxx/73xxx, corroborated by two ST community threads, one on this exact part with the AN2606 table reproduced.

So "set BOOT0 and jump to `0x1FF00000`" does not work over the fitted connector. Any update path over USB-C has to be written.

For rev-B there is a zero-firmware alternative: route D+/D− to PA11/PA12 and the ROM DFU works with no code at all, at the cost of full-speed only. Worth listing alongside the ICM CLKIN routing of TN-16 §10.3.

### 1.2 Code cannot erase the flash it is executing from

*"During a program/erase operation to the Flash memory, any attempt to read the Flash memory stalls the bus. The read operation proceeds correctly once the program/erase operation has completed."* [fact]

The F723ZE is single-bank, so there is no read-while-write partner bank. Two consequences:

- An erase of a *different* sector is survivable from flash-resident code — the CPU simply stalls until it finishes — but interrupts are dead for the duration, which kills USB.
- An erase of the sector holding the running code is not survivable at all.

**Therefore the erase-and-program loop must execute from SRAM, and the entire image must be buffered before the first byte is erased.** This is the fact that a DFU run-time interface alone does not address, and it is what "stage 2" was really for.

### 1.3 The board cannot be permanently bricked

SWD on PA13/PA14 is never reassigned, there is no watchdog and no low-power mode (TN-16 §3.11). ST-LINK recovery always exists:

```
STM32_Programmer_CLI -c port=SWD mode=UR -e all -w firmware.elf -v -rst
```

The exposure throughout this work is schedule, not hardware.

---

## 2. Requirement, as agreed

> Press build in STM32CubeIDE, have the new firmware land on the board over USB-C, and have the board then behave as an ordinary virtual COM port.

Explicitly out of scope: **debugging**. This is a download path only — no breakpoints, no stepping, no live watch, no SWO. Acceptable because bring-up has been printf-driven throughout (TN-16), and the SWD header stays populated for the hard problems and for recovery.

---

## 3. Architecture

### 3.1 What was chosen, and what was rejected

| Option | Verdict |
|---|---|
| ROM DFU | Impossible on this connector — §1.1 |
| Resident DFU loader at `0x08000000`, app relinked to `0x08010000` | Correct but disproportionate. Separate CubeIDE project, relink, VTOR change, 64 KiB of flash, and it blocks on the unverified sector map. Recovers automatically from a bad flash |
| **Self-flasher inside the application** | **Chosen.** No second image, no relink, no VTOR change, no CubeProgrammer. Roughly a tenth of the work. Does not recover from a bad flash |

The deciding argument: a bad flash needs ST-LINK either way *if you are at the bench*, which is where all firmware iteration happens. The loader's automatic recovery only pays off in the unattended Raspberry Pi window — by which point firmware is frozen, which is precisely when it will not be needed.

### 3.2 The self-flasher

```
  host                                    device
  ----                                    ------
  fw <size> <crc32hex>        ---->       validate size, arm receiver
                              <----       FWREADY <n>
  <size> raw bytes            ---->       memcpy into SRAM staging buffer,
                                          straight from the USB ISR
                              <----       FWRECV <size>
                              <----       FWCRC ok        (zlib CRC-32)
                              <----       FWVEC ok        (SP and reset vector)
                                          probe .RamFunc execution
                              <----       FWPROG
                                          USBD_Stop, __disable_irq,
                                          jump to RAM:
                                            mass erase
                                            program from staging buffer
                                            read-back verify
                                            SYSRESETREQ
  wait for the port to return
```

Four points of design that matter:

**Received bytes bypass the console ring.** `fw_rx_isr()` gets first refusal inside `CDC_Receive_HS` and copies directly into the staging buffer. The console's 256-byte ring cannot absorb back-to-back 512-byte high-speed bulk packets between main-loop iterations. Flow control is inherent: ST's CDC only re-arms the OUT endpoint from the receive callback, so the host is throttled by NAKs.

**Mass erase, not sector erase.** Deliberate — it removes any dependence on the STM32F723ZE sector map, which is *still* unverified against RM0431 (§4). There is nothing else in flash worth preserving. Costs a few seconds per update.

**The RAM routine calls nothing.** Every HAL and non-inline CMSIS function lives in flash. `fw_flash_and_reset()` contains only register writes, inline barriers and loops. It is marked `long_call` because `.RamFunc` at `0x20000000` is 384 MiB from the caller at `0x08000000` and a direct `BL` reaches ±16 MiB — without it the link fails with *relocation truncated to fit*. Reset is written straight to `SCB->AIRCR` rather than calling `NVIC_SystemReset()`, which would almost certainly inline, but "almost" is the wrong word for a function that must not touch flash.

**Execution from `.RamFunc` is probed before anything is erased.** CubeMX places `*(.RamFunc)` inside `.data` at `0x20000000`, which on this part is DTCM. ST shipping that linker script for this exact device is good evidence that the Cortex-M7 will fetch instructions from there [inference], but it is inference. So `fw_task()` calls the routine once in probe mode and checks for a magic return value. If the processor cannot execute there, it faults *before* the erase, with flash intact and a reset all that is needed.

### 3.3 What this cannot do

**The flasher is part of the image it replaces.** An image that is written correctly but does not run takes the flasher with it, and recovery is via ST-LINK. Guards against the failure modes that *are* catchable:

- CRC-32 over the whole image before anything is erased
- initial stack pointer must land in SRAM; reset vector must point into flash with the Thumb bit set
- read-back verification of every word after programming, still from RAM
- size range check, so a typo'd length cannot mass-erase the part

The residual risk is power loss in the few seconds between `FWPROG` and the board reappearing.

### 3.4 DFU run-time interface: compiled out

`SHEPPARD_USB_DFU_RUNTIME` is now `0`. With a self-flasher there is nothing for a DFU interface to talk to — a host issuing `DFU_DETACH` would only reboot the application into itself. The `#if` removes the DFU state machine and its 18 descriptor bytes entirely.

The composite wrapper (`usbd_composite.c`) is **retained**. With DFU off it serves a plain two-interface CDC configuration that carries an IAD: about 180 bytes of flash over the stock class, no runtime cost. Kept because reverting to the stock CDC descriptor would re-risk an enumeration path that is tested and working, and because a resident loader is then one `#define` away. Say the word and it goes.

`boot_ctrl.c` is likewise retained: the failed-boot counter is dormant without a loader, but `boot_ctrl_reset_now()` backs the `reset` command and the backup-register discipline will be wanted by the logger anyway.

---

## 4. Still unverified

**[verify] — the STM32F723ZE flash sector map.** No longer blocking, because mass erase does not need it. It becomes load-bearing again the moment anyone wants sector-selective erase (faster updates), a resident loader, or flash-resident configuration storage. The assumed layout is 4 × 16 KiB + 1 × 64 KiB + 3 × 128 KiB, which matches the DfuSe descriptor `@Internal Flash /0x08000000/04*016Kg,01*064Kg,03*128Kg` published for other 512 KiB parts but has not been checked against RM0431 for this family.

**[inference] — instruction fetch from DTCM at `0x20000000`.** Mitigated by the runtime probe (§3.2), so a wrong inference costs a reset rather than a brick.

**[verify] — RAM budget.** The 160 KiB staging buffer plus everything else must fit in 256 KiB. This fails loudly at link time (*region RAM overflowed*) rather than silently, so it needs no pre-checking — but note the number from the `.map` file, because the logger's ring buffer will want the same memory (TN-16 open item 7).

---

## 5. What is in the tree

New:

| File | Role |
|---|---|
| `Core/Inc/sheppard_config.h` | every compile-time switch, in one place |
| `Core/Inc/fwupdate.h`, `Core/Src/fwupdate.c` | protocol, staging, CRC-32, RAM flasher |
| `Core/Inc/console.h`, `Core/Src/console.c` | CDC-primary console, line assembly, extensible command table |
| `Core/Inc/boot_ctrl.h`, `Core/Src/boot_ctrl.c` | backup-register boot protocol |
| `USB_DEVICE/App/usbd_composite.h/.c` | composite class driver (DFU compiled out) |
| `tools/sheppard_flash.py` | host side; pyserial only |

Modified:

| File | Change | Generated? |
|---|---|---|
| `Core/Src/main.c` | includes, VTOR, console/fw wiring, commands replace the single-character protocol | user code only |
| `USB_DEVICE/App/usb_device.c` | `USBD_CDC` → `USBD_Composite` redirect; device-descriptor patch | user code only |
| `USB_DEVICE/App/usbd_cdc_if.c` | RX routed to `fw_rx_isr()` then the console | user code only |
| `USB_DEVICE/Target/usbd_conf.h` | `USBD_MAX_NUM_INTERFACES` 1 → 2 | **generated — see §8** |

### 5.1 Two edits that deserve explanation

**`#define USBD_CDC USBD_Composite` in `usb_device.c`.** The generated line `USBD_RegisterClass(&hUsbDeviceHS, &USBD_CDC)` sits outside every USER CODE marker and is restored on regeneration. The `#define` lives in `USER CODE BEGIN Includes`, which the preprocessor reaches *after* `usbd_cdc.h` has declared the real object, so it redirects exactly that one reference. Scope is one translation unit.

**Device descriptor patched at runtime.** CubeMX writes `bDeviceClass = 0x02` (Communications). A configuration containing an IAD must report `0xEF / 0x02 / 0x01` instead. With `0x02` a host is not obliged to look for the IAD: Windows declines `usbccgp`, binds `usbser` to interface 0 only, and the COM port opens but moves no bytes. `bcdDevice` is bumped at the same time because Windows caches the driver binding against `VID&PID&REV`.

### 5.2 Behavioural changes

- The single-character CDC protocol is gone. `b` and `T2026-07-26 14:32:05` are now `burst 200` and `time 2026-07-26 14:32:05`. The parser tokenises and range-checks instead of indexing absolute byte positions, which is what silently produced garbage on a short field (TN-16 §8.4).
- The once-per-second `cdc seq=` heartbeat is gone.
- Every `uart_log()` call now reaches CDC and, while `SHEPPARD_CONSOLE_UART_MIRROR` is 1, USART1 as well.
- Characters are echoed, so typing in Tera Term is visible.
- Periodic scan output is suppressed while an image is streaming.

**The UART mirror ships enabled**, contrary to the "opt-in" answer, because TN-16 §3.1 and §7.3 both depend on USART1 being the channel that works when USB does not. Set it to 0 for science builds, where §7.4 requires USB disconnected anyway.

---

## 6. Acceptance

### 6.1 Stage 1 — composite CDC [measured, 26 Jul 2026]

| # | Test | Result |
|---|---|---|
| 1 | Build | pass |
| 2 | USART1 console | pass |
| 3 | Enumeration, composite parent | pass |
| 4 | `help` over the COM port | pass |
| 5 | `ver`, `usb` | pass |
| 6 | `burst 200` | pass |
| 7 | `time …` then `scan` | pass |
| 10 | `dfu` → reset → re-enumerate | pass |

Tests 8, 9 and 11 (descriptor dump, CubeProgrammer DFU detection, `dfu-util -l`) are **withdrawn** — they existed only to characterise the DFU route, which is no longer taken. Test 11 in particular should not be run: `dfu-util` on Windows needs Zadig to bind WinUSB, and picking the wrong interface breaks the working COM port.

### 6.2 Stage 2 — self-flasher

Flash this build over SWD first. Keep the ST-LINK attached for the first attempt.

| # | Test | Pass criterion | If it fails |
|---|---|---|---|
| 1 | Build | links; note `Debug/GMWM.bin` size and the RAM figure from the `.map` | *region RAM overflowed* → reduce `SHEPPARD_FW_STAGE_SIZE` |
| 2 | `help` | `fw` appears in the list | `fw_init()` not called |
| 3 | `fw 100 0` | `FWABORT size-out-of-range` | argument parsing |
| 4–5 | `python tools/sheppard_selftest.py` | 7 of 7 PASS. Covers size-range rejection, bad CRC, correct CRC with a non-firmware payload, and an abandoned transfer, then confirms the board is still running the same build | see below |
| 6 | `python tools/sheppard_flash.py --bin "Debug/GMWM STM32.bin"` | full sequence through `FWPROG`, board reappears, `ver` shows the new build timestamp | |
| 7 | Change `SHEPPARD_BUILD_TAG`, rebuild, reflash over USB | `ver` shows the new tag — proves it really reflashed rather than rebooted | |
| 8 | Unplug/replug, `ver` again | same tag; the write was persistent | |

**Tests 1–3 passed on hardware, 26 Jul 2026.** [measured]

Tests 4–5 are automated by `tools/sheppard_selftest.py`, which cannot erase the
board: every case it exercises is designed to be refused before the erase step.
The CRC check is the one that matters — it is the only thing between a
corrupted transfer and a blank chip. Run it before test 6.

The full operating procedure, including CubeIDE integration and recovery,
is TN-17A.

If test 6 stops after `FWPROG` and the board never returns: the image was written but does not run. Reflash over SWD (§1.3) and report what `ver` said beforehand.

If it faults at `FWABORT ramfunc-probe-failed`: the DTCM inference of §3.2 was wrong. Tell me and I will move `.RamFunc` into SRAM1 with an explicit linker section — the probe exists precisely so this costs a reset rather than the board.

---

## 7. CubeIDE integration

Run → External Tools → External Tools Configurations → new **Program**:

```
Location:          <path to python.exe>
Working directory: ${workspace_loc:/GMWM Software}
Arguments:         ${workspace_loc:/GMWM Software}/tools/sheppard_flash.py
                   --bin ${workspace_loc:/GMWM Software}/Debug/GMWM.bin
```

Requires the `.bin`: Project → Properties → C/C++ Build → Settings → MCU/MPU Post build outputs → **Convert to binary file**.

Bind it to a keyboard shortcut (Preferences → Keys → *Run Last Launched External Tool*), or move the command into a post-build step to flash on every successful build. `pip install pyserial` once.

---

## 8. Post-regeneration checklist

CubeMX restores anything outside USER CODE markers. After any `.ioc` regeneration:

- [ ] `USB_DEVICE/Target/usbd_conf.h` — `USBD_MAX_NUM_INTERFACES` back to `2U`.
      **Reverted on every regeneration so far, without exception. Check first.**
      With `1U` the device enumerates but the CDC data interface is unreachable,
      so the COM port opens and carries nothing
- [ ] `STM32F723ZETX_FLASH.ld` — `_Min_Stack_Size` back to `0x1000`. CubeIDE
      templates the two size lines but leaves the `MEMORY` block and the
      `.dtcm` section alone, so the DTCM/SRAM1 split survives while the stack
      silently shrinks to `0x400`
- [ ] `Core/Src/stm32f7xx_it.c` — `#include "sampler.h"` in `USER CODE BEGIN
      Includes` and `sampler_pendsv();` in `USER CODE BEGIN PendSV_IRQn 0`.
      Both sit inside USER CODE markers so they *should* survive, but losing
      them is silent: the drain chain stalls after its first step and every
      record comes back empty with `reads 0/0` (TN-19 §5)
- [ ] confirm the new source files are still in the build path (`Core/Src`, `USB_DEVICE/App`)
- [ ] confirm `USER CODE BEGIN Includes` in `usb_device.c` still carries the `USBD_CDC` redirect, and `PreTreatment` the descriptor patch
- [ ] confirm `CDC_Receive_HS` still calls `fw_rx_isr()` before `console_rx_feed()`, and still ends with the `SetRxBuffer` / `ReceivePacket` pair
- [ ] `FATFS/App/fatfs.c` — `get_fattime()` body (TN-16 §3.7)
- [ ] `bsp_driver_sd.c` — `#include "main.h"` (TN-16 §3.8)
- [ ] `Core/Src/stm32f7xx_it.c` — the three EXTI handlers (TN-16 §9.1)

This belongs in TN-16 §3.10 as a standing checklist rather than living here.

---

## 9. Items for the TN-16 open list

| Item | Priority | Note |
|---|---|---|
| Stack `_Min_Stack_Size` 0x400 → 0x1000 | **Medium**, raised from Low | already open item 19; the console and flasher add nesting depth |
| RAM budget: 160 KiB staging vs the logger's ring buffer | Medium | both want the same memory; open item 7 sizes the ring |
| Confirm F723ZE flash sector map against RM0431 | Medium, was High | no longer blocking now that mass erase is used |
| rev-B: route USB D+/D− to OTG_FS (PA11/PA12) | Medium | free ROM DFU, trades HS bandwidth |
| Record `SHEPPARD_BUILD_TAG` and `-O` level in every record header | Medium | open item 20; `sheppard_config.h` now makes this one string |
| Decide `SHEPPARD_CONSOLE_UART_MIRROR` for science builds | Low | free noise reduction, TN-16 §7.4 |

---

## 10. Sources

- STMicroelectronics, **AN2606** *STM32 microcontroller system memory boot mode* — bootloader peripheral table for STM32F72xxx/73xxx: <https://www.st.com/resource/en/application_note/an2606-stm32-microcontroller-system-memory-boot-mode-stmicroelectronics.pdf>
- ST Community, *STM32F723 DFU Mode – Questions* — "the system USB DFU bootloader is only available on the FS USB", with the AN2606 table: <https://community.st.com/t5/stm32-mcus-products/stm32f723-dfu-mode-questions/td-p/626583>
- ST Community, *Usage of System Bootloader via USB of STM32F723IEK6* — same conclusion, independent thread: <https://community.st.com/t5/stm32-mcus-embedded-software/usage-of-system-bootloader-via-usb-of-stm32f723iek6/td-p/229253>
- ST Community, *STM32F7 running code from RAM and erasing flash simultaneously* — bus-stall behaviour and the RAM-execution workaround: <https://community.st.com/t5/stm32-mcus-products/stm32f7-running-code-from-ram-and-erasing-flash-simultaneously/td-p/715892>
- STMicroelectronics, **RM0431** *STM32F72xxx and STM32F73xxx reference manual* — embedded flash chapter and flash organisation, **sector table still to be checked**: <https://www.st.com/resource/en/reference_manual/rm0431-stm32f72xxx-and-stm32f73xxx-advanced-armbased-32bit-mcus-stmicroelectronics.pdf>
- Arm, *Cortex-M7 Processor Technical Reference Manual* — TCM interfaces: <https://developer.arm.com/documentation/ddi0489/f/memory-system/tcm-interfaces/tcm-configuration>
- Vendor source in-tree: `Middlewares/ST/STM32_USB_Device_Library` (v2.11-series; `USE_USBD_COMPOSITE` not defined, `USBD_CoreFindIF()` returns 0 unconditionally, so all interface requests reach the registered class)

---

## 11. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 26 Jul 2026 | Initial issue. OTG_FS-only ROM DFU constraint; two-image loader architecture; stage-1 implementation and acceptance procedure |
| 1.1 | 26 Jul 2026 | Stage 1 verified on hardware. **Architecture changed** from a resident DFU loader to an in-application self-flasher after the loader's cost was judged disproportionate to its only advantage (automatic recovery from a bad flash, which pays off only in the unattended window when firmware is frozen anyway). Added §1.2 on the flash bus-stall constraint, which is the real content of the old "stage 2". DFU run-time interface compiled out. Sector-map verification downgraded from blocking to open |
