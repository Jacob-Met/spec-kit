"""Regressions for exponent values in workflow expressions (#5073)."""

import pytest

from specify_cli.workflows.base import StepContext
from specify_cli.workflows.engine import WorkflowEngine
from specify_cli.workflows.expressions import evaluate_condition, evaluate_expression


@pytest.fixture
def ctx():
    return StepContext(inputs={"n": 5, "s": "1e3", "non_number": "nope"})


@pytest.mark.parametrize(
    "literal,expected",
    [
        ("1e3", 1000.0),
        ("-2E+2", -200.0),
        ("1_2e-1", 1.2),
        (".5E-1", 0.05),
        ("1_000", 1000),
    ],
)
def test_exponent_literals_have_numeric_type(ctx, literal, expected):
    value = evaluate_expression("{{ " + literal + " }}", ctx)
    assert value == expected
    assert type(value) is type(expected)


def test_exponent_strings_coerce_consistently_with_workflow_inputs(ctx):
    assert WorkflowEngine._coerce_input("s", "1e3", {"type": "number"}) == 1000
    assert evaluate_condition("{{ inputs.n < 1e3 }}", ctx)
    assert evaluate_condition("{{ inputs.s > 100 }}", ctx)
    assert evaluate_condition("{{ inputs.s == 1000 }}", ctx)
    assert not evaluate_condition("{{ inputs.non_number > 100 }}", ctx)


@pytest.mark.parametrize("literal", ["1e", "1e+", "1e_3", "1__0", "1_"])
def test_malformed_exponents_are_rejected(ctx, literal):
    with pytest.raises(ValueError, match="invalid expression"):
        evaluate_expression("{{ " + literal + " }}", ctx)
