# Release and deposit procedure

Two separate things, often confused:

| | Where it comes from | What it needs |
|---|---|---|
| **Data DOI** | a manual upload to Zenodo | nothing on GitHub at all |
| **Code DOI** | a GitHub release, archived automatically by Zenodo | a **public** repository |

The data deposit is §2–§4 and can be done today. The code DOI is §5 and is
blocked until §0 is resolved.

---

## 0. Read this first

**`.gitignore` stops future commits. It does not remove anything already in the
repository's history.** Seven commits in this repository add or modify the
technical notes, and the manuscript tree is tracked as well. Anyone with read
access can recover all of it with

```
git log --all --diff-filter=A --name-only
git show <commit>:<path>
```

Zenodo's GitHub integration [can only access public repositories][zgh]. So a
code DOI by that route means making this repository public, and making *this*
repository public publishes the history.

Three ways out, in the order I would consider them.

### A. Keep this repository private; upload the data deposit by hand

Nothing about history needs to change, because the data deposit never touches
GitHub. This is the whole of §2–§4 and it is sufficient for everything the
dataset is for — the DOI, the citation, the CV entry.

Cost: no code DOI yet. That can be added at any time, and adding it later does
not affect the data DOI.

### B. Publish a clean repository with no history

Export the working tree, drop the internal files, and initialise a new
repository from it. The current repository stays private and keeps being the
working one.

```powershell
cd "C:\"
git clone --depth 1 "file:///C:/IMU Research Project" IMU-release
cd IMU-release
Remove-Item -Recurse -Force .git
Remove-Item -Recurse -Force paper, Misc, "Test Datasets", Figures -EA SilentlyContinue
Remove-Item TN-*.md, SUPERSEDED.md, SESSION_HANDOVER.md, *_AUDIT_*.md, `
            Table_Verification_*.md, Concept_Note*.md, Preprint_Scaffold*.md, `
            DOCUMENTS_TO_ADD_TO_PROJECT.md, ZENODO_DEPOSIT_PLAN.md -EA SilentlyContinue
git init -b main
git add .
git commit -m "Initial public release: firmware, analysis tools, hardware, deposit build"
```

Then create an empty repository on GitHub and push to it. **Check the file list
before the first push** — once it is public, it is public:

```powershell
git ls-files | Select-String -Pattern "TN-|SUPERSEDED|AUDIT|Concept_Note|paper/|Test Datasets"
# expect: no output
```

### C. Rewrite this repository's history

`git filter-repo --path-glob 'TN-*.md' --invert-paths` and similar, then force
push. It works, but every existing clone and fork keeps the old objects, and if
the repository has ever been public you should assume the notes are already
copied. B is less work and has no failure mode.

**Check the current visibility before deciding.** GitHub → the repository →
Settings → General → Danger Zone shows whether it is public or private.

[zgh]: https://help.zenodo.org/docs/github/enable-repository/

### Before any of them: know what is in the source comments

The firmware and the analysis tools cite the project's own notes by number in
their comments. `.gitignore` does nothing about that, because the citations are
inside files that *should* be published.

```powershell
cd "C:\IMU Research Project\zenodo"
python check_public.py
python check_public.py --detail    # file:line for every hit
```

None of them disclose a result — they disclose that an internal numbering
scheme exists. Whether that is acceptable is a judgement. The script reports
and does not rewrite, because a blind regex pass over source comments is a good
way to damage working code for nothing. If you decide to strip them, do it in
the export of route B and keep the working tree intact.

The data deposit is unaffected either way: `build_deposit.py` scrubs the reader
it ships and fails the build if anything survives.

---

## 1. Untrack the internal files

Do this whichever route you take. It changes what future commits contain.

```powershell
cd "C:\IMU Research Project"
git rm -r --cached . --quiet
git add .
git status --short
```

`git status` should now show the internal files as deleted from the index while
they remain on disk. Confirm before committing:

```powershell
git status --short | Select-String -Pattern "^D " | Measure-Object
git ls-files | Select-String -Pattern "TN-|SUPERSEDED|AUDIT|paper/"   # expect none
git commit -m "Untrack internal notes, manuscript and generated figures"
```

---

## 2. Build the deposit

```powershell
cd "C:\IMU Research Project\zenodo"
python build_deposit.py --records "..\Test Datasets" --out build
```

The build refuses to finish if any record fails verification, if the 19-bit
relation does not hold in every word, or if any internal reference survives
into a deposit text file. Expected output: 11 files, about 100 MB.

To reserve the DOI first (§4 step 2) and have it appear inside the README,
codebook, licence and citation, rebuild with it:

```powershell
python build_deposit.py --records "..\Test Datasets" --out build `
                        --doi "10.5281/zenodo.XXXXXXX" --version 1.0.0
```

`--keep-gate-rule` ships the record headers exactly as logged, including the
internal name of the thermal criterion in `gate.rule`. Default is to normalise
it; see §3 of the deposit's own `README.md`.

---

## 3. Check it before uploading

```powershell
cd build
python read_sdat.py verify (Get-ChildItem -Recurse -Filter *.sdat).FullName
```

That needs the bundles unpacked first. The complete check, from an empty
directory, is the one that matters — it proves the deposit stands alone:

```powershell
$t = "$env:TEMP\deposit-check"
Remove-Item -Recurse -Force $t -EA SilentlyContinue
New-Item -ItemType Directory $t | Out-Null
Copy-Item build\* $t
cd $t
Get-ChildItem *.zip | ForEach-Object { Expand-Archive $_ -DestinationPath records -Force }
python read_sdat.py verify (Get-ChildItem records -Filter *.sdat).FullName | Select-String "^FAIL"
# expect: no output
```

Then confirm the manifest:

```powershell
Get-Content MANIFEST-SHA256.txt |
  Where-Object { $_ -match "^[0-9a-f]{64}  \w[-\w]*\.zip::" } |
  ForEach-Object {
    $h, $n = $_ -split "  ", 2
    $f = "records\" + ($n -split "::")[1]
    if ((Get-FileHash $f -Algorithm SHA256).Hash -ne $h.ToUpper()) { "MISMATCH $f" }
  }
# expect: no output
```

---

## 4. Upload to Zenodo

1. Sign in at <https://zenodo.org>. Add an ORCID first if you do not have one —
   it takes ten minutes, it is free, and a deposit without one is materially
   weaker. Link it under Profile → Linked accounts.

2. **New upload** → **Get a DOI now!** to reserve the DOI. Do not delete the
   draft afterwards; the reservation is lost with it.

3. Rebuild with the reserved DOI (§2) so it appears in the README, codebook and
   citation, then upload all 11 files from `build\`.

4. Metadata:

   | Field | Value |
   |---|---|
   | Resource type | Dataset |
   | Title | Static-bench gyroscope records for rate-register quantisation analysis: paired 16-bit register and 19-bit FIFO streams from two ICM-42688-P specimens |
   | Creators | Rhodes, James — *Independent researcher* — ORCID |
   | Description | §1 and §3 of the deposit `README.md` |
   | Licence | Creative Commons Attribution 4.0 International |
   | Version | 1.0.0 |
   | Language | English |
   | Keywords | MEMS gyroscope; quantisation noise; Allan variance; angle random walk; inertial sensor calibration; ICM-42688-P; truncating quantiser; sensor characterisation |

   Leave *Related identifiers* empty for now. Metadata stays editable forever,
   so the manuscript link can be added when there is one.

5. **Preview**, read it as a stranger, then **Publish**.

**Files are editable for 45 days after publishing. Metadata is editable
indefinitely.** So a metadata gap is cheap and a file mistake is not. After 45
days a file change means a new version with its own DOI.

---

## 5. Code DOI, later

Only after §0 is resolved and a public repository exists.

1. Zenodo → Profile → Linked accounts → connect GitHub.
2. Zenodo → GitHub → toggle the repository **On**.
3. On GitHub, draft a release and tag it:

```powershell
git tag -a v1.0.0 -m "Firmware, analysis tools and hardware as used for the dataset"
git push origin v1.0.0
```

4. Publish the release on GitHub. Zenodo ingests it and issues a DOI.
5. Edit the **data** deposit's metadata and add the code DOI under
   *Related identifiers* → `isSupplementedBy`. Add the reverse link on the code
   record.

---

## 6. After publishing

- Put the **concept** DOI on the CV and in the manuscript, not the version DOI.
  The concept DOI always resolves to the newest version; the version DOI pins
  one release.
- Fill the manuscript's data-availability statement with the concept DOI and
  the repository URL.
- New records later — the remaining run plan, a second campaign — are a **new
  version** of the same deposit, not a new record. Rebuild with
  `--version 1.1.0` and use *New version* on the Zenodo record.

---

## What the build produces

| File | |
|---|---|
| `sheppard-phase-sweep.zip` | 50 records |
| `sheppard-odr-sweep.zip` | 14 records |
| `sheppard-offset-calibration.zip` | 22 records |
| `sheppard-aaf-variation.zip` | 8 records |
| `summary.csv` | 282 rows, 22 columns |
| `read_sdat.py` | standalone reader |
| `CODEBOOK.md` | column definitions and derived quantities |
| `README.md` | deposit-level documentation |
| `MANIFEST-SHA256.txt` | hashes, including per-record inside each bundle |
| `LICENSE-DATA.txt` | CC-BY-4.0 |
| `LICENSE-CODE.txt` | MIT |

11 files, about 100 MB. Zenodo allows 100 files and 50 GB per record.
