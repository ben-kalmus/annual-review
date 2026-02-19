#!/usr/bin/env python3
"""
Reads a CSV file and outputs it with duplicate column headers renamed
by appending _2, _3, ... so that miller (mlr) can process them by name.

Usage:
    python3 dedup_csv_headers.py input.csv          # writes to stdout
    python3 dedup_csv_headers.py input.csv | mlr ...
"""
import csv
import sys

path = sys.argv[1] if len(sys.argv) > 1 else None
fh = open(path, newline="") if path else sys.stdin

reader = csv.reader(fh)
writer = csv.writer(sys.stdout)

headers = next(reader)

seen: dict[str, int] = {}
deduped: list[str] = []
for h in headers:
    if h in seen:
        seen[h] += 1
        deduped.append(f"{h}_{seen[h]}")
    else:
        seen[h] = 1
        deduped.append(h)

writer.writerow(deduped)
for row in reader:
    writer.writerow(row)
