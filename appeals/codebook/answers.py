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
                 question='Whether the appeal turns on judgment-based standards, and which issues were raised.',
                 parts=[F.arguments_stated, F.disputes_application, F.challenges_validity, F.principal_issue,
                        F.issues_raised],
                 examples=[
                     example('How often do appeals dispute how a judgment-based standard was applied?', """
                         SELECT arguments_stated, disputes_application, count(*) AS appeals
                         FROM appeals GROUP BY ALL ORDER BY ALL"""),
                     example('Which issues do appellants raise?', """
                         SELECT item AS issue, count(*) FILTER (WHERE answer = 'yes') AS appeals,
                                count(*) FILTER (WHERE answer = 'not stated') AS not_stated
                         FROM issues_raised GROUP BY 1 ORDER BY 2 DESC""")])

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
