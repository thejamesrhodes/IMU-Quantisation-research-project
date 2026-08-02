# Documents created in this session — to add to the project knowledge list

**30 July 2026.** Everything below was written in this conversation and lives in
`C:\IMU Research Project`. The project documentation list currently ends at
TN-20, so none of it is registered.

Add in this order — the first three change what earlier documents mean.

---

## Technical notes — supersede earlier content

| File | What it settles | Supersedes |
|---|---|---|
| **`SUPERSEDED.md`** | Central register, Z.1–Z.9. **Read before quoting any number from TN-13 onwards.** | replaces the never-written Appendix Z convention in four notes |
| **`TN-24 — Night 3 Results, the Third Reference Correction, and the ODR-Dependent Step`** | η was low by 1/64 campaign-wide; slot-2 replication; repeatability σ_η = 0.0065; step size ODR-dependent at 15σ; AAF axis dead; software dither closes the ρ↔ODR confound | every η in TN-20/21/22/23 |
| **`TN-25 — The Bussgang Gain, Recovered from the Corpus and Measured`** | G derived and measured, 0.095–2.179; E_φ[G] = 1 confirmed at 0.9σ; deadband sign structure; whiteness criterion marginal on the sweep; `\arwSpan` untraceable | fills a gap present since TN-20 |
| `TN-21` §9–10 (appended) | slot-2 step size from `p2cal`; the 2×2 design | TN-21 §4's per-part hypothesis |

## Audit and framing

| File | What it is |
|---|---|
| **`CORPUS_AUDIT_30Jul2026.md`** | Nine things the older corpus has that TN-20…TN-24 lost. Item 1 (the deflation withdrawal) is the one that would have produced a wrong paper |
| `Table_Verification_30Jul2026.md` | Tables 1 and 2 against primary sources; three corrections; rows 4–6 still open |

## Manuscript material

| File | What it is |
|---|---|
| **`paper/Example_Full_Paper.md`** | Full-length worked example, all eight sections plus two appendices, with every recovered corpus item placed where it belongs. Not the manuscript |
| `paper/Methods_Worked_Example.md` | A methods section on a *different* experiment, annotated — a style reference |
| `paper/Writing_Notes.md` | Line edits of your own §4.1 prose with the reasoning |
| `paper/sections/04_method.tex` | Reordered: apparatus → reference-quantiser → procedure → estimators → circularity → record selection |
| `Preprint_Scaffold_v0_1.md` | Section frame, figure budget, readiness gates |

## Operational

| File | What it is |
|---|---|
| `SESSION_HANDOVER.md` | Current state, defects, next actions |
| `Test Datasets/plan_night3.txt` | The run that produced the above (executed, 45/45) |
| `Test Datasets/plan_night4.txt` | **Not yet run.** Pins σ_η to ±10%. 7 h 18 min |
| `Test Datasets/RUN_NIGHT3_STEPS.md` | Run card: upload, arm, morning decision table |
| `GMWM Software/tools/software_dither.py` | The R6 software-dither leg |

---

## Suggested reading order for a cold start

1. `SUPERSEDED.md` — what is no longer true
2. `TN-24` — the correction and the replication
3. `TN-25` — the half of the physics that was missing
4. `CORPUS_AUDIT_30Jul2026.md` — what the older documents still hold
5. `paper/Example_Full_Paper.md` — where it is all going
6. `SESSION_HANDOVER.md` — what to do next
