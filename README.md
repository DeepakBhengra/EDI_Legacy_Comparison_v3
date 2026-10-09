# GDL vs Legacy X12 Comparison

Python tool that compares one GDL EDI X12 file with one Legacy (Impulse / ECC) X12 file and writes an Excel report.

Each input can come from a **local file** or from the **SFTP server**. Comparison rules are unchanged: ISA/GS once, `ST`–`SE` blocks paired by the `N1` warehouse line, and `LIN`/`QTY` matched by LIN content inside that block.

## Project layout

| File | Role |
| --- | --- |
| `compare_segments.py` | CLI: local vs SFTP source selection, then run the 846 compare |
| `edi846_compare.py` | GDL vs Legacy X12 846 comparison (N1 blocks, LIN/QTY) |
| `x12_format.py` | X12 format detection, vendor delimiters, segment splitting |
| `sftp_client.py` | SFTP login, folder listing, X12 download |
| `excel_report.py` | Comparison / Summary / GDL File / Legacy File workbooks |
| `cli_prompts.py` | Interactive MX/SG, INV/POS, and file menus |

`python compare_segments.py` is still the command to run.

## Matching rules

| Situation | GDL Segment | Legacy Segment | status | Row color |
| --- | --- | --- | --- | --- |
| `ISA` or `GS` contents are equal | line | line | `MATCH` | none |
| `ISA` or `GS` contents differ | line | line | `MISMATCH` | orange |
| `ST`–`SE` header (`ST`, `BIA`, `N1`, `N2`, `N3`, `N4`, `PER`, `CTT`, `SE`) equal | line | line | `MATCH` | none |
| Those header lines differ | line | line | `MISMATCH` | orange |
| GDL `LIN` exists in the same warehouse block before `CTT` | GDL `LIN`/`QTY` | matching Legacy `LIN`/`QTY` | `MATCH` | none |
| GDL `LIN` is not in that Legacy block | GDL `LIN`/`QTY` | blank | `Missing in Impulse` | red |
| Legacy `LIN`/`QTY` has no GDL pair in that block | blank | Legacy `LIN`/`QTY` | `Missing in GDL` | red |

## How to run

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

In VS Code / Cursor, press `Ctrl+Shift+P` → **Python: Select Interpreter** → choose `.venv`.

### If you see `paramiko is required for SFTP`

Packages were installed with a different `pip` than the Python that runs the script. In the **same** terminal that shows `(.venv)`, run:

```powershell
python -c "import sys; print(sys.executable)"
python -m pip show paramiko
python -m pip install -r requirements.txt
python -c "import paramiko; print('ok', paramiko.__version__)"
python compare_segments.py
```

Use `python -m pip install ...`, not `pip install ...`.

If `pip show paramiko` is still empty, the editor is using another interpreter. Select `.venv\Scripts\python.exe` (Windows) or `.venv/bin/python` (macOS / Linux), then install again.

`paramiko` is only required for SFTP. Local files work without it:

```powershell
python compare_segments.py --local
```

### Interactive: pick local or SFTP for each file

```bash
export SFTP_PASSWORD='your-password'   # only needed if a file comes from SFTP
python compare_segments.py
```

You will be asked:

1. **GDL input source** — local file or SFTP server
2. **Legacy input source** — local file or SFTP server (can differ from GDL)
3. If SFTP is used: country (`MX` / `SG`) and report (`INV` / `POS`)
4. The GDL file, from `data/` or from `/GDL/{country}/{report}`
5. The Legacy file, from `data/` or from `/ECC_IMPULSE/{country}/{report}`

SFTP file lists show the detected format. Only **X12** files can be selected.

### Non-interactive examples

Both files local:

```bash
python compare_segments.py --gdl path/to/gdl.txt --legacy path/to/legacy.txt
python compare_segments.py --local
```

Both files from SFTP:

```bash
python compare_segments.py --source sftp --country MX --report INV \
  --gdl-file APPLE_846.txt --legacy-file APPLE_846.txt
```

Mixed (GDL local, Legacy SFTP):

```bash
python compare_segments.py --gdl path/to/gdl.txt --legacy-source sftp \
  --country MX --report INV --legacy-file APPLE_846.txt
```

Compare every matching X12 pair on SFTP (older bulk audit):

```bash
python compare_segments.py --all --country MX --report INV
```

Optional overrides: `SFTP_HOST`, `SFTP_PORT`, `SFTP_USER`, `SFTP_PASSWORD`.

## Excel report

A two-file comparison writes four sheets, in this order:

1. **Comparison** — `GDL Segment`, `Legacy Segment`, `status`
2. **Summary** — MATCH / MISMATCH / missing counts and ST–SE block counts
3. **GDL File** — original GDL segments used for the comparison
4. **Legacy File** — original Legacy segments used for the comparison

`--all` still writes **File Audit**, **Summary**, and one comparison sheet per vendor.

A timestamp is added to the output name so older workbooks are not overwritten.

## X12 formatting

Remote files are often wrapped. Before comparison each X12 interchange is split on the trading-partner segment terminator (Apple `?`, Cisco newline, Dell `¦`, and so on). If the vendor is not in the built-in table, separators are read from the `ISA` envelope.

## Optional tests

```bash
python -m pytest -q
```
