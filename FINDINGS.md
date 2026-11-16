# Findings: what was tried for the table part, and what it showed

Short record of the experiments behind the pipeline in `tables/` (2026-11-10 to 2026-11-16), so that nothing here is tried again by mistake. The experiment code, answer keys, review pages and full reports stay outside this repository; only the final pipeline is here. Experiment numbers (E1 to E14) are the ones the code comments cite.

Test documents: three scanned Vietnamese Q3/2025 financial reports, image only, no text layer. VIC (72 pages, amounts in millions of VND, 19 pages sideways), DXG (54 pages, colour JPEG pages), NVL (90 pages, pages stored as many image pieces, amounts up to 15 digits). Number format: `83.455.099` (dot = thousands), `(130.770)` negative, `-` nil.

## 1. Result

- **VIC, against a human-checked answer key** (48 table pages, 3869 cells): 8 wrong cells, 3 of them content (two dashes no reader has, one letter the print does not settle) and 5 only tone marks or capitals. MinerU alone: 168 wrong (69 content). Gemini alone: 279 (274). PaddleOCR-VL alone: 353 (108). All 1274 amount cells are right.
- **DXG and NVL, no answer key:** a random sample of 60 rows per file, read from the page image by a separate model that did not see the output: no amount, dash or blank differs. What differs: one missing label, tone marks in rows not yet joined, and two faults no check sees (below).
- **Flags** (places a person should look): VIC 52, DXG 88, NVL 166.

## 2. Experiments

| # | what was tried | what it showed | kept? |
|---|---|---|---|
| E1 | Gemini reads the tables, PP-OCRv5 reads the digits, the table's own sums decide | Gemini read every non-zero number but dropped 101 of 124 printed dashes and invented 5 values in a row of dashes. Sums caught the 5 inventions and none of the lost dashes. Sums confirm, they do not find errors. | sums only as a check |
| E2 | Open models on the GPU: PaddleOCR-VL-1.6 against MinerU2.5-Pro, all 72 pages | Same digits everywhere. Labels exact: MinerU 92.3%, Paddle 74.6% (diacritics). MinerU 3.6 s/page, Paddle 18.3 s/page. | MinerU as the base reader |
| E3 | Gemini as a second reader against MinerU | Catches MinerU's real faults, but drops dashes and shifts numbers one column (false alarms). Its row labels are better. | Gemini for text only |
| E4-E5, E9 | Answer key: readers' agreement, then disputes read from crops, then two rounds of human checking with each question drawn on the crop | 50 of 50 sampled agreed cells right. The page has misprints; the key keeps the print. Without the question drawn on the image the checker could not find the cell. | (evaluation) |
| E6 | workflow v1: MinerU numbers, Gemini text on every joined row | Fixed 79 cells, broke 67: Gemini repeats names, names unlabelled subtotals, adds "Trong đó:". | no |
| E7 | Rule 1 (two amounts glued in one cell) and rule 2 (Gemini's text only when the same letters and digits, ratio ≥ 0.9) | 137 → 46 wrong cells | yes |
| E8 | Step 3: merge wrapped MinerU rows the way Gemini groups them, text only moved | 44 of 44 row regions right | yes |
| E10 | Parser fix for escaped `\|`; rule 3 (wrong thousands separator); step 4 (a total row only Gemini has, taken when it equals the sum above) | 21 → 10 wrong cells | yes |
| E11 | Checks without an answer key: coverage (every amount box OCR reads must be in a cell), the legal forms' line-code sums (B01/B02/B03), counting ink marks for dashes, MinerU's crop resolution | Coverage found both missing totals, no false alarm. Form sums: 90 of 90 pass, 0 false alarms, where discovered sums gave 17 false alarms. Dash counting: 113 of 181, unusable. Crop resolution does not explain MinerU's errors. | coverage and form sums |
| E12 | Two new reports run blind | New MinerU faults: a value column not read (NVL p11), one misread digit (NVL p44), label columns left outside the table (NVL p82, DXG p44), lines under the table box. Rule 2 wrote item numbers twice (77 cells). Old flags were mostly noise. | led to E13 |
| E13 | Item number fix (`own_part`); checks as flags; rule 4 (digit vote: box OCR + Gemini against MinerU); second MinerU read of a flagged table from a wider crop; text join for rows without amounts | Digit fixed; 6 of 11 flagged tables repaired by the second read (3 total rows, 3 label columns), nothing lost; 96 / 106 more rows joined on DXG / NVL. Flags 102 / 528 / 659 → 52 / 88 / 166. | yes |
| E13 | MinerU's capitals inside rule 2 | 2 cells right, 1 right → wrong on VIC. Gate was "no right → wrong". | no |
| E14 | Random sample of rows read from the page by a model that sees only the image | Equals the human key on 173 of 173 VIC cells; finds faults no check sees. Cheapest answer key for new files. | as the test method |

## 3. Lessons

1. **Split the job by what each reader is good at.** MinerU: digits, dashes, columns. Gemini: Vietnamese spelling and which printed lines form one row. Box OCR: which amounts are printed on the page. Nothing else from Gemini is safe.
2. **Digits are rarely the problem; structure is.** Dropped dashes, two printed lines in one cell, wrapped labels split into rows, a total row or a column lost.
3. **Two readers that agree can share a fault** (MinerU and Paddle both glue amounts, both miss the same totals).
4. **A known equation beats a discovered one.** Form line-code sums: no false alarm. Discovered row/column sums: wrong rules on multi-page and cash-flow statements.
5. **Box OCR is a poor reader and a good witness.** As a table reader it is right on 80% of cells; asked only "which amounts are on this page" it finds rows and columns the main reader lost. It sees almost no dashes (1 of 534 dash cells).
6. **Missing totals are a layout fault**: MinerU's table box ends above the total line. A second read from a wider crop repairs it.
7. **A rule tuned on one file can add errors on the next** (rule 2 and item numbers). Rules here name no file, page, company, column position or label text.
8. **Forms have a sign habit**: VIC and DXG print deductions as plain numbers, NVL as negatives; the form check accepts both.
9. **Measure a claim from a config file on the real pages** before acting on it (the "tables are read at 150 dpi" claim was wrong: minimum 164 dpi, no link to errors).
10. **Score content and marks apart.** A wrong tone mark matters little; a wrong or missing number matters a lot.

## 4. Not worth trying again

- Gemini as a source of numbers, dashes, columns or new content (E1, E3, E6).
- Discovered sums as an error detector (E1, E11).
- Counting ink marks for dashes (E11).
- PaddleOCR-VL as the base reader (E2).
- MinerU's capitals in rule 2 (E13).
- Reading several times with one model, stated confidence, or an LLM judge as the flag; a text-only LLM pass to fix diacritics (it also "fixes" misprints); super-resolution or dewarping on flat scans; a table-cell detector as referee.

## 5. Open

- **Flagged, not repaired:** a value column MinerU does not read (NVL p11); a label column the second read does not bring back (DXG p44); lines under a table that are not a total (DXG p38); two text lines glued in one cell (DXG p39, p43).
- **No flag sees it:** an empty printed column that MinerU drops, which shifts the header (NVL p13); a heading over the whole row placed in the first column; a dash dropped by both MinerU and Gemini.
- **Not tested:** a fourth report nobody has looked at; rules 1 and 3 fired on VIC only.
- **Next ideas, untried:** MinerU's own token scores (`scored=True`) as a witness for dashes; vendor line items (vnstock) as a free answer key for the three statements; a second formula table for reports under Circular 99/2025 (from 2026); other industries (banks, insurers) use other forms.
- **Joining with the text part:** output format, where a table sits among the text blocks of its page, tables that run over several pages. See `architecture_design.md` section 8.
