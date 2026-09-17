import pytest

from evospaice import cli


def test_tree_build_dispatches_arguments(monkeypatch) -> None:
    received = []
    monkeypatch.setattr("evospaice.tree.centroid.main", lambda argv: received.append(argv) or 0)
    assert cli.main(["tree", "build", "--embeddings", "input.npz"]) == 0
    assert received == [["--embeddings", "input.npz"]]


def test_tree_compare_dispatches_arguments(monkeypatch) -> None:
    received = []
    monkeypatch.setattr(
        "evospaice.tree.compare_representations.main",
        lambda argv: received.append(argv) or 0,
    )
    assert cli.main(["tree", "compare", "--genus", "Papilio"]) == 0
    assert received == [["--genus", "Papilio"]]


def test_tree_evaluate_dispatches_arguments(monkeypatch) -> None:
    received = []
    monkeypatch.setattr(
        "evospaice.validate.whole_tree.main", lambda argv: received.append(argv) or 0
    )
    assert cli.main(["tree", "evaluate", "--inferred", "tree.nwk"]) == 0
    assert received == [["--inferred", "tree.nwk"]]


def test_tree_help_lists_bottom_up_commands(capsys) -> None:
    with pytest.raises(SystemExit, match="0"):
        cli.main(["tree", "--help"])
    output = capsys.readouterr().out
    assert all(command in output for command in ("build", "compare", "evaluate"))
