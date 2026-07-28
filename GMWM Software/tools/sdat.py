#!/usr/bin/env python3
"""
sdat.py -- reader and verifier for Sheppard .sdat records.

The .sdat file is the archival artefact of this project: everything published
must be re-derivable from it by someone who has only the file and this reader.
So this module does three things, in order of importance:

  1. VERIFY.  Refuse to hand back data it cannot vouch for.  Block magic,
     sequence continuity, CRC-32 over every payload, packet header sanity and
     timestamp continuity are all checked, and the result is reported as a
     pass/fail per record rather than buried in a warning.

  2. DECODE.  Turn the vendor's verbatim 20-byte FIFO packets into integer
     codes.  No scaling is applied to the stored arrays -- TN-06 v1.2 calls raw
     integer codes "the single most important firmware constraint in the
     project", and the same applies on the way back out.  Physical units are
     offered as a separate, explicit step.

  3. MEASURE.  Report the two independent clocks (board TIM2 against the
     sensor's own TMST) and the achieved sample rate, because a record whose
     rate is not what the header claims is not usable evidence.

LAYOUT (record.h)
    offset 0            4096 B   UTF-8 JSON header, space-padded
    offset 4096 + 4096k          fixed 4 KiB blocks
    block               32 B header + 4000 B payload + 64 B pad

PACKET 4, 20 bytes, DS-000347 Rev 1.6 section 6.1
    0        FIFO header
    1..6     accel X/Y/Z, bits [19:4], big-endian signed 16
    7..12    gyro  X/Y/Z, bits [19:4], big-endian signed 16
    13..14   temperature, signed 16
    15..16   TMST, unsigned 16
    17..19   low nibbles: byte17 = AX[3:0]<<4 | GX[3:0], and so on for Y, Z

    The 16-bit gyro word that this project compares against is bytes 7..8 taken
    as-is.  TN-19 section 1 established that the 16-bit UI register is bits
    [19:4] of the 20-bit fine word -- a TRUNCATION toward negative infinity,
    not a rounder -- so the comparison word needs no arithmetic at all.

USAGE
    python sdat.py verify  FILE [FILE ...]
    python sdat.py info    FILE
    python sdat.py export  FILE -o OUT.npz
    python sdat.py rate    FILE
    python sdat.py selftest

numpy is required for `export` and for the decoded arrays.  `verify` and `info`
work without it, so a record can always be checked for integrity on a machine
with nothing installed.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import zlib
from dataclasses import dataclass, field
from typing import Iterator

try:
    import numpy as np
except ImportError:                                    # pragma: no cover
    np = None

# --- format constants, mirroring record.h ---------------------------------

HEADER_BYTES = 4096
BLOCK_BYTES = 4096
BLKHDR_BYTES = 32
PACKET_BYTES = 20
MAX_PACKETS = 200
PAYLOAD_BYTES = MAX_PACKETS * PACKET_BYTES             # 4000

BLOCK_MAGIC = 0x4B4C4253                               # 'SBLK'

F_FIFO_OVERFLOW = 1 << 0
F_RING_OVERFLOW = 1 << 1
F_BUS_FAULT = 1 << 2
F_PARTIAL = 1 << 3
F_THERMAL_GATE = 1 << 4

FLAG_NAMES = {
    F_FIFO_OVERFLOW: "fifo_overflow",
    F_RING_OVERFLOW: "ring_overflow",
    F_BUS_FAULT: "bus_fault",
    F_PARTIAL: "partial",
    F_THERMAL_GATE: "thermal_gate",
}

# struct format for sdat_block_hdr_t: packed, little-endian.
_BLKHDR = struct.Struct("<II Q HHHH HH I")
assert _BLKHDR.size == BLKHDR_BYTES, _BLKHDR.size

# Scaling.  Kept here rather than applied on load; see the module docstring.
GYRO_LSB_PER_DPS_HIRES = 131.072                       # 20-bit, +/-2000 dps
GYRO_LSB_PER_DPS_UI = 16.384                           # 16-bit
TEMP_LSB_PER_C = 132.48                                # DS section 14.9
TEMP_OFFSET_C = 25.0


# ==========================================================================
# Block-level structures
# ==========================================================================

@dataclass
class BlockHeader:
    magic: int
    seq: int
    t_us: int
    n_packets: int
    fifo_bytes: int
    flags: int
    temp_raw: int
    overruns: int
    faults: int
    crc32: int

    @property
    def flag_names(self) -> list[str]:
        return [n for bit, n in FLAG_NAMES.items() if self.flags & bit]


@dataclass
class Problem:
    """One verification failure.  Kept as data, not raised, so that a single
    bad block does not hide the rest of the record."""
    block: int
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"block {self.block}: {self.kind}: {self.detail}"


@dataclass
class VerifyResult:
    path: str
    header: dict
    n_blocks: int = 0
    n_packets: int = 0
    problems: list[Problem] = field(default_factory=list)
    flags_seen: int = 0
    fifo_peak: int = 0
    t_first_us: int = 0
    t_last_us: int = 0
    last_block_packets: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def f_board_hz(self) -> float:
        """Sample rate against the board's TIM2.

        A block's t_us is the trigger of the read that contributed its FIRST
        packet, so the two anchors available here are t_1 (block 0) and t_j
        (the last block).  With reads r_1..r_M delivering k_i packets that
        accumulated over (t_{i-1}, t_i], the samples falling strictly inside
        (t_1, t_j] are

            sum_{i=2..j} k_i  =  (N - N_last)  -  k_1 + k_j

        where N_last is the packet count of the last block.  Reads never
        straddle a block -- storage_fill_ptr commits early instead -- so the
        last block holds exactly reads r_j..r_M and the identity is exact.
        The residual k_j - k_1 is zero whenever the per-read packet count is
        steady, which it is once the FIFO reaches its working point, and is
        bounded by one watermark otherwise.

        Subtracting the FIRST block's packets instead is wrong by a whole
        block: at ODR 100 that read 91.98 Hz against a true 101.08 Hz.
        """
        span = self.t_last_us - self.t_first_us
        n = self.n_packets - self.last_block_packets
        if span <= 0 or n <= 0:
            return float("nan")
        return n * 1e6 / span


def _parse_block_header(raw: bytes) -> BlockHeader:
    return BlockHeader(*_BLKHDR.unpack(raw))


def read_header(path: str) -> dict:
    """Parse the 4 KiB JSON header.  Raises ValueError if it is not valid
    JSON, which is the correct behaviour: a record whose provenance block
    cannot be read is not a record."""
    with open(path, "rb") as f:
        raw = f.read(HEADER_BYTES)
    if len(raw) < HEADER_BYTES:
        raise ValueError(f"{path}: shorter than one header ({len(raw)} B)")
    text = raw.decode("utf-8", errors="replace").rstrip(" \t\r\n\0")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: header is not valid JSON: {e}") from None


def iter_blocks(path: str) -> Iterator[tuple[int, BlockHeader, bytes]]:
    """Yield (index, header, payload) for each 4 KiB block after the header.

    Payload is the full 4000 bytes the CRC covers, not just the used part;
    callers slice to n_packets themselves.
    """
    with open(path, "rb") as f:
        f.seek(HEADER_BYTES)
        idx = 0
        while True:
            blk = f.read(BLOCK_BYTES)
            if not blk:
                return
            if len(blk) < BLOCK_BYTES:
                # A torn final block: report by yielding nothing further.  The
                # verifier notices via the file-size check.
                return
            hdr = _parse_block_header(blk[:BLKHDR_BYTES])
            yield idx, hdr, blk[BLKHDR_BYTES:BLKHDR_BYTES + PAYLOAD_BYTES]
            idx += 1


# ==========================================================================
# Verification
# ==========================================================================

def verify(path: str, check_crc: bool = True,
           max_problems: int = 200) -> VerifyResult:
    """Full integrity pass.  Does not require numpy."""
    hdr = read_header(path)
    res = VerifyResult(path=path, header=hdr)

    size = os.path.getsize(path)
    body = size - HEADER_BYTES
    if body < 0:
        res.problems.append(Problem(-1, "truncated", "no data blocks"))
        return res
    if body % BLOCK_BYTES:
        res.problems.append(Problem(
            -1, "truncated",
            f"{body} B of blocks is not a multiple of {BLOCK_BYTES}; "
            f"final block is {body % BLOCK_BYTES} B and was dropped"))

    expect_seq = None
    prev_t = None

    for idx, bh, payload in iter_blocks(path):
        res.n_blocks += 1

        if bh.magic != BLOCK_MAGIC:
            res.problems.append(Problem(
                idx, "magic", f"0x{bh.magic:08X} != 0x{BLOCK_MAGIC:08X}"))
            if len(res.problems) >= max_problems:
                break
            continue

        # Sequence.  A gap here is a lost block: not recoverable, and not the
        # same thing as a sample gap, so it is reported separately.
        if expect_seq is not None and bh.seq != expect_seq:
            res.problems.append(Problem(
                idx, "sequence",
                f"seq {bh.seq}, expected {expect_seq} "
                f"({bh.seq - expect_seq} block(s) missing)"))
        expect_seq = bh.seq + 1

        if not (0 < bh.n_packets <= MAX_PACKETS):
            res.problems.append(Problem(
                idx, "n_packets", f"{bh.n_packets} outside 1..{MAX_PACKETS}"))
            if len(res.problems) >= max_problems:
                break
            continue

        if check_crc:
            got = zlib.crc32(payload) & 0xFFFFFFFF
            if got != bh.crc32:
                res.problems.append(Problem(
                    idx, "crc", f"computed 0x{got:08X}, stored 0x{bh.crc32:08X}"))

        # Timestamps must advance.  Equal is allowed only in the pathological
        # case of two reads inside one microsecond, which TIM2 cannot resolve.
        if prev_t is not None and bh.t_us < prev_t:
            res.problems.append(Problem(
                idx, "time", f"t_us {bh.t_us} < previous {prev_t}"))
        prev_t = bh.t_us

        # Packet headers.  Bit 7 of the FIFO header byte is HEADER_MSG, set
        # when the FIFO was empty -- a packet with it set is padding that
        # should never have been written, so its presence means the drain read
        # past the end of the data.
        used = payload[:bh.n_packets * PACKET_BYTES]
        for p in range(bh.n_packets):
            h = used[p * PACKET_BYTES]
            if h & 0x80:
                res.problems.append(Problem(
                    idx, "empty_packet",
                    f"packet {p} has HEADER_MSG set (read past FIFO end)"))
                break

        if res.n_blocks == 1:
            res.t_first_us = bh.t_us
        res.t_last_us = bh.t_us
        res.last_block_packets = bh.n_packets
        res.n_packets += bh.n_packets
        res.flags_seen |= bh.flags
        res.fifo_peak = max(res.fifo_peak, bh.fifo_bytes)

        if len(res.problems) >= max_problems:
            res.problems.append(Problem(
                idx, "aborted", f"stopped after {max_problems} problems"))
            break

    # An empty record is not a passing record. It reports zero problems on
    # every structural test precisely because there is nothing to test.
    if res.n_blocks == 0:
        res.problems.append(Problem(
            -1, "empty", "no data blocks: the record was opened but never "
                         "written to"))

    # Cross-check against what the firmware wrote into the header.
    timing = hdr.get("timing") or {}
    claimed = timing.get("n_samples")
    if isinstance(claimed, int) and claimed != res.n_packets:
        res.problems.append(Problem(
            -1, "count",
            f"header claims {claimed} samples, blocks contain {res.n_packets}"))

    integ = hdr.get("integrity") or {}
    if not integ.get("closed", False):
        res.problems.append(Problem(
            -1, "unclosed",
            "header was never finalised -- power lost or firmware reset "
            "mid-record; the data before the last block is still usable"))
    if integ.get("fifo_overflows"):
        res.problems.append(Problem(
            -1, "fifo_overflow",
            f"{integ['fifo_overflows']} FIFO overflow event(s): samples were "
            f"overwritten before being read, continuity is broken"))

    return res


# ==========================================================================
# Decoding
# ==========================================================================

@dataclass
class Record:
    """A decoded record.  All arrays are raw integer codes."""
    header: dict
    verify: VerifyResult

    gyro20: "np.ndarray"      # int32 [n,3], signed 20-bit
    gyro16: "np.ndarray"      # int16 [n,3], the UI register word, bits [19:4]
    accel20: "np.ndarray"     # int32 [n,3]
    temp_raw: "np.ndarray"    # int16 [n]
    tmst_raw: "np.ndarray"    # uint16 [n], as stored
    tmst_us: "np.ndarray"     # int64 [n], unwrapped and scaled
    block_index: "np.ndarray"  # int32 [n], which block each sample came from
    block_t_us: "np.ndarray"  # int64 [n_blocks]

    @property
    def n(self) -> int:
        return self.gyro20.shape[0]

    def gyro_dps(self, hires: bool = True) -> "np.ndarray":
        """Physical units.  Separate from the stored arrays on purpose."""
        if hires:
            return self.gyro20.astype(np.float64) / GYRO_LSB_PER_DPS_HIRES
        return self.gyro16.astype(np.float64) / GYRO_LSB_PER_DPS_UI

    def temp_c(self) -> "np.ndarray":
        return self.temp_raw.astype(np.float64) / TEMP_LSB_PER_C + TEMP_OFFSET_C


def _require_numpy() -> None:
    if np is None:
        raise RuntimeError(
            "numpy is required to decode packets.  `pip install numpy`.  "
            "`verify` and `info` work without it.")


def _decode_payload(buf: "np.ndarray") -> tuple:
    """Decode an [n, 20] uint8 array into integer codes.

    The 20-bit words are assembled as (hi16 << 4) | nibble and then sign-
    corrected by subtracting 2**20 where the sign bit is set.  Doing the shift
    on the *unsigned* 16-bit view and fixing the sign afterwards avoids the
    trap of shifting an already-signed value, which would sign-extend into the
    nibble position and corrupt the four low bits.
    """
    def be16u(a, b):
        return (buf[:, a].astype(np.uint32) << 8) | buf[:, b].astype(np.uint32)

    def to20(hi_a, hi_b, ext_byte, ext_shift):
        hi = be16u(hi_a, hi_b)
        lo = (buf[:, ext_byte].astype(np.uint32) >> ext_shift) & 0x0F
        v = ((hi << 4) | lo).astype(np.int64)
        return np.where(v >= (1 << 19), v - (1 << 20), v).astype(np.int32)

    def to16(hi_a, hi_b):
        v = be16u(hi_a, hi_b).astype(np.int64)
        return np.where(v >= (1 << 15), v - (1 << 16), v).astype(np.int16)

    # byte 17 = AX[3:0]<<4 | GX[3:0]; likewise 18 for Y, 19 for Z.
    accel20 = np.stack([to20(1, 2, 17, 4),
                        to20(3, 4, 18, 4),
                        to20(5, 6, 19, 4)], axis=1)
    gyro20 = np.stack([to20(7, 8, 17, 0),
                       to20(9, 10, 18, 0),
                       to20(11, 12, 19, 0)], axis=1)
    gyro16 = np.stack([to16(7, 8), to16(9, 10), to16(11, 12)], axis=1)
    temp = to16(13, 14)
    tmst = be16u(15, 16).astype(np.uint16)
    return accel20, gyro20, gyro16, temp, tmst


def _unwrap_tmst(tmst: "np.ndarray", res_us: int) -> "np.ndarray":
    """Unwrap the 16-bit sensor timestamp to a monotonic microsecond count.

    At TMST_RES = 1 us the field wraps every 65.536 ms; at 16 us, every
    1.049 s.  The unwrap assumes no gap longer than half a wrap period, which
    is why the firmware selects 16 us at and below ODR 100: at ODR 25 a single
    dropped sample already spans 80 ms and the 1 us field would be ambiguous.
    A gap that does break the assumption shows up as a negative jump in the
    result, which the caller can test for.
    """
    t = tmst.astype(np.int64)
    d = np.diff(t)
    wraps = np.cumsum(d < -(1 << 15)).astype(np.int64)
    out = t.copy()
    out[1:] += wraps << 16
    return (out - out[0]) * int(res_us)


def load(path: str, check_crc: bool = True,
         skip_bad_blocks: bool = True) -> Record:
    """Verify, then decode.  Blocks that failed verification are excluded by
    default rather than silently included."""
    _require_numpy()
    res = verify(path, check_crc=check_crc)
    hdr = res.header

    bad = {p.block for p in res.problems if p.block >= 0} if skip_bad_blocks else set()

    chunks, blk_t, blk_idx = [], [], []
    for idx, bh, payload in iter_blocks(path):
        if idx in bad or bh.magic != BLOCK_MAGIC:
            continue
        n = bh.n_packets
        if not (0 < n <= MAX_PACKETS):
            continue
        arr = np.frombuffer(payload, dtype=np.uint8,
                            count=n * PACKET_BYTES).reshape(n, PACKET_BYTES)
        chunks.append(arr)
        blk_t.append(bh.t_us)
        blk_idx.append(np.full(n, idx, dtype=np.int32))

    if not chunks:
        raise ValueError(f"{path}: no usable blocks")

    buf = np.concatenate(chunks, axis=0)
    accel20, gyro20, gyro16, temp, tmst = _decode_payload(buf)

    res_us = int((hdr.get("config") or {}).get("tmst_res_us", 1) or 1)
    tmst_us = _unwrap_tmst(tmst, res_us)

    return Record(header=hdr, verify=res,
                  gyro20=gyro20, gyro16=gyro16, accel20=accel20,
                  temp_raw=temp, tmst_raw=tmst, tmst_us=tmst_us,
                  block_index=np.concatenate(blk_idx),
                  block_t_us=np.asarray(blk_t, dtype=np.int64))


# ==========================================================================
# Reporting
# ==========================================================================

def _fmt_hz(x: float) -> str:
    return "n/a" if x != x else f"{x:.3f}"


def cmd_info(args) -> int:
    hdr = read_header(args.file)
    print(json.dumps(hdr, indent=2))
    return 0


def cmd_verify(args) -> int:
    worst = 0
    for path in args.file:
        try:
            res = verify(path, check_crc=not args.no_crc)
        except ValueError as e:
            print(f"FAIL  {path}\n      {e}")
            worst = 2
            continue

        cfg = res.header.get("config") or {}
        nominal = cfg.get("odr_nominal_hz")
        f_board = res.f_board_hz
        status = "PASS" if res.ok else "FAIL"
        print(f"{status}  {os.path.basename(path)}")
        print(f"      {res.n_blocks} blocks, {res.n_packets} samples, "
              f"nominal ODR {nominal} Hz, measured {_fmt_hz(f_board)} Hz")
        if nominal and f_board == f_board:
            print(f"      rate offset {100.0 * (f_board / nominal - 1.0):+.3f}%")
        print(f"      fifo peak {res.fifo_peak} B, "
              f"flags seen: {', '.join(n for b, n in FLAG_NAMES.items() if res.flags_seen & b) or 'none'}")

        for p in res.problems[:args.max_show]:
            print(f"      ! {p}")
        if len(res.problems) > args.max_show:
            print(f"      ! ... {len(res.problems) - args.max_show} more")

        if not res.ok:
            worst = max(worst, 1)
    return worst


def cmd_rate(args) -> int:
    """The two clocks, compared.  This is TN-16 section 10.1's measurement made
    per record instead of once."""
    rec = load(args.file, check_crc=not args.no_crc)
    hdr = rec.header
    nominal = (hdr.get("config") or {}).get("odr_nominal_hz")

    f_board = rec.verify.f_board_hz

    # Sensor clock: TMST is stamped at the sample instant, so it is free of the
    # FIFO queue lag that corrupted the first 8 kHz V0.4 comparison.
    span_tmst = int(rec.tmst_us[-1] - rec.tmst_us[0])
    f_sensor = (rec.n - 1) * 1e6 / span_tmst if span_tmst > 0 else float("nan")

    print(f"{os.path.basename(args.file)}")
    print(f"  samples            {rec.n}")
    print(f"  nominal ODR        {nominal} Hz")
    print(f"  f vs TIM2 (board)  {_fmt_hz(f_board)} Hz"
          + (f"   {100.0 * (f_board / nominal - 1.0):+.3f}%" if nominal else ""))
    print(f"  f vs TMST (sensor) {_fmt_hz(f_sensor)} Hz"
          + (f"   {100.0 * (f_sensor / nominal - 1.0):+.3f}%" if nominal else ""))
    if f_board == f_board and f_sensor == f_sensor:
        print(f"  board/sensor ratio {f_board / f_sensor:.6f}")

    # Sample-to-sample continuity from the sensor's own clock.  A record with a
    # uniform step is contiguous; anything else is a gap whose size is known
    # exactly, which is stronger evidence than the firmware's drop counters.
    d = np.diff(rec.tmst_us)
    step = int(np.median(d))
    if step > 0:
        odd = np.flatnonzero(d != step)
        print(f"  median step        {step} us")
        print(f"  irregular steps    {odd.size} "
              f"({100.0 * odd.size / max(d.size, 1):.4f}%)")
        if odd.size:
            missing = int(np.sum(np.round(d[odd] / step) - 1))
            print(f"  implied missing    {missing} samples")
            for i in odd[:10]:
                print(f"    at sample {i + 1}: step {d[i]} us "
                      f"({d[i] / step:.2f} x nominal)")
    return 0 if rec.verify.ok else 1


def cmd_export(args) -> int:
    rec = load(args.file, check_crc=not args.no_crc)
    out = args.out or os.path.splitext(args.file)[0] + ".npz"
    np.savez_compressed(
        out,
        gyro20=rec.gyro20, gyro16=rec.gyro16, accel20=rec.accel20,
        temp_raw=rec.temp_raw, tmst_raw=rec.tmst_raw, tmst_us=rec.tmst_us,
        block_index=rec.block_index, block_t_us=rec.block_t_us,
        header_json=np.array(json.dumps(rec.header)),
    )
    print(f"{rec.n} samples -> {out}")
    return 0


# ==========================================================================
# Self-test
#
# Builds a synthetic record in memory and round-trips it.  This exists so the
# reader can be checked without hardware, and so that a change to either the
# firmware format or this file has to break loudly rather than quietly.
# ==========================================================================

def _synth(path: str, n_blocks: int = 3, last_packets: int = 37,
           odr: int = 1000, tmst_res: int = 1) -> dict:
    hdr = {
        "format": "sdat/1", "magic": "SDAT", "run_id": "selftest",
        "config": {"odr_nominal_hz": odr, "tmst_res_us": tmst_res,
                   "word_bits": 20},
        "timing": {"n_samples": (n_blocks - 1) * MAX_PACKETS + last_packets},
        "integrity": {"closed": True, "fifo_overflows": 0},
    }
    raw = json.dumps(hdr).encode()
    blob = bytearray(raw + b" " * (HEADER_BYTES - len(raw)))

    step_us = 1_000_000 // odr
    sample = 0
    t_us = 1_000_000
    for b in range(n_blocks):
        n = last_packets if b == n_blocks - 1 else MAX_PACKETS
        payload = bytearray(PAYLOAD_BYTES)
        for p in range(n):
            o = p * PACKET_BYTES
            payload[o] = 0x68                       # header, HEADER_MSG clear
            # gyro X = a known ramp, so a decode error cannot pass unnoticed
            g20 = (sample * 37 - 1000) & 0xFFFFF
            payload[o + 7] = (g20 >> 12) & 0xFF
            payload[o + 8] = (g20 >> 4) & 0xFF
            payload[o + 17] = g20 & 0x0F            # gyro nibble in low half
            tm = (sample * step_us // tmst_res) & 0xFFFF
            payload[o + 15] = (tm >> 8) & 0xFF
            payload[o + 16] = tm & 0xFF
            sample += 1
        # The anchor is the trigger of the read that STARTS the block, so it
        # belongs at the block's leading edge. Stamping it at the trailing edge
        # instead shifts every anchor by one block and the rate estimator --
        # which relies on the anchors bracketing all but the last block --
        # comes out high by the ratio of the record length to itself minus one.
        flags = F_PARTIAL if n < MAX_PACKETS else 0
        bh = _BLKHDR.pack(BLOCK_MAGIC, b, t_us, n, 1000, flags, 0, 0, 0,
                          zlib.crc32(bytes(payload)) & 0xFFFFFFFF)
        blob += bh + payload + b"\0" * (BLOCK_BYTES - BLKHDR_BYTES - PAYLOAD_BYTES)
        t_us += n * step_us

    with open(path, "wb") as f:
        f.write(blob)
    return hdr


def cmd_selftest(args) -> int:
    import tempfile

    fails = []

    def check(name, cond, detail=""):
        print(f"  {'ok  ' if cond else 'FAIL'}  {name}"
              + (f"   {detail}" if detail and not cond else ""))
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "selftest.sdat")
        _synth(p)

        res = verify(p)
        check("verify passes on a clean synthetic record", res.ok,
              "; ".join(str(x) for x in res.problems))
        check("block count", res.n_blocks == 3, str(res.n_blocks))
        check("sample count", res.n_packets == 437, str(res.n_packets))

        if np is not None:
            rec = load(p)
            expect = np.array([(i * 37 - 1000) for i in range(rec.n)],
                              dtype=np.int64)
            expect = np.where(expect >= (1 << 19), expect - (1 << 20), expect)
            expect = np.where(expect < -(1 << 19), expect + (1 << 20), expect)
            check("20-bit gyro decode round-trips",
                  bool(np.array_equal(rec.gyro20[:, 0], expect.astype(np.int32))))
            check("16-bit word equals bits [19:4] of the 20-bit word",
                  bool(np.array_equal(rec.gyro16[:, 0].astype(np.int64),
                                      np.right_shift(rec.gyro20[:, 0].astype(np.int64), 4))))
            d_tmst = np.diff(rec.tmst_us)
            check("TMST unwraps to a uniform step",
                  bool(np.all(d_tmst == d_tmst[0])),
                  f"steps seen: {np.unique(d_tmst)[:5]}")
            # 3 blocks of 200/200/37 at a 1 ms step: the anchors are 200 ms
            # apart per full block, so the last block's 37 packets must be
            # excluded from the numerator, not the first block's 200.
            check("measured rate matches the synthetic ODR",
                  abs(rec.verify.f_board_hz - 1000.0) < 1.0,
                  _fmt_hz(rec.verify.f_board_hz))
        else:
            print("  skip  decode tests (numpy not installed)")

        # Corruption must be caught, not tolerated.
        with open(p, "r+b") as f:
            f.seek(HEADER_BYTES + BLKHDR_BYTES + 100)
            f.write(b"\xAA")
        check("a single flipped payload byte fails CRC",
              any(x.kind == "crc" for x in verify(p).problems))

    print()
    if fails:
        print(f"SELFTEST FAILED: {len(fails)} check(s): {', '.join(fails)}")
        return 1
    print("SELFTEST PASSED")
    return 0


# ==========================================================================

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Read and verify Sheppard .sdat records.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p):
        p.add_argument("--no-crc", action="store_true",
                       help="skip CRC checking (much faster on huge files)")

    p = sub.add_parser("verify", help="integrity-check one or more records")
    p.add_argument("file", nargs="+")
    p.add_argument("--max-show", type=int, default=10)
    add_common(p)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("info", help="print the JSON header")
    p.add_argument("file")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("rate", help="compare the board and sensor clocks")
    p.add_argument("file")
    add_common(p)
    p.set_defaults(func=cmd_rate)

    p = sub.add_parser("export", help="decode to a .npz of raw integer codes")
    p.add_argument("file")
    p.add_argument("-o", "--out")
    add_common(p)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("selftest", help="round-trip a synthetic record")
    p.set_defaults(func=cmd_selftest)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
