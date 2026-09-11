# Usability test protocol

Five participants, three tasks, roughly 20 minutes each.

**Frozen build: tag `usability-freeze-1` (commit 9bc7565), served at
<https://syracuse-budget-explorer-alans-project.vercel.app>.** Every participant sees this
build. Any change under `app/` or `data/` invalidates the pool and needs a new tag and a
fresh set of five. Sessions run against different builds are separate pools and must never
be merged into one count.

Recruit people who do not work in government, accounting or data. A participant who
already knows what a fund balance is cannot tell you whether a resident understands one.

## Before the session

Say this, and nothing more:

> This is a website for looking at the Syracuse city budget. I did not design it to test
> you — I am testing it. If you get stuck, that is information I need, so please say what
> you are thinking out loud as you go. I will not be able to help you during the tasks.

Do not explain the tabs. Do not say the words "proposal", "adopted", "fund" or "workbook"
before the tasks are over. Start each participant at the site root with no tab preselected.

## The three tasks

Read each task once, verbatim. Start timing when you finish reading. Stop when they give
you an answer they are willing to commit to — not when they land on the right screen.

1. Find Public Works spending.
2. Find the biggest year-over-year change.
3. Explain where City revenue comes from.

If they stall for 90 seconds, mark it, then ask "what would you try next?" and let them
continue. Do not point. Do not confirm or deny a wrong answer until the debrief.

## The provenance probe

Only after all three tasks, and in this order:

1. "Were any of the numbers you saw more or less certain than the others?"
2. If no: "Did you see anything about where these numbers come from?"
3. If still no, open a line detail and ask what "FY27 workbook proposal" means to them.

Asking earlier teaches them the answer and destroys the finding.

## Recording sheet

One per participant. Copy the block below.

```
Participant:                        Date:
Not a finance/government worker:  yes / no
Device:  desktop / phone

TASK 1 — Public Works spend
  Answer given:                                   Time:        Success: Y / N
  Route taken:
  Hesitated at:
  Misunderstood:

TASK 2 — Changed the most
  Answer given:                                   Time:        Success: Y / N
  Route taken:
  Hesitated at:
  Misunderstood:

TASK 3 — Revenue sources
  Answer given:                                   Time:        Success: Y / N
  Route taken:
  Hesitated at:
  Misunderstood:

PROVENANCE PROBE
  Noticed proposal vs adopted unprompted:   yes / no
  Noticed after prompt 2:                   yes / no
  What they thought "workbook proposal" meant:

ONE QUOTE — ask at the end: "what confused you most?" (verbatim, their words):

OTHER WORDING THAT TRIPPED THEM (verbatim):
```

Record the answer they actually gave, not just pass or fail. A confident wrong answer is
the most valuable thing a session produces, and a pass/fail column throws it away.

## Reading the results

Fix an issue only if it appears in two or more participants, or if it blocked task
completion for anyone. One person's confusion is noise. Everything below that bar gets
recorded and left alone — a list of known problems you chose not to fix yet is a stronger
artifact than a list of fixes.
