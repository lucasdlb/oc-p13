# UI Workflow

Use this workflow when changing the Angular UI or reviewing visual regressions. The required review target for this POC is desktop; tablet and mobile captures are optional exploration only.

## Visual Loop

1. Start the application stack needed for the screen under review.
2. Capture the current UI into `.scratch/ui-reviews/<label>/`.
3. Inspect the desktop screenshots for both initial and demo-move states.
4. Make the smallest UI change that addresses the observed problem.
5. Rebuild and recapture with a new label.
6. Compare the new desktop capture against the previous `.scratch/ui-reviews/<label>/` set.

Completion criterion: the desktop captured states prove the intended UI behavior, or the remaining gap is recorded in that capture's `notes.md`.

## Scope

Desktop is the source of truth for visual review in the current POC demo. Do not block UI work on tablet or mobile captures unless the user explicitly asks for responsive polish.

## Capture Tool

The capture tool is repo-level development tooling, not frontend application code.

Location:

```text
tools/ui-capture/
```

Install/update its dependencies from that directory:

```bash
npm install
```

Run Angular in one shell:

```bash
cd frontend
npm start
```

Capture in another shell:

```bash
cd tools/ui-capture
npm run capture -- dashboard-v3
```

Use a different running URL when needed:

```bash
CAPTURE_BASE_URL=http://localhost:4200 npm run capture -- dashboard-v3
```

The tool writes all viewport files by default, but desktop is the required review target:

```text
.scratch/ui-reviews/<label>/desktop-initial.png
.scratch/ui-reviews/<label>/desktop-after-demo-move.png
```

Optional exploratory outputs:

```text
.scratch/ui-reviews/<label>/laptop-initial.png
.scratch/ui-reviews/<label>/laptop-after-demo-move.png
.scratch/ui-reviews/<label>/tablet-initial.png
.scratch/ui-reviews/<label>/tablet-after-demo-move.png
.scratch/ui-reviews/<label>/mobile-initial.png
.scratch/ui-reviews/<label>/mobile-after-demo-move.png
.scratch/ui-reviews/<label>/notes.md
```

## Review Notes

Use `notes.md` for observations, proposed directions, and the decision taken for that capture label. Keep screenshots in `.scratch`; they are working artifacts for UI review, not source-of-truth documentation.

## Dependency Rule

Keep Playwright in `tools/ui-capture` unless it becomes part of a real frontend E2E test suite. Screenshot capture is an agentic review tool, so it should not add dependencies to the Angular app package.
