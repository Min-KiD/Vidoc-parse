# Findings: what was settled for the table part

What the pipeline in `tables/` rests on, in short. Measured on three scanned Vietnamese financial reports (image only, no text layer); one of them has a human-checked answer key.

## Result

- On the report with an answer key: about 2 wrong cells per 1000, most of them only a tone mark or a capital; every amount right. The best single reader alone had about 20 times more wrong cells.
- On the two reports without a key, a random sample of rows read from the page image found no amount, dash or blank that differs.
- About 7 minutes for a 72-page report on one GPU and one CPU, with the same result as running the stages one after the other.

## Settled

1. **Each reader does only what it is good at.** MinerU2.5-Pro gives digits, dashes and columns. Gemini gives Vietnamese spelling and which printed lines form one row, nothing else. Box OCR (PP-OCRv6, CPU) tells which amounts are printed on the page.
2. **MinerU's grid is the base; a cell changes only with proof**: two readers agree against it, or a sum holds. Every rule names no file, page, company, column position or label text.
3. **Errors are in the structure, not the digits**: dropped dashes, two lines in one cell, wrapped labels split into rows, a total row or a column lost. The rules and the second read of a flagged table target these.
4. **Checks with a known equation, not discovered ones**: the legal forms' line-code sums and "every printed amount is in some cell". What cannot be repaired with proof is flagged for a person.
5. **Content and marks are scored apart**: a wrong number matters, a wrong tone mark much less.
6. **Speed without changing the reads**: stages that use different resources (GPU, CPU, network) run side by side and the model is loaded once; MinerU reads one page at a time, because more pages at once changes its reads.

## Not used

- Gemini as a source of numbers, dashes, columns or new rows.
- Sums discovered from the table as an error detector.
- PaddleOCR-VL as the base reader.
- A text-only model pass to fix diacritics (it also "fixes" misprints).

## Open

- Faults that are flagged but not repaired (a value column MinerU does not read, a label column outside the table), and a few no check sees (an empty printed column dropped, a dash dropped by both readers).
- Not tested on a report nobody has looked at, or on other forms (banks, insurers, Circular 99/2025).
- Joining with the text part: see `architecture_design.md` section 8.
