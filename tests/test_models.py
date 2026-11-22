from src.models import average_params, size_points


def test_points_thresholds():
    assert [size_points(x) for x in (3, 8, 8.1, 14, 17.5, 26, 33, 100, 151)] == [
        20,
        20,
        18,
        18,
        12,
        12,
        8,
        4,
        0,
    ]


def test_average_of_distinct_models_and_unknown():
    sizes = {"a": 3, "b": 32}
    assert average_params(["a", "b", "a"], sizes) == 17.5
    assert average_params(["a", "x"], sizes) is None
