# Context for whoever works here next

This project is a rewrite. An earlier version, `~/src/court-appeals-analysis`,
was an exploratory prototype. It answered the same research questions, but it
grew a large framework, layers of versioning, and labeling rules written case
by case. This repository keeps what was learned and leaves the rest behind.
This page is the part worth knowing. The [README](../README.md) says what we're
building, and [PIPELINE.md](PIPELINE.md) gives the current design in detail.

## How the user works

- **Questions get answers, not actions.** When the user asks how to do
  something or where a decision should live, answer in chat. Edit files, run
  pipelines or spend money only when asked directly.
- **Commit only when asked.**
- **Keep work inside this repository.** The old project is read-only
  reference.
- **Don't copy code or move data from the old project until the user asks.**
  The goal is a lean design, not a port. When a piece is carried over, rewrite
  it to fit here.
- **Write plainly.** Docs say what something does and why, in ordinary
  English.
- **Visuals are standalone HTML pages.** Serve them on `0.0.0.0` and share
  the LAN address (`192.168.88.3`), since `localhost` is unreachable for the
  user.
- **Decisions about definitions are the user's.** Bring them a short question
  with a recommendation. Prefer questions about general rules over questions
  about individual cases: rules fitted to the reference cases were a main
  failure of the prototype.

## The research

The study concerns appeals of town land-use decisions about **new housing**
heard by the Vermont Environmental Division, as seen through its published
decisions. "New housing" means the permission at issue lets someone build,
place or convert a structure that will contain dwelling units, or create lots
for housing. Enforcement, changes of occupancy and accessory work are out of
scope, and so are permits for something already built. The research questions
are in [PIPELINE.md](PIPELINE.md#research-questions).

The decisions are the only source, which sets hard limits on what can be
claimed:
- appeals that left no published decision are invisible;
- a missing final decision doesn't prove a case is still open;
- nothing here shows whether homes were built.

## The corpus

These figures come from the September 2026 snapshot. The old project's
`analysis/doc-types/` and `analysis/case-length/` pages show them in full.

- **Size.** About 2,600 listing entries pointing to 2,560 distinct PDFs,
  posted 2000–2026, about 100 a year.
- **The court's type tag can't filter.** The listing's document-type filter
  splits by era: almost everything posted before 2017 is tagged "Opinions"
  and almost everything after is "Decisions". "Orders" (4) and "Judgements"
  (1) are barely used. Every document is some kind of ruling.
- **What the documents are.** By content: summary judgment rulings 34%,
  merits decisions after a hearing 19%, other motion rulings 17%, dismissal
  rulings 13%, post-judgment rulings 10%, short judgment orders 4%,
  procedural orders 2%.
- **Which documents carry which facts.** Background facts (the project, the
  town's decision, the appellants, the grounds, the filing date) come mainly
  from merits and summary judgment decisions. End dates and outcomes come
  from merits decisions, post-judgment rulings and judgment orders. Dropping
  any document type would cost end dates, so all documents are kept.
- **Dockets.** One docket per case gives about 1,760 dockets. 60% have a
  single document. Only about 43% of dockets have a document that says
  outright that it ends the case ("This concludes the matter").
- **Length.** The median docket is about 21k characters (about 5k tokens);
  the longest is about 420k. Roughly 3% exceed the decision model's standard
  context, and few of those are in scope. They are mostly Act 250 and
  state-permit disputes with one very long merits decision.
- **Shared decisions are copied.** A decision issued in several dockets
  appears in full in each docket's text, so some sibling dockets have
  identical text. That costs extra calls, and it means extraction must keep to
  the docket at hand.
- **Expected in-scope share.** The prototype's estimate was roughly a fifth
  to a quarter of cases, with a sizable uncertain group. This hasn't been
  measured under the new definitions.

## The decision model

TypeSafe's **Jev** is the first decision model. Its docs are at
`https://docs.typesafe.ai/llms.txt`, and they are the source of truth; check
them before integrating.

- **Request shape.** One request carries a `state` (the docket text) and any
  number of named questions. Each question is a `choice` (up to 255 options),
  a yes/no `noul`, or a `score` (2–10 ordered levels).
- **Answers.** Jev returns probabilities only: no text and no quotes. That is
  why every answer that needs evidence goes through a reasoning-model step.
- **Limits** (Jev 1.14): 32k tokens for each question (the state plus that
  question) and 64k for the whole request. The header
  `TypeSafe-Danger-Zone-Long-Context: true` raises both to 262k, at some cost
  in speed and accuracy. All dockets fit in that mode.
- **Pricing.** Input tokens only, about $0.042 per million.

Code reaches it only through the decision-model interface described in the
README, so it can be swapped out.

## What the prototype taught us

- **Definitions first.** The prototype started extracting before its
  definitions were settled. Rules then grew one surprising case at a time
  until nobody could see the whole. Here the question list in PIPELINE.md is
  the definition, and the code follows it.
- **"Unknown" and "no" are different answers.** Treating them alike was a
  constant source of errors.
- **Never infer an outcome from a ruling on a motion.** Interim rulings are
  common, and a long case can end in the record with trial still pending.
- **Keep to this docket.** Shared decisions discuss several dockets, and facts
  leak between them.
- **Say who did it.** Effects need an actor. "Housing changes" quietly mixed
  changes the town made with changes the court made until the rule said "the
  court".
- **Score everything that is structured.** The prototype scored a hand-picked
  list of facts, so some structured data, such as each appellant's role, was
  never measured.
- **Prefer small closed questions.** Large prompts that ask for a whole record
  at once are hard to test and hard to fix.

## The reference set

The prototype has 76 hand-checked dockets, 40 of them in scope, split into
development and held-back sets. They are labeled in the prototype's own
format, which doesn't match the questions here, and its 16 newest labels
were never approved. They live in the old project under `reference/`. They
will need relabeling as answers to this project's question IDs before the
gate thresholds can be tuned. The case selection, their texts and the second
readings are still useful. Held-back dockets must stay out of development.

## What's in the old project, for reference

Read these for understanding only. Don't copy them.

| Path in `~/src/court-appeals-analysis` | Why you'd look |
|---|---|
| `in/` | The raw listing snapshot and the PDFs stored by hash, which this project will reuse when the user says so |
| `steps/fetch/vtec-environmental.py` | How the listing is crawled politely |
| `steps/text/` | Native text, the ink check, OCR and selection, with their thresholds |
| `steps/cases/group/docket-headings.py` | The docket-heading rules that PIPELINE.md describes, with the edge cases they handle |
| `docs/question-pipeline.html` | The interactive prototype of the extraction graph this design is based on |
| `analysis/` | The document-type and case-length analyses |
| `proposal.html` | The original research proposal and its view of what the decisions can and can't show |
| `reference/` | The labeled dockets and the old labeling guide, as history rather than rules |

Everything else there (the step and prompt libraries, the pipeline tags,
the lab and experiment records, the research server and the legacy-run
reproduction) solved problems this rewrite deliberately doesn't have.

## Settled decisions

- **Storage.** The pipeline's working store is SQLite (`data/appeals.sqlite`),
  in write-ahead-log mode so the dashboard can read during a run. Analysis
  of finished results (output snapshots, an MCP server for querying them,
  and a public data dashboard) uses DuckDB, and is designed separately.
- **The reasoning model is not fixed.** DeepSeek Flash is in use for now;
  others will be tried through `config.toml`.

## Open decisions

The user will decide these, so don't assume them:
- the reasoning model and the budget,
- the gate thresholds and the long-context threshold,
- how the relabeling is done,
- the order of the build phases.
