# Context & History — how Thelivu came to be built this way

A short record of the reasoning behind the rules, so the *why* travels with the
*what*. If a rule ever feels inconvenient, read this before bending it.

## How it started

The project began as help writing a pointed opinion piece on Kerala politics —
the LDF's masala bonds and the new UDF government's white paper. That op-ed became
the accidental stress-test for everything that followed.

## The realization that shaped everything

While building that piece, several strong, confident claims were brought to the
table: that the new CM took a chartered flight *booked by Adani*; that the health
minister said privatisation was the only way; that the private-equity firms buying
Kerala's hospitals had *funded the Congress campaign*. On checking each against
the record: the flight was real but the Adani link was an unproven allegation the
CM denied; the minister had said the **opposite** (he denied privatisation); and
the funding claim didn't survive the data at all. **Two of three didn't hold.**

That is the whole reason this is a verification engine with a human gate, and not
a publishing bot. The failure mode is not hypothetical — we lived it on the very
first piece.

## How the mission evolved

It moved through three positions before settling:
1. First instinct: *expose* — connect the dots on a set of assumed villains.
2. Then: claimed *neutral* — but the reference channels (More Perfect Union etc.)
   revealed a real lean.
3. Settled: **transparent perspective** — argue a view from the side of ordinary
   people, openly, while holding the facts to a strict, independent standard. Not
   neutral, not disguised. Honest about both.

## The insights that became rules

- **Channels are tips, not truth.** The reference channels (ColdFusion, Coffeezilla,
  Johnny Harris, More Perfect Union, FYI) surface *topics*. The open web — primary
  records, established news — is what verifies. "One source proposes, the whole web
  disposes."
- **"Connecting the dots" is the conspiracy mechanism unless disciplined.** The
  "PE + white paper + bond money = coordinated capture" story felt compelling and
  was *not supported* — the bond money was mostly the BJP's and predated the UDF.
  Hence the pattern-synthesizer demands the link itself be evidenced, classifies
  coincidence vs correlation vs causation vs coordination, and downgrades by default.
- **Finding "more sources like ours" destroys verification.** If the source pool
  all leans one way, "verified" just means "agreed with by people who think like
  us." Hence the scout hunts cross-spectrum and primary sources, not more of the same.
- **Under-coverage selects, never confirms.** Obscurity tells you what to look at,
  never what to believe — and obscure claims face a higher bar, not a lower one.
- **Build, don't re-voice.** Re-wording a channel's script is an IP and credibility
  problem. Rebuild from the record; credit the tip.
- **Oversimplification is the explainer's failure mode.** The clean, satisfying arc
  is the dangerous one. Keep the complication.
- **The human publish gate is gone (2026-08-29, Anil, explicit).** Every story
  that clears editorial review publishes and posts autonomously, including
  ones naming a real person alongside an allegation — see
  `engine/distribution/sweep.py`. Telegram still gets a per-run heads-up;
  Anil's stated fallback is deleting anything he judges unnecessary after
  the fact, not reviewing before.

## The character of the project

At every fork where rigor and reach conflicted, the choice was rigor: cutting an
unprovable claim, labelling a perspective instead of hiding it, refusing to
automate before validating. That is the project's spine. Keep it.

## The decisions that came out of it

Name **Thelivu** (clarity / evidence). Stance **transparent perspective**. Language
**English**. **One** human-reviewed piece a day. **FYI** as first source. Run
**attended** on an M1 Mac via Claude Code under a Pro plan, transcripts-first, with
automation deferred until validation proves the pipeline.
