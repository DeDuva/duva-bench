Write `/app/summarize.py`, a command-line program that reads
log lines on standard input and writes one JSON object to standard output:

```
2026-08-07T10:00:00Z INFO  starting
2026-08-07T10:00:01Z ERROR db unreachable
```

The object holds:

- `counts`: number of lines per level, e.g. `{"INFO": 1, "ERROR": 1}`
- `first_error`: the message of the first `ERROR` line, or `null` if there is none
- `malformed`: how many lines did not match the format

Keys sorted, one trailing newline. A line is well-formed if it is an ISO-8601
timestamp, whitespace, an uppercase level, whitespace, and a message. Standard
library only.
