# Demo checklist

1. Start the dashboard if port 8000 is idle: `..\.venv\Scripts\python.exe start.py --no-browser` from `dream-tool\`
   on Windows (`../.venv/bin/python start.py --no-browser` on macOS / Linux). Open `http://localhost:8000/`. The browser
   UI is served by the backend and needs no separate build.
2. Check that the simulation reports Ready and that the 3D view and camera feeds update. Offline use needs no API
   variables. For live use, the launcher reads the Dream SDK credential file or a configured `DREAM_API_KEY`; the
   provider URLs come from the same file. The API-key badge confirms local configuration only: a live task is needed
   to confirm provider access, and it consumes credits.
3. To introduce the page, open **Tutorial → Dashboard basics** (or start the dashboard at
   `http://localhost:8000/?tour=basics`). It walks through the page in nine steps and spends nothing.
4. For a credit-free demonstration, choose **Offline demo** on the Dashboard, or open **Test Suite → Quick Test**, tick
   **Dry run** and start the campaign. The dry-run report is deliberately unevaluated.
5. Open **Test Suite → Report**, choose a campaign by date and task, inspect the timing and task outcome separately,
   and open Export for JSON, CSV or the browser print view.
6. If a live run is authorized for the demo, use a supported placement prompt such as “Put the apple onto the plate.”
   Review the final target and release evidence before describing the outcome.
7. If a campaign pauses at a provider limit, open its report to see completed trials and resume requirements. Stop
   campaigns from the Test Suite. If the simulator fails, consult the application log and restart the local backend
   after checking that no execution is active.
