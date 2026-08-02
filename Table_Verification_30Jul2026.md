# Table verification against primary sources — 30 July 2026

Every row of Table 1 and Table 2 checked against the source rather than against
the corpus that produced it. **Three corrections, one confirmation that matters
more than the rest, and one claim that had to be weakened.**

---

## The confirmation: Kalibr concedes the condition in its own words

Verified verbatim on the Kalibr wiki, *Additive "White Noise"*:

> "Note: This assumes that the noise was filtered with an ideal low-pass filter
> that filters noise above f = 1/(2Δt) (in other words, an ideal decimation
> stage). This may or may not be the case, depending on your sensor settings.
> **If you simply "subsample" your gyro or accel, you are not allowed to scale
> your "white noise density" in that way.**"

And on the model's own adequacy, from *Kalibr IMU Noise Parameters in Practice*:

> "**So clearly, the model is optimistic.** ... From our experience, for
> lowest-cost sensors, increasing the noise model parameters by a factor of 10x
> or more may be necessary."

This closes Gate 1's most important citation. It is far better evidence than
anything inferable from source code, because it is the toolchain stating the
condition itself.

**Also verified:** Kalibr's measurement model is $\tilde\omega = \omega + b + n$
— two error terms, no quantisation coefficient anywhere. The discrete scaling
is $\sigma_d = \sigma_c/\sqrt{\Delta t}$.

**And a point worth its own sentence in the paper:** Kalibr's reference [1] for
the Allan-variance method is **IEEE Std 952-1997 — the FOG standard.** That is
this paper's argument in one line. The method is imported from an
angle-increment instrument and applied to a rate register without the
architectural distinction ever being made.

---

## Correction 1 — the inflation factor

| | |
|---|---|
| Corpus (Concept Note §2) | "recommends inflating parameters by five-to-ten times" |
| Source | "increasing the noise model parameters by a factor of **10x or more**" |

Understated. Fix the quotation.

## Correction 2 — the attribution is wrong

The corpus cites this material as **Rehder et al. (2016)**. It is not. It is the
project **wiki**, last revised by Patrick Geneva in March 2023. Rehder et al.
2016 ("Extending kalibr", ICRA) is a separate document.

Citing a wiki page as a peer-reviewed paper is the kind of error a referee
notices and generalises from. Both now appear in `references.bib` as separate
entries, the wiki as `@misc` with an access date.

## Correction 3 — `allan_variance_ros` reports more than claimed

| | |
|---|---|
| Corpus | "Fits N, sometimes K; not Q" |
| Source | Reports angle random walk, bias instability **and** rate random walk — so N, B and K, always |

No quantisation coefficient, which is the part that matters. It emits a Kalibr
`imu.yaml` containing `update_rate`, so it inherits the √ODR transfer rather
than implementing one of its own.

---

## The claim that had to be weakened

GMWM-to-Kalman-Q v1.2 Z.4 says:

> "The surveyed pipelines DO NOT MODEL register quantisation AT ALL — it is
> absent from the model set, not approximated within it."

**As a blanket claim this is not sustainable.** The Allan-variance literature
these tools derive from fits the five-coefficient model Q/N/B/K/R, GMWM
implementations offer a quantisation latent process, and `imu_utils` may fit Q
internally even though it reports only `gyr_n` and `gyr_w`. A referee who knows
the tools will catch "at all".

**The sustainable version is sharper, not weaker:**

> Where a quantisation coefficient exists at all, it is the IEEE-952 $Q$ at
> $-1$ slope — an angle-increment construct. A rate register never produces
> that slope, so the coefficient is fitted in the wrong place and the
> register's contribution is absorbed by the white-noise process instead. No
> pipeline links a quantisation term to $\Delta$, full-scale range or output
> word length, and none exposes $\rho$ or $\mu$.

That survives the informed referee, and it is a better argument: a tool that
*does* fit a quantisation coefficient and *still* cannot capture this term is a
more striking illustration than a tool that ignores quantisation entirely.

Table 1 rewritten accordingly.

---

## Table 2 (symbols) — no corrections

| Entry | Check | Status |
|---|---|---|
| $\Delta = 61.035$ mdps at ±2000 dps | $2000/32768 \times 1000$ | correct |
| Sensitivity 16.4 LSB/(°/s) at FS_SEL 0 | DS-000347 Rev 1.6 Table 1 | confirmed |
| $\Delta' = \Delta/8$ | gyro20 always even, min spacing 0.1250 Δ measured | confirmed |
| ZRO tempco ±5 mdps/K | DS-000347 Rev 1.6 Table 1, "ZRO Variation vs. Temperature ±0.005 °/s/°C" | confirmed |
| OFFSET_USER ±64 dps, 1/32 dps | DS-000347 Rev 1.6 §5.4 and §17.18–17.22 | confirmed |
| Vaccaro & Zaki notation collision | — | still to check in the paper itself |

---

## Still unverified — Table 1 rows 4–6

`\todo` markers are in the table for each.

- **GMWM (simts/wv)** — needs the paper documenting the latent-process set, not
  just the package. Does its quantisation process carry a $-1$ slope, and is
  there any link to $\Delta$?
- **MATLAB Sensor Fusion** — `allanvar` doc page. Which coefficients does the
  documented workflow fit?
- **NaveGo** — Gonzalez et al.
- **`imu_utils` internal fit** — the README settles the *output* (N and B only)
  but not whether Q is fitted internally. Needs a source read.

Half a day. Until then Table 1 has four honest gaps rather than four unsourced
assertions, which is the right state for it to be in.

---

## Fixed while verifying

Three LaTeX/BibTeX faults that would have bitten later:

1. **BibTeX has no comments in the LaTeX sense.** It scans for `@` and tries to
   parse an entry wherever it finds one — including on a `%` line. A comment
   reading "these are @misc/@software entries" was a hard parse error.
2. **`@software` is not defined by `unsrt`** (nor by `iopart-num`). Changed to
   `@misc` with the version in the title.
3. **Bare underscores in `note` fields** — `update_rate`, `gyr_n` — are
   subscript operators and illegal in text mode. All escaped.

The paper now builds clean: exit 0, no errors, bibliography resolving, 7 pages.
