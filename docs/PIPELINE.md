# Pipeline configuration

The current design of what we extract and how, as decided so far. The
[README](../README.md) explains the building blocks (`Question`, `Scan`,
`Gate`, `Base`, `Step`, `Field`, `Derive`, `Answer`). This document fills them
in. Values marked *to set* are still to be decided or tuned.

## Research questions

Every extracted value exists to answer one of these. A value that serves none
is not extracted.

| | Research question | Answered by |
|---|---|---|
| Scope | Is this docket a municipal appeal about new housing? | S1–S5 → X1 |
| A | Which town decisions about new housing get appealed: when the appeal was filed, in which town, how many units and lots, and what kind of permission | A1–A7 |
| B | Who appeals, and against what: whether the town approved or denied, who the appellants are, and whether they had lawyers | B1–B5 → X6 |
| C | On what grounds: whether the appeal turns on judgment-based standards, and which issues were raised | C1–C5 |
| D | What the court does: how it heard the appeal, and how the docket ended | D1–D5 → X2 |
| E | How long: days from the appeal's filing to the court's first decision that leaves nothing pending | A1/A2, E1/E2 → X4 |
| F | What the appeal cost the housing: stays, unit changes and design changes the court imposed, and where permission ended up | F1–F5 → X3, X5 |

Out of scope by decision:
- **Supreme Court proceedings.** The end of a case is the Environmental
  Division's first final decision.
- **Whether appeals were frivolous.**
- **Construction outcomes,** which the decisions can't show.

## Conventions

The conventions and rulings live in the codebook, next to the answers they
govern, so they travel with every run's graph description and every release:

- **Rules every answer follows** are in `appeals/codebook/conventions.py`:
  one row per docket, "not stated" versus "no" versus "out of scope", quotes
  as evidence, closed answers, date precision, units added, actors, how the
  scan and the steps settle an answer, and what the source can't show.
- **Rulings about one answer** are `notes` on its field, derived value or
  answer: after-the-fact permits (S3), deemed approvals (B1), groups of
  neighbors (B3, X6), procedural dismissals (C1), the end of the case (D2),
  stays and design changes the court imposed (F1, F5), unit changes (X3) and
  durations (X4).

To change a convention or a ruling, edit it there. The dashboard, the
published releases and the MCP server all read it from the graph
description; nothing else repeats it.

## Ingest

### Source

The Vermont Judiciary's opinions library, filtered to the Environmental
division:
`https://www.vtcourts.gov/opinions-decisions?f%5B0%5D=court_division_opinions_library_%3A3`.
It has 25 entries per page, about 2,600 entries in total, posted from 2000 to
the present. Each entry has a title, a posting date, the division, a docket
number, and a `/media/<id>` link that redirects to the PDF.

Every entry is taken. The listing's document-type filter (Opinions, Decisions,
Orders, Judgements) is not used, because it marks the posting era rather than
the kind of document.

**Plausible dates.** Every date read from the listing, a docket number or a
model's reply must be a real calendar date from 1990, when the Environmental
Court was created, to the current year. A listing date outside that range is
dropped, and the entry keeps a note with the date as listed; the listing has
at least one such typo ("03/31/0022"). Saved snapshots are parsed again on
every ingest, so a parser fix reaches entries already stored.

### Documents

- Each PDF is stored once under the SHA-256 of its bytes. A file must look
  like a PDF and be under 100 MiB.
- Each document keeps every listing entry that links to it: title, posting
  date, listing docket number and media URL.
- Requests go one at a time with a pause between them, retry with backoff on
  429 and 5xx responses, and stop on 403 or a very long Retry-After.

### Page text

For each page, in order:

1. **Native text** from Poppler's `pdftotext` in layout mode.
2. **Usability check.** A page with enough clean native text is kept. A
   sparse or garbled page is rendered to measure its ink:
   - nearly no ink: **blank**,
   - visible content without enough text: **needs OCR**,
   - anything uncertain: **OCR candidate**.
3. **OCR** with Tesseract for pages that need it or are candidates. The page
   is rendered in grayscale, and the Tesseract and Poppler versions are
   recorded with the result.
4. **Selection:**
   - usable native text wins;
   - OCR is chosen when the native text is missing or garbled, or when OCR
     finds much more text;
   - weak OCR (fewer than 10 characters or 2 words, mean confidence under 45,
     or garbled) leaves the page **unresolved**.

A page without usable text still appears in the docket text, as
`[No selected text: STATUS]`, so page numbering stays complete.

### Dockets

A docket is a case. Docket numbers come in two formats: `128-8-10 Vtec`
(sequence-month-year, used until about 2020) and `25-ENV-00114` (year-ENV-
sequence).

Rules, in order:

1. **Heading dockets.** A document's dockets are the numbers after a "Docket
   No." or "Case No." label in the first 3,000 characters of page 1, and only
   when the label is part of the heading:
   - **Where the label sits.** It must begin a column of the caption: at the
     start of a line, after a bracket column (`}` or `|`), or after a wide
     gap.
   - **Mentions and citations are skipped.** These include a label inside a
     sentence, a line that carries on as a sentence after the numbers, a
     left-margin label whose previous line ends mid-sentence with a comma, and
     "Supreme Court Docket No.".
   - **Stacked lists.** Numbers continue down the label's column, so a stacked
     list is read whole. A parenthetical note between stacked numbers doesn't
     end the column.
   - **Normalization.** Dash variants, line breaks and bracket columns between
     a number and "Vtec", footnote markers ("Vtec1") and OCR's letter O for
     zero ("22-ENV-OOO3O") are all read as the plain docket.
2. **Listing fallback.** A document whose heading names no docket uses its
   listing entry's docket. A listing docket that the heading doesn't name never
   creates a docket, because the listing has typos and Supreme Court numbers.
   It is flagged instead.
3. **Membership.** Each docket's documents are all those naming it. A
   document with no docket at all is kept as its own case.
4. **Flags, never changes.** A heading docket one digit away from the listing
   docket, one filed after the document was posted, or one whose number spells
   an implausible year, is flagged for review and left as is. An implausible
   year is never used as a filing date.

Documents within a docket are ordered by posting date, then by hash.

### Docket text

```xml
<docket number="…">
<document n="1" title="…" posted="YYYY-MM-DD" dockets="…; …">
<page n="1" source="native|ocr">…</page>
<page n="2" status="blank">[No selected text: blank]</page>
</document>
…
</docket>
```

The text is page markup plus the selected text, with nothing else added.
Quotes cite `document n` and `page n`.

### Length

| | Characters | Tokens (est.) |
|---|---|---|
| Median docket | about 21k | about 5k |
| 99th percentile | about 220k | about 55k |
| Longest | about 420k | about 105k |

Token figures assume 4 characters per token. A docket over the decision
model's standard per-question context (32k tokens for Jev 1.14, roughly
120k characters with room for the questions) is sent in long-context mode
(up to 262k tokens). The long-context threshold is *to set*, from measured
token counts.

## The extraction graph

**Kinds of question:**
- **Choice:** one option from a fixed set.
- **Yes/no ×n:** a set of separate yes/no questions, one per option.
- **LLM value:** a value the reasoning model supplies with a quote, never
  asked of the decision model.

Every question that could be silent includes "not stated" as an answer.

### Scope

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| S1 | Is the decision under appeal by a municipal body or officer (board, commission, zoning administrator)? | yes · no · not stated | Scan (Choice) | X1 |
| S2 | What kind of municipal action is under appeal? | application for permission · enforcement or violation notice · bylaw or policy · other | Scan (Choice) | X1 |
| S3 | What would the permission allow physically? | build a new structure · place a structure · convert or renovate an existing building · create building lots · authorize something already built · no physical change · not stated | Scan (Choice) | X1 |
| S4 | Will the structure or lots be used for housing? | yes · no · not stated | Scan (Choice) | X1 |
| S5 | Does the project add dwelling units, replace existing ones, or neither? | adds · replaces · neither · not stated | Scan (Choice) | X1 |

**In scope (X1)** = S1 yes ∧ S2 application ∧ S4 yes ∧ (S5 adds or replaces ∨
S3 creates lots) ∧ S3 is not "already built" or "no physical change".

### A · Which decisions get appealed

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| A1 | Does a document state the date the appeal was filed? If so, what is it? | yes · no → date + precision | Scan (Choice); value from L2 | X4, A |
| A2 | If not, the earliest dated event showing the appeal existed; and the month or year the docket number gives | date + precision | L2b; code, from the docket number | X4 |
| A3 | In which municipality is the project? | one of the Vermont municipalities found in the text · not stated | Scan (Choice over candidates) | A |
| A4 | How many new dwelling units would the project add, as proposed? | stated? → count | Scan (Choice); value from L6a | X3, A |
| A5 | Is the appeal limited to part of the proposal? How many units added in that part? | yes · no · not stated → count | Scan (Choice); values from L6b, L6c | X3, A |
| A6 | How many new building lots for housing would the application create? | stated? → count | Scan (Choice); value from L6d | A |
| A7 | Which kinds of permission are at issue? | subdivision · site plan · planned development or master plan · conditional use · variance · zoning permit · other | Scan (Yes/no ×7); each flagged kind confirmed by its own L3 step | A |

### B · Who appeals, and against what

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| B1 | What did the municipal decision appealed to this court decide? When several municipal bodies decided in turn, the last one. | approved · approved with conditions · approved in part (and denied in part) · denied · not stated | Scan (Choice); confirmed by L3 | X2, X5, B |
| B2 | Are all appellants named, rather than "X, et al."? | yes · no | Scan (Choice); context for L4 | X6 |
| B3 | For each appellant: who are they? | applicant or owner · individual neighbor · group of neighbors · other organization · municipality · state agency · other · not stated | L4 (LLM value) | X6 |
| B4 | For each appellant: were they represented? | represented by a lawyer · self-represented · not stated | L4 (LLM value) | X6 |
| B5 | How many new dwelling units did the municipality approve? | count · not stated | L6e (LLM value) | X3 |

### C · On what grounds

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| C1 | Do the documents say what the appellant argued? | yes · no (no makes C2–C4 "not stated") | Scan (Choice); confirmed by L7 | C |
| C2 | Does an argument dispute how a judgment-based standard (compatibility, character of the area, adequacy) was applied? | yes · no | Scan (Choice); confirmed by L7 | C |
| C3 | Does an argument challenge whether such a standard is valid, for example as too vague? | yes · no | Scan (Choice); confirmed by L7 | C |
| C4 | Did the court treat the judgment-based argument as a principal issue? | yes · no · not stated | Scan (Choice); confirmed by L7 | C |
| C5 | Which issues did the appellant raise? | traffic or access · density · character or appearance · natural resources · noise or lighting · dimensional rules · procedure · standing · vested rights · other | Scan (Yes/no ×10); each flagged issue confirmed by its own L8 step | C |

### D · What the court does

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| D1 | How did the court hear the appeal? | de novo · on the town's record · not stated | Scan (Choice); quoted by L9 | D |
| D2 | Does a decision leave nothing pending in this docket? | yes · no | Scan (Choice); confirmed by L5 | X4, D |
| D3 | If so, how did the docket end? | decided on the merits · dismissed · settled · withdrawn · not stated | Scan (Choice); confirmed by L5 | X2, D |
| D4 | If decided on the merits, what did the court do with the application? | granted · granted with conditions · denied · sent back to the municipality · not stated | Scan (Choice); confirmed by L5 | X2, X5, D |
| D5 | If dismissed, on what basis? | standing · timeliness · jurisdiction · mootness · other · not stated | Scan (Choice); confirmed by L5 | D |

The scan reads the whole docket at once, so D2–D5 describe the docket as a
whole.

### E · How long

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| E1 | Date of the court's first decision leaving nothing pending | date + precision | L5e (chained after L5a) | X4 |
| E2 | If no decision ends the docket: date of the latest order | date + precision | L5f | X4 |

### F · What it cost the housing

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| F1 | Did the court stop construction or stay the permit? Dates? | yes · no → start, end | Scan (Choice); confirmed by L10 | F |
| F2 | Did the court's result change the number of units added from what the municipality approved? | more · fewer · same · not stated | Scan (Choice); count from L6 | X2, X3 |
| F3 | Did it change the number of units added from what the application proposed? | more · fewer · same · not stated | Scan (Choice); count from L6 | X3 |
| F4 | How many new dwelling units did the court approve? | count · not stated | L6f (LLM value) | X3 |
| F5 | Did the court impose conditions that change the buildings' size or design? | yes · no | Scan (Choice); confirmed by L11 | F |

### Gates

Thresholds are *to set* per question from the reference set.

| Gate | Condition | Passes to |
|---|---|---|
| Scope | P(in scope) from S1–S5. At or above the high threshold: continue. At or below the low threshold: stop. Between them: run L1 first. | Base and all steps / L1 / stop |
| Counts | A4, A5 or A6 stated, or F2/F3 is more or fewer | L6 |
| Discretion | C1 yes and (C2 or C3 at or above threshold) | L7 |
| Review | D1 is not "not stated" | L9 |
| Final | D2 at or above threshold | L5 |
| Stay | F1 at or above threshold | L10 |
| Design | F5 at or above threshold | L11 |

An item of A7 or C5 at or above `check` is flagged, and its own step
confirms or refutes it, with a prompt saying whether the scan was fairly
confident (at or above `sure`) or uncertain. An item below `check` is
recorded as the scan's "no" without a step.

An out-of-scope docket keeps its scan answers and makes no reasoning-model
calls.

### Steps

Each step asks the reasoning model for **one detail**, with the quote that
supports it, and returns JSON of the step's type. Details that depend on each
other run as a chain: one conversation, in which each step names the step it
follows and sees every exchange along that line. A chain is a line, or a tree
where one step has two possible follow-ups; a step never follows two steps. A
step runs only if earlier answers call for it (its *only if*): how
the docket ended is asked only once a final decision is found, and the
dismissal basis only if it was dismissed. Every step starts from the docket's
cached `Base`, which states the scan's answers as claims, so most steps
confirm or refute rather than answer from scratch.

A reply that isn't valid JSON of the step's type goes back to the model with
the errors (twice by default) before the step fails. A reply cut off at the
output limit is not the model's mistake: the same request is sent again
unchanged (twice by default).

Steps are numbered by chain, in the order the chains run, and lettered by
their order within the chain: L5 is the court's chain, L5a to L5f. A step
that is asked once per flagged item is named after its item, as in
L3_variance. Steps run in the order listed. A step can depend on an answer
from another chain only through its *only if*, never through context: the
units the court approved (L6f) follow the other counts, and run only if the
court's chain found the application granted, which is why the court's chain
(L5) runs before the counts (L6). When a scope step finds the docket out of
scope, the remaining steps are skipped.

| Step | Gate | Only if | Asks for | Follows |
|---|---|---|---|---|
| L1a–e Scope | scope borderline | — | S1, S2, S3, S4, S5, one at a time; each halts the docket when it rules scope out | the scope step before it |
| L2a Filing date | — | — | the filing date as a document states it | — |
| L2b Earliest event | — | L2a not stated | the earliest dated event showing the appeal existed | L2a |
| L3 Town decision | — | — | B1 | — |
| L3 per kind | — | that A7 kind flagged | whether that kind of permission is at issue | — |
| L4a Appellants | — | — | each appellant's name and role (B2 says whether the list can be complete) | — |
| L4b Lawyers | — | — | for each appellant, represented or self-represented | L4a |
| L5a Final decision | final | — | whether a decision leaves nothing pending, quoting the first | — |
| L5b How it ended | final | L5a yes | D3 | L5a |
| L5c Result | final | L5b on the merits | D4 | L5b |
| L5d Dismissal basis | final | L5b dismissed | D5 | L5b |
| L5e End date | — | L5a yes | the date of that decision | L5a |
| L5f Latest order | — | L5a not yes | the date of the latest dated order | L5a |
| L6a Units added: proposed | counts | — | A4 | — |
| L6b Partial appeal | counts | — | A5 | L6a |
| L6c Units added: under appeal | counts | L6b yes | units added in the part under appeal | L6b |
| L6d Housing lots | counts | — | A6 | L6a |
| L6e Units added: town | counts | — | B5 | L6c |
| L6f Units added: court | counts | L5c granted, with or without conditions | F4 | L6e |
| L7a Arguments stated | discretion | — | C1 | — |
| L7b–d Judgment standards | discretion | L7a yes | C2, C3, C4, one at a time | the L7 step before it |
| L8 per issue | — | that C5 issue flagged | whether the appellant raised it | — |
| L9 Review standard | review | — | the passage establishing how the court heard the appeal | — |
| L10a Stay | stay | — | whether the court itself stayed the permit | — |
| L10b Stay dates | stay | L10a yes | start and end | L10a |
| L11a Size or design | design | — | whether the court itself imposed such conditions | — |
| L11b The change | design | L11a yes | a one-sentence description, quoted | L11a |

A reasoning-model answer with a verified quote overrides the scan's answer.
Each override is logged as a disagreement, and those logs are the data for
tuning thresholds. A field can also be "not stated" by rule when an earlier
answer makes it moot: C2–C4 when L7a finds no arguments stated, D3–D5 when
L5a finds no final decision, D4 unless the docket was decided on the merits,
and D5 unless it was dismissed.

### Derived fields

| ID | Field | From |
|---|---|---|
| X1 | In scope | S1–S5 (L1's answers when it ran) |
| X2 | Whether the court ended somewhere different from the town | D3, D4 and F2, against B1 |
| X3 | Change in units added: against the town (F4 − B5) and against the application (F4 − A4, or A5 when the appeal covered only part); F2 and F3 give the direction when counts aren't stated | A4, A5, B5, F2, F3, F4 |
| X4 | Duration in days, exact or at least, with each end recorded as closed or open (see the rulings above). Start: A1 when stated to the day, else the earliest of the latest possible days of A1, A2 and the docket number. End: E1's earliest possible day, else E2's | A1, A2, E1, E2 |
| X5 | Last observed permission: the court's result, or else the town's decision | D4, B1 |
| X6 | Appellant mix, folding groups of neighbors into neighbors; the count is unknown when B2 is no | B2–B4 |

### Calls per docket

- **Out of scope:** one decision-model request and no reasoning-model calls.
- **In scope:** the same request, plus roughly 15 to 40 small reasoning-model
  calls on one cached `Base`, depending on the gates, the flagged items and
  the answers along each chain. The first live test (Tuggle PUD, October 2026)
  made 29 calls costing about a cent off-peak.

## To set

- The thresholds for each gate, and the scope gate's high and low thresholds.
- The long-context threshold, in measured tokens.
- The reasoning model. DeepSeek Flash is in use for now; others will be
  tried: any model reached through the Anthropic or OpenAI API can be added
  as a file in `providers/` and chosen in `config.toml`.
- A spending limit for development runs.
- The reference set: dockets labeled as answers to these question IDs.
  Thresholds are tuned against it.
