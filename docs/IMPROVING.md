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
| Compare | `uv run python data/answer-keys/full-2026-10/scripts/compare.py <before> <after> --change "<name>=<field>,<field>"` (one `--change` per change; `scope` stands for the scope fields) | Scores both runs against today's key and prints the verdict, the change table, scope movement and the ranked regressions for the post-experiment assessment. See "Judging a change" below. Writes `compare-<before>-<after>.json`. |
| Sort | `uv run python data/answer-keys/full-2026-10/scripts/classify.py <run>` | Splits disagreements into *settled* (an adjudicator already ruled on that docket and field), *scope-caused* (one side has the docket out of scope, so its fields can't agree), *convention* (the same meaning written two ways) and *real*. Writes `real-<run>.json`. |
| Adjudicate | one Sonnet subagent per docket; instructions in `adjudication/instructions.md` | Only real disagreements, and only on dockets in scope or where scope itself is disputed. Each verdict says who is right (key, pipeline, both defensible, neither), the cause (pipeline error, key error, definition gap) and why, with a page. |
| Apply | `uv run python data/answer-keys/full-2026-10/scripts/apply_adjudication.py <folder>` | Writes "pipeline" and "neither" verdicts into the key, marked `adjudicated`. Lists it can't apply go to `unapplied.json` for a labeling pass. |
| Check | `uv run python data/answer-keys/full-2026-10/scripts/check_labels.py labels` | Every label's shape, values against the codebook's types, the scope rule, and every quote on its page. |

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
- **Verdict** (development dockets only): net loss if scope breaks more than it fixes or net units fall below the
  wash band; a wash within it; a net improvement above it, noting any field below it. The band is ±6 units, from
  pass 4: a full rerun moved the fields no change touched by +17/−11 units, so a smaller net change can't be told
  from chance. A field's own move inside the band is noise too. Revisit the band as passes add readings.
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

Then add the pass to "Passes" below: what ran, the verdict and change table, the regressions and their causes,
and what changed.

Rules learned the hard way:
- **Use Sonnet for checking.** Opus adjudication of 26 dockets was thorough but expensive; Sonnet did the
  second round well.
- **Don't re-review what is settled.** A disagreement an adjudicator already ruled on stays settled; the
  classifier skips it. Apply verdicts to the key instead of re-examining them.
- **Never rescan the corpus while iterating.** Passes run on the key's dockets only. The corpus is scanned again
  once, in the final pipeline run after iterating ends. Changing scan wording is fine during a pass: it rescans
  only the key's dockets, but it changes every step's cache key, so the pass becomes a full rerun (about $0.65).
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

Passes 3 and 4 were scored without adjudication, so they aren't in the table; see their entries.
Pass 3 (run `20261018-234503-a702`): Against the
same key, raw agreement rose from 1,230 to 1,257 of 1,515 development answers and from 256 to 258 of 275
held-back answers, and real disagreements fell from 117 to 93. Scope didn't change.

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

### Pass 3: grounds evidence rules (pipeline at 9a08818 plus uncommitted changes)

Run `20261018-234503-a702`, $0.31 (estimated $0.27). Only L7a, L8 and L9 changed; the scan and every other step
came from the cache. Scored and classified only: the project owner asked for no adjudication this pass, so
nothing below has been checked by a reviewer.

Changed:
- **L8:** answer above "not at issue" only for a standard a party argued about this project or the court applied
  to it, with a quote about that kind. Passing words, background facts and neighbouring kinds don't count.
- **L9:** the same rule for the other questions.
- **Rulings by the project owner**, in the L8 prompt, the codebook notes and `edge_cases.md`:
  - a general Statement-of-Questions question (such as "all of § 500") disputes only the standards argued
    specifically;
  - a standard found moot or not required, or sent back to the town board to review first, is "set aside";
  - `arguments_stated` counts only arguments about the town's decision itself, not ones only about procedure
    (reinstatement, deadlines, standing, jurisdiction). This is in L7a, not the G1 scan.
- **Key:** 101-5-07 traffic and water to "decided, not disputed", and 93-8-18 water to "set aside", under those
  rulings.

**Compare verdict** (`compare.py 20261018-224823-fd23 20261018-234503-a702`): net improvement, net units +8 against a
±2 band, no scope movement, no unexpected movement. By field: judgment standards +9 answers (43% of errors closed),
results +10 (62%), conditions +3 (50%), other questions −1 (a wash, with 7 fixed and 8 broken). Held back +2.

Found (development answers, both runs scored against the same key):

| Field | Pass 2 | Pass 3 |
|---|---|---|
| judgment_grounds | 98/126 | 107/126 |
| judgment_results | 102/126 | 111/126 |
| judgment_conditions | 105/126 | 114/126 |
| other_questions | 130/162 | 129/162 |

- **Judgment standards improved:** for example 164-12-17 water, 189-11-10 historic and 23-2-06 relief (now set
  aside). 110-6-08 now reads "not stated" throughout. Misses stayed at 2, so the stricter rule cost no recall.
- **Other questions didn't improve.** False "at issue" answers went from 21 to 22, with churn: several fixed and
  as many new (110-6-08 earlier and meaning, 209-11-04 meaning, 35-3-04 appeal). The L9 sentence wasn't enough.
- **New judgment errors to look at:** 164-12-17 traffic is now decided with a condition (round 2 said its
  cul-de-sac condition is traffic, so the key may be wrong here); 189-11-10 water condition "yes".
- **124-7-99:** L7a now says no arguments although site was decided and disputed. The follow-ups kept the grounds
  answered, so the safety net worked, but `arguments_stated` is wrong there.

### Pass 4: conversions, unit comparisons and affirmative L9 kinds (2026-10-18)

Run `20261019-003005-e7da`, $0.64, a full rerun because the scan changed (the key's 64 dockets only). Compare
against pass 3: **net improvement, +23 units** (band ±6), development. No adjudication.

Changed, with the project owner's rulings:
- **Scope:** a new S2 option, `convert a non-residential use to housing` (with or without construction), and "no
  physical change" now means a change of use that creates no dwelling units. L1b reads S2, so it follows. CONTEXT.md
  and `edge_cases.md` say the same. Key: 40-4-13 (an office made into an apartment) and 121-10-16 (a mill made
  wholly residential) relabeled to the new option.
- **Unit comparisons** are now derived columns: from the unit counts when both are known, else from a new quoted
  step, L6g (for example a court upholding the town's approval without restating its size), else "not stated". The
  scan's U4 and U5 now only open the counts gate. The quoted answers are kept as `units_vs_town_stated` and
  `units_vs_application_stated`. The key scripts now score derived columns too.
- **L9 and G3:** each other-question kind is now the question the court must answer, with examples of how a
  decision puts it, in place of "Not:" lists. L9 states that question in a sentence before the level. "Who can
  appeal" covers only the appeal or an appellant as a whole; the court narrowing single questions is not this kind
  (6 key labels moved to "not at issue").

Change table (development; `--change` for scope, unit comparisons and other_questions):

| Change | Errors before → after | Fixed | Broken | Net units | Read |
|---|---|---|---|---|---|
| Scope: change-of-use conversions | 40 → 38 | 5 | 3 | +4/−3 | 1 docket rightly into scope (40-4-13) |
| Unit comparisons | 15 → 2 | 13 | 0 | +13/−0 | real gain |
| Affirmative L9 kinds | 27 → 25 | 11 | 9 | +6/−3 | within noise |
| Untouched (noise) | 78 → 73 | 20 | 15 | +17/−11 | chance alone |

Regressions and their causes:
- **40-4-13, newly in scope (high):** 27 of its 70 answers are wrong, in two branches.
  - *Arguments (14 answers):* the key says no arguments are stated because the Statement of Questions only asks
    whether the use complies; the run says yes and puts every standard at "not at issue". A definition gap: under
    the general-question ruling the run's reading is consistent, so the key likely needs updating.
  - *Ending (6):* the ending gate stops at P(C2 = yes) ≥ 0.5 and the scan gave 0.12, so L5a never ran. The court
    remanded with a judgment order ("This completes the current proceedings"). A gate keeping a step from running.
- **121-10-16 traffic (high, reviewed key, 3 answers):** L8 now says not at issue, quoting a criteria list. L8 didn't
  change; the scan's traffic probability moved from 0.68 to 0.59 between runs. Rerun noise.
- **90-6-01, held back, wrongly into scope (high):** L1d now says the amended permit adds a unit; the key says the
  unit was approved by the earlier permit. Rerun noise on a hard rule (an amendment of an approved unit adds none).
- **101-5-07 water, held back (high, reviewed key):** L8 picked "taken up" (a farmland question left for trial) over
  the decided § 500 ruling, against the furthest-point rule. Rerun noise.
- **L9 (medium, 9 answers on 5 dockets):** the named questions show two patterns. A recited fact taken as a ruling
  ("Appellant timely filed an appeal", 176-10-04 and 209-11-04, read as "decided, not disputed"). A question put
  under a neighbouring kind (39-2-06 property for where a right-of-way should go; 249-11-05 meaning for whether a
  30-foot right-of-way exists).
- **118-7-03, 23-2-06 judgment standards (medium):** levels and conditions moved with no prompt change. Rerun noise.

### Pass 5a: arguments ruling and ending gate (2026-10-18)

Run `20261019-013457-fcec`, $0.07, against pass 4. The scan was unchanged, so only L7a–e and the ending steps on
dockets the lower gate now lets through reran. **Wash, −2 units** (band ±6). The question-first L9 runs alone as 5b.

Changed:
- **Arguments ruling** (project owner): a Statement of Questions asking only whether the project complies counts as
  arguments stated, disputing no standard. In L7a, the codebook note and `edge_cases.md`; the key's 40-4-13 label
  updated to match.
- **Ending gate** `final` from 0.5 to 0.1, so L5a checks endings the scan doubts.

| Change | Errors before → after | Fixed | Broken | Net units | Read |
|---|---|---|---|---|---|
| Arguments ruling | 38 → 50 | 0 | 12 | +0/−6 | within noise, but every move a break |
| Ending gate | 23 → 19 | 6 | 2 | +6/−2 | within noise; all 6 fixes on 40-4-13 |
| Untouched | 87 → 87 | 0 | 0 | — | cached, no noise reading |

The ruling's gain doesn't show in the table, because the key changed for both runs: with it and the gate, 40-4-13
went from 27 wrong answers (pass 4, old key) to 5.

Regressions:
- **27-2-10 and 35-3-04, `arguments_stated` yes → none found (high on 27-2-10: the judgment standards went "not
  stated", 7 answers).** Both appeals argue that the application was deemed approved because the town decided late.
  L7a's list of procedural arguments includes "deadlines", meant as the appeal's filing deadline, and the model read
  the town's decision deadline into it. A definition gap in our wording.
- **39-2-06 ending (medium, 2 answers).** The lower gate let L5a run, and it answered "no final decision" from the
  interim decision. The ending appears only in a later Supreme Court entry order reciting the Environmental
  Division's merits decision. The existing rule then blanked `how_ended` and `court_result`, which the scan had right.
- **Condition-challenge lists on 121-10-16 (medium).** L7b–e reran because L7a's prompt changed; the lists' wording
  moved. Rerun noise.

**Rerun as 5a2** (run `20261019-014137-abc4`, $0.11), with two fixes: L7a names the procedural arguments that don't
count as those about the court appeal itself (reinstatement, the filing deadline, standing, jurisdiction) and counts
arguments that the town's process was defective (a deemed approval, inadequate findings); L5a accepts an ending
shown by a later document that recounts it. The project owner set the bar: keep the batch only if it beats pass 4.
Against pass 4: **net improvement, +10 units**.

| Change | Errors before → after | Fixed | Broken | Net units | Read |
|---|---|---|---|---|---|
| Arguments ruling | 38 → 38 | 3 | 3 | +3/−3 | within noise; its gain is the key's 40-4-13 (14 answers) |
| Ending gate | 23 → 13 | 10 | 0 | +10/−0 | real gain |

27-2-10, 35-3-04 and 39-2-06 recovered. The only breaks are in the condition-challenge chain, which reruns whenever
L7a changes: 121-10-16's list wording, and 196-9-08's challenge dropped (yes → no). Rerun noise, unconfirmed.

### Pass 5b: question-first L9, reverted (2026-10-18)

Run `20261019-014748-94c7`, $0.50, against 5a2, the only change. **Wash, −1 unit.** With its revision (5b2,
below), it failed the project owner's bar (beat 5a2) and was reverted: L9 is the per-kind version from 5a2.

Changed: the nine per-kind L9 steps became L9a (list the docket's other questions, up to 12, one sentence and a
quote each) and L9b (for each, its kind with all kinds side by side, and its level). `other_questions` is derived:
each kind takes the furthest level of its questions. G3 stays in the scan only to decide whether L9a runs (any kind
at 0.5 or above); in this run it skipped no docket. Drop it, and the gate, at the final pipeline run.

| Change | Errors before → after | Fixed | Broken | Net units | Read |
|---|---|---|---|---|---|
| Question-first L9 | 27 → 27 | 16 | 16 | +5/−6 | within noise |

- **It traded false positives for misses:** false "at issue" 19 → 13, missed 2 → 7, wrong level 6 → 7.
- **The list was good; the sorting wasn't.** L9a found 6 to 12 questions per docket. L9b gave each exactly one kind,
  and pulled whole dockets toward one: on 164-12-17, 8 of 10 questions went to "earlier permits" (the docket is a
  permit amendment), including the 75% open-space rule and the reading of a bylaw section; on 189-11-10, 7 of 11 went
  to "allowed use and defined terms", including whether septic systems are structures under a setback. The kind
  definitions expect one dispute to count under several kinds (a measuring dispute is both meaning and measurable),
  which a single-kind sort can't express.
- **The court managing the appeal still leaked** into "who can appeal" (39-2-06 and 93-8-18: questions dismissed as
  outside the appeal), though most such items went to "none of these".
- **Cost:** 233 calls, about 3.5 times the per-kind L9's, because every L9b call carries the whole docket.

**Revised as 5b2** (run `20261019-015601-4270`, $0.34): L9a leaves out the court's handling of the case (motions,
the Statement of Questions); L9b sorts all of a docket's questions in one call and may give a second kind. Against
5a2: **wash, −3 units** (14 fixed, 15 broken). Reverted with 5b.

| Run | False "at issue" | Missed | Wrong level | Total |
|---|---|---|---|---|
| 5a2 (per-kind L9) | 19 | 2 | 6 | 27 |
| 5b (one kind per question) | 13 | 7 | 7 | 27 |
| 5b2 (second kind allowed) | 18 | 3 | 7 | 28 |

- The second kind brought back the misses (7 → 3) and the false positives with them (13 → 18). It was given to 37
  of 153 questions, most often "allowed use and defined terms" for questions about reading a statute or a
  stipulation (110-6-08, 27-2-10, 93-8-18), which that kind's question doesn't ask.
- Cost: $0.34, more than twice the per-kind L9. The two calls per docket are long: L9a averaged $0.0074 a call,
  about seven times a per-kind L9 call, because it writes up to 12 quoted questions.
- Three structures landed within one error of each other. The limit is likely in the kind definitions, or in the
  key's other-question labels, not in how the steps are arranged.

What the failed experiment taught:
- **Listing worked; sorting didn't.** L9a found real questions (6 to 12 a docket). The errors moved between kinds of
  error as the sorting rules changed, but the total didn't.
- **One kind per question is too few, and a free second kind is too many.** If this is tried again, settle first
  which kinds may pair (the definitions only call for meaning with measurable rules).
- **Writing out lists is expensive.** A step that writes many quoted items costs several times a yes/no step.
- **Before restructuring a field again, measure its noise.** A field that sits at the same error count under three
  designs may be at its noise floor, or limited by its key.

### Noise check (2026-10-18)

Run `20261019-023832-492d`, $1.07: the 5a2 pipeline (same graph hash) on the 64 dockets with `--fresh-steps`, the
scan reused. Every difference from 5a2 (`20261019-014137-abc4`) is chance. `scripts/noise.py <run> <fresh-run>`
gives flip rates by area, field and step, comparing what each answer decides rather than its wording.

- **Overall:** 28 answers fixed and 30 broken by chance alone; net −6 units, gross +19/−25. With pass 4's untouched
  reading (+6), chance has now landed on both edges of the ±6 band.
- **About a fifth of errors are coin flips:** of about 161 wrong answers per run, 127 are wrong in both runs and 68
  answers are right in one run only.
- **Stable areas** (no step answer changed): proceeding and physical change (L1a, L1b), filing date (L2a), the
  town's decision (L3a), the ending chain (L5a to L5d), the review standard (L10), stays and design changes.
- **Unstable areas:**

| Field | Flip rate | Wrong in both runs | Coin flips | Step and its flip rate |
|---|---|---|---|---|
| other_questions | 12% | 20 | 19 | L9, 18% |
| appeal_partial | 19% | 2 | 3 | L6b, 30% |
| permission_kinds | 7% | 5 | 8 | L3 kinds, 13% |
| appellants, appellant_lawyers | 10–14% | 1 | 5 | L4a, L4b, 31% (partly name formatting) |
| unit counts and comparisons | 5–10% | 9 | 4 | L6e 17%, L6g 27% |
| judgment standards | 4–5% | 20 | 13 | L8, 6% |

- **What it means for the passes:** chance alone moves about 19 other-question answers. The 16 fixed and 16 broken
  in 5b, and 14 and 15 in 5b2, were mostly that. A smaller real effect on other questions can't be seen in one run.
- One pair of runs is one sample; rates on small counts (L6g ran on 11 dockets) are rough.

### Pass 6a: this permission only, units added said affirmatively, condition lists (2026-10-18)

Run `20261019-033224-3734`, $0.18, against 5a2 (`20261019-014137-abc4`). The scan was unchanged. Scored with the
wash band at ±8. First scored as a net loss (−9 units) because of the convention below; the project owner ruled
that a count the documents show to be none is 0, the key was updated in code (27 answers), and the rescore is a
**net improvement, +21 units**.

Changed:
- **Scope (L1b, L1d):** answer for what the permission under appeal itself allows, beyond what was already approved
  or built; a follow-up approval of an earlier condition allows only what it adds; approval of work already done is
  "authorize something already built"; a subdivision whose houses need later permits neither adds nor replaces.
- **Units added (L6):** counted as what this permission allows beyond what exists or was approved; a lots-only
  subdivision adds 0; a property total with no count of existing units is "not stated".
- **Condition lists** follow the no-arguments rule, like `conditions_challenged`.
- **Rulings** (project owner): a remainder lot keeping an existing home is not a new lot; a denial approved 0 units
  for group or care housing too. In L6d to L6f, `housing_lots`'s note and `edge_cases.md`.

| Change | Errors before → after | Fixed | Broken | Net units | Read |
|---|---|---|---|---|---|
| This permission only (scope) | 38 → 38 | 5 | 5 | +4/−4 | 23-ENV-00071 rightly out; 23-2-06 wrongly out |
| Units added, affirmative | 37 → 15 | 24 | 2 | +24/−2 | real gain (after the ruling; before it, 9 fixed and 17 broken) |
| Condition lists | 8 → 8 | 0 | 0 | — | 110-6-08 now "not stated" as intended (the lists shifted elsewhere) |

- **The fixes hit their targets:** 121-10-16's property total is now "not stated" (3 answers); 189-11-10's lots-only
  subdivision counts 0 units and 4 lots (5 answers); 27-2-10 and 39-2-06 lots are right; 23-ENV-00071 left scope,
  and in held back so did 90-6-01.
- **The first scoring's 17 unit breaks were one convention:** the pipeline said 0 where the key said "not stated",
  for units of lots-only subdivisions and lots of projects that create none, and the key itself was split. **Ruling**
  (project owner): when the documents show a project creates no units or lots, the count is 0; "not stated" is for
  when they don't let you tell. Applied to the key in code, following the codebook (units 0 when `units_effect` is
  neither, for each body that decided; lots 0 when the project neither creates lots nor is a subdivision; the
  comparisons from the counts), except 118-7-03, whose land-condominium house sites the documents leave unclear.
  In `edge_cases.md` and the notes on `units_added_proposed` and `housing_lots`.
- **Left after the rescore:** `units_added_under_appeal` 0 on 249-11-05 and 39-2-06, where L6b, the noisiest step,
  calls the appeal partial.
- **23-2-06 wrongly out of scope (high):** L1c reran only because it follows L1b, and on this inn with the owners'
  living quarters it flipped from housing to not housing. Rerun noise on a hard case.
- **23-ENV-00104, held back, wrongly in (high):** L1b now calls a boundary line adjustment "create building lots",
  though L1d quotes that it creates no new lot. Unclear whether the new wording or noise caused it.

### Pass 6b: a remand entered as the judgment ends the docket (2026-10-18)

Runs `20261019-034532-b1ef` ($0.88, a full rerun: the scan changed) and `20261019-035057-5364` ($0.04), against
pass 6a (`20261019-033224-3734`). Not committed. (Fix 5 of this slate, a Sonnet review of likely key errors, was
dropped: 75 of the 81 stable errors on in-scope dockets had already been adjudicated, nearly all for the key.)

Changed (project owner's ruling): a remand to the municipal panel that the court enters as its judgment, or says
completes its proceedings, ends the docket, even if the town must act again or other matters wait on it. In C2's
"yes", in L5a and in `edge_cases.md`.

- **C2 alone did not reach L5a.** The `{C2}` placeholder gives a step the question, not its options' meanings. The
  scan moved (93-8-18: 0.01 → 0.73 that the docket ended; 40-4-13: 0.12 → 0.96), but L5a, now let through, still
  read the paused matters as pending. The rule went into L5a's own text in the second run. Lesson: a definition in
  a scan option reaches a step only if the step's prompt repeats it.

| Change | Errors before → after | Fixed | Broken | Net units | Read |
|---|---|---|---|---|---|
| Remand as judgment (C2 + L5a) | 7 → 3 | 4 | 0 | +4/−0 | the targeted fields: right where intended |
| Untouched (noise) | 118 → 126 | 24 | 32 | +20/−25 | the third noise reading |

- **Verdict as the rule reads: net loss, −1 unit,** carried by the untouched fields: every step reran because the
  scan changed. The noise readings are now +6, −6 and −5 net, about 45 units gross each time.
- **118-7-03 wrongly out of scope (high):** pass 6a's new L1d sentence ("a subdivision whose houses are left to later
  permits neither adds nor replaces") was read on rerun to cover a land condominium whose houses "will be built by
  the purchasers of the house sites". In 6a the same step said it adds. The wording is ambiguous on this case.
- **121-10-16 judgment standards (high, 8 answers):** levels moved from "not at issue" to decided. Rerun noise.

### Pass 6c: follow-ups to 6b (2026-10-19)

Runs `20261019-035715-813a` ($0.16) and `20261019-040249-a3eb` ($0.01), against 6b (`20261019-035057-5364`). Not
committed.

- **L1d:** houses this permission approves are added even if purchasers will build them; a subdivision adds none
  only when its houses need permits of their own.
- **L6d** now carries the lot rulings in its own text: 0 when the documents show the project creates no lots, and a
  lot released from a restriction (such as open space) is a new lot. They had been only in the codebook note and
  `edge_cases.md`, which steps don't see.
- **A first try also reworded the shared units-added rule** to match L1d. It broke the lots-only zeros (4 answers:
  the step couldn't tell whether the houses need permits of their own, so it answered "not stated") and was undone.

| Change | Errors before → after | Fixed | Broken | Net units | Read |
|---|---|---|---|---|---|
| L1d: houses purchasers build | 36 → 33 | 3 | 0 | +2/−0 | 118-7-03 rightly back in scope (70 answers, 60 right) |
| L6d: zero lots and released lots | 9 → 3 | 6 | 0 | +6/−0 | no breaks |

**Audit: scan definitions that never reach their steps.** Twelve steps cite a scan question (`{F1}`, `{C2}`, …) whose
option meanings they never see: the placeholder gives the question, not the meanings. Only C2's meanings carried
rules, now repeated in L5a; the other eleven restate their options. The same leak applies to field notes and
`edge_cases.md`, which only the key's labelers read: a rule there reaches the pipeline only if a step's prompt says it.

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
   - **Scope moved by step noise** (90-6-01 in pass 4): consider whether a scope step that flips against a
     confident scan should be asked twice.
4. **The ending gate** stops L5a when the scan gives under a 0.5 chance of a final decision, so a confident-looking
   scan "no" is never checked (40-4-13, a remand with a judgment order). Consider a lower threshold, as the scope gate
   got in pass 1.
5. **Unstable step answers.** Rerun noise moved scope (90-6-01) and reviewed grounds answers (121-10-16, 101-5-07).
   Consider asking a step twice when it contradicts a confident scan, and keeping the answer only when both agree.
6. **L9 patterns** from the named questions: a recited fact read as a ruling, and a question put under a
   neighbouring kind. A question-first design (5b, 5b2) didn't help; see what it taught before trying another.
   The noise check comes first.
7. **Unit counts.** The pipeline counts a property's total units as units added when the existing units aren't
   stated (121-10-16). For lots-only subdivisions, units added should follow the "neither" rule (0), which the
   key now uses.
8. **The kinds-of-permission convention:** "not stated" against "no" (see the key section).
9. **Misfiled documents in the corpus.** Document 1 of 189-11-10 is a Stowe Highlands entry (35-3-11 Vtec)
   filed under this docket. Start with a manual exclusion list of (document, docket) pairs that grouping
   applies; later, perhaps flag documents whose caption names another docket.
10. **Quote check leftovers.** About 36 of 90 failed quotes were paraphrases or text not on the page. Footnote
   numbers inside quoted text are one fixable cause.
11. **A clean held-back score** before a release run (see the held-back caveat).

## Open definition questions

Raised as "both defensible" by adjudicators and not yet put to the project owner:
- Is a party later dismissed as an appellant still listed among the appellants?
- When decision dates conflict across documents (such as September 12 against 13), which wins?
- Does a remainder lot that keeps an existing home count as a new lot? (The adjudicators said no.)
- For denied group or care housing, is the town-approved count 0 (the denial rule) or "not stated" (the
  care-housing rule)?
- Is a town board's authority against the state's on wastewater a "permits" question?
- Do arguments made only on motions count as arguments stated?
- Does a court's hedged recital ("it appears that two lots were sought") state a count?
