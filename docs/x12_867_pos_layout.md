# X12 867 POS layout (this file)

Source: `data/POS_x12_1015.txt`  
GDL vs Legacy compare: `edi867_compare.py` (PTD loops paired by ship-to `N1*ST`, items by `LIN`).  
Transaction: **ANSI X12 867** Product Transfer and Resale Report (Point of Sale).  
GS functional ID: `PT`. Version: `004010`.  
Sender: Ingram Micro Mexico (`004919486MX`). Receiver: Samsung (`SEM950215S98`).

This dump is **one ST–SE message**. Counts below are from this file, not the 867 maximums.

## Tree

```
ISA                              1     interchange header
  GS                             1     functional group (PT = 867)
    ST*867                       1     transaction set
      BPT                        1     beginning of product transfer / POS report
      DTM                        1     report date (091)
      N1*DS                      1     distributor / reporting location  ─┐
        N3                       1     street                            │ header party
        N4                       1     city / state / postal / country   ─┘
      PTD*SD                     1..n  sold-to / resale detail loop      ← repeats 104 times
        N1*ST                    1     ship-to customer                  ─┐
          N3                     0..1  street (missing on 1 dummy ST)    │ party pair
          N4                     1     city / state / postal / country   │ repeats once
        N1*BT                    1     bill-to / sold-to                 │ per PTD
          N3                     1                                       │
          N4                     1                                       ─┘
        ITEM                     1..n  product sold at this ship-to      ← repeats 158 times total
          QTY                    1     quantity
          LIN                    1     vendor part + manufacturer SKU
          UIT                    1     unit price (EA)
          PID                    1     free-text description
          DTM*003                1     invoice date
          DTM*011                1     ship date
      CTT                        1     control totals
      SE                         1     transaction trailer
    GE                           1     group trailer
IEA                              1     interchange trailer
```

## Repeating rules (as used here)

| Loop | Trigger segment | Repeats in this file | What one occurrence is |
| --- | --- | --- | --- |
| Interchange | `ISA` … `IEA` | 1 | Whole file |
| Group | `GS` … `GE` | 1 | One 867 batch |
| Transaction | `ST*867` … `SE` | 1 | One POS report |
| Header party | `N1*DS` | 1 | Ingram reporting location |
| **Resale / POS header** | **`PTD*SD`** | **104** | One ship-to / bill-to pair (a customer drop) |
| Party inside `PTD` | `N1*ST` then `N1*BT` | exactly 2 per `PTD` | Ship-to, then bill-to |
| **Line item inside `PTD`** | **`QTY`** | **1–31 per `PTD` (158 total)** | One SKU sold at that ship-to |

A new `PTD*SD` starts the next customer. A new `QTY` (without a new `PTD`) starts another SKU for the **same** ship-to / bill-to. Most `PTD` loops have one item (92 of 104). Twelve loops have 2, 3, 5, 7, or 31 items.

`N2`, `PER`, `REF`, `PO4`, `SLN`, and `UIT` sub-elements beyond unit/price do not appear in this file.

## Envelope

| Segment | Meaning | This file |
| --- | --- | --- |
| `ISA` | Interchange. Element separator `*`, sub-element `>`, segment `~`. | `ISA*00*…*01*004919486MX*ZZ*SEM950215S98*261016*2331*U*00401*000005625*0*P*>~` |
| `GS` | Group. `GS01=PT` = Product Transfer and Resale. | `GS*PT*004919486MX*SEM950215S98*20261016*2331*971*X*004010~` |
| `GE` | Group trailer. `GE01` = number of ST sets. | `GE*1*971~` |
| `IEA` | Interchange trailer. `IEA01` = number of GS groups. | `IEA*1*000005625~` |

## Header (once per ST)

### `ST` — transaction set header

`ST*867*0001~`

| Element | Value | Meaning |
| --- | --- | --- |
| ST01 | `867` | Product Transfer and Resale Report |
| ST02 | `0001` | Control number (matches `SE02`) |

### `BPT` — beginning of product transfer

`BPT*00*261016232504*20261016*02~`

| Element | Value | Meaning |
| --- | --- | --- |
| BPT01 | `00` | Original |
| BPT02 | `261016232504` | Report / reference number |
| BPT03 | `20261016` | Report date (CCYYMMDD) |
| BPT04 | `02` | Resale (POS) |

### `DTM` — report date (header)

`DTM*091*20261016~`

| Qualifier | Meaning here | Count |
| --- | --- | --- |
| `091` | Report / period date (same calendar day as ISA) | 1, header only |

### Header `N1` / `N3` / `N4` — distributor

```
N1*DS*INGRAM MICRO MEXICO*1*10~
N3*LAGUNA DE TERMINOS NO.249~
N4*MEXICO D.F.**11320*MX*WH*00~
```

| Segment | Qualifier | Meaning |
| --- | --- | --- |
| `N1*DS` | DS = distributor / reporting location | Name + ID qualifier `1` (DUNS-style) + ID `10` |
| `N3` | | Street |
| `N4` | | City, postal, country `MX`. Extra `WH*00` is Ingram warehouse coding on this DS row |

## Detail loop — `PTD` (repeats)

Each `PTD*SD` is one POS sale **location** (ship-to + bill-to), then one or more SKUs.

```
PTD*SD~
N1*ST*…*91*<Ingram account>~
N3*…~
N4*…~
N1*BT*…~
N3*…~
N4*…~
QTY*39*<qty>~          ┐
LIN**VP*<part>*MG*<SKU>~│  repeats for each
UIT*EA*<unit price>~    │  SKU at this
PID*X****<description>~ │  ship-to
DTM*003*<invoice date>~ │
DTM*011*<ship date>~    ┘
```

### `PTD` — product transfer and resale detail

`PTD*SD~`

| Element | Value | Meaning |
| --- | --- | --- |
| PTD01 | `SD` | Sold (POS / resale) |

104 occurrences. Always `SD` in this file.

### Parties inside `PTD` (always ST then BT)

| Segment | Qualifier | ID | Meaning |
| --- | --- | --- | --- |
| `N1*ST` | Ship-to | `91` + Ingram account (always present) | End customer / ship-to name |
| `N3` + `N4` | | | Ship-to address. **One** ST has no `N3` (dummy: `N4*DUMMY*ZZ*999999999*MX`) |
| `N1*BT` | Bill-to | name only (no ID qualifier in this file) | Sold-to / reseller. May differ from ST (drop-ship) |
| `N3` + `N4` | | | Bill-to address (always both in this file) |

`N4` layout: `N4*<city>*<state>*<postal>*<country>~`  
Country is always `MX`. State is the X12 code (`CX`, `EM`, `NL`, …).

## Item loop inside `PTD` (repeats)

Trigger: `QTY`. Always this order: `QTY` → `LIN` → `UIT` → `PID` → `DTM*003` → `DTM*011`.

### `QTY` — quantity sold / returned

| Qualifier | Meaning here | Count |
| --- | --- | --- |
| `39` | Units sold (POS quantity) | 157 |
| `76` | Return (one line only) | 1 |

`QTY*39*4~` → qualifier `39`, quantity `4`.

`CTT02` (1151) is the hash total of these quantity values.

### `LIN` — item identification

`LIN**VP*0B93621*MG*SM-X236BZSAMXO~`

| Element | Value | Meaning |
| --- | --- | --- |
| LIN01 | empty | No assigned line number |
| LIN02 / LIN03 | `VP` / vendor part | Ingram / vendor part (`0B93621`) |
| LIN04 / LIN05 | `MG` / manufacturer SKU | Samsung model (`SM-X236BZSAMXO`) |

All 158 lines use **`VP` + `MG`**.

### `UIT` — unit of measure and price

`UIT*EA*4930.28~`

| Element | Value | Meaning |
| --- | --- | --- |
| UIT01 | `EA` | Each |
| UIT02 | amount | Unit price |

### `PID` — product description

`PID*X****GALAXY-TAB-A11-PLUS 6GB 128GB  SYST~`

| Element | Value | Meaning |
| --- | --- | --- |
| PID01 | `X` | Free-form |
| PID05 | text | Description (padded / truncated to a fixed width in this dump) |

### Item `DTM` (always both, always this order)

| Qualifier | Meaning | Count |
| --- | --- | --- |
| `003` | Invoice date | 158 |
| `011` | Shipped / ship date | 158 |

## Trailer

```
CTT*158*1151~
SE*1683*0001~
GE*1*971~
IEA*1*000005625~
```

| Segment | This file | Meaning |
| --- | --- | --- |
| `CTT01` | `158` | Number of line items (`QTY` / `LIN` count) |
| `CTT02` | `1151` | Hash total of quantities |
| `SE01` | `1683` | Segment count from `ST` through `SE` inclusive |
| `SE02` | `0001` | Matches `ST02` |

## Segment inventory in this file

| Tag | Count | Role |
| --- | --- | --- |
| ISA, GS, ST, BPT, CTT, SE, GE, IEA | 1 each | Envelope / report header / trailer |
| DTM | 317 | 1 header `091` + 158× `003` + 158× `011` |
| N1 | 209 | 1 `DS` + 104 `ST` + 104 `BT` |
| N3 | 208 | Address line 1 (one ST omitted) |
| N4 | 209 | Geographic |
| PTD | 104 | Repeating POS location loop |
| QTY, LIN, UIT, PID | 158 each | Repeating item loop |

Total segments: **1687** (ISA through IEA). `SE01` = **1683** (ST through SE).
