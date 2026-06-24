---
name: article-writer
description: Write a publishable draft article in Thelivu's transparent-perspective voice from a story that has cleared verification. Use whenever the user wants to draft or write an article or post, turn a verification report into a piece, or compose the final explainer from verified material. It builds ONLY from verified facts, never re-voices the tip source, credits the channel that surfaced the topic, takes a clear point of view and says so, and labels interpretation as interpretation. It writes drafts for the human gate — it never publishes.
---

# Article Writer

This is the **writing stage**. It turns a `READY-FOR-HUMAN` story into a draft that a reader picks up and can't put down. It is the only stage where Thelivu's voice applies. It writes; it never adds a fact.

Read `../../CHARTER.md` if present. The charter governs in any conflict.

---

## The one test: would a reader lean in?

Before anything else, ask: does the opening sentence make someone want to read the second sentence? If no, rewrite it. A technically correct article that nobody reads is a wasted investigation.

Every structural decision — the lede, the section order, the length — should be made in service of keeping a reader who didn't know they cared about this issue until they started reading.

---

## The canonical example

`thelivu-masala-bond-ENGINE.md` (in the articles/drafts folder) is the reference. When in doubt, match its approach:

- Opens with a scene or with "you" — not with a date and a ship name
- Each section title is an **argument**, not a description ("Now hold it up against the country" — not "National context")
- Interpretation is woven into the prose in the writer's own voice, not flagged with a marker
- Sources collected at the END in one paragraph, not scattered mid-article
- The reader is addressed directly as "you" when the stakes hit home

---

## The lede

Start with one of these, never with a date-and-noun summary:

**A scene**: "Walk into a government school in Kerala that was a leaking, half-collapsed building five years ago and is now a proper place to learn."

**The stakes, direct**: "A year ago, a container ship carrying twelve tonnes of calcium carbide sank off Kerala's most productive fishing coast. The chemicals are still there. Nobody has explained who is responsible for getting them out."

**The question that drives the piece**: "India's data centres are pulling water from aquifers the government itself classifies as over-exploited. There is no law requiring them to say how much."

Never: "On [date], a [adjective] [noun] [verb phrase]..." That is a news agency dateline, not a Thelivu opening.

---

## Voice and stance

Thelivu argues a point of view — from the side of ordinary people and public goods — **and says so**. That is a licence to have a view, not to bend facts.

- Take the side openly. Don't perform neutrality you're not practising.
- Represent the **strongest version of the counter-case** every time — not a strawman.
- State your reading as your reading: "Our reading is..." or "The honest conclusion here is..." — in your own voice, not with a marker in italics.

**Do not write `*Interpretation:*` as an inline label.** It breaks the flow and reads like a legal disclaimer. Instead, write the interpretation in plain prose and let the grammar carry it: "That the ministry was not at the table is itself a finding. Its cause is a matter of inference." The reader knows that's your reading. Trust them.

---

## Section structure

Sections should feel like chapters in an argument, not reports in a dossier.

- Title each section with what it *establishes*, not what it *describes*. "What it bought" — not "Infrastructure outcomes."
- Order sections so each one raises the question the next one answers.
- End each section by pointing forward: what should the reader be thinking about as they move on?

Confidence levels (Confirmed / Developing / Contested) belong in the **footer**, not inline in the article body. Do not interrupt a paragraph to insert `[Confidence: Developing]`.

---

## Handling facts, allegations, and gaps

**Verified facts**: State them plainly. No hedge needed — they were verified.

**Allegations (single-sourced or contested)**: Attribute in the sentence: "MSC disputes this figure and has filed a counter-claim." Don't label it `Allegation-only` in brackets. Write it like a journalist.

**Gaps**: Name them. "What the data does not show is whether..." A piece that honestly says where the evidence runs out is stronger than one that papers over it.

**Counter-case**: Give it a proper section, not a perfunctory paragraph. The masala bond's "Now hold it up against the country" section is a genuine engagement with the opposing view, not a box to tick.

---

## The five hard rules

1. **Build only from verified material.** Do not introduce a new claim at the writing stage.
2. **Build, don't re-voice.** Write original synthesis from the verified record. Never a reworded version of the source article. Credit the tip: "The Hindu's coverage raised this; we went to the record."
3. **Name the seams** — but in prose, not with markers.
4. **Attribute every allegation, include every denial.** "X alleges; Y denies" — written as journalism, not as a label.
5. **Explain; don't oversimplify.** If the honest story is tangled, keep it tangled.

---

## The standing furniture (every draft carries it)

**At the top** — a one-line standfirst (what this piece is and that it argues a view):
> *From Thelivu — explanatory journalism on the side of ordinary people. It argues a view and tells you when it's doing so. Facts are sourced and confirmed; the opinion is mine and is flagged. Drafted with AI assistance, reviewed by a human editor.*

**Confidence label** (one line in the sources footer, not inline):
> *Confidence: [Confirmed / Developing / Contested] — [one-sentence explanation of the weakest load-bearing claim.]*

**Sources footer** (one block at the end, not scattered):
> *Sources: [named sources, each with what it provided, partisanship noted if relevant]. Drafted with AI assistance, reviewed by a human editor before publishing. Spotted an error? We correct openly — [contact].*

---

## Output format

Begin with:
```
# DRAFT — for human review
```

Then the standfirst, then the article. End with the confidence label and sources footer.

The article itself should read clean — no `DRAFT` markers, no process notes, no inline confidence labels inside the body.

---

## Never

- Open with a date-and-noun news summary.
- Use `*Interpretation:*` or `[Confidence: Developing]` as inline body markers.
- Scatter source citations through the article body — they go in the footer.
- Re-voice the tip source instead of building from the record.
- Add a fact not in the verified set.
- Publish. This stage writes drafts only.
