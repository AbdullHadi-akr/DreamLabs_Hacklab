# Demo checklist

1. From the repo, run `.venv/bin/python start.py --no-browser` if port 8000 is idle. Open `http://localhost:8000/`. The browser UI is served by the backend and needs no separate build.
2. Check that the simulation reports Ready and that the viewport and camera feeds update. Offline use needs no API variables. For live use, the launcher reads the existing Dream SDK credential file or a configured `DREAM_API_KEY`; provider URLs come from the same SDK configuration. The API-key badge confirms local configuration only. A live task is needed to confirm provider access and consumes credits.
3. For a credit-free demonstration, choose Offline demo on Dashboard, or open Test Suite → Quick Test, enable Dry run and start the campaign. The dry-run report is deliberately unevaluated.
4. Open Test Suite → Report, choose a campaign by date and task, inspect the timing and task outcome separately, and open Export for JSON, CSV or the browser print view.
5. If a live run is authorized for the demo, use a supported placement prompt such as “Put the apple onto the plate.” Review final target and release evidence before describing the outcome.
6. If a campaign pauses at a provider limit, open its report to see completed trials and resume requirements. Stop campaigns from Test Suite. If the simulator fails, consult the application log and restart the local backend after checking that no execution is active.
