using System.Text;

namespace EvalLab.Core.Cases.RomanNumerals;

public static class RomanNumerals
{
    public static string ToRoman(int value)
    {
        // Baseline: additive-only. Subtractive forms (IV, IX, XL, XC, CD, CM)
        // are missing, so 4 renders as "IIII", 9 as "VIIII", etc. Fix this.
        var builder = new StringBuilder();
        var remaining = value;

        while (remaining >= 1000) { builder.Append('M'); remaining -= 1000; }
        while (remaining >= 500)  { builder.Append('D'); remaining -= 500; }
        while (remaining >= 100)  { builder.Append('C'); remaining -= 100; }
        while (remaining >= 50)   { builder.Append('L'); remaining -= 50; }
        while (remaining >= 10)   { builder.Append('X'); remaining -= 10; }
        while (remaining >= 5)    { builder.Append('V'); remaining -= 5; }
        while (remaining >= 1)    { builder.Append('I'); remaining -= 1; }

        return builder.ToString();
    }
}
