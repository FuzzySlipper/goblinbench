using System.Globalization;

namespace EvalLab.Core.Cases.ExpressionEvaluator;

public static class Evaluator
{
    // Baseline: strict left-to-right evaluation, no operator precedence.
    // "1 + 2 * 3" returns 9 instead of 7. Supports only +, -, *, / and parens.
    // Missing: precedence, right-associative ^, // (floor div), % (modulo),
    // unary +/-, functions (sin/cos/max/min), constants (pi/e), implicit
    // multiplication, and floor/Python-style semantics for // and %.
    public static double Evaluate(string expression)
    {
        var pos = 0;
        var value = EvalSequence(expression, ref pos);
        SkipWhitespace(expression, ref pos);
        if (pos < expression.Length)
        {
            throw new FormatException($"Unexpected character '{expression[pos]}' at position {pos}");
        }
        return value;
    }

    private static double EvalSequence(string s, ref int pos)
    {
        SkipWhitespace(s, ref pos);
        var value = ReadOperand(s, ref pos);
        while (true)
        {
            SkipWhitespace(s, ref pos);
            if (pos >= s.Length || s[pos] == ')') break;
            var op = s[pos++];
            SkipWhitespace(s, ref pos);
            var rhs = ReadOperand(s, ref pos);
            value = op switch
            {
                '+' => value + rhs,
                '-' => value - rhs,
                '*' => value * rhs,
                '/' => value / rhs,
                _ => throw new FormatException($"Unknown operator '{op}'")
            };
        }
        return value;
    }

    private static double ReadOperand(string s, ref int pos)
    {
        SkipWhitespace(s, ref pos);
        if (pos < s.Length && s[pos] == '(')
        {
            pos++;
            var inner = EvalSequence(s, ref pos);
            if (pos >= s.Length || s[pos] != ')') throw new FormatException("Missing ')'");
            pos++;
            return inner;
        }
        var start = pos;
        while (pos < s.Length && (char.IsDigit(s[pos]) || s[pos] == '.')) pos++;
        if (start == pos) throw new FormatException($"Expected number at position {pos}");
        return double.Parse(s.AsSpan(start, pos - start), CultureInfo.InvariantCulture);
    }

    private static void SkipWhitespace(string s, ref int pos)
    {
        while (pos < s.Length && char.IsWhiteSpace(s[pos])) pos++;
    }
}
