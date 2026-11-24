from main import main


def test_main_runs(capsys):
    main()
    captured = capsys.readouterr()
    assert "Hello from cogs-118d-final-project!" in captured.out
