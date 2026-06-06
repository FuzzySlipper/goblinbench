using EvalLab.Core.Cases.ExpressionEvaluator;

namespace EvalLab.Tests.Strict;

public sealed class ExpressionEvaluatorStrictTests
{
    [Theory]
    [Trait("Suite", "Strict")]
    [Trait("Case", "expression-evaluator")]
    [InlineData("-7 // 2", -4d)]
    [InlineData("7 // 2", 3d)]
    [InlineData("7 // -2", -4d)]
    public void Evaluator_floor_division_floors_toward_negative_infinity(string expression, double expected)
    {
        Assert.Equal(expected, Evaluator.Evaluate(expression));
    }

    [Theory]
    [Trait("Suite", "Strict")]
    [Trait("Case", "expression-evaluator")]
    [InlineData("-7 % 2", 1d)]
    [InlineData("7 % -2", -1d)]
    public void Evaluator_modulo_takes_sign_of_divisor(string expression, double expected)
    {
        Assert.Equal(expected, Evaluator.Evaluate(expression));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "expression-evaluator")]
    public void Evaluator_unary_in_exponent_position()
    {
        Assert.Equal(0.25d, Evaluator.Evaluate("2 ^ -2"));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "expression-evaluator")]
    public void Evaluator_implicit_multiplication_with_constant()
    {
        Assert.Equal(2 * Math.PI, Evaluator.Evaluate("2pi"), 6);
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "expression-evaluator")]
    public void Evaluator_nested_function_calls()
    {
        Assert.Equal(3d, Evaluator.Evaluate("max(3, min(5, 2))"));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "expression-evaluator")]
    public void Evaluator_function_with_constant_argument()
    {
        Assert.Equal(1d, Evaluator.Evaluate("sin(pi / 2)"), 6);
    }
}
