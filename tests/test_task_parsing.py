"""Task understanding: which object goes into which container (needed to measure success)."""

import pytest

from dreamtool.scene import parse_task

UNDERSTOOD = [
    ("put apple into the bowl", ("apple", "bowl")),
    ("Put the banana on the plate", ("banana", "plate")),
    ("Pick up the Banana and put it on the green plate", ("banana", "plate")),
    ("place the water bottle in the bowl", ("water_bottle", "bowl")),
    ("put bottle in the bowl", ("water_bottle", "bowl")),
    ("Could you please pick up the apple and put it into the bowl?", ("apple", "bowl")),
    ("move the apple from the plate to the bowl", ("apple", "bowl")),
    ("drop the orange inside the big white bowl.", ("orange", "bowl")),
    ("put the banana on top of the plate", ("banana", "plate")),
    ("put the orange in the orange bowl", ("orange", "bowl")),
    ("put the apple into the orange bowl", ("apple", "bowl")),
    ("take the apple out of the bowl and put it on the plate", ("apple", "plate")),
    ("apple -> bowl", ("apple", "bowl")),
    ("PUT APPLES INTO THE BOWL", ("apple", "bowl")),
    ("Leg den Apfel in die Schüssel", ("apple", "bowl")),
    ("Lege die Banane auf den Teller", ("banana", "plate")),
]

NOT_UNDERSTOOD = [
    "wave hello",
    "put the apple next to the bowl",  # next to: no container goal
    "put the apple in front of the bowl",
    "take the apple out of the bowl",
    "put the red fruit into the bowl",  # no object named: cannot be measured
    "pick up the bowl",
    "put the apple on the table",
    "Do not place the apple in the bowl.",  # negated
    "don't put the banana on the plate",
    "Leg den Apfel nicht in die Schüssel",
    "Put the banana on the plate and then remove it",  # acts again after placing: no single final goal
    "put the apple in the bowl, then take it out again",
]

ALSO_UNDERSTOOD = [
    ("put the apple in the bowl next to the plate", ("apple", "bowl")),  # "next to" describes the bowl
    ("put the apple in the bowl please", ("apple", "bowl")),
]


@pytest.mark.parametrize("task,expected", ALSO_UNDERSTOOD)
def test_also_understood(task, expected):
    assert parse_task(task) == expected


@pytest.mark.parametrize("task", ["Pick up the Banana and put it on the green plate", "Leg den Apfel in die Schüssel"])
def test_test_suite_understands_natural_sentences(task):
    from dashboard.extensions.test_suite.evaluation import placement

    assert placement(task) == parse_task(task) is not None


@pytest.mark.parametrize("task,expected", UNDERSTOOD)
def test_understood(task, expected):
    assert parse_task(task) == expected


@pytest.mark.parametrize("task", NOT_UNDERSTOOD)
def test_not_understood(task):
    assert parse_task(task) is None
