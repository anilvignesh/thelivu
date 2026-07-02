---
name: story-tracker
description: Follow up on previously published Thelivu stories — check whether courts complied, governments responded, schemes were fixed, named parties answered. Use weekly to surface "what happened next" stories from the archive. Produces follow-up leads only, not publishable copy.
---

# Story Tracker

Published stories are not closed files. A court ordered compliance — did it happen? A CAG report named a scheme — did the next budget fix it? A minister denied an allegation — has new evidence since emerged? This skill returns to the archive and checks.

This skill enforces the project's editorial charter (`../../CHARTER.md`). Read it if present.

**Hard exclusion:** cinema, celebrity, sports, lifestyle. If a prior story touched those (it shouldn't have), skip it.

---

## What to do

You receive a list of previously published stories with their throughlines, publication dates, and key claims. For each story:

1. **Identify the accountability hook.** What was the central claim or finding? Who was named? What was the expected next step (court compliance, government response, legislative action, scheme reform)?

2. **Search for developments since publication.** Use web_search with targeted queries:
   - `[throughline keywords] update [month year]`
   - `[named person/department] response [topic]`
   - `[court case / CAG scheme] compliance 2024`
   - `[named entity] latest news site:thehindu.com OR site:indiaspend.com`

3. **Classify each story:**
   - **Follow-up warranted** — significant new development (compliance achieved, further irregularity found, subject responded, new documents released, accountability delivered or denied)
   - **Still developing** — situation is ongoing, no new hard development yet
   - **Closed** — matter resolved, no further coverage needed

4. **For stories with follow-up warranted**, write a follow-up lead brief:
   - What the original story found
   - What has changed since
   - What the new angle is
   - What primary records to check
   - Whether this is a "accountability delivered" story or a "still no compliance" story — both are worth publishing

---

## The "accountability gap" pattern

The most valuable follow-ups are where:
- A court ordered something → government hasn't complied → contempt risk
- A CAG report named a failure → same department got a budget increase → nobody noticed
- A person denied wrongdoing on record → new documents contradict the denial
- A scheme was "reformed" after scrutiny → the reform was cosmetic → scheme continues unchanged

These are the stories that show the journalism had consequence — or that it needs a second chapter.

---

## Output format

```
# Story Tracker — [date]

## Story [N]: [original throughline]
- Published: [date]
- Original finding: [one line]
- Development found: Yes | No | Partial
- What changed: [specific finding — or "nothing found yet"]
- Source: [URL or search query]
- Follow-up type: Accountability delivered | Still no compliance | Subject responded | New documents | Closed
- Priority: High | Medium | Low | Skip
- Follow-up brief: [if High/Medium — what the investigator should look into, what records to pull]

## Story [N+1]: ...
```

End with a count: N stories checked, X with follow-up warranted, Y still developing, Z closed.

If no developments found for any story, say so clearly — "checked N stories, no significant new developments this week." Do not manufacture leads.

---

## Structured output block (MANDATORY — must appear at the very end)

After the story-by-story entries, output this block containing only High and Medium priority follow-ups. If there are none, output an empty array. The block must be valid JSON.

```
FOLLOW_UPS
[
  {
    "story_id": <integer — the Story N number from your entries above>,
    "throughline": "<original throughline, one line>",
    "priority": "High" | "Medium",
    "brief": "<2-3 sentences: what changed, what the new angle is, what records to pull>"
  }
]
END_FOLLOW_UPS
```

Do not include Low or Skip priority stories in this block. Do not add commentary outside the JSON array.
