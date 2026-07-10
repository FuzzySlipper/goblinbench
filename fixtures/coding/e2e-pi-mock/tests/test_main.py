from src.main import add, sub


def test_add_is_preserved() -> None:
    assert add(3, 2) == 5


def test_sub_is_added() -> None:
    assert sub(3, 2) == 1
