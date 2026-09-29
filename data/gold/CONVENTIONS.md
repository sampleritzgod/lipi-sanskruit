# Transcription conventions (gold set)

Every CER number in this project is measured against these transcriptions. If two people follow different rules, the score measures the rules, not the model. So: **one rulebook, and when in doubt, ask and add the answer here.**

## The basic rule: diplomatic transcription

Type **what the scribe wrote**, in modern Unicode Devanagari. Do not type what the text *should* say.

| Situation | Do | Don't |
|---|---|---|
| Scribe's spelling mistake | Type it as written | Correct it |
| Words run together (no spaces) | Type without spaces | Add word breaks |
| Scribe left a visible gap | One space | Several spaces |
| पृष्ठमात्रा (vowel stroke before the letter, e.g. for के, को) | Type the modern form: के, को | Type the stroke as a separate letter |
| Anusvara ं vs. nasal consonant (अंग / अङ्ग) | Exactly as written | Normalise either way |
| ऽ avagraha | ऽ | Leave it out |
| Dandas | । and ॥ as written | ASCII `|` or `||` |
| Numerals | Devanagari digits (१२३) | ASCII digits (123) |

## Unclear text

| Situation | Markup | Example |
|---|---|---|
| You are fairly sure but not certain of a letter | `[..]` around it | `तस्य[भ्रा]ता` |
| One akshara you cannot read | `[?]` | `[?]गबाहु` |
| A damaged/missing stretch (hole, stain, torn) | `[...]` | `राजा [...] तस्य` |
| Whole line unreadable | Press **Alt+S** (skip) | |

## Leave out (for now)

- Marginal notes, later additions in the margins, library stamps and numbers. These are outside the main text block, and the line cutter already excludes them.
- Page/folio numbers in the corners.
- Red decorative marks and ruling lines.

If a line crop includes pieces of the line above or below, type only the **main line** the crop is centred on.

## Typing

- Use a Unicode Devanagari keyboard: macOS System Settings → Keyboard → Input Sources → add **Devanagari – QWERTY** (or **Hindi – InScript**).
- Never type Gujarati letters, even though they look similar (त/ત, र/ર). The tool flags these, and a flagged line must be fixed before it counts.
- The tool also flags ASCII digits, Latin letters, doubled spaces and unbalanced `[ ]`.

## Open questions (decide with the corrector, then write the answer here)

1. How do we record scribal corrections: a crossed-out akshara, or an insertion marked with a kakapada (^)?
2. Do we keep the scribe's `ब`/`व` confusion as written, or should we note both?
3. How do we transcribe the old form of `ख` that looks like `ष`? (Rule so far: type what the letter *is* in this hand, i.e. ख.)
