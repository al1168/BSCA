"""Line-buffered file-like object used to forward stdout from the
backfill scripts into the Setup GUI's log area, one complete line at
a time. Pure stdlib — no Qt imports, so it unit-tests cheaply."""
from typing import Callable


class LineBuffer:
    """A minimal file-like that buffers writes until a newline arrives,
    then fires `on_line(line_text)` for each complete line (the
    trailing '\\n' is stripped; a trailing '\\r' is also stripped so
    CRLF endings produce one clean line). A partial line at flush()
    or close() time is emitted as its own line."""

    def __init__(self, on_line: Callable[[str], None]):
        self._on_line = on_line
        self._buf = ""

    def write(self, s: str) -> int:
        # Return value is required by the io.TextIOBase write() contract.
        # `print()` and `contextlib.redirect_stdout` don't inspect it, but
        # buffered adapters and any caller that assigns `n = f.write(...)`
        # do — return the character count to keep that contract intact.
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.endswith("\r"):
                line = line[:-1]
            self._on_line(line)
        return len(s)

    def flush(self) -> None:
        if self._buf:
            self._on_line(self._buf)
            self._buf = ""

    def close(self) -> None:
        self.flush()
