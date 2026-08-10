Write `/app/normalize.py`, a command-line program that reads one JSON document
from standard input and writes a normalized form of it to standard output.

Normalized means:

- object keys sorted at every depth
- two-space indentation
- a single trailing newline
- UTF-8 output, with non-ASCII characters written as themselves rather than as
  `\u` escapes

Invalid JSON on standard input must print `invalid json` to standard error and
exit with status 2. Nothing else may be written to standard output in that case.

Do not add dependencies; the standard library is enough.
