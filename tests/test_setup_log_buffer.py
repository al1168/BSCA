from setup_gui.log_buffer import LineBuffer


def test_partial_write_buffers_no_callback():
    """A write without a newline buffers, fires no callback."""
    captured = []
    buf = LineBuffer(captured.append)
    buf.write("partial line, no newline yet")
    assert captured == []


def test_single_complete_line_fires_once():
    """A write ending in '\\n' fires the callback once with the line
    contents and no trailing newline."""
    captured = []
    buf = LineBuffer(captured.append)
    buf.write("hello\n")
    assert captured == ["hello"]


def test_multiple_lines_in_one_write_fire_in_order():
    """A multi-line write fires once per complete line, in order."""
    captured = []
    buf = LineBuffer(captured.append)
    buf.write("line one\nline two\nline three\n")
    assert captured == ["line one", "line two", "line three"]


def test_split_writes_assemble_correctly():
    """Lines split across multiple writes are reassembled."""
    captured = []
    buf = LineBuffer(captured.append)
    buf.write("first ")
    buf.write("half ")
    buf.write("of line\n")
    assert captured == ["first half of line"]


def test_flush_emits_trailing_partial_line():
    """A partial line buffered at flush() time is emitted as a line
    (without a trailing newline)."""
    captured = []
    buf = LineBuffer(captured.append)
    buf.write("no newline here")
    buf.flush()
    assert captured == ["no newline here"]


def test_flush_with_empty_buffer_is_noop():
    """Calling flush() with nothing buffered does nothing."""
    captured = []
    buf = LineBuffer(captured.append)
    buf.flush()
    assert captured == []


def test_close_calls_flush():
    """Closing flushes any partial trailing line."""
    captured = []
    buf = LineBuffer(captured.append)
    buf.write("last bit")
    buf.close()
    assert captured == ["last bit"]


def test_write_returns_byte_count_for_redirect_stdout_compatibility():
    """`contextlib.redirect_stdout` (and print) inspect write()'s
    return value as the number of characters written."""
    buf = LineBuffer(lambda _line: None)
    assert buf.write("hello") == len("hello")
    assert buf.write("\n") == 1


def test_carriage_return_lf_treated_as_one_line():
    """Windows-style \\r\\n endings produce one line without the \\r."""
    captured = []
    buf = LineBuffer(captured.append)
    buf.write("crlf line\r\n")
    assert captured == ["crlf line"]
