# AGENTS.md

## Dev environment tips

- Use:
  C:\Application\Anaconda\envs\llm_env\python.exe

- Always use the absolute Python path for dependency installation.


## Running commands

- Use the configured interpreter for Python commands:

```powershell
C:\Application\Anaconda\envs\llm_env\python.exe
```

- The planned end-to-end CLI (after `src/main.py` is implemented) is:

```powershell
C:\Application\Anaconda\envs\llm_env\python.exe -m src.main --ifc .\examples\sample.ifc
```

- The current scaffold does not yet contain `src/main.py`; do not report the
  application as runnable until that entry point has been implemented.


## Testing instructions

- Verify the application starts successfully.
- Real IFC test models are stored under `./test_sampe/` in the project root.
- Verify IFC files from `./test_sampe/` can be loaded; do not treat these large
  binary fixtures as source files or modify them during tests.
- Verify compliance checking pipeline produces expected outputs.


## Code style

- Use Python type hints.
- Keep functions focused.
- Avoid unnecessary dependencies.
- Prefer readable and maintainable code.


## Project-specific instructions

- Keep BIM data extraction, rule evaluation, and reporting logic separated.

- Normalize linear BIM measurements to millimetres. Treat
  `IfcDoor.OverallWidth` as overall door width, never as clear width.

- Keep LLM evacuation-door classification in `src/ai`; IFC parsing must only
  extract facts, and clear-width resolution plus compliance checks must remain
  deterministic.

- Keep intermediate data representations explicit.

- Avoid using LLMs for deterministic compliance checks.

- Design modules so that data models can evolve during development.


## Common pitfalls

Avoid:

- Mixing IFC parsing and business logic.
- Adding unnecessary frameworks.
- Hardcoding assumptions that should be configurable.

<!-- BEGIN brain.md -->
## Project Brain

This project keeps a **Project Brain**: a persistent memory layer of its durable decisions, requirements, and constraints. Read `./BRAIN.md` for the full read/write contract.

Use it actively:
- Before any task or discussion, load the relevant brain context with the `brain` CLI's read commands.
- Whenever a decision, requirement, constraint, or durable insight surfaces — in discussion or in code — record it with the `brain` CLI before moving on; don't wait to be asked.
- All reads and writes go through the `brain` CLI — never hand-edit brain files.

The brain skills (`brain-setup`, `brain-page`, `brain-ingest`, `brain-bootstrap`) are installed in your global skills directory.
<!-- END brain.md -->
