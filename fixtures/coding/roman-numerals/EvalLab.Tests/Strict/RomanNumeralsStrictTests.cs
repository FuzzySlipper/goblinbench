using EvalLab.Core.Cases.RomanNumerals;

namespace EvalLab.Tests.Strict;

public sealed class RomanNumeralsStrictTests
{
    [Theory]
    [Trait("Suite", "Strict")]
    [Trait("Case", "roman-numerals")]
    [InlineData(9, "IX")]
    [InlineData(40, "XL")]
    [InlineData(90, "XC")]
    [InlineData(400, "CD")]
    [InlineData(900, "CM")]
    public void ToRoman_emits_subtractive_pairs(int value, string expected)
    {
        Assert.Equal(expected, RomanNumerals.ToRoman(value));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "roman-numerals")]
    public void ToRoman_renders_mixed_value()
    {
        Assert.Equal("LVIII", RomanNumerals.ToRoman(58));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "roman-numerals")]
    public void ToRoman_renders_max_supported_value()
    {
        Assert.Equal("MMMCMXCIX", RomanNumerals.ToRoman(3999));
    }

    [Theory]
    [Trait("Suite", "Strict")]
    [Trait("Case", "roman-numerals")]
    [InlineData(0)]
    [InlineData(-1)]
    [InlineData(4000)]
    public void ToRoman_rejects_out_of_range_values(int value)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => RomanNumerals.ToRoman(value));
    }
}
