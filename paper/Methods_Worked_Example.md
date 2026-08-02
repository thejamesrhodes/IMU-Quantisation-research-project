# A worked methods section — deliberately on a different experiment

**This is not your methods section and must not be pasted into the paper.** The
subject is a crystal oscillator measured against a GPS-disciplined reference,
chosen because it is structurally identical to yours — an instrument with one
odd design choice, an estimator with a circularity trap, a reference channel
that is itself imperfect, pre-specified exclusions, and one correction found by
looking — while being about something else entirely. Every move below maps onto
a move you need to make.

Read the annotations, not the prose.

---

## 4. Instrumentation and methods

```latex
\section{Instrumentation and methods}
\label{sec:method}

\subsection{Apparatus}

Frequency offset was measured on twelve 10\,\si{\mega\hertz} oven-controlled
crystal oscillators (Bliley NV47M-10, nominal ageing
\SI{5e-10}{\per\day}) against a GPS-disciplined rubidium reference
(Symmetricom X72, specified Allan deviation \num{2e-12} at
\SI{100}{\second}). Phase difference was digitised by a dual-mixer
time-difference bridge at \SI{1}{\hertz} and logged to a host over an
optically isolated link.

The oscillators were run from a linear bench supply rather than the
switch-mode units supplied with them. This is not a quality preference: the
switch-mode units inject a \SI{140}{\kilo\hertz} ripple that the oscillators'
internal regulators attenuate by only \SI{34}{\deci\bel}, leaving a residual
that appears in the phase record as a coherent line and destroys the
Gaussianity the estimator of \S\ref{sec:estimator} assumes. The supply is
therefore a controlled variable, not an implementation detail, and it was held
fixed across the campaign.
```

**What is happening here.** The first paragraph is nothing but part numbers,
counts and specifications with their sources — no narrative, no justification,
no order-of-events. Somebody could buy this equipment.

The second paragraph does the one thing a methods section must do beyond
listing: it justifies a choice that would otherwise look arbitrary or fussy,
briefly, inline, and in terms of the measurement rather than of preference.
Note the shape — *this is not X, it is Y, because Z, therefore it is a
controlled variable.* That construction is worth stealing. Note also that the
justification carries a number (34 dB), so the reader can check whether the
reasoning holds rather than taking it on trust.

Note what is **absent**: any mention of what was tried first, what broke, or
how long it took. That belongs in a lab notebook.

---

```latex
\subsection{Estimator, and why the obvious one is circular}
\label{sec:estimator}

Fractional frequency offset $y$ was estimated as the slope of a
least-squares line through the phase record, not from a period count. The
distinction is not one of precision. A period counter gates on threshold
crossings, so its estimate of the period depends on the slew rate at the
crossing, which depends in turn on the harmonic content --- the quantity a
subsequent spectral analysis is intended to measure. Estimating $y$ by
counting and then testing the spectrum would be to assume the answer.

The phase-slope estimator is free of this coupling because it uses the
mixer's output directly and never thresholds it. Its standard error over a
record of $N$ samples at interval $\tau_0$ is

\begin{equation}
  \operatorname{SE}(\hat y) = \sigma_\phi
      \sqrt{\frac{12}{N^3 \tau_0^2}} \, C^{1/2},
  \label{eq:se}
\end{equation}

with $\sigma_\phi$ the phase noise per sample and $C = 1.4$ a
correlation-inflation factor obtained from the measured autocorrelation of
the bridge output at lag one. All uncertainties quoted in
\S\ref{sec:results} are $1\sigma$ from \eqref{eq:se}.
```

**What is happening here.** The anti-circularity argument is the second
subsection, not a footnote, and it is stated as a *structural* property of the
estimator rather than as a precaution taken. That is the difference between a
reader believing you and a reader wondering.

The construction to steal: **name the obvious estimator, say why it is wrong,
say why yours is not.** Three sentences. Do not hedge it — "we felt the period
count might be less reliable" invites the referee to disagree. "Estimating $y$
by counting and then testing the spectrum would be to assume the answer" does
not.

$C = 1.4$ is given *with its provenance*. An unexplained inflation factor is
the first thing a referee circles.

---

```latex
\subsection{The reference is not a reference}
\label{sec:refimperfect}

The rubidium standard is treated throughout as the frequency reference, but
it has its own instability, and over the averaging times used here that
instability is not negligible against the specimens'. The three-cornered-hat
decomposition of \citet{gray1974} was therefore applied to two references
and each specimen in turn, and the reference's contribution removed:

\begin{equation}
  \sigma^2_{y,\mathrm{spec}}(\tau)
    = \sigma^2_{y,\mathrm{obs}}(\tau) - \sigma^2_{y,\mathrm{ref}}(\tau).
  \label{eq:tch}
\end{equation}

At \SI{100}{\second} this removes \SI{11}{\percent} of the observed
variance; at \SI{10}{\second} it removes \SI{31}{\percent} and is therefore
not optional. Uncorrected values are reported alongside corrected ones
throughout, so the size of the correction is visible rather than absorbed.
```

**What is happening here.** This is your §4.3, and the moves are the same. A
channel treated as ground truth is not ground truth; the correction is stated
as an equation; **the size of the correction is quantified at two operating
points**, one where it is small and one where it is not; and both corrected and
uncorrected values get reported.

That last sentence is the one that buys credibility. A correction whose
magnitude is hidden looks like a fudge no matter how principled it is.

---

```latex
\subsection{Records, exclusions and analysis}

Each oscillator was logged for \SI{72}{\hour} after a \SI{48}{\hour}
warm-up, at \SI{23.0 \pm 0.5}{\celsius} in a still enclosure. Records were
excluded on three criteria, all fixed before logging began: a GPS holdover
event of any duration reported by the reference; an enclosure excursion
beyond \SI{\pm 1.0}{\celsius}; and a bridge saturation flag. Four of the
sixteen records were excluded, all by the first criterion, and the excluded
records are deposited with the rest.

Analysis was performed with \texttt{allantools} 2019.9 under Python 3.11,
and the analysis was run once. No estimator, exclusion rule or averaging
time was changed after the data were examined, with one exception, which is
identified as such in \S\ref{sec:refimperfect}: the three-cornered-hat
correction was introduced after an unexplained \SI{31}{\percent} excess at
short $\tau$ was traced to the reference. It is reported here as a post-hoc
correction, and validated on a held-out specimen not used to derive it.
```

**What is happening here.** Four things, and all four are load-bearing.

The exclusion criteria are given **before** any result appears, with the
explicit words *fixed before logging began*, followed by how many records each
criterion actually removed. A reader who learns the exclusion rule after seeing
the numbers cannot unlearn the suspicion.

The software has a **version number**. "Analysed in Python" is not
reproducible; `allantools 2019.9` is.

"The analysis was run once" is a sentence almost nobody writes and everybody
should.

And the exploratory correction is labelled, in the methods, with the words
*post-hoc*, plus the out-of-sample validation that makes it defensible. Notice
that admitting it costs nothing — the held-out validation does all the work,
and the admission makes the validation believable.

---

## The seven moves, extracted

1. **Uniform past tense.** "was measured", "were excluded", "was run". Mixed
   tense is the commonest flaw in a first methods section and the easiest to
   fix with a single read-through.
2. **Every number carries a source or a measurement.** Datasheet reference,
   or "measured", or an equation. A bare number is a defect.
3. **Justify only the choices that look odd**, inline, in one or two sentences,
   in terms of the measurement. Everything else is stated, not defended.
4. **The anti-circularity argument gets its own subsection**, stated as a
   property of the estimator rather than as care taken.
5. **Quantify every correction** at a point where it is small and a point where
   it is large, and report corrected and uncorrected values together.
6. **Exclusion rules before results, with counts**, and say when they were
   fixed.
7. **Software versions, and "run once".**

## And three things to leave out

Chronology. What was tried and abandoned. Any sentence beginning "It is
important to note that" — if it is important, the sentence after it is the one
you meant to write.
