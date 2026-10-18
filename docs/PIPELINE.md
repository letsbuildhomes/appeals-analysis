# Pipeline configuration

The current design of what we extract and how, as decided so far. The
[README](../README.md) explains the building blocks (`Question`, `Scan`,
`Gate`, `Base`, `Step`, `Field`, `Derive`). This document fills them
in. Values marked *to set* are still to be decided or tuned.

## Research questions

The pipeline's output is its facts and derived values: one row of
well-structured data per docket, for any question. The research questions
that shaped what it extracts are in [RESEARCH-QUESTIONS.md](RESEARCH-QUESTIONS.md),
with the columns and example queries that answer them. They are not built
into the pipeline, the releases or the MCP server.

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
- **Rulings about one answer** are `notes` on its field or derived value: after-the-fact permits (S2), deemed approvals (T1), groups of
  neighbors (`appellants`, `appellant_mix`), procedural dismissals (G1), the
  end of the case (C2), stays and design changes the court imposed (D1, D2),
  unit changes (`unit_change`) and durations (`duration`).

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

The questions and values are grouped by topic, in the order of
`appeals/codebook/topics.py`. A scan question's ID is a letter for its topic
and a number; a value only the reasoning model supplies goes by its field
name. "Settles" names the facts a question settles where they differ from it,
and "Feeds" the derived values that read them.

### Scope

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| S1 | What kind of proceeding is this docket? | municipal permit application · several, including a municipal permit application · municipal enforcement · municipal bylaw or policy · other municipal decision · Act 250 permit · ANR stormwater permit · ANR wastewater permit · other state permit or decision · state enforcement · other · not stated | Scan (Choice) | `in_scope` |
| S2 | What would the permission allow physically? | build a new structure · place a structure · convert or renovate an existing building · create building lots · authorize something already built · no physical change · not stated | Scan (Choice) | `in_scope` |
| S3 | Will the structure or lots be used for housing? | yes · no · not stated | Scan (Choice) | `in_scope` |
| S4 | Does the project add dwelling units, replace existing ones, or neither? | adds · replaces · neither · not stated | Scan (Choice) | `in_scope` |

**In scope (`in_scope`)** = S1 is a municipal permit application, alone or with other
decisions in the docket ∧ S3 yes ∧ (S4 adds or replaces ∨ S2 creates lots) ∧
S2 is not "already built" or "no physical change". An appeal of a preliminary
step on an application, such as sketch plan review, counts as a municipal
permit application even when the court holds the step was not appealable:
those appeals are housing projects that were appealed, and why they were
thrown out is data the study wants.

S1 is one question about the whole proceeding rather than "is it municipal?"
and "what kind of municipal action?" asked separately. A docket is one
proceeding, so its kinds exclude each other, and the out-of-scope kinds are
kept: every row says what its docket is, including Act 250 and state permit
appeals. Stormwater and wastewater permits from the Agency of Natural
Resources have their own answers because they are of interest beyond this
study. The kind of municipal permission (subdivision, site plan and so on) is
not part of S1: one decision often grants several, so it is asked as a set
(K1).

### Filing dates

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| F1 | Does a document state the date the appeal was filed? If so, what is it? (`filing_date`) | yes · no → date + precision | Scan (Choice); value from L2a | `duration` |
| `earliest_event` | If not, the earliest dated event showing the appeal existed | date + precision | L2b (LLM value) | `duration` |
| `docket_filing` | The month or year the docket number gives | date + precision | code, from the docket number | `duration` |

### The town's decision

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| T1 | What did the municipal decision appealed to this court decide? When several municipal bodies decided in turn, the last one. And its date. (`town_decision`, `town_decision_date`) | approved · approved with conditions · approved in part (and denied in part) · denied · not stated → date + precision | Scan (Choice); confirmed by L3a; date from L3b | `court_changed_outcome`, `duration`, `last_permission` |
| `municipality`, `place_within_town` | In which Vermont town or city is the project, and in which village or other named place within it? | one of Vermont's 256 towns, cities, gores and grants · not stated; a place name · not stated | L3c (LLM value, checked against the list) | — |

**The town** is asked of the reasoning model rather than the scan: it only
matters for dockets in scope, which are the ones that reach the steps. The
model writes the name; code checks it against the Census Bureau's list of
Vermont's 256 towns, cities, gores and grants
(`appeals/codebook/vermont_towns.tsv`), which is never put in the prompt. A
name off the list goes back with the names it most likely meant: "Saint
Johnsbury" gets "St. Johnsbury", and "Rutland" gets "Rutland City or Rutland
Town", since four names (Barre, Newport, Rutland and St. Albans) belong to
both a city and a town. A village is not a town: it is recorded as the place
within its town.

### Kinds of permission

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| K1 | Which kinds of permission are at issue? (`permission_kinds`) | subdivision · site plan · planned development or master plan · conditional use · variance (the statutory variance only; a waiver is "other") · zoning permit · other | Scan (Yes/no ×7); each flagged kind confirmed by its own L3 step | — |

### Appellants and their lawyers

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| A1 | Are all appellants named, rather than "X, et al."? (`appellants_named`) | yes · no | Scan (Choice); context for L4 | `appellant_mix` |
| `appellants` | For each appellant: who are they? | applicant or owner · individual neighbor · group of neighbors · other organization · municipality · state agency · other · not stated | L4a (LLM value) | `appellant_mix` |
| `appellant_lawyers` | For each of the first 10 appellants: was an attorney their lawyer at any point in the docket, and who? | represented by a lawyer · self-represented · not stated → lawyer names and firms | L4b, once per appellant (LLM value) | `appellant_mix` |

### Arguments and grounds

A **judgment standard** is one the project must meet whose terms leave the outcome to judgment, with no
measurable test (a number, distance or list), counted only where it is applied to this project rather than
merely quoted in a list of criteria. Not judgment standards: disputes over whether a measurable rule was met,
the court's own procedural discretion, equitable claims such as estoppel, constitutional tests, and impacts
argued only to show standing. A standard is **central** when a party contested whether the project meets it
and the court ruled on it ("decided, disputed"). Every other kind of question an appeal can turn on is asked
the same way (G3), so a docket shows every kind it dealt with, and an appeal with no central judgment standard
shows what it turned on instead (`what_was_central`).

**How these questions were chosen.** The grounds experiments (October 2026) tested the questions on the
decision model before they were built, against a temporary 46-docket answer key. What they settled:
- **One level question per kind,** not "at issue?" and "how far?" separately: the two gave the same answers.
- **Kinds grouped by what moves together:** 21 topics became the 7 judgment groups, and 25 candidate other
  questions became 9. Catch-alls ("another standard", "any discretion?") were dropped: the decision model
  can't answer "none of these", and a broad question fired on discretion of every kind.
- **Each question says what does not count and where it goes,** because the decision model sees one
  question at a time. That is what fixed site design and the two other questions that over-flagged.
- **"Decided, disputed" defines central:** it separates real disputes from the findings a court makes only
  because it runs through every criterion.
- **Conditions are a form, not a topic:** a follow-up asks whether each dispute was about a condition, and
  G4 catches challenges no group does.
- **Results against the key:** the judgment groups caught 48 of 54 central cases (23 false flags); the other
  questions 67 of 75 (38 false flags). Answers at a top probability of 0.6 or more repeated exactly between
  two scans; closer calls did not, which is why the follow-ups are worded by that line.

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| G1 | Do the documents say what the appellant argued? (`arguments_stated`) | yes · no (no makes G2 and G4 "not stated") | Scan (Choice); confirmed by L7a | — |
| G2 | For each of seven kinds of judgment standard, how far did the docket get with it? Kinds: character and fit (character of the area; scale, design or appearance; scenic effects) · historic · neighbor effects (nuisance; privacy, light, air) · traffic and services (traffic, access, street layout; schools, fire, municipal water and sewer) · water and environment (water supply, wastewater, stormwater, flooding, natural resources) · site design (landscaping, screening, buffers, open space, planned-development design criteria, only where argued about itself) · dimensional relief (variances and waivers) (`judgment_grounds`, `judgment_results`, `judgment_conditions`, `relief_kind`) | not at issue · raised only · taken up · decided, disputed · decided, not disputed · set aside → result (met · met with conditions · partly met · not met), whether the dispute was about a condition, and for dimensional relief which kind (statutory variance · bylaw waiver · planned-development modification) | Scan (Choice ×7); each kind with a 0.3 or higher chance of being at issue followed up by its own L8 step | `judgment_central`, `judgment_at_issue`, `what_was_central` |
| G3 | For each of nine other kinds of question, how far did the docket get with it? Kinds: measurable rules (setbacks, height, lot size and frontage, density, parking) · allowed use and defined terms (including how a rule is measured, when that is disputed) · nonconforming uses and structures · municipal process (notice, hearing, completeness, defects in the town's decision) · who can appeal (standing, timeliness, jurisdiction) · earlier permits and approvals (vested rights, unappealed permits, repeat applications, compliance) · property rights (title, easements, covenants) · constitutional and equitable claims (vagueness, takings, fair housing, estoppel) · other permits (Act 250, state wastewater or stormwater) (`other_questions`) | the same six levels as G2 | Scan (Choice ×9); each kind with a 0.5 or higher chance of being at issue followed up by its own L9 step | `what_was_central` |
| G4 | Did a party challenge a condition attached to the permit, arguing whether it should be imposed or how strict? (`conditions_challenged`, `conditions_challenged_by`, `conditions_outcome`) | yes · no → for each challenged condition (up to 5): what it requires, who challenged it, what the court did | Scan (Choice); confirmed by L7b, then L7c–e | — |

### The court's decision

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| C1 | How did the court hear the appeal? (`review_standard`) | de novo · on the town's record · not stated | Scan (Choice); quoted by L10 | — |
| C2 | Does a decision leave nothing pending in this docket? (`final_decision`) | yes · no | Scan (Choice); confirmed by L5 | `duration` |
| C3 | If so, how did the docket end? (`how_ended`) | decided on the merits · dismissed · settled · withdrawn · not stated | Scan (Choice); confirmed by L5 | `court_changed_outcome` |
| C4 | If decided on the merits, what did the court do with the application? (`court_result`) | granted · granted with conditions · denied · sent back to the municipality · not stated | Scan (Choice); confirmed by L5 | `court_changed_outcome`, `last_permission` |
| C5 | If dismissed, on what basis? (`dismissal_basis`) | standing · timeliness · jurisdiction · mootness · other · not stated | Scan (Choice); confirmed by L5 | — |
| `final_decision_date` | Date of the court's first decision leaving nothing pending | date + precision | L5e (chained after L5a) | `duration` |
| `latest_order_date` | If no decision ends the docket: date of the latest order | date + precision | L5f | `duration` |

The scan reads the whole docket at once, so C2–C5 describe the docket as a
whole.

### Units added

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| U1 | How many new dwelling units would the project add, as proposed? (`units_added_proposed`) | stated? → count | Scan (Choice); value from L6a | `unit_change` |
| U2 | Is the appeal limited to part of the proposal? How many units added in that part? (`appeal_partial`, `units_added_under_appeal`) | yes · no · not stated → count | Scan (Choice); values from L6b, L6c | `unit_change` |
| U3 | How many new building lots for housing would the application create? (`housing_lots`) | stated? → count | Scan (Choice); value from L6d | — |
| U4 | Did the court's result change the number of units added from what the municipality approved? (`units_vs_town`) | more · fewer · same · not stated | Scan (Choice); count from L6 | `court_changed_outcome`, `unit_change` |
| U5 | Did it change the number of units added from what the application proposed? (`units_vs_application`) | more · fewer · same · not stated | Scan (Choice); count from L6 | `unit_change` |
| `units_added_town_approved` | How many new dwelling units did the municipality approve? | count · not stated | L6e (LLM value) | `unit_change` |
| `units_added_court_approved` | How many new dwelling units did the court approve? | count · not stated | L6f (LLM value) | `unit_change` |

### Stay and design change

| ID | Question | Answers | Asked by | Feeds |
|---|---|---|---|---|
| D1 | Did the court stop construction or stay the permit? Dates? (`stayed`, `stay_start`, `stay_end`) | yes · no → start, end | Scan (Choice); confirmed by L11 | — |
| D2 | Did the court impose conditions that change the buildings' size or design? (`design_changed`, `design_change`) | yes · no | Scan (Choice); confirmed by L12 | — |

### Gates

Thresholds are *to set* per question from the reference set.

| Gate | Condition | Passes to |
|---|---|---|
| Scope | P(in scope) from S1–S4. At or above the high threshold: continue. At or below the low threshold: stop. Between them: run L1 first. | Base and all steps / L1 / stop |
| Counts | U1, U2 or U3 stated, or U4/U5 is more or fewer | L6 |
| Grounds | G1 yes at or above `grounds` (0.3, low so dockets with arguments are rarely skipped) | L7, L8 |
| Review | C1 is not "not stated" | L10 |
| Final | C2 at or above threshold | L5 |
| Stay | D1 at or above threshold | L11 |
| Design | D2 at or above threshold | L12 |

Every follow-up step reads **one number**: the scan's probability of the claim the step checks. For a K1
item or G4 that is P(yes); for a kind in G2 or G3 it is the chance the kind is at issue at all,
1 − P(not at issue). The same number decides both whether the step runs and how it is asked:

| That number | What happens |
|---|---|
| below the low bound (`check` 0.3; `other_check` 0.5 for G3) | no step; the field keeps the scan's answer |
| from the low bound up to `sure` (0.6) | the step runs, told the scan was unsure, and asked to decide |
| `sure` or above | the step runs, told the scan's reading, and asked to confirm or refute it |

For a kind in G2 or G3, the scan's reading is its most likely level among those that count as at issue.
`sure` also labels every scan answer stated as a claim ("fairly confident" or "uncertain"). It is 0.6
because answers at or above it repeated exactly when the grounds experiments asked the same questions
twice, and closer calls did not. The low bounds differ by question: they trade cost against missed cases,
and G3's kinds come up often enough that 0.5 lost no case in the answer key.

An out-of-scope docket keeps its scan answers and makes no reasoning-model
calls.

### Steps

Each step asks the reasoning model for **one detail**, with the quote that
supports it, and returns JSON of the step's type. Details that depend on each
other run as a chain: one conversation, in which each step names the step it
follows and sees every exchange along that line. A chain is a line, or a tree
where one step has two possible follow-ups; a step never follows two steps. A
step runs only if earlier answers call for it (its *only if*): how the docket
ended is asked only once a final decision is found, and the dismissal basis
only if it was dismissed. Every step starts from the docket's cached `Base`:
the framing, the docket text, and every scan answer as a claim. The step's own
question states again the claims it checks, so most steps confirm or refute
rather than answer from scratch. The full set of claims stays in the Base on
purpose: it is a map of the docket the steps lean on. Taking it out (tried in
October 2026) cost accuracy in the grounds steps and doubled their reasoning,
at the price that a change to any question's wording, or to `sure`, reruns
every step. A step in a chain replays the earlier steps' turns exactly as they
were sent and received, then appends its own question, so each request extends
the one before it and the provider's prefix cache covers the whole chain so
far. Every question ends with the reply's JSON schema and what each answer
option means, so a definition written once on the question or the step reaches
the model.

A reply that isn't valid JSON of the step's type goes back to the model with
the errors (twice by default) before the step fails. A reply cut off at the
output limit, or an empty one, is not a mistake the model can correct: the
same request is sent again unchanged (twice by default). Every attempt
records the stop reason the API reported.

Steps are numbered by chain, in the order the chains run, and lettered by
their order within the chain: L5 is the court's chain, L5a to L5f. A step that
is asked once per flagged item is named after its item, as in L3_variance.

Every question, gate, step, fact and derived value names one **topic**, from
the ordered list in `appeals/codebook/topics.py`, such as "Units added" or
"Arguments and grounds": the conversations about one subject, with the scan
questions that open them and the facts they settle. Topics organize reading:
the dashboard draws one row per topic, the case page groups a docket's facts
by them, and the MCP server's `describe` takes a topic. They change one thing
about the data: the scope topic's facts and derived values are reported for
every docket, in scope or not.

Steps run in the order listed. A step can depend on an answer from another
chain only through its *only if*, never through context: the units the court
approved (L6f) follow the other counts, and run only if the court's chain
found the application granted or denied, which is why the court's chain (L5)
runs before the counts (L6). When a scope step finds the docket out of scope,
the remaining steps are skipped. A scope step that answers "not stated" does
not end the chain, and the scope field keeps the scan's answer: a step that
can't tell doesn't take a docket out of the study.

| Step | Gate | Only if | Asks for | Follows |
|---|---|---|---|---|
| L1a–d Scope | scope borderline | — | S1, S2, S3, S4, one at a time; each halts the docket when it rules scope out | the scope step before it |
| L2a Filing date | — | — | the filing date as a document states it | — |
| L2b Earliest event | — | L2a not stated | the earliest dated event showing the appeal existed | L2a |
| L3a Town decision | — | — | T1 | — |
| L3b Town decision date | — | — | the date of that decision (the written decision's, when the vote differs) | L3a |
| L3c Town and place | — | — | the town or city, as the state writes it, and the place within it | L3b |
| L3 per kind | — | that K1 kind flagged | whether that kind of permission is at issue | — |
| L4a Appellants | — | — | each appellant's name and role (A1 says whether the list can be complete) | — |
| L4b Lawyers, per appellant | — | — | for each of the first 10 appellants L4a listed, one call: represented by an attorney at any point, self-represented or not stated, and the lawyers' names and firms | L4a |
| L5a Final decision | final | — | whether a decision leaves nothing pending, quoting the first | — |
| L5b How it ended | final | L5a yes | C3 | L5a |
| L5c Result | final | L5b on the merits | C4 | L5b |
| L5d Dismissal basis | final | L5b dismissed | C5 | L5b |
| L5e End date | — | L5a yes | the date of that decision | L5a |
| L5f Latest order | — | L5a not yes | the date of the latest dated order | L5a |
| L6a Units added: proposed | counts | — | U1 | — |
| L6b Partial appeal | counts | — | U2 | L6a |
| L6c Units added: under appeal | counts | L6b yes | units added in the part under appeal | L6b |
| L6d Housing lots | counts | — | U3 | L6a |
| L6e Units added: town | counts | — | the units the town approved | L6c |
| L6f Units added: court | counts | L5c granted (with or without conditions) or denied | the units the court approved | L6e |
| L7a Arguments stated | grounds | — | G1 | — |
| L7b Condition challenged | grounds | L7a yes and G4 yes at or above `check` | G4 | L7a |
| L7c Which conditions | grounds | L7b yes | each challenged condition, described in a few words | L7b |
| L7d Who challenged, per condition | grounds | — | for each of the first 5 conditions L7c listed, one call: who challenged it | L7c |
| L7e The court's ruling, per condition | grounds | — | for each of the first 5 conditions, one call: upheld, struck, changed, added, refused or not decided | L7c |
| L8 per kind of judgment standard | grounds | L7a yes and that G2 kind flagged | G2 for that kind: level, result and whether about a condition | — |
| L8_relief_kind | grounds | L8_relief at a level above "not at issue" | which kind of dimensional relief | L8_relief |
| L9 per other kind of question | — | that G3 kind flagged (every docket that proceeds, arguments stated or not) | G3 for that kind: its level | — |
| L10 Review standard | review | — | the passage establishing how the court heard the appeal | — |
| L11a Stay | stay | — | whether the court itself stayed the permit | — |
| L11b Stay dates | stay | L11a yes | start and end | L11a |
| L12a Size or design | design | — | whether the court itself imposed such conditions | — |
| L12b The change | design | L12a yes | a one-sentence description, quoted | L12a |

A reasoning-model answer with a verified quote overrides the scan's answer.
For the yes/no steps about whether something happened (L3_*, L5a, L6b, L7a,
L7b, L11a, L12a), the step may also answer "none found": the documents show
nothing of the kind, so no passage can show it. That needs no quote, overrides
the scan too, and is recorded as "no", with the trace marking it. Each
override is logged as a disagreement, and those logs are the data for tuning
thresholds. A field can also be "not stated" by rule when an earlier answer
makes it moot: G2 and G4 when no arguments are stated, C3–C5 when L5a finds no
final decision, C4 unless the docket was decided on the merits, and C5 unless
it was dismissed.

### Derived fields

| Field | What | From |
|---|---|---|
| `in_scope` | In scope | S1–S4 (L1's answers when it ran) |
| `court_changed_outcome` | Whether the court ended somewhere different from the town | C3, C4 and U4, against T1 |
| `unit_change` | Change in units added: against the town (court approved − town approved) and against the application (court approved − proposed, or the part under appeal when the appeal covered only part); U4 and U5 give the direction when counts aren't stated | U1, U2, U4, U5, `units_added_town_approved`, `units_added_court_approved` |
| `duration` | Duration in days, exact or at least, with each end recorded as closed or open and whether it is inferred. Start: the filing date (F1) when stated to the day; else the town's decision date when stated to the day and not after the latest possible filing day, as a closed start marked inferred; else the earliest of the latest possible days of the filing date, the earliest event and the docket number. End: the first final decision's earliest possible day, else the latest order's | `filing_date`, `earliest_event`, `docket_filing`, `town_decision_date`, `final_decision_date`, `latest_order_date` |
| `last_permission` | Last observed permission: the court's result, or else the town's decision | C4, T1 |
| `appellant_mix` | Appellant mix, folding groups of neighbors into neighbors; the count is unknown when A1 is no. Representation counts each appellant once and covers the appellants L4b asked about (representation_of) | A1, `appellants`, `appellant_lawyers` |
| `judgment_central` | A judgment standard was central: any kind of G2 at "decided, disputed" | G2 |
| `judgment_at_issue` | A judgment standard was at issue: any kind of G2 above "not at issue" | G2 |
| `what_was_central` | What was central: a judgment standard; other questions only (G3, no judgment standard at "decided, disputed"); or nothing | G2, G3 |

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
