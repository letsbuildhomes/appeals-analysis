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

- **One row per docket.** Facts about another docket, even one decided in the
  same document, are not this docket's.
- **"Not stated" is a real answer**, and it is different from "no". A "no"
  needs the documents to say so.
- **Every answer except "not stated" has evidence**: a short exact quotation
  with its document and page number. Code checks each quotation against the
  page text.
- **Closed answers only.** Options that aren't mutually exclusive become
  separate yes/no questions. Dates, counts and names are the only open values.
- **Dates are as precise as the documents allow:** a day, a month or a year,
  with the precision recorded.
- **Code combines answers into research answers.** No model does the
  combining.
- **Rules are composable tests, not lists of case types.** Examples illustrate
  a rule but never decide it.

### Rulings so far

- **"Authorize something already built"** (after-the-fact permits) is out of
  scope. Scope comes from the build, place, convert and create-lots tests.
- **A named group of neighbors** counts as neighbors, not as an organization.
- **A procedural dismissal** whose documents don't say what the appellant
  argued leaves the grounds as "not stated".
- **Stays and housing changes count only when the court imposed them.**
  Changes the town made belong to the town's decision.
- **Units are units added.** Every count of dwelling units is the number of
  new units the project would create. Existing units that remain are not
  counted, even when a decision gives a total for the whole property or
  development; a unit that replaces one removed counts as one.
- **Unit changes are measured two ways:** against what the town approved and
  against what the application proposed. The question is whether the appeal
  moved the outcome, and by how many units.
- **The end of the case is the court's first decision that leaves nothing
  pending.** Partial rulings don't end it, and later post-judgment proceedings
  don't extend it.
- **The docket number dates the filing when nothing else does.** `128-8-10
  Vtec` was filed in August 2010; `25-ENV-00114` in 2025. Code reads it; no
  model is asked.
- **One question for the town's decision.** Its outcomes are exclusive
  (approved, approved with conditions, approved in part, denied), so B1 asks
  for one of them rather than asking separately whether anything was
  approved or denied, which decisions rarely say outright. A deemed approval
  counts as approved.
- **The scan's confidence shapes the prompts.** A claim whose most likely
  answer is at or above `sure` (0.8) is stated as "fairly confident", and
  below it as "uncertain". An A7 or C5 item at or above `check` (0.3) gets its
  own step, told which of the two it is; below `check` it is recorded as the
  scan's "no" with no step.
- **Out-of-scope rows hold only scope.** The scan, facts and derived values
  keep everything for the trace, but the research row of an out-of-scope
  docket reads "out of scope" outside the scope fields. That differs from
  "not stated": we did not study the docket.
- **Durations are exact or a lower bound.** A date stated only to the month or
  year counts as its latest possible day when it starts the case, and its
  earliest possible day when it ends it. Each end of the interval is closed
  (an exact date of the filing or of the final decision) or open (only a
  bound: a month or year, the earliest dated event, the docket number, or the
  latest order when no decision ends the docket). Any open end makes the
  duration "at least"; a start on or after the end leaves it unknown.

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
   docket, or one filed after the document was posted, is flagged for review
   and left as is.

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
| A4 | How many new dwelling units would the project add, as proposed? | stated? → count | Scan (Choice); value from L5a | X3, A |
| A5 | Is the appeal limited to part of the proposal? How many units added in that part? | yes · no · not stated → count | Scan (Choice); values from L5b, L5c | X3, A |
| A6 | How many new building lots for housing would the application create? | stated? → count | Scan (Choice); value from L5d | A |
| A7 | Which kinds of permission are at issue? | subdivision · site plan · planned development or master plan · conditional use · variance · zoning permit · other | Scan (Yes/no ×7); each flagged kind confirmed by its own L3 step | A |

### B · Who appeals, and against what

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| B1 | What did the municipal decision appealed to this court decide? When several municipal bodies decided in turn, the last one. | approved · approved with conditions · approved in part (and denied in part) · denied · not stated | Scan (Choice); confirmed by L3 | X2, X5, B |
| B2 | Are all appellants named, rather than "X, et al."? | yes · no | Scan (Choice); context for L4 | X6 |
| B3 | For each appellant: who are they? | applicant or owner · individual neighbor · group of neighbors · other organization · municipality · state agency · other · not stated | L4 (LLM value) | X6 |
| B4 | For each appellant: were they represented? | represented by a lawyer · self-represented · not stated | L4 (LLM value) | X6 |
| B5 | How many new dwelling units did the municipality approve? | count · not stated | L5e (LLM value) | X3 |

### C · On what grounds

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| C1 | Do the documents say what the appellant argued? | yes · no (no makes C2–C4 "not stated") | Scan (Choice); confirmed by L6 | C |
| C2 | Does an argument dispute how a judgment-based standard (compatibility, character of the area, adequacy) was applied? | yes · no | Scan (Choice); confirmed by L6 | C |
| C3 | Does an argument challenge whether such a standard is valid, for example as too vague? | yes · no | Scan (Choice); confirmed by L6 | C |
| C4 | Did the court treat the judgment-based argument as a principal issue? | yes · no · not stated | Scan (Choice); confirmed by L6 | C |
| C5 | Which issues did the appellant raise? | traffic or access · density · character or appearance · natural resources · noise or lighting · dimensional rules · procedure · standing · vested rights · other | Scan (Yes/no ×10); each flagged issue confirmed by its own L7 step | C |

### D · What the court does

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| D1 | How did the court hear the appeal? | de novo · on the town's record · not stated | Scan (Choice); quoted by L8 | D |
| D2 | Does a decision leave nothing pending in this docket? | yes · no | Scan (Choice); confirmed by L9 | X4, D |
| D3 | If so, how did the docket end? | decided on the merits · dismissed · settled · withdrawn · not stated | Scan (Choice); confirmed by L9 | X2, D |
| D4 | If decided on the merits, what did the court do with the application? | granted · granted with conditions · denied · sent back to the municipality · not stated | Scan (Choice); confirmed by L9 | X2, X5, D |
| D5 | If dismissed, on what basis? | standing · timeliness · jurisdiction · mootness · other · not stated | Scan (Choice); confirmed by L9 | D |

The scan reads the whole docket at once, so D2–D5 describe the docket as a
whole.

### E · How long

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| E1 | Date of the court's first decision leaving nothing pending | date + precision | L10a (chained after L9a) | X4 |
| E2 | If no decision ends the docket: date of the latest order | date + precision | L10b | X4 |

### F · What it cost the housing

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| F1 | Did the court stop construction or stay the permit? Dates? | yes · no → start, end | Scan (Choice); confirmed by L11 | F |
| F2 | Did the court's result change the number of units added from what the municipality approved? | more · fewer · same · not stated | Scan (Choice); count from L5 | X2, X3 |
| F3 | Did it change the number of units added from what the application proposed? | more · fewer · same · not stated | Scan (Choice); count from L5 | X3 |
| F4 | How many new dwelling units did the court approve? | count · not stated | L5f (LLM value) | X3 |
| F5 | Did the court impose conditions that change the buildings' size or design? | yes · no | Scan (Choice); confirmed by L12 | F |

### Gates

Thresholds are *to set* per question from the reference set.

| Gate | Condition | Passes to |
|---|---|---|
| Scope | P(in scope) from S1–S5. At or above the high threshold: continue. At or below the low threshold: stop. Between them: run L1 first. | Base and all steps / L1 / stop |
| Counts | A4, A5 or A6 stated, or F2/F3 is more or fewer | L5 |
| Discretion | C1 yes and (C2 or C3 at or above threshold) | L6 |
| Review | D1 is not "not stated" | L8 |
| Final | D2 at or above threshold | L9 |
| Stay | F1 at or above threshold | L11 |
| Design | F5 at or above threshold | L12 |

An item of A7 or C5 at or above `check` is flagged, and its own step
confirms or refutes it, with a prompt saying whether the scan was fairly
confident (at or above `sure`) or uncertain. An item below `check` is
recorded as the scan's "no" without a step.

An out-of-scope docket keeps its scan answers and makes no reasoning-model
calls.

### Steps

Each step asks the reasoning model for **one detail**, with the quote that
supports it, and returns JSON of the step's type. Details that depend on each
other run as a chain. A chained step keeps the earlier steps' exchanges in
context, and it runs only if their answers call for it (its *only if*): how
the docket ended is asked only once a final decision is found, and the
dismissal basis only if it was dismissed. Every step starts from the docket's
cached `Base`, which states the scan's answers as claims, so most steps
confirm or refute rather than answer from scratch.

A reply that isn't valid JSON of the step's type goes back to the model with
the errors (twice by default) before the step fails. A reply cut off at the
output limit is not the model's mistake: the same request is sent again
unchanged (twice by default).

In the tables, "L3" names a group of steps, L3a to L3c and so on. Steps run in
the order listed. The court's result (L9) comes before the counts (L5)
because the units the court approved depend on it. When a scope step finds
the docket out of scope, the remaining steps are skipped.

| Step | Gate | Only if | Asks for | Chained after |
|---|---|---|---|---|
| L1a–e Scope | scope borderline | — | S1, S2, S3, S4, S5, one at a time; each halts the docket when it rules scope out | the earlier scope steps |
| L2a Filing date | — | — | the filing date as a document states it | — |
| L2b Earliest event | — | L2a not stated | the earliest dated event showing the appeal existed | L2a |
| L3 Town decision | — | — | B1 | — |
| L3 per kind | — | that A7 kind flagged | whether that kind of permission is at issue | — |
| L4a Appellants | — | — | each appellant's name and role (B2 says whether the list can be complete) | — |
| L4b Lawyers | — | — | for each appellant, represented or self-represented | L4a |
| L9a Final decision | final | — | whether a decision leaves nothing pending, quoting the first | — |
| L9b How it ended | final | L9a yes | D3 | L9a |
| L9c Result | final | L9b on the merits | D4 | L9a, L9b |
| L9d Dismissal basis | final | L9b dismissed | D5 | L9a, L9b |
| L10a End date | — | L9a yes | the date of that decision | L9a |
| L10b Latest order | — | L9a not yes | the date of the latest dated order | L9a |
| L5a Units added: proposed | counts | — | A4 | — |
| L5b Partial appeal | counts | — | A5 | L5a |
| L5c Units added: under appeal | counts | L5b yes | units added in the part under appeal | L5a, L5b |
| L5d Housing lots | counts | — | A6 | L5a |
| L5e Units added: town | counts | — | B5 | L5a–c |
| L5f Units added: court | counts | L9c granted, with or without conditions | F4 | L9a–c, L5a, L5e |
| L6a Arguments stated | discretion | — | C1 | — |
| L6b–d Judgment standards | discretion | L6a yes | C2, C3, C4, one at a time | the earlier L6 steps |
| L7 per issue | — | that C5 issue flagged | whether the appellant raised it | — |
| L8 Review standard | review | — | the passage establishing how the court heard the appeal | — |
| L11a Stay | stay | — | whether the court itself stayed the permit | — |
| L11b Stay dates | stay | L11a yes | start and end | L11a |
| L12a Size or design | design | — | whether the court itself imposed such conditions | — |
| L12b The change | design | L12a yes | a one-sentence description, quoted | L12a |

A reasoning-model answer with a verified quote overrides the scan's answer.
Each override is logged as a disagreement, and those logs are the data for
tuning thresholds. A field can also be "not stated" by rule when an earlier
answer makes it moot: C2–C4 when L6a finds no arguments stated, D3–D5 when
L9a finds no final decision, D4 unless the docket was decided on the merits,
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
  tried, and any endpoint of the Anthropic or OpenAI format can be swapped in
  through `config.toml`.
- A spending limit for development runs.
- The storage format (SQLite is the leading option).
- The reference set: dockets labeled as answers to these question IDs.
  Thresholds are tuned against it.
