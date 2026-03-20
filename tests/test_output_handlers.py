"""Tests for output handler implementations."""

from pygit_sync import BufferedOutputHandler, ConsoleOutputHandler, NullOutputHandler


class TestNullOutputHandler:
    """NullOutputHandler should accept all calls silently."""

    def test_info(self):
        handler = NullOutputHandler()
        handler.info("test")
        handler.info("test", indent=2)

    def test_success(self):
        handler = NullOutputHandler()
        handler.success("test")
        handler.success("test", indent=1)

    def test_warning(self):
        handler = NullOutputHandler()
        handler.warning("test")
        handler.warning("test", indent=1)

    def test_error(self):
        handler = NullOutputHandler()
        handler.error("test")
        handler.error("test", indent=1)

    def test_section(self):
        handler = NullOutputHandler()
        handler.section("title")

    def test_debug(self):
        handler = NullOutputHandler()
        handler.debug("test")


class TestConsoleOutputHandler:
    def test_info_prints(self, capsys):
        handler = ConsoleOutputHandler()
        handler.info("hello")
        captured = capsys.readouterr()
        assert "hello" in captured.out

    def test_info_with_indent(self, capsys):
        handler = ConsoleOutputHandler()
        handler.info("hello", indent=2)
        captured = capsys.readouterr()
        assert captured.out.startswith("    ")  # 2 * "  "

    def test_section_prints(self, capsys):
        handler = ConsoleOutputHandler()
        handler.section("My Section")
        captured = capsys.readouterr()
        assert "My Section" in captured.out
        assert "---" in captured.out

    def test_debug_verbose(self, capsys):
        handler = ConsoleOutputHandler(verbose=True)
        handler.debug("debugging")
        captured = capsys.readouterr()
        assert "debugging" in captured.out

    def test_debug_non_verbose(self, capsys):
        handler = ConsoleOutputHandler(verbose=False)
        handler.debug("debugging")
        captured = capsys.readouterr()
        assert captured.out == ""


class TestBufferedOutputHandler:
    """BufferedOutputHandler collects messages for deferred printing."""

    def test_info_buffered(self):
        handler = BufferedOutputHandler()
        handler.info("hello")
        assert len(handler.messages) == 1
        assert "hello" in handler.messages[0]

    def test_info_with_indent(self):
        handler = BufferedOutputHandler()
        handler.info("hello", indent=2)
        assert handler.messages[0].startswith("    ")  # 2 * "  "

    def test_success_buffered(self):
        handler = BufferedOutputHandler()
        handler.success("ok")
        assert len(handler.messages) == 1
        assert "ok" in handler.messages[0]

    def test_warning_buffered(self):
        handler = BufferedOutputHandler()
        handler.warning("warn")
        assert len(handler.messages) == 1
        assert "warn" in handler.messages[0]

    def test_error_buffered(self):
        handler = BufferedOutputHandler()
        handler.error("err")
        assert len(handler.messages) == 1
        assert "err" in handler.messages[0]

    def test_section_buffered(self):
        handler = BufferedOutputHandler()
        handler.section("Title")
        assert len(handler.messages) == 3  # blank line, title, separator
        assert "Title" in handler.messages[1]
        assert "---" in handler.messages[2]

    def test_debug_suppressed(self):
        handler = BufferedOutputHandler()
        handler.debug("debug msg")
        assert len(handler.messages) == 0

    def test_flush_to(self, capsys):
        handler = BufferedOutputHandler()
        handler.info("line1")
        handler.info("line2")
        target = ConsoleOutputHandler()
        handler.flush_to(target)
        captured = capsys.readouterr()
        assert "line1" in captured.out
        assert "line2" in captured.out
        assert len(handler.messages) == 0  # cleared after flush
