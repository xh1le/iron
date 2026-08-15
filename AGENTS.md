# iron — agent conventions

- Always lowercase "iron" in code/docs.
- Units: mm for CAD via fusion360 MCP; but iron itself is a Python/React desktop app in this repo.
- **Push to GitHub after every change**: after editing files and verifying (build/tests), run:
  `git add -A && git commit -m "<short message>" && git push`
  Remote: `origin` (github.com/xh1le/iron). Never wait for the user to ask.
- Frontend changes require `cd frontend && npm run build` before the running server picks them up (static dist). Server: `python run.py` (port 7744). Watchdog auto-recovers.
- Backend tests: `python -m pytest -q` in repo root.
- UI conventions: glassmorphism, cool gray palette, custom pickers (ModelPicker/ProjectPicker), Confirm/Modal components for dialogs, toast for feedback, Markdown component for agent output.
- Don't use window.prompt/confirm — use Modal/Confirm.
