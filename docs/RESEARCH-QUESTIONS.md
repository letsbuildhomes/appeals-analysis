# Research questions

The study set out to answer these questions. They shaped what the pipeline
extracts: each fact and derived value was added because one of them needed
it. They are **not** part of the pipeline or the MCP server. The pipeline's
output is the facts and derived values themselves, a general set of
well-structured data, and the MCP server lets a user ask their own questions
of it. Answering these questions is analysis, done later over a published
release, such as for a public dashboard.

Each question below lists the release columns that answer it and some example
queries, written as DuckDB SQL over a release (see
[RELEASES.md](RELEASES.md) for the tables). The examples are not run or
checked by anything: a change to the release's tables can break them, so check
one before relying on it.

Out of scope by decision:

- **Supreme Court proceedings.** The end of a case is the Environmental
  Division's first final decision.
- **Whether appeals were frivolous.**
- **Construction outcomes,** which the decisions can't show.

## Scope

Is this docket a municipal appeal about new housing?

Columns that answer it:

- `in_scope`: In scope
- `proceeding`: Kind of proceeding
- `physical_change`: What the permission allows
- `housing_use`: Used for housing
- `units_effect`: Adds or replaces units

**How many dockets were studied, how many are in scope, and how many failed?**

```sql
SELECT status, in_scope, count(*) AS dockets
FROM dockets
GROUP BY ALL
ORDER BY ALL
```

**What are the out-of-scope dockets? (the kind of proceeding, among complete dockets)**

```sql
SELECT proceeding, count(*) AS dockets
FROM dockets
WHERE status = 'complete' AND NOT in_scope
GROUP BY 1
ORDER BY 2 DESC
```

## Which decisions get appealed

When the appeal was filed, in which town, how many units added and lots, what kind of permission.

Columns that answer it:

- `filing_date`: Filing date
- `earliest_event`: Earliest dated event
- `docket_filing`: Filing month or year from the docket number
- `municipality`: Municipality
- `place_within_town`: Place within the town
- `units_added_proposed`: Units added: proposed
- `appeal_partial`: Appeal covers only part
- `units_added_under_appeal`: Units added: under appeal
- `housing_lots`: New housing lots
- `permission_kinds`: Kinds of permission

**How many appeals were filed each year? (the filing date, else the docket number)**

```sql
SELECT left(coalesce(filing_date, docket_filing), 4) AS year, count(*) AS appeals
FROM appeals
GROUP BY 1
ORDER BY 1
```

**Which kinds of permission are appealed most?**

```sql
SELECT item AS kind, count(*) FILTER (WHERE answer = 'yes') AS appeals, count(*) FILTER (WHERE answer = 'not stated') AS not_stated
FROM permission_kinds
GROUP BY 1
ORDER BY 2 DESC
```

**Which towns have the most appeals?**

```sql
SELECT coalesce(municipality, 'not stated') AS municipality, count(*) AS appeals
FROM appeals
GROUP BY 1
ORDER BY 2 DESC
LIMIT 20
```

## Who appeals, and against what

Whether the town approved or denied, who the appellants are, whether they had lawyers.

Columns that answer it:

- `town_decision`: Town's decision
- `town_decision_date`: Date of the town's decision
- `appellant_mix`: Appellant mix
- `appellants_named`: All appellants named
- `appellants`: Appellants
- `appellant_lawyers`: Appellants' representation
- `units_added_town_approved`: Units added: town approved

**Who appeals which town decisions? (appeals with at least one neighbor appellant)**

```sql
SELECT a.town_decision, count(*) AS appeals, count(*) FILTER (WHERE EXISTS (SELECT 1
FROM appellant_mix_roles r
WHERE r.docket = a.docket AND r.option = 'neighbor')) AS with_neighbor_appellants, count(*) FILTER (WHERE a.appellants_count IS NULL) AS appellants_not_established
FROM appeals a
GROUP BY 1
ORDER BY 2 DESC
```

**How often are appellants represented by a lawyer?**

```sql
SELECT option AS representation, sum(count) AS appellants, count(DISTINCT docket) AS appeals
FROM appellant_mix_representation
GROUP BY 1
ORDER BY 2 DESC
```

## On what grounds

Whether the appeal turned on standards that leave the outcome to judgment, which kinds, how far each got, and which other kinds of question it dealt with.

Columns that answer it:

- `arguments_stated`: Arguments stated
- `judgment_grounds`: Judgment standards: how far each got
- `judgment_results`: Judgment standards: the court's result
- `judgment_conditions`: Judgment standards: dispute about a condition
- `relief_kind`: Kind of dimensional relief
- `other_questions`: Other questions: how far each got
- `conditions_challenged`: A condition was challenged
- `conditions_challenged_by`: Who challenged each condition
- `conditions_outcome`: What the court did with each condition
- `judgment_central`: A judgment standard was central
- `judgment_at_issue`: A judgment standard was at issue
- `what_was_central`: What was central

Central (`judgment_central`) means disputed and decided; at issue (`judgment_at_issue`) is broader. Report both, and keep "not stated" (arguments not described) apart from "no".

**How often was a judgment standard central to the appeal?**

```sql
SELECT judgment_central, judgment_at_issue, count(*) AS appeals
FROM appeals
GROUP BY ALL
ORDER BY appeals DESC
```

**Which kinds of judgment standard were central, and how often were they at issue?**

```sql
SELECT item AS kind, count(*) FILTER (WHERE answer = 'decided, disputed') AS central, count(*) FILTER (WHERE answer NOT IN ('not at issue', 'not stated')) AS at_issue
FROM judgment_grounds
GROUP BY 1
ORDER BY 2 DESC
```

**What were the appeals without a central judgment standard about?**

```sql
SELECT o.item AS kind, count(*) AS appeals
FROM appeals a
JOIN other_questions o ON o.docket = a.docket
WHERE a.judgment_central = 'no' AND o.answer = 'decided, disputed'
GROUP BY 1
ORDER BY 2 DESC
```

**What was central to each appeal, and how did the appeals end?**

```sql
SELECT what_was_central, how_ended, count(*) AS appeals
FROM appeals
GROUP BY ALL
ORDER BY appeals DESC
```

**Who challenged conditions, and what did the court do with them?**

```sql
SELECT b.challenged_by, o.outcome, count(*) AS conditions
FROM conditions_challenged_by b
JOIN conditions_outcome o ON o.docket = b.docket AND o.condition = b.condition
GROUP BY ALL
ORDER BY conditions DESC
```

## What the court does

How the court heard the appeal, and how the docket ended.

Columns that answer it:

- `review_standard`: Review standard
- `final_decision`: A decision ends the docket
- `how_ended`: How the docket ended
- `court_result`: What the court did
- `dismissal_basis`: Dismissal basis
- `court_changed_outcome`: Court ended somewhere different from the town

**How did dockets end, and what did the court do?**

```sql
SELECT final_decision, how_ended, court_result, count(*) AS appeals
FROM appeals
GROUP BY ALL
ORDER BY 4 DESC
```

**What did the court do, counting only answers backed by a verified quote?**

```sql
SELECT a.court_result, count(*) AS appeals
FROM appeals a
JOIN confidence c ON c.docket = a.docket AND c.field = 'court_result'
WHERE c.source = 'step'
GROUP BY 1
ORDER BY 2 DESC
```

## How long

Days from filing (or the town's decision, when no filing date is stated) to the court's first decision that leaves nothing pending.

Columns that answer it:

- `duration`: Duration in days
- `final_decision_date`: Date of the first final decision
- `latest_order_date`: Date of the latest order

**How long do appeals take? (median days by filing year; exact durations and lower bounds kept apart)**

```sql
SELECT left(duration_start_date, 4) AS filed, duration_kind AS kind, count(*) AS appeals, median(duration_days) AS median_days
FROM appeals
WHERE duration_kind <> 'unknown'
GROUP BY ALL
ORDER BY ALL
```

## What it cost the housing

Stays, unit changes and design changes the court imposed, and where permission ended up.

Columns that answer it:

- `stayed`: Court stayed the permit
- `stay_start`: Stay start
- `stay_end`: Stay end
- `units_vs_town`: Units added vs the town's decision
- `units_vs_application`: Units added vs the application
- `units_added_court_approved`: Units added: court approved
- `design_changed`: Court changed size or design
- `design_change`: The size or design change
- `unit_change`: Change in units added
- `last_permission`: Last observed permission

**Where did permission end up after the appeal?**

```sql
SELECT last_permission, count(*) AS appeals
FROM appeals
GROUP BY 1
ORDER BY 2 DESC
```

**How many units did the court add or remove against the town's decision?**

```sql
SELECT count(*) FILTER (WHERE unit_change_vs_town IS NOT NULL) AS appeals_with_counts, sum(unit_change_vs_town) AS net_units_vs_town, count(*) FILTER (WHERE unit_change_direction_vs_town IN ('more', 'fewer')) AS changed_direction, count(*) FILTER (WHERE stayed = 'yes') AS stayed
FROM appeals
```
