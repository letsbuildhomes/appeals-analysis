# Improving the pipeline against the answer key

The home base for improvement passes: run the pipeline on the answer key's dockets, score it, judge the change,
fix the pipeline (or the key, or the definitions), and repeat. Read this before starting a pass; after one, report
with the post-experiment assessment below and add the pass to [IMPROVING-LOG.md](IMPROVING-LOG.md). Write findings
as general rules, not as fixes for one docket.

## How a pass runs

The answer key's labels and texts live in `data/answer-keys/full-2026-10/` (not in git; see its `README.md`). The
scripts that read them are in `scripts/answer-key/`.

| Step | Command (from the repository root) | What it does |
|---|---|---|
| Run | `uv run appeals run --model live --dockets "<the 64>" --tag key` | The pipeline on the key's dockets. Scans and steps are cached, so only what changed is paid for; a facts-only change costs nothing. A change to the scan reruns every step: about $0.90. |
| Score | `uv run python scripts/answer-key/score.py <run> --load` | Loads the key into `reference_answers` and scores field by field, per item for per-group fields, development and held-back apart. Writes `disagreements-<run>.json`. |
| Compare | `uv run python scripts/answer-key/compare.py <before> <after> --change "<name>=<field>,<field>"` (one `--change` per change; `scope` stands for the scope fields) | Scores both runs against today's key and prints the verdict, the change table, scope movement and the ranked regressions for the assessment. Writes `compare-<before>-<after>.json`. |
| Noise | `uv run python scripts/answer-key/noise.py <run> <fresh-run>` | Two runs of the same pipeline (the second with `--fresh-steps`), compared answer by answer: flip rates by area, field and step. |
| Sort | `uv run python scripts/answer-key/classify.py <run>` | Splits disagreements into settled, scope-caused, convention and real. Writes `real-<run>.json`. |
| Adjudicate | only when the project owner asks; instructions in the key's `adjudication/instructions.md` | One Sonnet subagent per docket, on real disagreements only. Each verdict says who is right, the cause and why, with a page. |
| Apply | `uv run python scripts/answer-key/apply_adjudication.py <folder>` | Writes "pipeline" and "neither" verdicts into the key, marked `adjudicated`. |
| Check | `uv run python scripts/answer-key/check_labels.py labels` | Every label's shape, values against the codebook's types, the scope rule, and every quote on its page. |

### Judging a change

Run `compare.py` on the run before and the run after a change. It answers "better, worse or a wash, and by how
much" without adjudication:
- **One yardstick.** Both runs are scored against the key as it stands, so key corrections don't count.
- **Moves, not totals.** Each answer is fixed, broken, shifted (wrong to a different wrong) or unchanged; net is
  fixed minus broken. "Closed" is net as a share of the field's errors before.
- **Scope first.** A docket moving in or out of scope is listed by name. Field answers on a docket that either run
  has out of scope are left out of the field counts.
- **Units damp cascades.** One field on one docket is one unit, better or worse by its error count. The verdict uses
  net units, so one docket with twenty knock-on answers counts as a few units, not twenty.
- **Reviewed or not.** A break against a key answer an adjudicator or ruling set is strong evidence; one against an
  unreviewed answer may be a key error.
- **Unexpected movement.** Unchanged steps come from the cache, so an answer that moves although none of its inputs
  changed points to a bug.
- **Verdict** (development dockets only). It counts the fields the named changes target, plus every docket that
  moved into or out of scope; the untouched fields are the noise reading, named only if they move beyond the band
  (then look for a bug or a missed target). Net loss if more dockets moved wrongly than rightly or the counted net
  units fall below the band; net improvement if more moved rightly or they rise above it, noting any counted field
  below it; a wash otherwise. The band is ±8 units: chance alone moved the whole key by +6, −6 and −5 net units
  (pass 4, the noise check, pass 6b), about 45 units gross each time. Until pass 6c the verdict counted every
  field, so full reruns were decided by noise. A field's own move inside the band is noise too.
- **A full rerun is also a noise reading.** When the scan changes, every step reruns, so the fields no change
  targets show what chance alone does. Report them apart from the targeted fields.
- **Branches.** Some fields answer one chain of questions: a standard's level, result and condition; the ending
  fields; the condition challenges; the appellants and their lawyers. One wrong turn shows in all of them, so a
  regression is reported per branch (one chain on one docket), not per answer.
- **Severity**, as `compare.py` ranks it:
  - **high:** a docket moved into or out of scope wrongly; a branch of 5 or more wrong answers, including on a
    docket newly in scope; a break against a reviewed key answer;
  - **medium:** a branch of 2 to 4 broken answers, or any break in a field a change targeted;
  - **low:** a single break in a field no change targeted. Treat these as noise unless several share a cause.

### The post-experiment assessment

After every pass, report to the project owner in this form, in this order, before anything else about the pass.
Keep each part short; tables come from `compare.py`, the rest is your reading of the evidence.

1. **Headline.** One sentence: the verdict, net units against the band, the cost, and the two run IDs.
2. **Change table.** The development table from `compare.py`, one row per change plus the untouched (noise) row,
   and a sentence on what each row means. The held-back table goes under it, marked report-only.
3. **Scope movement.** Each docket that moved, whether rightly, and for a docket newly in scope how many answers
   came with it and which branches are wrong. A new docket with a wrong branch is a gain and a regression at once:
   say both ("a whole docket came into scope, but its arguments branch is wrong, 14 answers").
4. **Regressions.** Every high and medium row, most severe first, grouped where one cause covers several. For
   each: what broke and how many answers; the severity and why; the likely cause, with what you checked (the step's
   answer and quote, whether a gate let the step run, the scan's probabilities, whether the docket's inputs
   changed); and the proposed fix and what it would cost. Name the cause as one of: the change itself, rerun
   noise, a gate that kept a step from running, a definition gap (a question for the project owner), or a likely
   key error. Low rows get one line unless they share a cause.
5. **Noise.** What the untouched row shows, and whether the wash band still looks right.
6. **Decisions needed.** Definition questions for the project owner, each with a recommendation.
7. **Next.** The change you'd make next, and why.
8. **State.** What changed on disk, what is committed, and what wasn't done.

### Rules learned the hard way

- **Adjudicate only when the project owner asks.** Reviewing disagreements with subagents burns usage; report
  the scores and let the owner decide. When it runs, use Sonnet: Opus was thorough but expensive.
- **Don't re-review what is settled.** A disagreement an adjudicator already ruled on stays settled; the
  classifier skips it. Apply verdicts to the key instead of re-examining them.
- **Never rescan the corpus while iterating.** Passes run on the key's dockets only. The corpus is scanned again
  once, in the final pipeline run after iterating ends. Changing scan wording is fine during a pass: it rescans
  only the key's dockets, but it changes every step's cache key, so the pass becomes a full rerun (about $0.65).
- **Settle definitions before relabeling.** Definition questions go to the project owner with a recommendation.
  Write the answer into the step prompt (or the option meaning) that answers the field: a step reads only its own
  prompt, the options of the question it answers, and the system prompt, never codebook notes, a scan question's
  option meanings or the key's edge cases (C2 in 6b, the lot rulings in 6c). `make_prompt.py` copies step prompts
  into the labeling prompt, so the labelers get it too; `edge_cases.md` is for labeler-only guidance.
- **Fix the key's consistency in code** where a codebook rule decides it (such as results "not decided" for a
  standard not decided), rather than with another agent pass.
- **Measure noise before judging small effects.** Rerunning the same pipeline moves about 45 units gross across
  the key. A field that sits at the same error count under several designs (other questions, passes 5b and 5b2)
  may be at its noise floor, or limited by its key.
- **Say what a step should do, not what it shouldn't.** Rules written as prohibitions ("never derive units from
  lots") lost to any number the decision stated; the affirmative definition fixed them (6a). Lists of exclusions
  grow with every case.
- **Steps that write long lists are expensive.** A step that writes many quoted items costs several times a
  yes/no step (5b).
- **Check a fix on the cases it targets before judging the total.** A change can hit every target and still score
  a loss on a convention the key disagrees with itself on (6a); settle the convention, then rescore.

## Building or extending the key

What worked when labeling, from the October 2026 grounds keys and this key:
- **Generate the labeling prompt from the codebook,** so the key and the pipeline can't drift apart. It copies the
  questions, options, notes and most step prompts; `edge_cases.md` adds labeler-only guidance and the owner's
  rulings, each of which must also be written into a step.
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

- Labeled by Sonnet, one subagent per docket, from a prompt generated from the codebook (`make_prompt.py`, now
  `prompt-v6.md`) plus `edge_cases.md`.
- Corrected by two rounds of adjudication (Opus, then Sonnet), by targeted updates when definitions changed, and
  in code by the project owner's rulings.
- 21 dockets in scope by the rule. Every label passes the code check.
- **Held-back caveat:** 5 of the 13 held-back dockets (101-5-07, 223-10-08, 38-2-00, 54-5-15, 90-6-01) have
  been through adjudication, and 223-10-08 shaped a definition. Treat the other 8 as the clean held-back set,
  or draw fresh held-back dockets before the production run.
- **Known key convention gap:** for kinds of permission, labelers often wrote "not stated" where the pipeline
  writes "no". The scripts treat this as a convention; decide which is right and fix one side.

## Where things stand

Pipeline at commit `4099881` plus the cleanup and pass 6e; latest run `20261019-050906-8c70`. Scored without
adjudication, against the key as it stands:

| | Development (51 dockets) | Held back (13) |
|---|---|---|
| Scope right | 50 | 11 |
| In-scope dockets found | 17 of 18 | 3 of 3 |
| False passes | 0 | 2 (23-ENV-00104, 38-2-00) |
| Field agreement, dockets in scope on both sides | 93% (1,101 of 1,190) | 96% (202 of 210) |

- **The one development miss** is 23-2-06, an inn with the owners' living quarters, which L1c flipped to "not
  housing" by chance in pass 6a.
- **Where development errors are:** other questions 17, judgment standards 27 (levels 14, results 8, conditions
  5), condition-challenge lists 10, kinds of permission 4, kind of relief 4.
- **Noise:** chance alone moves about 45 units gross per full rerun; the wash band is ±8. About a fifth of errors
  are coin flips; the rest repeat run to run (the noise check in the log).
- **Passes so far:** see [IMPROVING-LOG.md](IMPROVING-LOG.md). Kept: grounds evidence rules (3), conversions and
  derived unit comparisons (4), the arguments ruling and ending gate (5a), this-permission scope and units said
  affirmatively (6a), remands entered as judgment (6b), the lot rules in L6d (6c) and what an earlier-permits or
  who-can-appeal question must name (6e). Reverted: the question-first L9 (5b) and the codebook rule register (6d).

## Open ideas, not yet tried

Roughly in order of expected value.

1. **A clean held-back score** before the production run (see the held-back caveat).
2. **Judgment standards** (27 development errors, mostly stable): read the stable errors by pattern before changing
   prompts.
3. **Sibling dockets** (a quarter of the corpus shares a decision): a sentence in the Base naming the siblings, or
   an anchoring step for shared dockets only. Agreed in principle and deferred.
4. **Unstable scope steps.** Rerun noise has moved scope three times (90-6-01, 23-2-06, 118-7-03), each on a
   borderline case. Consider asking a scope step twice when it contradicts a confident scan.
5. **Other questions** sit near their noise floor (about 19 answers move by chance): any experiment there needs two
   runs to read.
6. **Rules the key's labelers follow that no step says yet** (the review in the log): a boundary adjustment, after
   the fact, even if denied, a state appeal with its own docket, accessory units, care-housing counts, and four in
   the grounds. Write one into its step when an error points to it.
7. **The kinds-of-permission convention:** "not stated" against "no" (see the key section).
8. **Misfiled documents in the corpus.** Document 1 of 189-11-10 is a Stowe Highlands entry (35-3-11 Vtec) filed
   under this docket. Start with a manual exclusion list of (document, docket) pairs.
9. **Quote check leftovers.** About 36 of 90 failed quotes were paraphrases or text not on the page. Footnote
   numbers inside quoted text are one fixable cause.

## Open definition questions

Raised as "both defensible" by adjudicators and not yet put to the project owner:
- Is a party later dismissed as an appellant still listed among the appellants?
- When decision dates conflict across documents (such as September 12 against 13), which wins?
- Is a town board's authority against the state's on wastewater a "permits" question?
- Does a court's hedged recital ("it appears that two lots were sought") state a count?
