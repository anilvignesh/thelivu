# Run 113 — refresh notes (2026-07-28)

Attended research for the refresh of *"A Minister Resigned. The Cases Against the
Students Didn't."* (published 2026-07-26). Reel #10 is built and `ready` but is
**deliberately NOT posted** — the FIR thread, which is the piece's whole thesis,
moved twice after publication.

Both paid APIs are dry (Anthropic balance; Gemini returns 429 "prepayment credits
are depleted"), so this was gathered attended via the social desk (YouTube search,
Jina web reads, RSS) against the DB-approved source pool. Tier and status are
marked per item — **do not flatten these into "right-wing groups attacked
students."** That is not what the record shows.

## 1. Development that overtakes the current piece

**Assam and Bihar say they will release detained protesters and withdraw FIRs.**
Scroll.in, 2026-07-28 ~08:20 IST. The decisions followed a CJP threat of fresh
protests if the BJP state governments went back on the promise not to pursue
demonstrators.
→ Status: **announced, not executed.** This does NOT falsify the piece — its line
is precisely "a promise is not a withdrawal" — but the piece reads as though
nothing has moved, and something has. The refresh should carry it and keep the
distinction: *announced ≠ withdrawn*, state by state.

Also live on Scroll the same morning:
- "CJP warns arrests could spark new protests"
- "Madhya Pradesh content creator booked for purportedly abusive reel about
  Dharmendra Pradhan" — relevant to the speech-and-FIRs thread.

## 2. The right-wing angle — what the record actually supports

### FACT — incitement, and the organisation's own repudiation
**T G Mohandas**, political commentator, former head of the BJP Intellectual Cell
in Kerala, RSS-associated. In videos on the YouTube channel *Pathrika* (24 and
26 July) he said that in charge of the Jantar Mantar protest he would impose
curfew and then **shoot**: "Some may die and some may suffer injuries… The bodies
will be collected and taken to hospitals." In another he claimed rapes would occur
if police withdrew and said some women protesters "like rape" and would not
complain. In a 24 July video he justified police violence and alleged, without
evidence, that students wore police uniforms.

**RSS publicly disowned him, 2026-07-28** — Dakshin Keralam Prant Sah Karyavah
K B Sreekumar: *"Shri T.G. Mohandas's comments on the recent protest are his
personal thoughts. He is not an RSS official at any level. RSS doesn't agree with
his views and such views should be condemned in the strongest possible manner."*
Congress called the remarks "vile" and attacked the RSS over them.
Source: The News Minute (DB-approved), 2026-07-28.

→ This is **speech, not a physical attack**, and the repudiation is part of the
story, not a footnote. If this runs, it runs with the RSS statement in it.
→ **Not yet verified first-hand:** the *Pathrika* videos themselves. Before
publishing, watch them — do not rely on a single outlet's transcription for
quotes this grave. Highest defamation care: a named living person.

### ALLEGATION — partisan, single-sided
2026-06-06: **AIYF and AISF** (both CPI-affiliated) alleged that people affiliated
with the RSS tried to disrupt the protest by harassing and assaulting protesters.
→ One political formation alleging it of a rival. Attribute or leave out; it is
not established.

### DOCUMENTED, minor
2026-07-18: a woman chanting pro-Hindutva slogans **threw ink** at CJP figure
Abhijeet Dipke.

### CONFRONTATIONS THAT ARE NOT ATTACKS — do not upgrade these
- Times Now: "CJP Vs 'RSS Supporter' … Heated Faceoff" — an argument.
- DNA: "Clash between **Nihang** and CJP protesters" — **Nihangs are a Sikh order,
  not a Hindutva organisation.** This clip is exactly the kind of thing that gets
  recirculated as "right-wing group attacks students." Do not conflate.

### FACT — a Hindutva activist assaulted two students on their way to the protest
**SUPERSEDES the "not found" that stood here.** Owner supplied the leads; the
sweep below had missed them. Two outlets, plus video, plus the accused's own
account.

Two students from **Bareilly, Uttar Pradesh**, travelling to the CJP protest at
Jantar Mantar, were stopped on the morning of Saturday 25 July by **Satyam
Pandit**, described by Deccan Herald as a "controversial Ghaziabad-based saffron
leader". Told the pair were going to join the protest, he assaulted them. A video
purportedly showing Pandit **slapping** one of them went viral on **X** on Sunday
26 July. The students: *"Don't be seen anywhere near the protest site, Pandit
threatened us."* They returned home on Monday 27 July and demanded police book
him. No FIR reported as filed at the time of writing.

**Pandit publicly justified it.** In a video released Monday 27 July he called the
protesters "anti-nationals" and "anti-Hindu": *"The protesters raised slogans
against Lord Rama, Sanatan Dharma and prime minister Narendra Modi……I will never
tolerate these things."*

Sources: Deccan Herald, 27 July 2026 15:26 IST (plus its companion piece "Slapped,
harassed for taking part in CJP's Jantar Mantar protest, two Bareilly youths urge
police to take action"); India Today, 27 July 2026.

→ This is the strongest item in this section by some distance: the conduct is on
video AND admitted-and-defended by the person who did it. Legal characterisation
("assault") is still for the police and courts — say what he did and what he said,
not that he has been found guilty of anything.
→ **Precision that matters:** Pandit is an *individual* Hindutva activist. No
reporting reviewed ties this to **ABVP, Bajrang Dal, VHP, Sri Ram Sene, Hanuman
Sena or Karni Sena** as organisations. "A saffron activist attacked two students"
is supported. "Right-wing organisations are attacking students" is not — do not
make that jump.

### FACT — a policeman fired an AK-47 at protesters (Bihar)
**"Bihar policeman who fired AK-47 at protesters suspended; viral video triggers
political storm"** — The Hindu, 2026-07-28. Siwan SP confirmed action taken.
→ Materially escalates the force question the piece already covers, and it is
*state* force, distinct from the Hindutva-activist thread above. Bihar also
reported **694 detained** during Saturday's protests (via @the_hindu, 28 July).

## 3. Why the sweep missed the Bareilly assault (post-mortem)

The owner found it; this sweep did not. Four causes, three of them fixable today.

1. **Wrong vocabulary.** Every query was built on *organisation* names — ABVP,
   Bajrang Dal, RSS, Ram Sene, Hanuman Sena. The reporting says "**saffron
   leader/activist**" and names an *individual*. No query could have matched.
   → Search generic descriptors too: saffron, Hindutva activist, right-wing
   leader, and the victim side ("student assaulted", "slapped", town names).
2. **The outlets that covered it are not in our pool.** Deccan Herald and India
   Today are in neither `sources.yaml` nor the DB-approved list. Deccan Herald is
   also one of the 403 sites — the exact problem the Jina reader was built for,
   so we can read it, we just weren't looking at it.
3. **It broke on X.** The Deccan Herald image credit is literally "Credit: X
   video". This is the blind spot flagged in §4 cashing out within the hour.
4. **Not fixable, and not a miss:** the piece published 2026-07-26 03:42; the
   video went viral on 26 July and the students spoke on 27 July. At publication
   this had not happened yet. The story moved — that is what the refresh is for.

Also broken and worth fixing: **`https://www.thenewsminute.com/feed` returns only
ONE item**. RSS was effectively contributing nothing to this sweep and that went
unremarked at the time. Treat a 1-item feed as a broken input, not a quiet day.

## 4. Known blind spot on this story

The DB-approved pool includes three **X**-platform sources (Scroll.in, AFP Fact
Check, Saurav Das) that we cannot read: the social desk has no X support by
design. Worse, two of them are barely reachable by other means —
`scroll.in/feed` returns nothing, Scroll article bodies return **403** and Jina
retrieves only the page shell (the listing page is currently the only usable
surface), and `factcheck.afp.com/rss.xml` returns nothing.

If organised physical attacks were reported, X is where they would surface first.
That is exactly what happened with Bareilly.

**CLOSED, or closeable today — Nitter works.** `https://nitter.net/<handle>/rss`
returns real, current X posts and the social desk already speaks RSS, so this
needs **no new dependency, no credentials and no install**. Verified 2026-07-28
against `nitter.net/scroll_in/rss`: 8 live items, including "Bihar Police said
694 persons were detained", "CJP demands BJP states must immediately release
detained protesters", and "Right to protest constitutionally protected, mere
agitation cannot justify police crackdown: SC" — all of which this sweep had
otherwise missed. Public instances are flaky (poast 403, xcancel 302), so treat
the instance as configurable and fall back across a list.

This is a strictly smaller supply-chain surface than agent-reach, which installs
~9 unpinned upstream tools and stores authenticated X cookies next to production
credentials. Wire Nitter first; judge agent-reach on what is still missing after.
