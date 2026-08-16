# AI writing tells — a self-check for every writing skill

Adapted from [blader/humanizer](https://github.com/blader/humanizer) (MIT), itself
built on Wikipedia's [Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)
guide. Condensed for Thelivu: this is a checklist a pipeline-function skill runs on
its own draft before emitting the final structured output — not a separate
conversational rewrite step, and not a license to add anything CHARTER.md or the
skill you're reading this from doesn't already allow. **Where this file and the
skill you're in disagree, the skill wins** — this is a bug-catcher, not a style
authority. In particular: Thelivu's no-fabrication rule is already stricter than
the source's (no invented facts, full stop — the source's "voice/personality"
allowance for opinions does not extend permission to add anything article-writer
or video-script wouldn't already sanction).

## Before emitting output, scan the draft for these clusters

A single hit means nothing. Several together is the tell — that's when to rewrite.

- **Inflated significance** — "stands/serves as a testament to", "marks a pivotal
  moment", "underscores its importance", "reflects a broader trend". Cut the
  puffery; state what happened.
- **-ing tacked-on fake depth** — "…, highlighting/underscoring/reflecting X."
  Usually deletable with no loss.
- **Promotional language** — "vibrant", "rich", "boasts", "renowned", "nestled in
  the heart of", "groundbreaking". Thelivu already forbids this in spirit
  (neutrality/symmetry check); this is the vocabulary list for it.
- **Vague attribution** — "experts believe", "observers have cited", "industry
  reports suggest" with no named source. Thelivu's charter already requires named
  sources for load-bearing facts — this is the same rule from the phrasing side.
- **Formulaic "Challenges and Future Prospects"** sections, or upbeat non-answers
  as a close ("the future looks bright"). End on the last concrete fact instead.
- **AI-vocabulary words** — actually, delve, crucial, intricate, pivotal, key
  (adj.), landscape (abstract), tapestry, testament, underscore (verb), vibrant.
- **Copula avoidance** — "serves as / boasts / features" instead of plain "is/has".
- **Negative parallelisms** — "not just X, it's Y"; tailing negations ("no
  guessing" tacked on instead of a real clause).
- **Rule-of-three padding** and **elegant-variation synonym cycling** (protagonist
  → main character → central figure → hero, for the same person in one passage).
- **Em/en dashes as the default punctuation.** Thelivu's own house style already
  uses these sparingly in the reference article — if a draft leans on them for
  every aside, replace most with a period, comma, or colon.
- **Boldface-as-emphasis overuse**, inline-header bullet lists ("**Security:**
  Security has been strengthened…"), Title Case headings, decorative emojis.
- **Collaborative-chatbot leakage** — "I hope this helps", "let me know", "Want me
  to continue?" — must never appear in output. (The pipeline-function contract in
  skill_runner.py already forbids this; this is a second line of defence.)
- **Filler and hedging** — "in order to", "due to the fact that", "it is important
  to note that", stacked qualifiers ("could potentially possibly").
- **Manufactured staccato drama** — a run of short declarative fragments built to
  sound punchy rather than to say something. One short sentence for emphasis is
  fine; a stack of them is a tell.
- **Fake-candid openers** — "Honestly?", "Here's the thing", "Look," before an
  ordinary point.

## What NOT to flag

Don't gut real writing chasing these. Perfect grammar, formal vocabulary used
correctly, one `however`, one em dash, a short emphatic sentence, unsourced but
attributed opinion — none of these alone are AI tells. Only a *cluster* is.

## Where this applies

`article-writer`, `video-script`, `carousel-composer`'s slide copy, and
`social-desk`'s LEADS/output phrasing. `editorial-reviewer` checks for clusters of
these as part of its framing/language pass (see its SKILL.md).
