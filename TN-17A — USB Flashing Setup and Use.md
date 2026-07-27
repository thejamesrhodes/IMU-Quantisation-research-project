# TN-17A — USB Flashing: Setup and Use

**Version 1.0 — 26 July 2026**
**Companion to TN-17.** TN-17 explains *why* it works this way. This one is the procedure.

Written to be followed start to finish. Sections 1–3 are done once. Section 6 is what you do every day after that.

---

## 0. What you end up with

Right now, changing one line of firmware means: build, plug in the ST-LINK, flash, unplug. After this, it means: build, press one button, done — over the same USB-C cable that already carries the console.

Two things it does **not** do:

- **No debugging.** No breakpoints, no stepping, no watching variables live. If you need those, the ST-LINK still works exactly as it does now — nothing here stops you plugging it in.
- **No recovery.** If you flash firmware that builds fine but hangs on startup, the thing that receives the next update went with it. You get it back with the ST-LINK (§8). Budget for this happening occasionally; it is the price of not having a separate bootloader.

---

## 1. One-time setup

### 1.1 Python and pyserial

You already use Python for the analysis scripts, so this is one command. Open a Command Prompt:

```
python --version
```

You should see `Python 3.something`. Then:

```
pip install pyserial
```

`pyserial` is the library that lets Python open a COM port. That is the only dependency — no STM32CubeProgrammer, no DFU driver, no Zadig.

While you are here, note where Python actually lives, because CubeIDE needs the full path:

```
where python
```

Copy that path somewhere. It looks something like
`C:\Users\James\AppData\Local\Programs\Python\Python312\python.exe`.

### 1.2 Make CubeIDE produce a .bin file

CubeIDE builds an `.elf` by default. The `.elf` is a container with debug symbols and section headers; what actually gets written to flash is the raw bytes, which is the `.bin`. You need to switch that on.

1. Right-click **GMWM STM32** in Project Explorer → **Properties**
2. **C/C++ Build** → **Settings**
3. Tab: **MCU/MPU Post build outputs** (older versions call it **MCU Post build outputs**)
4. Tick **Convert to binary file (-O binary)**
5. **Apply and Close**, then build the project

Check it worked — this file should now exist:

```
C:\IMU Research Project\GMWM Software\Debug\GMWM STM32.bin
```

> **Note the space in the filename.** The Eclipse project is called `GMWM STM32` even though the folder is `GMWM Software`, and the artifact is named after the project. Every path containing that space has to be inside double quotes on a command line. This is the single most common reason the commands below fail.

Note the file size while you are looking at it. Anything up to 160 KiB is fine; the firmware refuses larger images rather than overflowing its buffer.

### 1.3 Find the board

Plug the board in with a **data** USB-C cable. A charge-only cable enumerates nothing and looks exactly like a dead board — if anything below fails at the first step, try a different cable before anything else.

In Device Manager, under **Ports (COM & LPT)**, you should see a COM port. You do not need to remember the number: the scripts find the board by its USB vendor and product ID, so it does not matter if Windows renumbers it.

> **Close Tera Term before running any script.** Windows lets only one program open a COM port at a time. If Tera Term has it, the script cannot, and the error will not obviously say so.

---

## 2. Prove the safety checks work — do this before anything else

Before trusting the board to overwrite itself, confirm it refuses to do so when it should. There is a script for this, so you are not hand-typing binary into a terminal.

Flash the current firmware over SWD as normal, then:

```
cd "C:\IMU Research Project\GMWM Software"
python tools\sheppard_selftest.py
```

It feeds the board bad data five ways and checks each one is refused. **Nothing in it can erase the board** — every case is designed to be rejected before the erase step, and the last check confirms the board is still running the firmware it started with.

Expected ending:

```
==============================================================
  PASS  board responds to `ver`                 sheppard 0.1.0 (usb-stage1)  built ...
  PASS  tiny image refused                      FWABORT size-out-of-range 100 ...
  PASS  oversize image refused                  FWABORT size-out-of-range 999999 ...
  PASS  bad CRC refused                         FWCRC bad got=... want=deadbeef
  PASS  junk payload refused by vector check    FWVEC bad: initial SP not in SRAM
  PASS  abandoned transfer times out            FWABORT timeout after 100 of 4096 bytes
  PASS  flash untouched, board alive            sheppard 0.1.0 (usb-stage1)  built ...
==============================================================
All 7 checks passed. The safety gates work; sheppard_flash.py is safe to use.
```

Test 3 is the one that matters. A CRC-32 is a checksum over the whole image; if a single bit arrives wrong the number will not match, and the board refuses to erase anything. That check is all that stands between a corrupted transfer and a blank chip. If it does not pass, stop and tell me.

Test 5 takes about seven seconds of apparent nothing — that is the receive timeout expiring, which is the correct behaviour.

---

## 3. Set up the CubeIDE button

Now make it a one-click operation.

1. Menu **Run** → **External Tools** → **External Tools Configurations...**
2. Select **Program** in the left tree, click the **New Configuration** icon (blank page with a `+`)
3. Fill in:

**Name:**
```
Flash over USB
```

**Location:** (your Python path from §1.1)
```
C:\Users\James\AppData\Local\Programs\Python\Python312\python.exe
```

**Working Directory:**
```
C:\IMU Research Project\GMWM Software
```

**Arguments:** (all on one line — note both sets of quotes)
```
"C:\IMU Research Project\GMWM Software\tools\sheppard_flash.py" --bin "C:\IMU Research Project\GMWM Software\Debug\GMWM STM32.bin"
```

4. **Build** tab → tick **Build before launch**, and below it select **GMWM STM32** as the project to build.

   > This makes the one button mean *build then flash*, which is what you actually want. Without it the button flashes whatever was last compiled, so editing a file and pressing flash appears to succeed while changing nothing — the board really does rewrite its flash, with the old image. That failure reports success at every step and is maddening to diagnose. As a second line of defence, `sheppard_flash.py` now refuses to flash a `.bin` that is older than your sources unless you pass `--force`.

5. **Common** tab → tick **External Tools** under *Display in favorites menu*. This puts it in the toolbar dropdown.
6. **Apply**, then **Close**.

Optional but worth it — a keyboard shortcut. **Window → Preferences → General → Keys**, search for *Run Last Launched External Tool*, and bind it to something free like `Ctrl+Alt+U`.

---

## 4. First real flash

Keep the ST-LINK plugged in for this one. Not because it is needed, but so recovery is instant if something is wrong.

Build the project, then either press the new button or run:

```
cd "C:\IMU Research Project\GMWM Software"
python tools\sheppard_flash.py --bin "Debug\GMWM STM32.bin"
```

What you should see, and what each line means:

```
port      : COM7  (0483:5740)                 <- found the board by USB ID
image     : Debug\GMWM STM32.bin  73412 bytes  crc32=9f3c11ae
built     : 2026-07-27 00:41:12               <- when that .bin was produced
    -> fw 73412 9f3c11ae                      <- telling the board what is coming
    <- FWREADY 73412                          <- board has cleared space, send it
    sent 73412 bytes in 0.2 s
    <- FWRECV 73412                           <- got exactly the right number of bytes
    <- FWCRC ok                               <- every bit arrived intact
    <- FWVEC ok                               <- it looks like a real firmware image
    <- FWPROG                                 <- last thing you will hear; committed
waiting for the board to come back...
board is back on COM7
now running: sheppard 0.1.1 (usb-stage1)  built Jul 27 2026 00:41:10
```

That last line is the one to read. It is the board telling you what it is
*actually* executing, not the script telling you it thinks it succeeded.
Check the version and the timestamp match what you just built.

Between `FWPROG` and `board is back` the chip erases its entire flash and rewrites it from the copy held in RAM. That takes a few seconds and the USB device disappears while it happens — Windows may make its disconnect noise. That is normal.

**This is the only window in which pulling the plug does real damage.** A few seconds, once per flash. If it happens, §8.

### What each protocol line actually means

| Line | Meaning |
|---|---|
| `FWREADY <n>` | Board accepted the size, cleared its buffer, is waiting for `n` bytes |
| `FWRECV <n>` | Received `n` bytes and stopped |
| `FWCRC ok` | Checksum matches — the transfer was not corrupted |
| `FWVEC ok` | First eight bytes look like a valid ARM vector table |
| `FWPROG` | Committed. Erasing and rewriting now |
| `FWABORT <reason>` | Refused before doing anything. **Flash is untouched** |
| `FWCRC bad` / `FWVEC bad` | Refused. **Flash is untouched** |
| `FWFAIL FLASH_SR=...` | Failed *during* writing. Flash is damaged; recover over SWD (§8) |

Anything beginning `FWABORT`, `FWCRC bad` or `FWVEC bad` is safe — the board has not touched its flash and is still running the old firmware. Only `FWFAIL`, and a board that never comes back, need the ST-LINK.

---

## 5. Prove it really reflashed

Worth confirming once that the new firmware actually landed, rather than the board simply having rebooted into the old one.

1. Open `Core/Inc/sheppard_config.h`
2. Change the build tag, e.g.

```c
#define SHEPPARD_BUILD_TAG          "usb-test-1"
```

3. Build, then flash over USB
4. Open Tera Term on the COM port and type `ver`

You should see `usb-test-1` in the output, along with a build timestamp from a minute ago. That is proof it worked.

Then unplug the board completely, plug it back in, and type `ver` again. Same tag means the write was persistent and not something living in RAM.

---

## 5A. The companion app (easier than everything above)

`tools/sheppard_console.py` does the terminal and the flashing in one window,
so CubeIDE only has to build.

```
cd "C:\IMU Research Project\GMWM Software"
python tools\sheppard_console.py
```

Make a desktop shortcut to that and you never type it again. (Right-click the
desktop → New → Shortcut, and for the target put your Python path followed by
the script path, both in quotes.)

**Connection**

- Finds the board by USB ID, never by COM number, and does not care when
  Windows renumbers the ports.
- Reconnects on its own. The board disappears every time you flash it or type
  `reset`; the app just picks it back up.
- Status dot: amber while looking, green when connected, red if another
  program already holds the port.

**Firmware** (sidebar)

- **Flash over USB** — stale-image guard, progress bar, and a read-back of
  the version afterwards, so the last thing you see is the board saying what
  it is actually running.
- **Run safety self-test** — the same five checks as
  `sheppard_selftest.py`, run through the app's own connection. Nothing in it
  can erase the board.
- The image is found automatically: newest `.bin` under `Debug\` or
  `Release\`. Its name, size and build time are shown under the buttons, so a
  stale build is visible before you press anything. **File → Select firmware
  image** overrides it.

**Terminal** (View menu)

- Timestamps per line, hex view, echo of sent commands, auto-scroll
- Font size up/down
- Find box under the terminal highlights every match
- **File → Start log file** appends everything received — the Tera Term
  logging you were using
- **File → Save terminal buffer** dumps what is on screen
- **File → Send file (raw)** pushes a file's bytes straight at the board
- Up arrow recalls previous commands

**Command buttons**

Edit them with the *Edit buttons...* button. One per line, `label = command`:

```
rate 10m = rate 600
scan     = scan
```

Everything — window size, image path, macros, view options — is remembered in
`~\.sheppard_console.json`. Delete that file to start clean.

> Only one program can hold a COM port. With this app open, Tera Term and the
> command-line scripts will all fail to connect. That is expected; the app
> replaces them. Close it if you want to use them.

If the app cannot work out where the project is, use **File → Set project
folder** and point it at the folder containing `Core\`. It remembers.

---

## 6. Daily use

With the app:

```
edit in CubeIDE  ->  Ctrl+B (build)  ->  press Flash  ->  ~3 s  ->  running
```

Or from the command line / CubeIDE button:

```
edit code  ->  Ctrl+B (build)  ->  Ctrl+Alt+U (flash)  ->  ~3 s  ->  running
```

The ST-LINK stays in the drawer unless you need breakpoints or recovery.

Two habits worth keeping:

- **Close Tera Term before flashing, reopen after.** The COM port is exclusive. The script will report that it cannot find the board, which is misleading.
- **Bump `SHEPPARD_BUILD_TAG` when the build changes in a way that could affect data.** It appears in `ver` and will go into every record header, which is how you answer "which firmware produced this dataset?" six months from now.

### Console commands

Type `help` on the COM port for the current list.

| Command | Does |
|---|---|
| `help` | list commands |
| `ver` | firmware version, build tag, timestamp, clock frequencies |
| `usb` | USB connection state |
| `scan` | identify all four IMUs and dump one sample from each |
| `rate [s]` | count data-ready interrupts over a window and report true ODR |
| `sd` | mount the card and run the filesystem test |
| `burst <n>` | USB throughput test |
| `time YYYY-MM-DD HH:MM:SS` | set the real-time clock |
| `reset` | reboot |
| `fw <size> <crc>` | start a firmware transfer (the script uses this; you never type it) |

`rate` blocks while it measures — deliberately, because it wants a quiet window with nothing else on the SPI buses. Default ten seconds, any key aborts. Use `rate 600` when you want a number good enough to put in a record header.

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Flashes fine, but `ver` shows the **old** version or build time | The `.bin` was never rebuilt. Everything reports success because the board genuinely did rewrite its flash — with the old image | Build the project, then flash. The script now refuses a `.bin` older than your sources; if you see that error, that is what happened. Tick *Build before launch* (§3 step 4) so it cannot recur |
| `... is N min older than your sources` | Same thing, caught before flashing | Build first. `--force` overrides if you really mean it |
| `no Sheppard virtual COM port found` | Tera Term has the port | Close it |
| Same, with Tera Term closed | Charge-only cable | Try a different USB-C cable **first**, before anything else |
| Same, cable known good | Board not running, or USB not enumerated | Check the LEDs; reflash over SWD |
| `image not found` | `.bin` output not enabled, or path typo | §1.2, and check the quotes around the space in `GMWM STM32.bin` |
| `no FWREADY` | Board is running firmware older than the self-flasher | Flash once over SWD to get the current build on |
| `FWABORT size-out-of-range` | Image bigger than 160 KiB | Raise `SHEPPARD_FW_STAGE_SIZE` in `sheppard_config.h`, or check you are not passing the `.elf` by mistake |
| `FWCRC bad` | Corrupted transfer | Run it again. If it repeats, try a different cable or USB port |
| `FWVEC bad` | The file is not a firmware image | You almost certainly passed the `.elf` instead of the `.bin` |
| `FWABORT ramfunc-probe-failed` | The processor cannot execute the flashing routine from where the linker put it | Tell me — this is a known open assumption in TN-17 §3.2 and the fix is a linker change. Flash is untouched |
| Stops after `FWPROG`, never returns | Written but does not run | §8. Tell me what `ver` said beforehand |
| `FWFAIL FLASH_SR=...` | Hardware error during writing | §8, and send me the number |
| Windows disconnect noise during flash | Normal — the device really does disappear | Ignore |

---

## 8. Recovery over SWD

Always available. SWD is on PA13/PA14 and is never reassigned, there is no watchdog and no low-power mode, so the board can always be reached with the ST-LINK.

Easiest route: plug in the ST-LINK and press the normal **Run** button in CubeIDE. That is all.

If CubeIDE will not connect, use the command line — the important part is `mode=UR` (connect under reset), which is the fix for *"Unable to get core ID"* per TN-16 §3.11:

```
STM32_Programmer_CLI -c port=SWD mode=UR -e all -w "C:\IMU Research Project\GMWM Software\Debug\GMWM STM32.elf" -v -rst
```

`STM32_Programmer_CLI` lives under your CubeIDE installation, in a folder named something like
`plugins\com.st.stm32cube.ide.mcu.externaltools.cubeprogrammer...\tools\bin`.
Search for the filename if you cannot find it.

Note this recovery command takes the **`.elf`**, not the `.bin` — the elf carries its own load addresses. The `.bin` is only for the USB path, which is told separately where to put it.

---

## 9. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 26 Jul 2026 | Initial issue, after stage-2 tests 1–3 passed on hardware. Adds `tools/sheppard_selftest.py` so the negative tests are automated rather than hand-driven |
