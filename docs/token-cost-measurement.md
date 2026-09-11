# Measuring what caching and batching are actually worth

Both prompt caching and the Batch API are *conditional* wins, and the condition
is measurable from `token_usage`. Re-run this before changing either — the right
answer moves when call cadence does.

```sql
SELECT skill, COUNT(*) AS calls,
       SUM(COALESCE(input_tokens,0))        AS uncached_in,
       SUM(COALESCE(output_tokens,0))       AS out,
       SUM(COALESCE(cache_write_tokens,0))  AS cache_wr,
       SUM(COALESCE(cache_read_tokens,0))   AS cache_rd
FROM token_usage
WHERE recorded_at > NOW() - INTERVAL '30 days'
GROUP BY skill ORDER BY 3 DESC;
```

`input_tokens` is the UNCACHED REMAINDER, not the prompt size. The effective
cost of a skill is therefore:

    with caching     uncached_in + cache_wr * 1.25 + cache_rd * 0.10
    without caching  uncached_in + cache_wr        + cache_rd

A cache write bills at 1.25x. **Writing a cache that nothing reads costs more
than not caching at all**, and there is no error or warning when that happens —
it just shows up as a slightly larger bill.

## What the first measurement said (30 days to 2026-09-11)

Overall 35% hit rate, **-26% spend** against no caching. But it splits hard:

| skill | calls | hit | vs no cache |
|---|---:|---:|---:|
| chief-of-staff | 26 | 60% | **-46%** |
| ek:record-builder | 20 | 57% | -41% |
| tech-steward | 9 | 54% | -40% |
| news-investigator | 130 | 50% | -37% |
| story-scout | 77 | 44% | -32% |
| topic-intake | 37 | 46% | -31% |
| beat-monitor | 25 | 31% | -23% |
| pattern-synthesizer | 32 | 3% | **+4%** |
| editorial-reviewer | 34 | 7% | +3% |
| article-writer | 34 | 6% | +2% |
| video-script | 204 | 4% | **+13%** |

The mechanism is not the variable — the **cadence** is. A skill called once per
reel build, ten-plus minutes apart, has nothing left in a 5-minute window to
hit. `NO_PROMPT_CACHE` in `engine/agents/skill_runner.py` is the denylist that
follows from this table; a new skill caches by default and shows up here if it
should not.

Five skills record **zero** cache traffic — `news-monitor`, `source-verifier`,
`newsworthiness-gate`, `reel-fact-check`, `story-tracker`. They do not go
through `_run_claude`, so nothing is being lost or wasted; they are simply
outside this mechanism.

## The Batch API

50% off input and output, asynchronous, and the only guarantee is **24 hours**.
That guarantee is the whole decision:

- **Fits:** the digger's batched review (`chief-of-staff`, ~26 calls/30d, runs
  every ~2 days, nobody is waiting) and any backfill or re-score over history.
  These are the largest per-call spenders and the least time-sensitive work we
  have.
- **Does not fit:** anything inside the daily publish path — `news-monitor`,
  `source-verifier`, `video-script`, the reel build. The pipeline has to land a
  story the same day; a 24h worst case can miss the day entirely, and the
  failure would be silent and occasional, which is the worst shape for it.

Caching and batching also stack: a batched request still reads a warm cache.
