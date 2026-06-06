"""Basic tests for pdf2md."""

from pdf2md.__main__ import main


def test_main_returns_zero():
    """Test that main returns 0."""
    assert main() == 0
