# The rubric: WCAG 2.2, levels A and AA

This file is yours: the inspector's judge reads it on every look. Change what counts, add
your own criteria, or replace it with a rubric of your own (brand, layout, anything a
picture can show). The judge may cite as "fails" or "measure" only an id listed under
Criteria; everything else it sees is "other".

## Criteria

- 2.4.7 Focus Visible (AA): the focused control is visibly marked. Fails when no mark shows, or when what is left of the mark no longer reads as focus. A mark clipped at one edge that still reads as a mark passes (clipping is 2.4.13, level AAA: not a failure here).
- 2.4.11 Focus Not Obscured (Minimum) (AA): the focused control is not entirely hidden by other content (a sticky bar, a footer, a toast). About the control, not its mark; partly covered passes.
- 2.4.3 Focus Order (A): after a step, focus lands where the user cannot follow, when the page moved or removed what had focus.
- 1.4.11 Non-text Contrast (AA): focus marks, control boundaries and state marks (a switch's on and off, a checkbox) need 3:1 against what is next to them.
- 1.4.3 Contrast (Minimum) (AA): text needs 4.5:1 (3:1 at 24px, or 18.66px bold). Placeholder text counts. Text of a truly disabled control, and decoration, are exempt.
- 1.4.1 Use of Color (A): a link inside text is told apart by more than colour, or by 3:1 against the text.
- 1.4.13 Content on Hover or Focus (AA): content that does appear on hover or focus stays and can be dismissed. A tooltip that never appears is not this criterion.
- 2.5.8 Target Size (Minimum) (AA): a target under 24x24 CSS px needs spacing so that a 24px circle on it touches no other target. Judge it only when the size is plain from the picture.
- 3.3.1 Error Identification (A): an error is identified and described in text. A text message passes, even if the field's border does not turn red.
- 3.3.2 Labels or Instructions (A): a required field is marked as required where it is shown.

## Rulings

- A disabled control may be focusable (aria-disabled); then only a missing mark is a finding.
- A focus mark shown after a mouse click is allowed.
- Two marks at once is a usability problem ("other"), not a failure, as long as the focused control is marked.
- A colour cannot be measured exactly from a picture: a contrast finding judged by eye is "measure", unless the gap is obvious (text barely distinguishable from its background).
- Never "fails" on a level AAA criterion or on anything outside the list above.
