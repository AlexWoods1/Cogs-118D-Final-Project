import pytest

from main import main


def test_main_runs(capsys: pytest.CaptureFixture[str]) -> None:
    """Exercise the original project entry point."""
    main()
    # Capture stdout the same way a caller running the command would see it.
    captured = capsys.readouterr()
    assert "Hello from cogs-118d-final-project!" in captured.out
