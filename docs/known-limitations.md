# Known limitations

Updated 22.11.2026, after the overnight sprint (which [overnight-summary.md](overnight-summary.md) describes as it was then).

- **Spending is counted, not billed.** The Dream Labs API does not report the balance. The dashboard counts calls ×
  price per run (`dashboard/credits.py`), refuses a run that could pass the monthly limit and stops a running run (or
  campaign) when the limit is reached. Runs made outside this dashboard, and models without a known price (a
  fine-tune), are not counted; the Dream Labs account stays the source for billing.
- **Automatic scoring needs a known task type.** The success check understands the task types listed in the Episodes
  tool (`RULES` in `dreamtool/scene.py`); the Test Suite's placement evaluation is strongest for object placement with
  observable target, release and stability. Other tasks still run, but stay "Unevaluated".
- **Dream-1 is not deterministic.** Identical scenes and prompts can give different runs, so one run illustrates
  behaviour; a reliability claim needs repeated or paired runs (Repeated Runs, A/B Comparison, Strategy A/B).
- **The simulator pauses physics during every request.** The real robot keeps moving meanwhile; the runner tells the
  client so (`latency="paused"`, see README → Latency). Results about timing do not transfer one to one.
- **Safety checks are limited.** Reports flag contacts between the two arms and modelled joint-limit violations.
  Workspace boundaries and contact force limits are not defined.
- **No scenario editor or saved regression baseline.** The Test Suite builds each campaign from its form; there is
  no stored set of scenes to rerun as a baseline.
- **Browser coverage.** The repository has JavaScript regression harnesses for the report and the viewer overlay
  (`tests/*.mjs`), but no automated check across screen sizes or of the browser console. The tutorial was checked by
  hand at desktop and phone width.
- **Multiplayer needs cloudflared** on the host laptop (README → Multiplayer); the quick link changes at every start.
