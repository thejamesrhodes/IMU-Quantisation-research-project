# Line edits on your §4.1, with the reasoning

Your content, your structure, your findings — this is prose editing only. Read
the *reasons*; the rewrites are illustrations of them, not text to paste.

---

## Sentence 1

**Yours**

> The experiment used a custom PCB, consisting of two ICM-42688-P MEMS
> gyroscopes, set to a full-scale range (FSR) of ±2000 °/s, and an
> STM32F723ZET6 microcontroller unit (MCU) to read the sensors and log data to
> an SD card.

**Problem.** One sentence carrying four jobs: what the board is, what's on it,
how it was configured, and what the MCU does. The "consisting of" list breaks
down because ±2000 dps isn't a thing the PCB consists of — it's a setting. And
"MEMS gyroscopes" is wrong: the ICM-42688-P is a six-axis IMU.

**Rewrite**

> Measurements were made on a purpose-built board carrying two ICM-42688-P
> six-axis IMUs, of which only the gyroscope channels were used. The two parts
> are referred to throughout as specimen 1 and specimen 2. Both were operated
> at a full-scale range of \SI{\pm 2000}{\dps}, giving a register least
> significant bit of $\Dlsb = \SI{61.035}{\mdps}$. An STM32F723ZET6
> microcontroller read both sensors over independent SPI buses and logged to
> microSD.

**Three moves.** The four jobs became four sentences. The specimen labels are
defined here because §5 depends on them. And Δ appears the moment FSR does,
because every later quantity divides by it — a reader shouldn't reach §4.2 not
knowing what Δ is.

---

## Sentence 2 — and a structural problem

**Yours**

> The 16-bit channel is the standard output of the ICM-42688-P and a truncation
> \todo{source} of the 20-bit channel obtained by reading the devices FIFO
> buffers.

**Problem, and it's the important one.** There is no source to find, because
this is *your result* — §5.1 establishes it from 450 discriminating samples. As
written, methods asserts what results discovers, and a referee reading in order
will conclude you assumed the architecture and then measured consistently with
your assumption. That's the circularity charge, arriving through the back door.

Also: "the devices FIFO buffers" wants an apostrophe.

**Rewrite**

> Each part exposes two output paths: a 16-bit user register, and a 20-bit
> high-resolution word available through the FIFO. Both were captured over the
> same physical samples, and the arithmetic relationship between them is
> established in \S\ref{sec:arch} rather than assumed here.

**The move.** Say what you captured; refuse to say what it means yet. "rather
than assumed here" is doing real work — it tells the referee you noticed the
trap before they did.

---

## Sentence 3 — delete it

**Yours**

> The PCB was designed to minimize electrical noise and crosstalk between the
> two gyroscopes, and care was taken to ensure that both sensors were exposed
> to the same environmental conditions during data collection.

**Problem.** "Care was taken" is unfalsifiable. A referee cannot check it,
cannot disagree with it, and learns nothing from it. Any sentence a sceptic
can neither verify nor contradict is costing you words and credibility at once.

The tell: if you can delete a sentence and lose no information, it had none.

**But you have a real control to put here instead.** TN-20 §4.1: both SPI buses
are forced to 8 MHz by `bus_init()`, and before firmware v0.2.12 slot 2 ran at
16 MHz — which would have written a bus-rate difference straight into the
specimen comparison.

**Rewrite**

> Both SPI buses were clocked at \SI{8}{\mega\hertz}, set from the measured
> peripheral clock at initialisation and read back into every record header.
> An earlier firmware revision ran the second bus at \SI{16}{\mega\hertz},
> which would have confounded a bus-rate difference with the specimen
> comparison.

**The move.** Specific, checkable, and it admits a fixed mistake. Naming the
error you found and corrected reads as competence, not weakness — it shows you
were looking for exactly the confound a referee would ask about.

---

## Sentence 4 — the nested-clause problem

**Yours**

> Throughout the experiment, all clock speeds such as the chosen 32MHz SYSCLK
> for the MCU where kept intentionally constant and low as an experimental
> control. This was done to avoid the increased electrical noise that occurs
> with higher clock speeds that could couple into the sensors and act as
> dither, abolishing the effect under study.

**Problems.** "all clock speeds such as" implies unnamed others — either list
them or name the one. "where" should be "were". And the second sentence has two
nested `that` clauses: *noise that occurs ... speeds that could couple*. By the
second one the reader has lost the subject.

"This was done to" is a construction to watch for. It always signals that the
reason is arriving late, in a separate sentence, when it could have been in the
first one.

**Rewrite**

> The system clock was held at \SI{32}{\mega\hertz} for the whole campaign.
> This is well below the part's capability and the choice is deliberate:
> digital switching noise couples into the analogue front end and acts as
> dither, raising $\rhod$ and suppressing the effect under study. The clock
> rate is therefore a controlled variable rather than a performance setting,
> and it was held fixed rather than optimised.

**Three moves.** One clock named, not a vague class. The reason arrives in the
same breath as the choice, in one chain with no nesting: *noise couples → acts
as dither → raises ρ → suppresses the effect.* And the last sentence gives the
reader a category for the choice, which is what stops it looking like an
oversight.

That construction — *this is not X, it is Y, therefore it is a controlled
variable* — is worth keeping. You'll need it again for the supply.

---

## Sentence 5 — numbers in the wrong place

**Yours**

> Power is supplied through a power-only USB cable instead of a battery during
> all datalogging, as it was found that the connected ground plane helped to
> minimise an electrical spur (spur at 119 Hz, measured at 1.28Δ on battery
> against 0.42Δ on USB, unkown exact source), which would destroy the
> gaussianity that the estimator assumes.

**Problems.** The measurement — which is the whole justification — is inside a
parenthesis, and parentheses are where readers put things they can skip. Move a
load-bearing number into the main clause.

"as it was found that" hides both the agent and the fact that this was
*measured*. You didn't find it; you measured it. Say so.

Then: "Power is supplied" (tense), "unkown", and "gaussianity" wants a capital
because it's a person's name.

**Rewrite**

> Records were taken with the board powered from a USB supply rather than from
> its battery. A coherent line at \SI{119}{\hertz} is present in the gyroscope
> channels of both specimens, and its amplitude is $1.28\,\Dlsb$ on battery
> against $0.42\,\Dlsb$ on USB — a factor of three. Its origin has not been
> identified. Because a coherent line violates the Gaussian input assumption
> on which the closed-form predictions of \S\ref{sec:theory} depend, the
> quieter supply was used throughout.

**Four moves.** The numbers are now in a main clause with the ratio stated, so
the reader doesn't have to divide. "Its origin has not been identified" gets
its own short sentence — admitting ignorance plainly is stronger than
parenthesising it, and burying it looks like you hoped nobody would notice. The
consequence is named specifically (violates the Gaussian assumption that §3
depends on) rather than gestured at. And the decision comes last, as a
consequence of the evidence rather than a preference.

---

## The seven habits underneath all of that

**1. One sentence, one job.** When a sentence carries three facts, the reader
holds two in memory while parsing the third. Splitting costs you nothing —
scientific prose is not judged on sentence variety.

**2. Load-bearing numbers go in main clauses.** If the reasoning depends on it,
it cannot live in a parenthesis or a footnote.

**3. Delete anything a sceptic can't check.** "Care was taken", "every effort
was made", "the design was optimised for". If you can't replace it with a
number or a specific, cut the sentence.

**4. Three constructions to search for and rewrite.**

| Watch for | Why | Instead |
|---|---|---|
| "It was found that…" | hides that you *measured* it | "X was measured at…" |
| "This was done to…" | reason arriving one sentence late | fold it into the first |
| "…which is important because…" | the reason is the sentence you meant | write that one |

**5. Untangle nested `that` clauses.** Two in one sentence is one too many.
Split into a chain: A causes B, which raises C, which suppresses D.

**6. Admit gaps in a short flat sentence.** "Its origin has not been
identified." Four words, no hedging, no parenthesis. A stated limitation is
evidence you looked; a buried one is evidence you hoped.

**7. Tense: what you *did* is past, what the instrument *is* is present.**
"Records were taken" but "the ICM-42688-P exposes two output paths". Your
instinct on this was already mostly right, which is why the drift is easy to
fix in one read-through.

---

## A workflow that helps more than any rule

Write badly first, on purpose. Get the facts down in whatever order they come,
then edit for the seven habits above in a separate pass. Trying to compose
correct sentences while also deciding what to say is what produces the
four-jobs-in-one-sentence problem, and it's slower.

The second pass is mechanical enough to do tired: search for "was found",
"care was taken", "this was done", "important", "very", and any parenthesis
containing a number. Fix each. That single pass will get you most of the way.

And read it aloud. Nested clauses are hard to hear, which is exactly why
they're hard to read.
