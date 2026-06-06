using EvalLab.Core.Cases.RomanNumerals;

namespace EvalLab.Tests.Visible;

public sealed class RomanNumeralsVisibleTests
{
    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "roman-numerals")]
    public void ToRoman_renders_one()
    {
        Assert.Equal("I", RomanNumerals.ToRoman(1));
    }

    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "roman-numerals")]
    public void ToRoman_uses_subtractive_form_for_four()
    {
        Assert.Equal("IV", RomanNumerals.ToRoman(4));
    }

    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "roman-numerals")]
    public void ToRoman_renders_a_typical_year()
    {
        Assert.Equal("MMXXIV", RomanNumerals.ToRoman(2024));
    }
}
