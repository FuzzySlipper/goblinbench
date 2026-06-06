using EvalLab.Core.Cases.ExpressionEvaluator;

namespace EvalLab.Tests.Visible;

public sealed class ExpressionEvaluatorVisibleTests
{
    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "expression-evaluator")]
    public void Evaluator_respects_multiplicative_precedence()
    {
        Assert.Equal(7d, Evaluator.Evaluate("1 + 2 * 3"));
    }

    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "expression-evaluator")]
    public void Evaluator_exponent_is_right_associative()
    {
        Assert.Equal(512d, Evaluator.Evaluate("2 ^ 3 ^ 2"));
    }

    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "expression-evaluator")]
    public void Evaluator_handles_implicit_multiplication_before_paren()
    {
        Assert.Equal(14d, Evaluator.Evaluate("2(3 + 4)"));
    }

    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "expression-evaluator")]
    public void Evaluator_handles_stacked_unary_minus()
    {
        Assert.Equal(3d, Evaluator.Evaluate("--3"));
    }
}
