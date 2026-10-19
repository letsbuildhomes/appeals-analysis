# Vermont municipal housing appeals

We study appeals of town decisions about new housing heard by the Vermont
Superior Court, Environmental Division. The court publishes its decisions as
PDFs. This project turns them into one row of research data per docket, and
every answer carries a quote from the decision it came from.

Every extraction question is listed in [docs/PIPELINE.md](docs/PIPELINE.md).
The research questions that shaped what we extract, and the columns and queries
that answer them, are in [docs/RESEARCH-QUESTIONS.md](docs/RESEARCH-QUESTIONS.md):
they are analysis over the data, not part of the pipeline. Background for
anyone starting work here is in [docs/CONTEXT.md](docs/CONTEXT.md).

## What the system does

```text
court website ─▶ documents ─▶ page text ─▶ dockets ─▶ extraction graph ─▶ research rows ─▶ releases
                                                          │                                     │
                                                     dashboard                  public site: dashboard · MCP
```

### 1. Documents

The Environmental Division's listing on the court website is read page by
page. Each listed PDF is downloaded once and stored under the SHA-256 hash of
its bytes, so a file is never fetched or stored twice. The listing entry's
title, posting date and docket number are kept with it. Every document in the
division is kept: the court's own document-type tag records when a document
was posted rather than what it is, so it is no use as a filter
([CONTEXT.md](docs/CONTEXT.md#the-corpus)).

Downloads are polite: one request at a time with a pause between, backing off
on rate limits and server errors.

### 2. Page text

Each page's text is extracted from the PDF's own text layer. A page whose
native text is missing, sparse or garbled is checked for ink, and pages with
visible content are read with OCR (Tesseract). Each page ends with one
chosen text and a note of where it came from (`native` or `ocr`), or a status
saying why it has none. Extraction is cached by document hash, so it runs
once per PDF.

### 3. Dockets

A **docket** is one case number, such as `129-9-12 Vtec` or `25-ENV-00114`,
and it is the unit of everything downstream. A docket's text is the text of
every document whose heading names that docket number, in posting order. A
decision the court issued in several dockets belongs in full to each of them.
The rules for reading a heading's docket numbers are in
[PIPELINE.md](docs/PIPELINE.md#dockets).

The docket text is written in a simple XML-like form so that quotes can cite a
document and page:

```xml
<docket number="129-9-12 Vtec">
<document n="1" title="Hinesburg Hannaford Act 250" posted="2013-05-02" dockets="129-9-12 Vtec; 163-11-12 Vtec">
<page n="1" source="native">
…page text…
</page>
</document>
</docket>
```

### 4. The extraction graph

Extraction is a graph of small, typed questions. The graph is ordinary code
built from a handful of building blocks. The same graph object drives
execution, renders as a diagram, and checks itself.

**Building blocks**

- **`Question`**: one closed question for a decision model. It has an ID, the
  question as asked, its kind (`choice` with named options, or yes/no), the
  meaning of each option, and the reason the question exists. A question never
  asks for free text. A **`YesNoSet`** asks one prompt as a separate yes/no
  question per item, shown as one node; a **`ChoiceSet`** does the same with
  one choice question per item, every item with the same options.
- **`Scan`**: a set of `Question`s sent together in one decision-model request
  over the same docket text. The questions run in parallel and can't see each
  other's answers. Each answer comes back as a probability or a probability
  distribution.
- **`Gate`**: a condition over earlier answers, such as "G1 is yes with a
  probability of at least 0.3". A gate is written as a small expression
  object, not a function, so code can evaluate it and the diagram can show it
  as text.
- **`Base`**: the shared start of every reasoning-model call for one docket.
  It holds a framing prompt, the docket text, and the scan's answers stated as
  claims to confirm or refute. It is built once and cached by the model
  provider.
- **`Step`**: one reasoning-model call asking for one detail. It appends a
  single question to the `Base` and declares the typed result it returns, with
  quotes. A step runs when its gate passes and, if it has one, when its
  `only_if` condition on earlier answers holds. It starts fresh from the
  `Base` unless it names a step it comes `after`, in which case the
  exchanges along that line are kept in context; related details run as
  such a chain, one conversation. A step can also run once per item of an
  earlier step's list (`for_each`), up to a limit, such as once per
  appellant; each iteration is its own call and record. Its
  reply must be JSON matching that type. A reply that doesn't parse or
  validate is sent back to the model with the errors, a set number of times,
  before the step fails; a reply cut off at the output limit, or empty, is
  sent again unchanged.
- **`Field`**: one settled value per docket, such as an appellant list, a
  date or a count, with its allowed values (always including "not stated").
  It takes its step's answer when the quote checks out, otherwise the scan's
  most likely answer, otherwise "not stated". A rule can make it "not stated"
  when an earlier answer makes the question moot, and a few fields, such as
  the filing month a docket number encodes, are computed in code. A field
  over a for-each step turns each iteration into entries (`per_item`).
- **`Derive`**: a plain function from named fields to a new field, such as a
  duration in days or the town's overall decision. No model is involved.

The models sit behind two small interfaces: a **decision model**, which answers
closed questions with probabilities (TypeSafe's Jev is the first
implementation), and a **reasoning model**, which answers a step's question
with structured output. Nothing else in the code names a model.

**Checks when the graph is built**

The graph refuses to build when:
- it has a cycle,
- a `Question` or `Step` feeds no `Field` or `Derive`,
- a node names no known topic,
- a gate refers to something that doesn't exist, or
- a structured field has no scoring rule.

Every structured field is scored against the reference answers, and free
text is never scored. The graph also exports itself as `graph.json` for the
dashboard.

**The executor**

Workers each take one docket through the layers in order, and every layer
writes one record:
1. **input**: the docket text.
2. **scan**: one decision-model request.
3. **plan**: every gate evaluated, with the numbers it used, and the steps to run.
4. **steps**: one reasoning thread on the docket's `Base`, with the planned
   steps run in order, so the cached prompt stays warm; every quote is checked
   against its cited page (or running onto the next), ignoring case, spacing and
   words hyphenated across a line break.
5. **facts**: one settled value per field.
6. **derive**: derived values.
7. **row**: the flat research row.

Dozens of workers run at once against shared rate limits per endpoint, and a
budget stops new model calls once it is spent.

Every node's output is stored under the docket, the node and a hash of the
node's inputs. That one table serves as:
- **the cache:** an unchanged node is never run twice,
- **the resume point:** an interrupted run simply runs again,
- **the trace:** the dashboard replays it to show what happened to a docket.

A **run** records the hash of the graph it used, the dockets it covered and
what it cost. Versioning is git and that hash, nothing more.

**Long dockets.** A docket that fits the decision model's standard context
goes in one request. A longer one, a few percent of dockets and mostly out of
scope, goes in long-context mode. The threshold is set in the configuration.

### 5. Dashboard

A small web app over the stored runs, with two views:

- **Graph**: the extraction graph, one row per topic (every node names
  one, in `codebook/topics.py`), with columns for the scan, gates, steps, facts
  and derived values. A conversation reads top to bottom, like a transcript.
  Clicking a box lights its neighbours (or, with Trace lineage, everything up
  and down the line) and opens a panel with its question, options, condition,
  prompt or code. Choosing a run and a docket replays its execution: which
  steps ran, which gates passed, and what each box answered. ELK
  (`static/vendor/elk.bundled.js`, EPL-2.0, license beside it) lays out the
  rows and routes the lines.
- **Case**: one docket's text with every cited quote highlighted, beside the
  facts that cite it, grouped by topic. Reference answers are shown alongside where they exist.

The dashboard only reads stored data and never changes it.

### 6. Releases and the public site

A finished run is frozen into a **release**: research tables in DuckDB, the
quotes behind them in a separate file, and a `release.json`. The JSON holds
the run's graph description, a data dictionary with a profile and query tips
for every column, the codebook's checked examples, and what changed since the
last release. The tables are laid out from the codebook's value types, so a
release follows the codebook with no hand-kept mapping.

The public site serves the current release at `/appeals/`. It has a
landing page, which explains the data, walks through how it is made and
shows how to connect an AI assistant; a page for every appeal, at
`/appeals/<version>/<docket>`, with each quote opening its page of the
decision; and an MCP server at `/appeals/mcp`. Through the MCP server, an AI
assistant can query the data, read what each column means, read the passages
behind any case's answers, and link the reader to the case's page.
[docs/RELEASES.md](docs/RELEASES.md) has the details and the deployment.

## Using it

Everything runs through `uv` and the `Makefile`; `make help` lists the targets.
Poppler is required, and Tesseract is needed only to OCR new scanned pages.

```sh
make setup            # install dependencies, check tools and keys
make graph            # build and check the extraction graph; writes data/graph.json
make run MODEL=fake LIMIT=40          # try the graph with made-up answers: no API calls
make run MODEL=live DOCKETS="a,b" TAG=scratch   # real calls, tagged; keys from .env (see .env.example)
make run MODEL=live LIMIT=0 STOP=scan TAG=scan  # every docket, scan only; STOP takes a step ID too
make runs [TAG=scratch]                          # list runs
make delete-runs TAG=scratch          # or RUN_ID=<id>; stored results are kept for later runs
make prune-results                    # delete stored results no run uses (asks first)
make serve            # dashboard on port 8800; restarts itself when the code changes
make release RUN_ID=<id>              # freeze a finished run into a release
make publish RELEASE=<id>             # make it the one the public site serves
make site                             # public site and MCP server on 0.0.0.0:8000 (SITE_HOST, SITE_PORT)
make test lint
```

The models, workers, the budget and gate thresholds are in `config.toml`, which
names each model as `provider/model`. Each provider has a file in `providers/`
with its address, the environment variable its key is read from, its rate
limits and its models' prices; its `kind` names the code in
`appeals/providers/` that reads the file and prices calls, so a provider with
unusual pricing (such as DeepSeek's peak hours) gets its own kind. Keys go in
`.env` (never committed) or on the command line (`appeals run --help`).

## Where things are

| Path | What |
|---|---|
| `appeals/ingest/` | listing, PDFs, page text, dockets |
| `appeals/graph/` | the building blocks, the executor and the model endpoints; knows nothing about housing |
| `appeals/providers/`, `providers/` | model providers: the code for each kind, and one file per provider with its models and prices |
| `appeals/codebook/` | the pipeline itself, one file per layer: questions → gates → steps → fields → derived → answers |
| `appeals/web/` | the dashboard server and its pages |
| `appeals/release/` | building releases from runs, reading them, and the guide that describes them |
| `appeals/site/` | the public site: the MCP server, the read-only API and the dashboard page |
| `deploy/` | the systemd unit for the public site |
| `data/` | the SQLite store (`appeals.sqlite`), PDFs, listing snapshots and releases (not in git) |

## Status

Ingest holds every PDF, the September and October 2026 listing snapshots
and all page text. The September material was imported once from the
prototype, and dockets are recomputed by the new rules. The extraction graph
is built and checked, and can be inspected in the dashboard. It has been
improved pass by pass against a 64-docket answer key (Jev for the scan,
DeepSeek Flash for the steps), with the gate thresholds set from it; [docs/IMPROVING.md](docs/IMPROVING.md) has the method and where
things stand. The whole corpus has been scanned once, for drawing the key;
the production run rescanned it on October 19, 2026, after a fresh crawl, and
became the first published release (v0.0.1, release `0faee78a2c22`).
[docs/PIPELINE.md](docs/PIPELINE.md) is the design, and
[docs/CONTEXT.md](docs/CONTEXT.md) explains how we got here.
