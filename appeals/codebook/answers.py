"""Layer 6: the research answers and the fields that make them up."""
from appeals.codebook import derived as X
from appeals.codebook import fields as F
from appeals.graph.nodes import Answer

scope = Answer('answer_scope', 'scope', title='Scope', question='Is this docket a municipal appeal about new housing?',
               parts=[X.X1, F.municipal_body, F.action_kind, F.physical_change, F.housing_use, F.units_effect])

which = Answer('answer_A', 'A', title='Which decisions get appealed',
               question='When the appeal was filed, in which town, how many units added and lots, what kind of permission.',
               parts=[F.filing_date, F.earliest_event, F.docket_filing, F.municipality, F.units_added_proposed,
                      F.appeal_partial, F.units_added_under_appeal, F.housing_lots, F.permission_kinds])

who = Answer('answer_B', 'B', title='Who appeals, and against what',
             question='Whether the town approved or denied, who the appellants are, whether they had lawyers.',
             parts=[F.town_decision, X.X6, F.appellants_named,
                    F.appellants, F.appellant_lawyers, F.units_added_town_approved])

grounds = Answer('answer_C', 'C', title='On what grounds',
                 question='Whether the appeal turns on judgment-based standards, and which issues were raised.',
                 parts=[F.arguments_stated, F.disputes_application, F.challenges_validity, F.principal_issue,
                        F.issues_raised])

court = Answer('answer_D', 'D', title='What the court does',
               question='How the court heard the appeal, and how the docket ended.',
               parts=[F.review_standard, F.final_decision, F.how_ended, F.court_result, F.dismissal_basis, X.X2])

how_long = Answer('answer_E', 'E', title='How long',
                  question='Days from filing to the court\'s first decision that leaves nothing pending.',
                  parts=[X.X4, F.final_decision_date, F.latest_order_date])

cost = Answer('answer_F', 'F', title='What it cost the housing',
              question='Stays, unit changes and design changes the court imposed, and where permission ended up.',
              parts=[F.stayed, F.stay_start, F.stay_end, F.units_vs_town, F.units_vs_application,
                     F.units_added_court_approved, F.design_changed, F.design_change, X.X3, X.X5])

ALL = [scope, which, who, grounds, court, how_long, cost]
