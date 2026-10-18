# Improving the pipeline against the answer key

The home base for improvement passes: run the pipeline on the answer key's dockets, score it, settle the
disagreements, fix the pipeline (or the key, or the definitions), and repeat. Read this before starting a pass,
and add to it when you finish one: what you ran, what you found, what you changed, what it bought, and what
you didn't get to. Write findings as general rules, not as fixes for one docket.

## How a pass runs

The answer key lives in `data/answer-keys/full-2026-10/` (not in git; see its `README.md`). Its scripts:

| Step | Command (from the repository root) | What it does |
|---|---|---|
| Run | `uv run appeals run --model live --dockets "<the 64>" --tag key` | The pipeline on the key's dockets. Scans and steps are cached, so only what changed is paid for; a facts-only change costs nothing. About $0.60 for a full rerun. |
| Score | `uv run python data/answer-keys/full-2026-10/scripts/score.py <run> --load` | Loads the key into `reference_answers` (source `full-2026-10`) and scores field by field, per item for per-group fields, development and held-back apart. Writes `disagreements-<run>.json`. |
| Sort | `uv run python data/answer-keys/full-2026-10/scripts/classify.py <run>` | Splits disagreements into *settled* (an adjudicator already ruled on that docket and field), *scope-caused* (one side has the docket out of scope, so its fields can't agree), *convention* (the same meaning written two ways) and *real*. Writes `real-<run>.json`. |
| Adjudicate | one Sonnet subagent per docket; instructions in `adjudication/instructions.md` | Only real disagreements, and only on dockets in scope or where scope itself is disputed. Each verdict says who is right (key, pipeline, both defensible, neither), the cause (pipeline error, key error, definition gap) and why, with a page. |
| Apply | `uv run python data/answer-keys/full-2026-10/scripts/apply_adjudication.py <folder>` | Writes "pipeline" and "neither" verdicts into the key, marked `adjudicated`. Lists it can't apply go to `unapplied.json` for a labeling pass. |
| Check | `uv run python data/answer-keys/full-2026-10/scripts/check_labels.py labels` | Every label's shape, values against the codebook's types, the scope rule, and every quote on its page. |

Rules learned the hard way:
- **Use Sonnet for checking.** Opus adjudication of 26 dockets was thorough but expensive; Sonnet did the
  second round well.
- **Don't re-review what is settled.** A disagreement an adjudicator already ruled on stays settled; the
  classifier skips it. Apply verdicts to the key instead of re-examining them.
- **No corpus rescans** without the project owner's approval. Changing scan wording invalidates every cached
  scan; a run on the key's 64 dockets rescans only those, for cents.
- **Settle definitions before relabeling.** Definition questions go to the project owner with a recommendation;
  the answer goes into the codebook (so the pipeline reads it) and into the key's edge cases.
- **Fix the key's consistency in code** where a codebook rule decides it (such as results "not decided" for a
  standard not decided), rather than with another agent pass.

## Building or extending the key

What worked when labeling, from the October 2026 grounds keys and this key:
- **Generate the labeling prompt from the codebook,** so the key and the pipeline can't drift apart; edge cases
  are the only hand-written definitions, and every one that settles a definition belongs in the codebook too.
- **Probe, review once, then label the rest.** Label 8 to 10 dockets, have a stronger model review them, and
  revise the prompt once if any correction is major (one that moves scope, a level across a line that matters,
  or a decided value). One revision round was enough every time.
- **One subagent per docket,** reading only the prompt and that docket's text, so facts don't leak between
  dockets. Name each docket's siblings in its task. At most 20 subagents run at once; keep a queue.
- **A quote for every answer, checked in code,** with the same normalization as the pipeline. Quotes make
  reviews fast and settle most disagreements.
- **A `doubts` field.** Labelers use it honestly, and it predicts where the key is weakest.
- **Draw by stratum with a fixed seed,** and report hand-picked hard cases apart from the random draw. Dockets
  chosen because a scan flagged something bias the key toward that thing.
- **Leave out the longest texts,** and dockets that share a decision with one already drawn.

## The answer key

64 dockets drawn from the baseline scan (run `20261018-200655-2c93`) by stratum: sure in scope, the check band,
the near-miss band, the municipal dockets the scope gate stops (split by which scope answer stops them), and
non-municipal dockets with housing language. Fixed seed, one docket per shared decision, texts over 150k
characters left out. Every fourth docket in a stratum is held back: 13 in all.

- Labeled by Sonnet, one subagent per docket, from a prompt generated from the codebook
  (`scripts/make_prompt.py`, now `prompt-v5.md`) plus hand-written `edge_cases.md`.
- Corrected by two rounds of adjudication (Opus, then Sonnet) and by targeted Sonnet updates when definitions
  changed.
- 21 dockets in scope by the rule. Every label passes the code check.
- **Held-back caveat:** 5 of the 13 held-back dockets (101-5-07, 223-10-08, 38-2-00, 54-5-15, 90-6-01) have
  been through adjudication, and 223-10-08 shaped a definition. Treat the other 8 as the clean held-back set,
  or draw fresh held-back dockets before a release check.
- **Known key convention gap:** for kinds of permission, labelers often wrote "not stated" where the pipeline
  writes "no" (about 30 items). The classifier treats this as a convention; decide which is right and fix one
  side.

## Where things stand

| | Pass 1 (run `20261018-214615-36df`) | Pass 2 (run `20261018-224823-fd23`) |
|---|---|---|
| Scope right, of 64 | 56 | 61 |
| In-scope dockets found | 17 of 20 | 20 of 21 |
| False passes (scope) | 5 | 2 |
| Field accuracy, dockets in scope on both sides | about 90% (14 dockets) | about 90% (20 dockets, 1,400 answers) |
| Where field errors are | grounds: other questions 18, judgment standards 16 | grounds: other questions 25, judgment standards 22, results 17 (of 139) |

Field accuracy counts adjudicated errors only: "both defensible" counts as agreement, and convention-only
mismatches are left out.

## Passes

### Pass 0: the baseline scan and the key (2026-10-18)

- **Scan of the whole corpus** (scope questions only, `--stop-after scan`): 1,718 dockets, $1.27, about 3
  minutes. 394 dockets went on to the steps.
- Jev averaged 4.0 characters per token, but 3.7 to 4.3 per docket; a 120k-character docket was rejected at the
  32k per-question limit. **Changed:** the long-context threshold went to 28,000 tokens.
- The 770 municipal dockets the gate stopped were grouped by which scope answer stopped them; the key drew from
  every group.
- **Probe:** Sonnet labeled 10 dockets, Opus reviewed them, and one revision (v1 to v2) followed. The project
  owner then settled the first definitions: Act 250 siblings out, group and care housing in, the decision
  actually appealed, no access roads, Essex Junction by name, and conditions not assumed (T1/C4).

### Pass 1 (pipeline at commits aaeef1d and 7485a64)

Run `20261018-214615-36df`, $0.66. 538 raw disagreements: 210 from 3 dockets the pipeline put out of scope, 117
convention, 173 real. Opus adjudicated 26 dockets. Verdicts: key 116, pipeline 38, both defensible 15,
neither 4.

Found:
- **The scope gate's near-miss band leaked.** 3 of 10 near-miss dockets were in scope, and the band was stopped
  unchecked. **Fixed:** one scope gate at 0.05, with L1 checking every docket that goes on (7485a64).
- **Confident scans included out-of-scope dockets** (5 of 16), such as an Act 250 sibling, a right-of-way and a
  change of use. **Fixed:** L1 for every docket.
- **Scope rules the project owner decided existed only in the key's prompt,** so the pipeline didn't know them.
  **Fixed:** moved into the S1 to S4 wording (9b9593f).
- **A new house was answered "not stated" for adds units,** dropping it from scope. **Fixed:** S4 says a new
  house on land with no dwelling adds one.
- **A standard with no follow-up read "not stated"** where the key read "not decided" and "no". **Fixed:** the
  result convention (9b9593f).
- **One wrong "no arguments" answer blanked every grounds field** (18 errors on one docket). **Fixed:** the
  follow-ups no longer depend on L7a, and the moot rule needs the scan or the follow-ups to agree.
- **6% of quotes failed the check,** some dropping correct answers. Most were words hyphenated across a line
  break, or a quote running onto the next page. **Fixed:** the check accepts both.
- **Definition gaps** settled by the project owner:
  - lots alone add no units;
  - building wins over lots;
  - a released open-space lot is a new lot;
  - a merits decision awaiting a judgment order ends the docket;
  - a ministerial remand is "granted";
  - a later reversal is flagged (`outcome_changed_later`), not used as the outcome;
  - place names are loose and unscored.

### Pass 2 (pipeline at 9b9593f)

Run `20261018-224256-7c97` ($0.59), then `20261018-224823-fd23` after a facts-only fix ($0). Sonnet adjudicated
the 16 in-scope dockets with new disagreements (86 items); only 6 key corrections followed.

Found:
- **The result convention fix missed real runs.** A result step for an unflagged standard is recorded as
  "skipped, condition not met", not as never run, and the unit test only covered the second case. **Fixed**
  before the second run; the test now covers both.
- **Key consistency:** labels whose arguments an adjudicator changed to "stated" still had "not stated" results
  for the other groups. **Fixed in code** with the codebook's own rule.
- **The scope errors left** are all old ones (see open ideas).

## Open ideas, not yet tried

Roughly in order of expected value.

1. **Grounds accuracy.** Most field errors are in `other_questions`, `judgment_grounds` and `judgment_results`.
   Read the round-2 verdicts by pattern before changing prompts. Candidates seen so far:
   - a ruling made in a sibling docket's part of a joint decision, counted for this docket;
   - a general Statement-of-Questions question (such as "all of §500") counted as disputing every standard;
   - "taken up" against "set aside" when a standard is remanded to the town board;
   - the pipeline citing the same quotes for every kind.
2. **Sibling dockets** (a quarter of the corpus shares a decision):
   - **A sentence in the Base** naming the siblings: "this docket is X; documents 1 and 3 also decide Y: answer
     only for X";
   - **An anchoring step** for shared dockets only, asking which decision this docket appeals and by whom.

   Both were agreed in principle and deferred.
3. **The remaining scope errors:**
   - **The decision actually appealed** when it only carries out an earlier permit's condition (23-ENV-00071,
     a landscaping approval);
   - **After-the-fact permits** for an apartment already built and lived in (38-2-00);
   - **Office space converted to an apartment,** answered "no physical change" by the scan (40-4-13). L1 should
     catch this; check why it didn't.
4. **Unit comparisons** (`units_vs_town`, `units_vs_application`) come from the scan only and are often wrong (12
   errors in pass 2). Consider deriving them from the unit counts when both are known, or adding a quoted step.
5. **Unit counts.** The pipeline counts a property's total units as units added when the existing units aren't
   stated (121-10-16). For lots-only subdivisions, units added should follow the "neither" rule (0), which the
   key now uses.
6. **The kinds-of-permission convention:** "not stated" against "no" (see the key section).
7. **Misfiled documents in the corpus.** Document 1 of 189-11-10 is a Stowe Highlands entry (35-3-11 Vtec)
   filed under this docket. Start with a manual exclusion list of (document, docket) pairs that grouping
   applies; later, perhaps flag documents whose caption names another docket.
8. **Quote check leftovers.** About 36 of 90 failed quotes were paraphrases or text not on the page. Footnote
   numbers inside quoted text are one fixable cause.
9. **A clean held-back score** before a release run (see the held-back caveat).

## Open definition questions

Raised as "both defensible" by adjudicators and not yet put to the project owner:
- Does a general question in the Statement of Questions (such as "all of §500") dispute every standard it
  covers, or only those argued specifically?
- Is a party later dismissed as an appellant still listed among the appellants?
- When decision dates conflict across documents (such as September 12 against 13), which wins?
- Does a remainder lot that keeps an existing home count as a new lot? (The adjudicators said no.)
- For denied group or care housing, is the town-approved count 0 (the denial rule) or "not stated" (the
  care-housing rule)?
- Is a town board's authority against the state's on wastewater a "permits" question?
- Do arguments made only on motions count as arguments stated?
- When a standard is remanded to the town board to review first, is it "taken up" or "set aside"?
- Does a court's hedged recital ("it appears that two lots were sought") state a count?
