# CASCADE — Documentation Index

**CASCADE** (Causal-Aware Stage-Chained Arrival & Delay Estimator) predicts a shipment's final ETA, quantifies the likelihood and magnitude of delay, and explains **which stage** drives it. It then turns that into decisions: a stable promise date, alerts, cost-of-delay and ranked interventions.

| Doc | Read it for | Primary audience |
|---|---|---|
| [PRD.md](PRD.md) | Problem, differentiators, beyond-the-brief decision layer, goals, requirements, success metrics | Everyone, reviewers |
| [Architecture.md](Architecture.md) | Components, data flow, latency budget, reliability and degradation chain, deployment, ADRs | Engineers, reviewers |
| [Design.md](Design.md) | Stage graph, simulator mechanics, schemas, features, models, explanations, evaluation, API contracts, UX wireframes, decision layer | Implementers |
| [TechStack.md](TechStack.md) | Tools and versions, the reason for each, rejected options, repo layout, commands | Engineers |
| [Rules.md](Rules.md) | Golden rules, code/data/ML/API/UX/testing rules, git workflow, quality gates | All contributors (incl. AI assistants) |
| [Phases.md](Phases.md) | 72-hour roadmap, phase gates, cut lists, report outline, demo script, solo critical path | Leads, everyone |
| [AsBuilt.md](AsBuilt.md) | Every deviation between plan and implementation, with reasons | Reviewers |
| [ReviewVerification.md](ReviewVerification.md) | External review checked claim by claim against the code (what is confirmed, what is not, what it missed) | Reviewers |
| [ImprovementPlan.md](ImprovementPlan.md) | v1.1 "trust every ETA" plan: P0/P1/P2 tickets with owners, files and acceptance criteria | Implementers |
| [ModelCard.md](ModelCard.md) | Auto-generated model card (intended use, performance, weaknesses) | Everyone |
| [../dashboard/README.md](../dashboard/README.md) | React dashboard: entry screen by role, sections, run and snapshot commands | Reviewers, UX |
| [ImplementationPlan.md](ImplementationPlan.md) | Ticket-level plan: owners, estimates, dependencies, files, acceptance criteria, risks | Implementers |

## The idea in 30 seconds

1. **A causal simulator with a cause ledger:** realistic logistics mechanics (missed connections, berth queues, customs weekends), and every hour of delay is tagged with its true cause.
2. **As-of nowcasting:** one model predicts the remaining delay at every checkpoint, so the ETA sharpens as stages complete.
3. **Propagation features:** buffers, cut-offs, congestion × lateness and calendar projection capture how upstream delay meets downstream capacity.
4. **Calibrated and explained:** conformal P10–P90 ranges plus stage-level waterfalls. Explanation accuracy is **measured** against the ground truth.
5. **The decision layer:** Promise ETA, alerts, cost-of-delay, intervention advisor and a disruption radar. Each prediction comes with a recommended action.
6. **Production-minded:** < 50 ms p95, a fallback chain, versioned artifacts with quality gates, and a one-command run.
