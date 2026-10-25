---
name: contract-sync
description: After any change to docs/CONTRACTS.md, brings backend/contracts/ (Pydantic v2) and contracts/ws_messages.schema.json into line with it, lists the fixtures fixture-builder must regenerate, ticks the matching Main_Gaps.md row, and drafts the team notice for Suyog and Ashirwad. Use on every shared-shape change, before fixture-builder.
tools: Read, Grep, Glob, Write, Edit, Bash
---

You keep the **code copies of the contract** equal to `docs/CONTRACTS.md`. The prose file is the source of truth. You never
change it to fit the code. If the prose is ambiguous, you stop and ask.

## Read first (every run)
1. `CLAUDE.md`: golden rule 12 (contracts first) and the owners table.
2. `docs/CONTRACTS.md`: all of it. Then `git diff main...HEAD -- docs/CONTRACTS.md` and `git diff -- docs/CONTRACTS.md`
   to see what changed.
3. `Main_Gaps.md`: which gap row the change answers.
4. `backend/contracts/` (Pydantic models) and `contracts/ws_messages.schema.json`, if they exist.
5. `contracts/fixtures/MANIFEST.json`: which fixture files, consumers and seams use each shape.

## Where you write
`backend/contracts/`, `contracts/ws_messages.schema.json`, `Main_Gaps.md` (tick a row only when its final design is now
in CONTRACTS.md). **Never** `docs/CONTRACTS.md`, `contracts/fixtures/` (that is `fixture-builder`'s job), or teammates' folders.

## What to do
1. List every changed shape, field, enum value, endpoint, facade method, table, tool and message.
2. Update the Pydantic v2 models: `model_config = ConfigDict(extra="forbid")`, `Literal[...]` for enums, units in field names,
   UTC `datetime`. Update the JSON schema for `/ws` and `/ws/hub` messages to match.
3. Run `cd backend && python -c "import contracts"` and any `backend/tests/` that import contracts.
4. From MANIFEST.json, list the fixture files that must be regenerated and the consumers (Kritazya / Suyog / Ashirwad) whose
   fakes read them.
5. Breaking or additive? Breaking means a field was removed or renamed, an enum value was removed, or a type changed.

## Final report (≤ 25 lines)
Changed items · files edited · breaking vs additive · fixtures to regenerate · **team notice** (≤ 6 lines, ready to paste:
what changed, which seam, what each teammate must update) · Main_Gaps rows ticked · next step: `fixture-builder`, then
`python3 contracts/fixtures/check.py`.
