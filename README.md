# GDL vs Legacy EDI Comparison

Python tool that compares one GDL EDI file with one Legacy (Impulse / ECC) file and writes an Excel report. It supports:

- **X12 846** inventory (ISA/GS, ST–SE warehouse blocks, LIN/QTY)
- **X12 867** POS / resale (ISA/GS, PTD ship-to loops, QTY/LIN/UIT)
- **EDIFACT INVRPT** inventory (UNB/UNZ, UNH–UNT, LIN/LOC/QTY)

Each input can come from a **local file** or from the **SFTP server**. The command to run is always `compare_segments.py`.

## Project layout

| File | Role |
| --- | --- |
| `compare_segments.py` | CLI: local vs SFTP source selection, then run the compare |
| `run_comparison.bat` | Windows one-click launcher (Desktop shortcut target) |
| `install_desktop_shortcut.bat` | Creates **EDI Comparison** on the Windows Desktop |
| `run_comparison.sh` | macOS / Linux launcher |
| `edi846_compare.py` | GDL vs Legacy X12 846 comparison (N1 blocks, LIN/QTY) |
| `edi867_compare.py` | GDL vs Legacy X12 867 POS comparison (PTD ship-to, QTY/LIN) |
| `edifact_invrpt_compare.py` | GDL vs Legacy EDIFACT INVRPT comparison (LOC+SKU items, RFF/QTY) |
| `x12_format.py` | X12 format detection, vendor delimiters, segment splitting |
| `edifact_format.py` | EDIFACT UNA delimiters and segment splitting |
| `sftp_client.py` | SFTP login, folder listing, X12/EDIFACT download |
| `excel_report.py` | Comparison / Summary / GDL File / Legacy File workbooks |
| `cli_prompts.py` | Interactive MX/SG, INV/POS, and file menus |
| `data/` | Sample GDL / Legacy / POS / INVRPT dumps |
| `reports/` | Timestamped Excel output (created on first run) |
| `docs/x12_867_pos_layout.md` | X12 867 POS segment layout |

Format is detected from the file head (`ISA` vs `UNA`/`UNB`/`UNH`). Mixed X12 vs EDIFACT, or mixed 846 vs 867, pairs are not compared.

---

## Run from the Desktop (one click, Windows)

You do **not** need to open VS Code after the files are on disk. The launcher creates `.venv` and installs packages the first time it runs.

### Put a shortcut on the Desktop

1. Open this project folder in File Explorer (the folder that contains `run_comparison.bat`).
2. Double-click **`install_desktop_shortcut.bat`**.
3. Click through the prompt. It creates **EDI Comparison.lnk** on your Desktop.
4. Double-click **EDI Comparison** on the Desktop.

A black command window opens, then the same prompts as `python compare_segments.py`:

1. GDL input source — local file or SFTP  
2. Legacy input source — local file or SFTP  
3. Country (`MX` / `SG`) and report (`INV` / `POS`) if SFTP is used  
4. The GDL file and the Legacy file  

When it finishes, the window shows the Excel path under `reports\` and waits for a key press so you can read it.

Leave `run_comparison.bat` in the project folder. The Desktop item is only a shortcut; do not copy the `.bat` to the Desktop by itself.

### Other ways to start it

- Double-click `run_comparison.bat` in the project folder.
- Right-click `run_comparison.bat` → **Send to → Desktop (create shortcut)**.
- For the bundled samples only, create a Desktop shortcut whose target is:

  `C:\path\to\this\folder\run_comparison.bat --local`

macOS / Linux: double-click or run `./run_comparison.sh` from the project folder (first time: `chmod +x run_comparison.sh`).

Python 3.10+ must be installed and on PATH (Windows installer: tick **Add python.exe to PATH**). SFTP still needs a password in the window, or `SFTP_PASSWORD` already set in the environment.

---

## Run in Visual Studio Code (every step)

You need **Python 3.10 or later** and the **Python** extension for VS Code (`ms-python.python`).

### 1. Open this folder

1. Start Visual Studio Code.
2. **File → Open Folder…** and select the project root (the folder that contains `compare_segments.py`).
3. Wait until the Explorer shows `compare_segments.py`, `requirements.txt`, and `data/`.

If you cloned from GitHub first:

```powershell
git clone https://github.com/DeepakBhengra/EDI_Legacy_Comparison_v3.git
```

Then open that cloned folder in VS Code.

### 2. Open the integrated terminal

1. **Terminal → New Terminal**, or press `` Ctrl+` `` (backtick).
2. Confirm the prompt path is the project root (you should see `compare_segments.py` if you run `dir` on Windows or `ls` on macOS / Linux).
3. Use **PowerShell** on Windows. If the terminal opened as Command Prompt, click the `+` dropdown on the terminal panel and choose **PowerShell**.

### 3. Create a virtual environment

In that same terminal:

**Windows PowerShell**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activate script:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

The prompt should show `(.venv)` on the left.

### 4. Select the interpreter in VS Code

1. Press `Ctrl+Shift+P` (macOS: `Cmd+Shift+P`).
2. Run **Python: Select Interpreter**.
3. Choose the environment you just created:
   - Windows: `.venv\Scripts\python.exe`
   - macOS / Linux: `.venv/bin/python`
4. Confirm the status bar (bottom-right) shows that interpreter, for example `Python 3.12.x ('.venv': venv)`.

If VS Code asks **Do you want to install the recommended Python extension?**, choose **Install** and repeat this step.

### 5. Install dependencies with that same Python

Stay in the terminal that shows `(.venv)` and run:

```powershell
python -c "import sys; print(sys.executable)"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The first command must print a path **inside `.venv`**. If it prints `C:\Python312\python.exe` or `/usr/bin/python3`, go back to step 4 and select `.venv`.

Check the packages:

```powershell
python -m pip show paramiko xlsxwriter pytest
```

Each should list a `Location:` under `.venv`. Use `python -m pip install ...`, not `pip install ...`.

### 6. First run: bundled X12 846 samples (no SFTP)

This does not need a network or password.

```powershell
python compare_segments.py --local
```

What you should see:

1. Banner `EDI X12 846 / 867 / EDIFACT COMPARISON`
2. `Reading GDL segments from ...\data\GDL_Segment.txt`
3. `Reading Legacy segments from ...\data\Legacy_Segment.txt`
4. `Comparison complete` with MATCH / MISMATCH counts
5. `Excel report:` a path under `reports\` with a timestamp, for example `reports\segment_comparison_20261029_162100.xlsx`

Open that `.xlsx` from Explorer or from VS Code. Sheets are **Comparison**, **Summary**, **GDL File**, **Legacy File**.

### 7. Interactive run (pick local or SFTP for each file)

```powershell
python compare_segments.py
```

Answer each prompt by typing the number and pressing Enter.

| Step | Prompt | What to choose |
| --- | --- | --- |
| 1 | `Select GDL input source` | `[1] Local file` or `[2] SFTP server` |
| 2 | `Select Legacy input source` | Same or different from GDL |
| 3 | `Select Country Profile` | `[1] Mexico (MX)` or `[2] Singapore (SG)` — only if a side is SFTP |
| 4 | `Select Report Type` | `[1] Inventory (INV - EDI 846)` or `[2] Point of Sale (POS - EDI 867)` — only if a side is SFTP |
| 5 | `Select GDL file` | A file listed from `data/`, an SFTP folder, or **Enter a custom path** |
| 6 | `Select Legacy file` | Same idea for the Legacy side |
| 7 | `SFTP password:` | Only if you chose SFTP and `SFTP_PASSWORD` is not already set |

SFTP file lists show the detected format in brackets, for example `APPLE_846.txt  [X12]`. Choose **X12** or **EDIFACT**. Both sides must be the same format (and for X12, both 846 or both 867).

### 8. Compare two local files you already have

Put the files anywhere, or copy them into `data/`. Then either pick them in the interactive menu or pass paths:

```powershell
python compare_segments.py --gdl data\GDL_Segment.txt --legacy data\Legacy_Segment.txt
python compare_segments.py --gdl data\POS_x12_1015.txt --legacy data\POS_x12_1015.txt
python compare_segments.py --gdl data\EDIFACT_INVRPT_GDL.txt --legacy data\EDIFACT_INVRPT_GDL.txt
```

On macOS / Linux use forward slashes (`data/POS_x12_1015.txt`).

### 9. Run from SFTP (INV 846 or POS 867)

Default server: `venus.ingrammicro.com`, user `EDI_REPORT`. Folders:

- GDL: `/GDL/{MX|SG}/{INV|POS}`
- Legacy: `/ECC_IMPULSE/{MX|SG}/{INV|POS}`

Set the password in the **same** VS Code terminal (do not commit it):

**Windows PowerShell**

```powershell
$env:SFTP_PASSWORD = 'your-password'
python compare_segments.py --source sftp --country MX --report INV
```

**macOS / Linux**

```bash
export SFTP_PASSWORD='your-password'
python compare_segments.py --source sftp --country MX --report INV
```

You will still be asked which GDL file and which Legacy file to compare, unless you pass the names:

```powershell
python compare_segments.py --source sftp --country MX --report INV --gdl-file APPLE_846.txt --legacy-file APPLE_846.txt
python compare_segments.py --source sftp --country MX --report POS --gdl-file SAMSUNG_867.txt --legacy-file SAMSUNG_867.txt
```

`--report INV` uses the inventory (846 / INVRPT) folders. `--report POS` uses the point-of-sale (867) folders.

Compare every matching X12 or EDIFACT pair in those folders:

```powershell
python compare_segments.py --all --country MX --report INV
```

Optional overrides: `SFTP_HOST`, `SFTP_PORT`, `SFTP_USER`, `SFTP_PASSWORD`. You can also pass `--sftp-password` instead of an environment variable.

### 10. Find the Excel report

1. In Explorer, open the `reports` folder in this project.
2. Sort by date. Each run adds a timestamp to the name so older workbooks are kept.
3. Two-file runs have four sheets:
   1. **Comparison** — `GDL Segment`, `Legacy Segment`, `status` (orange = MISMATCH, red = missing)
   2. **Summary** — MATCH / MISMATCH / missing counts and block / item counts
   3. **GDL File** — original GDL segments used for the comparison
   4. **Legacy File** — original Legacy segments used for the comparison
4. `--all` writes **File Audit**, **Summary**, and one comparison sheet per vendor.

Default output path: `reports/segment_comparison.xlsx` (timestamp inserted automatically). Override with `-o`:

```powershell
python compare_segments.py --local -o reports\my_run.xlsx
```

### 11. Run the tests (optional)

```powershell
python -m pytest -q
```

You should see all tests pass.

---

## If you see `paramiko is required for SFTP`

Packages were installed with a different `pip` than the Python that runs the script. In the **same** VS Code terminal that shows `(.venv)`:

```powershell
python -c "import sys; print(sys.executable)"
python -m pip show paramiko
python -m pip install -r requirements.txt
python -c "import paramiko; print('ok', paramiko.__version__)"
python compare_segments.py --local
```

If `pip show paramiko` is still empty:

1. `Ctrl+Shift+P` → **Python: Select Interpreter** → `.venv\Scripts\python.exe` (Windows) or `.venv/bin/python` (macOS / Linux).
2. Open a **new** terminal so it picks up that interpreter.
3. Run `python -m pip install -r requirements.txt` again.

`paramiko` is only required for SFTP. Local files work without it (`python compare_segments.py --local`).

---

## Non-interactive command examples

Both files local:

```powershell
python compare_segments.py --gdl path\to\gdl.txt --legacy path\to\legacy.txt
python compare_segments.py --local
```

GDL local, Legacy from SFTP:

```powershell
python compare_segments.py --gdl data\POS_x12_1015.txt --legacy-source sftp --country MX --report POS --legacy-file SAMSUNG_867.txt
```

Both files from SFTP:

```powershell
python compare_segments.py --source sftp --country MX --report INV --gdl-file APPLE_846.txt --legacy-file APPLE_846.txt
```

---

## X12 846 matching rules

| Situation | GDL Segment | Legacy Segment | status | Row color |
| --- | --- | --- | --- | --- |
| `ISA` or `GS` contents are equal | line | line | `MATCH` | none |
| `ISA` or `GS` contents differ | line | line | `MISMATCH` | orange |
| `ST`–`SE` header (`ST`, `BIA`, `N1`, `N2`, `N3`, `N4`, `PER`, `CTT`, `SE`) equal | line | line | `MATCH` | none |
| Those header lines differ | line | line | `MISMATCH` | orange |
| GDL `LIN` exists in the same warehouse block before `CTT` | GDL `LIN`/`QTY` | matching Legacy `LIN`/`QTY` | `MATCH` | none |
| GDL `LIN` is not in that Legacy block | GDL `LIN`/`QTY` | blank | `Missing in Impulse` | red |
| Legacy `LIN`/`QTY` has no GDL pair in that block | blank | Legacy `LIN`/`QTY` | `Missing in GDL` | red |

`ST`–`SE` blocks with an `N1` warehouse line are paired by that `N1`. `LIN`/`QTY` pairs are matched by LIN content inside the paired block, even when the order differs.

## X12 867 POS matching rules

An 867 Point of Sale interchange is split into the ISA/GS envelope, one header (`BPT`, report `DTM`, distributor `N1*DS`), repeating `PTD*SD` loops, then `CTT`/`SE`.

| Situation | GDL Segment | Legacy Segment | status | Row color |
| --- | --- | --- | --- | --- |
| `ISA` / `GS` / `ST` / `BPT` / `CTT` / `SE` equal | line | line | `MATCH` | none |
| Those envelope or header lines differ | line | line | `MISMATCH` | orange |
| `PTD` found by ship-to `N1*ST` | GDL PTD + parties + items | matching Legacy PTD | see below | |
| Same SKU (`LIN`) inside that PTD; item order differs | GDL `QTY`/`LIN`/`UIT`/`PID`/`DTM` | matching Legacy item | `MATCH` | none |
| `QTY` (or `UIT` / `PID` / item `DTM`) differs after `LIN` match | GDL line | Legacy line | `MISMATCH` | orange |
| GDL ship-to or SKU has no Legacy pair | GDL segments | blank | `Missing in Impulse` | red |
| Legacy ship-to or SKU has no GDL pair | blank | Legacy segments | `Missing in GDL` | red |

`PTD` order does not matter. Item order inside a `PTD` does not matter. Mixed X12 846 vs 867 pairs are not compared.

Sample POS dump: `data/POS_x12_1015.txt`. Segment layout: `docs/x12_867_pos_layout.md`.

## EDIFACT INVRPT matching rules

An INVRPT interchange is split into the UNB/UNZ envelope, one or more UNH–UNT messages, and LIN item loops (product + location + quantities).

| Situation | GDL Segment | Legacy Segment | status | Row color |
| --- | --- | --- | --- | --- |
| `UNB` / `UNZ` / `UNH` / `BGM` / `UNT` contents are equal | line | line | `MATCH` | none |
| Those envelope or header lines differ | line | line | `MISMATCH` | orange |
| Header `NAD` / `DTM` matched by qualifier (`DS`, `MF`, `91`, …) | line | line | `MATCH` or `MISMATCH` | none / orange |
| Item found by location (`LOC`) + product id (`LIN` C212) | GDL item segments | matching Legacy item | see below | |
| Same SKU at the same location; `LIN` line numbers differ | `LIN+2++SKU:MF` | `LIN+1++SKU:MF` | `MATCH` | none |
| `QTY` (with its `RFF` group) amounts differ | GDL `QTY` | Legacy `QTY` | `MISMATCH` | orange |
| GDL item has no Legacy pair at that location+SKU | GDL `LIN`/`LOC`/`QTY` | blank | `Missing in Impulse` | red |
| Legacy item has no GDL pair | blank | Legacy `LIN`/`LOC`/`QTY` | `Missing in GDL` | red |

Item order does not matter. `QTY` rows stay attached to the preceding `RFF` (for example `RFF+AEN:1` / on-hand `QTY+17`, `RFF+AEN:2` / reserved `QTY+16`). Optional `PIA`, `IMD`, line-level `DTM`, `CUX`, and `UNS` are compared when present.

Sample INVRPT dump: `data/EDIFACT_INVRPT_GDL.txt`.

## Formatting notes

Remote X12 files are often wrapped. Before comparison each X12 interchange is split on the trading-partner segment terminator (Apple `?`, Cisco newline, Dell `¦`, and so on). If the vendor is not in the built-in table, separators are read from the `ISA` envelope.

EDIFACT files are split on the UNA segment terminator (`'` by default) when the interchange is wrapped, or kept as one segment per line for newline dumps such as `data/EDIFACT_INVRPT_GDL.txt`.
