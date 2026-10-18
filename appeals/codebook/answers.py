"""Layer 6: the research answers and the fields that make them up.

Each answer's `examples` are SQL over a published release: the tables and
columns a release lays out from these fields (appeals/release/schema.py).
Building a release runs every example, so one that stops working stops the
release until it is fixed here.
"""
from appeals.codebook import derived as X
from appeals.codebook import fields as F
from appeals.graph.nodes import Answer


def example(question, sql):
    return {'question': question, 'sql': ' '.join(sql.split())}


scope = Answer('answer_scope', 'scope', title='Scope', question='Is this docket a municipal appeal about new housing?',
               parts=[X.X1, F.proceeding, F.physical_change, F.housing_use, F.units_effect],
               examples=[
                   example('How many dockets were studied, how many are in scope, and how many failed?', """
                       SELECT status, in_scope, count(*) AS dockets FROM dockets GROUP BY ALL ORDER BY ALL"""),
                   example('What are the out-of-scope dockets? (the kind of proceeding, among complete dockets)', """
                       SELECT proceeding, count(*) AS dockets FROM dockets
                       WHERE status = 'complete' AND NOT in_scope GROUP BY 1 ORDER BY 2 DESC""")])

which = Answer('answer_A', 'A', title='Which decisions get appealed',
               question='When the appeal was filed, in which town, how many units added and lots, what kind of permission.',
               parts=[F.filing_date, F.earliest_event, F.docket_filing, F.municipality, F.place_within_town, F.units_added_proposed,
                      F.appeal_partial, F.units_added_under_appeal, F.housing_lots, F.permission_kinds],
               examples=[
                   example('How many appeals were filed each year? (the filing date, else the docket number)', """
                       SELECT left(coalesce(filing_date, docket_filing), 4) AS year, count(*) AS appeals
                       FROM appeals GROUP BY 1 ORDER BY 1"""),
                   example('Which kinds of permission are appealed most?', """
                       SELECT item AS kind, count(*) FILTER (WHERE answer = 'yes') AS appeals,
                              count(*) FILTER (WHERE answer = 'not stated') AS not_stated
                       FROM permission_kinds GROUP BY 1 ORDER BY 2 DESC"""),
                   example('Which towns have the most appeals?', """
                       SELECT coalesce(municipality, 'not stated') AS municipality, count(*) AS appeals
                       FROM appeals GROUP BY 1 ORDER BY 2 DESC LIMIT 20""")])

who = Answer('answer_B', 'B', title='Who appeals, and against what',
             question='Whether the town approved or denied, who the appellants are, whether they had lawyers.',
             parts=[F.town_decision, F.town_decision_date, X.X6, F.appellants_named,
                    F.appellants, F.appellant_lawyers, F.units_added_town_approved],
             examples=[
                 example('Who appeals which town decisions? (appeals with at least one neighbor appellant)', """
                     SELECT a.town_decision, count(*) AS appeals,
                            count(*) FILTER (WHERE EXISTS (SELECT 1 FROM appellant_mix_roles r
                                WHERE r.docket = a.docket AND r.option = 'neighbor')) AS with_neighbor_appellants,
                            count(*) FILTER (WHERE a.appellants_count IS NULL) AS appellants_not_established
                     FROM appeals a GROUP BY 1 ORDER BY 2 DESC"""),
                 example('How often are appellants represented by a lawyer?', """
                     SELECT option AS representation, sum(count) AS appellants, count(DISTINCT docket) AS appeals
                     FROM appellant_mix_representation GROUP BY 1 ORDER BY 2 DESC""")])

grounds = Answer('answer_C', 'C', title='On what grounds',
                 question='Whether the appeal turned on standards that leave the outcome to judgment, which kinds, '
                          'how far each got, and which other kinds of question it dealt with.',
                 parts=[F.arguments_stated, F.judgment_grounds, F.judgment_results, F.judgment_conditions,
                        F.relief_kind, F.other_questions, F.conditions_challenged, F.conditions_challenged_by,
                        F.conditions_outcome, X.X7, X.X8, X.X9],
                 notes=['Central (X7) means disputed and decided; at issue (X8) is broader. Report both, and keep '
                        '"not stated" (arguments not described) apart from "no".'],
                 examples=[
                     example('How often was a judgment standard central to the appeal?', """
                         SELECT judgment_central, judgment_at_issue, count(*) AS appeals
                         FROM appeals GROUP BY ALL ORDER BY appeals DESC"""),
                     example('Which kinds of judgment standard were central, and how often were they at issue?', """
                         SELECT item AS kind,
                                count(*) FILTER (WHERE answer = 'decided, disputed') AS central,
                                count(*) FILTER (WHERE answer NOT IN ('not at issue', 'not stated')) AS at_issue
                         FROM judgment_grounds GROUP BY 1 ORDER BY 2 DESC"""),
                     example('What were the appeals without a central judgment standard about?', """
                         SELECT o.item AS kind, count(*) AS appeals
                         FROM appeals a JOIN other_questions o ON o.docket = a.docket
                         WHERE a.judgment_central = 'no' AND o.answer = 'decided, disputed'
                         GROUP BY 1 ORDER BY 2 DESC"""),
                     example('What was central to each appeal, and how did the appeals end?', """
                         SELECT what_was_central, how_ended, count(*) AS appeals
                         FROM appeals GROUP BY ALL ORDER BY appeals DESC"""),
                     example('Who challenged conditions, and what did the court do with them?', """
                         SELECT b.challenged_by, o.outcome, count(*) AS conditions
                         FROM conditions_challenged_by b
                         JOIN conditions_outcome o ON o.docket = b.docket AND o.condition = b.condition
                         GROUP BY ALL ORDER BY conditions DESC""")])

court = Answer('answer_D', 'D', title='What the court does',
               question='How the court heard the appeal, and how the docket ended.',
               parts=[F.review_standard, F.final_decision, F.how_ended, F.court_result, F.dismissal_basis, X.X2],
               examples=[
                   example('How did dockets end, and what did the court do?', """
                       SELECT final_decision, how_ended, court_result, count(*) AS appeals
                       FROM appeals GROUP BY ALL ORDER BY 4 DESC"""),
                   example('What did the court do, counting only answers backed by a verified quote?', """
                       SELECT a.court_result, count(*) AS appeals
                       FROM appeals a JOIN confidence c ON c.docket = a.docket AND c.field = 'court_result'
                       WHERE c.source = 'step' GROUP BY 1 ORDER BY 2 DESC""")])

how_long = Answer('answer_E', 'E', title='How long',
                  question='Days from filing (or the town\'s decision, when no filing date is stated) to the court\'s first decision that leaves nothing pending.',
                  parts=[X.X4, F.final_decision_date, F.latest_order_date],
                  examples=[
                      example('How long do appeals take? (median days by filing year; exact durations and lower '
                              'bounds kept apart)', """
                          SELECT left(duration_start_date, 4) AS filed, duration_kind AS kind, count(*) AS appeals,
                                 median(duration_days) AS median_days
                          FROM appeals WHERE duration_kind <> 'unknown' GROUP BY ALL ORDER BY ALL""")])

cost = Answer('answer_F', 'F', title='What it cost the housing',
              question='Stays, unit changes and design changes the court imposed, and where permission ended up.',
              parts=[F.stayed, F.stay_start, F.stay_end, F.units_vs_town, F.units_vs_application,
                     F.units_added_court_approved, F.design_changed, F.design_change, X.X3, X.X5],
              examples=[
                  example('Where did permission end up after the appeal?', """
                      SELECT last_permission, count(*) AS appeals FROM appeals GROUP BY 1 ORDER BY 2 DESC"""),
                  example('How many units did the court add or remove against the town\'s decision?', """
                      SELECT count(*) FILTER (WHERE unit_change_vs_town IS NOT NULL) AS appeals_with_counts,
                             sum(unit_change_vs_town) AS net_units_vs_town,
                             count(*) FILTER (WHERE unit_change_direction_vs_town IN ('more', 'fewer')) AS changed_direction,
                             count(*) FILTER (WHERE stayed = 'yes') AS stayed
                      FROM appeals""")])

ALL = [scope, which, who, grounds, court, how_long, cost]
