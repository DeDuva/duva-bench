Write `/app/dedupe.py`, a command-line program:

```
python3 /app/dedupe.py <key-column> < input.csv > output.csv
```

It reads CSV on standard input and writes CSV on standard output, keeping the
**last** row for each value of the key column and preserving the order of first
appearance. The header row is preserved.

A missing key column exits 2 with a message on standard error and writes nothing
to standard output. Standard library only (`csv` is standard).
