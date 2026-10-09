# Archived: hackathon control room

This is the local project-control tool used to coordinate the Starwatch build during the Agents 0.0.7 hackathon night. It is not part of the Starwatch product and is kept only as a record of how the work was organised.

It served a single-page dashboard on `127.0.0.1` over the project's `TODO.md`: an editable product page, a Kanban board, recorded decisions, an architecture graph (React and XYFlow, with the compiled bundle in `project_tracker/web/`) and an activity stream of the coding agents working on the entry. A small CLI (`scripts/control-room`) gave agents the same version-checked writes as the browser.

The detailed design notes are in [project_tracker/README.md](project_tracker/README.md). They describe the hackathon setup as it was, including local paths and terminal-session details that do not apply elsewhere.

## Tests

```sh
uv sync
uv run --with pytest pytest
```

The tests use disposable fixtures and a fake agent transport; they do not contact any outside service.
