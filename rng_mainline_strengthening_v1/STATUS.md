# Locked deployment archive

| Analysis | Archive | Contents |
|---|---|---|
| Reconciled deployment and distance | [mainline run_007](results/mainline/run_007/) | Event definitions, annual counts, at-risk landfills, common-support and expanded-support model estimates |
| Landmark comparison | [temporal run_007](results/temporal/run_007/) | Baseline registry cohort, evidence-screened endpoint and model comparisons using the historical pipeline layer |
| Archived graphics | [figures run_004](results/figures/run_004/) | Deployment chronologies, event-definition comparisons, landmark results and the historical reporting plot |
| Archived checks | [checks run_004](results/checks/run_004/) | Evidence, scope, numerical and figure checks documented at the time of the locked release |

The common-state model contains 1,317 landfills, 114 events and 38,071 at-risk landfill-years. Its odds ratio per doubling of mapped distance is 0.907 with a 95% spatial interval of [0.814, 1.012]. The exposure uses the full mapped pipeline layer. [Model table](results/mainline/run_007/deployment_comparisons.csv)

Event and source ledgers keep registry dates, assigned analysis dates and evidence bounds as separate fields. See the [evidence index](claims_to_evidence.md) for row definitions and the [evidence catalog](../evidence/README.md) for the adjudication inputs.

Use the [repository entry points](../README.md#reproduce-the-locked-model) to verify the public inputs, replay the model and redraw the deployment plots. See the [manuscript draft](../manuscript/MANUSCRIPT.md) for the common-window reporting analysis.
