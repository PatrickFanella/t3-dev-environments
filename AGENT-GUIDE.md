# Development environments for agents

Read this guide before starting a preview, running local project tests, adopting an existing T3 thread, or opening a remote preview on Kvant, Dozor, or Almaz. Use the existing repository instructions for required verification and delivery gates. This guide does not apply to production deployment or to unrelated repositories.

## Establish the current workspace

Run these from the thread's current directory:

```sh
rtk proxy hostname
rtk proxy git rev-parse --show-toplevel
rtk proxy git status --short --branch
rtk proxy git remote -v
```

Keep the current host, branch, worktree, and uncommitted edits. Never move an active thread to a different checkout merely to use this launcher. Resolve the profile from the repository identity, not the worktree directory name. Supported profiles: `augr`, `clpr`, `dash`, `deadweb-relay`, `dsa-seats`, `hasanara`, `patchwork`, `productivity-suite`, `subcult-os`, `switchyard`, `top-shelf-remodels`, `the-common-house`, `arkhiv`. Hasanara's origin may be named `transcript-create`; use profile `hasanara`.

The launcher is installed at `~/.local/share/t3-dev-environments/dev.py`; the command is `~/.local/bin/t3-dev`. Read the corresponding entry in `~/.local/share/t3-dev-environments/profiles.json` before relying on its test scope. If the command is absent from PATH, use its absolute path. If the installation is missing, report the host and path; do not fall back to production Compose.

## Preview and edit loop

From the verified worktree, replace `PROFILE` with the supported profile:

```sh
rtk proxy ~/.local/bin/t3-dev --profile PROFILE start
rtk proxy ~/.local/bin/t3-dev --profile PROFILE url
rtk proxy ~/.local/bin/t3-dev --profile PROFILE sync
```

`start` includes dependency setup and waits for the configured readiness check. Success prints the source directory, environment identity, and URL; check that they match the intended worktree. Edit the original worktree. The app runs a copied snapshot, so use `sync` after edits or run `watch` in a separate terminal for automatic copy/restart. Never edit the generated snapshot as the source of a fix. Dependency changes require another `setup` or `start`; `watch` only copies and restarts.

Use `status` and `logs` to investigate failures. Use `stop` for your own preview when finished unless the user needs it left running; stop the watch process separately. Stop retains development data and caches. Do not kill another thread's app to free a slot: identify the owner and report the conflict. Kvant permits two shared-launcher app stacks; Dozor and Almaz permit one each. Tests serialize per host and may wait for another run.

Kvant Subcult OS has a repository-owned setup. If the current checkout contains `scripts/dev-env.sh`, follow its AGENTS.md and use `rtk proxy bash scripts/dev-env.sh start`, `seed`, `watch`, `stop`, and `verify` as documented. Do not replace its required verification with the shared recipe. On remote Subcult checkouts, inspect the repository requirements even when using the shared T3 actions. An older worktree may lack a newly added script; do not reset or switch its branch to obtain one.

## Tests and evidence

```sh
rtk proxy ~/.local/bin/t3-dev --profile PROFILE test
rtk proxy ~/.local/bin/t3-dev --profile PROFILE verify
```

For a focused iteration, supply an explicit command in the test snapshot, for example:

```sh
rtk proxy ~/.local/bin/t3-dev --profile dsa-seats test --command 'npm run test:run -- src/ui/view-models.test.ts --maxWorkers=1'
```

`--command` replaces the recipe test command, including any migration command in it. Dependency setup, declared test services, isolation, and cleanup still run. Include required migrations yourself when choosing a custom DB test command. Broaden checks as required by the change and repository instructions; a focused pass is not the full verification gate.

Test state is separate from preview state. Never supply production credentials, reuse a production or preview database for destructive tests, mount the host Docker socket, or disable isolation to obtain a pass. Dependencies are installed with registry access, but app and test networks are isolated. Live-provider tests may require a separate authorized environment.

Record the host, source root, Git revision and dirty state, exact command, exit status, and relevant result counts. Distinguish readiness, rendered UI, focused tests, recipe suites, required repository verification, and hosted CI. `identity.json` records snapshot identity, not a successful test. `verify` means the recipe's Check Code command; it is not automatically identical to `make verify`.

Known observations from September 24, 2026 are diagnostic context, not accepted failures or permission to skip checks: Productivity Suite had one fixed-reference date assertion failure; Hasanara had HTTP-error decoding and CSV newline failures; DSA's full suite exhausted its 3 GiB Node heap inside the 4 GiB container limit. Reproduce on the current source. Do not rerun the whole DSA suite repeatedly or raise a shared host's limits without investigating memory needs and available capacity. Patchwork's preview uses fixtures, not live indexing or AT OAuth. Other previews may have empty or synthetic data and disabled integrations.

## Remote previews

Run the app on the host and exact worktree where the agent is working. Remote base checkouts are under `~/Work/T3/<project>`; T3 worktrees can be elsewhere. Kvant edits are not automatically transferred to remote checkouts.

`url` prints a command such as the following, which the user runs on Kvant:

```sh
rtk proxy ~/.local/bin/t3-preview dozor dash open --root /absolute/remote/worktree
```

Use the actual printed host/profile/root, not the example path. Pass `--root` for worktrees so the helper does not open or start the base checkout by mistake. The tunnel exposes only a local loopback URL and must be reopened after disconnection. Dozor's Git authentication was missing at installation; use the normal login flow if fetch/push is blocked. Never copy credentials between hosts to work around it.

## Existing threads

Existing threads can use the installed CLI immediately from their current Git checkout. The new default worktree mode and creation hook apply to new threads/worktrees; they do not relocate an existing thread or run setup retroactively. `start` performs setup when first used, so no manual migration is necessary.

An active agent may still have earlier instructions in its conversation. Ask it to read this file explicitly on its next turn. Do not restart T3, terminate a running turn, reset a branch, or discard work just to reload this guide. If the thread shares a checkout with other writers, snapshots may include their edits; disclose that limitation and arrange an isolated worktree at a clean handoff rather than silently moving active work.

The launcher supports old worktree paths without modifying their Git metadata. Missing scripts, dependencies, or compatibility issues in an old branch should be diagnosed in that branch. Preserve existing previews and confirm their owner before replacing them. When finishing, report which previews were left running and how to stop or reopen them.

## Ownership

Authoring source on Kvant: `~/Work/Tools/t3-dev-environments`. Installed guide: `~/.local/share/t3-dev-environments/AGENT-GUIDE.md` on all three hosts. Edit the authoring source and redeploy; do not maintain separate host copies. The README describes operations and rollback. Repository AGENTS.md requirements and the user's task remain authoritative.

## The Common House document recipe

`the-common-house` serves the repository’s `docs/` tree as source files with
Python 3 from the shared tools image; browse `/design/`. The repository now
contains a Unity project, but this recipe provides a document preview. It does
not launch the Editor, render Markdown, build the game, or run Unity tests.
Follow the repository instructions for those checks.
Test checks nonempty Markdown documents and simple inline local file links
in the repository README and `docs/`. Check Code also parses the import
provenance JSON. It does not validate remote links, heading anchors, creative
consistency, historical import hashes, Unity code, or gameplay.

The app has explicit development settings, no database services or credentials,
and the launcher's isolated snapshot and loopback proxy. Test uses its own
snapshot. These actions retain the document-only scope in both older design
checkouts and the current Unity repository. Unity checks require the actual
Editor and normal licensing, as described in the repository instructions.

## Arkhiv private pilot

Use profile `arkhiv` for the `arkhiv-politik` checkout (origin
`subculture-collective/arkhiv`). Go 1.26, Node 24, pnpm 10.33.0, and Poppler
are supplied by the shared tools image. Start Dev applies migrations and seeds
two synthetic collections before starting Go/Vite. `/api/ready` checks the
catalog through the frontend proxy. `ARKHIV_ARCHIVE` points to disposable local
preview storage; live documents are acquired separately on the homelab.

The retained preview database remains PostgreSQL 17. `test_db` selects PostgreSQL
15 only in disposable test snapshots to match the shared `pg_dump` client.
Never downgrade or remove a retained preview volume to resolve a client mismatch.
Test runs `make test`; Check Code runs `make verify`, including catalog integration
when `TEST_DATABASE_URL` names the isolated launcher service. The separate
`make test-browser` gate uses PostgreSQL 17 and a matching runtime backup client.
Application/test isolation remains enabled; no live acquisition occurs there.

## Rekolekt core (`hasanara`)

Use profile `hasanara` for Rekolekt core; its origin may end in
`transcript-create.git` or `rekolekt.git`. The recipe selects a layout from the
checkout. Current `main` is headless (backend and API only): Start Dev applies
migrations and serves uvicorn on the profile port, and readiness checks `/health`.
Test applies migrations and runs the non-integration pytest suite. Check Code
follows `scripts/verify.sh`, including integration tests against a disposable
`hasanara_test` database, but omits its Compose services and the networked
`pip-audit` steps. Setup builds the virtual environment from the newest CPython
3.11 that the pinned uv 0.12.22 installs (3.11.17 on October 4, 2026). The tools
image's Python 3.11.2 has older `HTTPError` and CSV quoting behavior, and two
repository tests fail with it.

A checkout that still contains `frontend/package.json` keeps the earlier recipe:
npm setup, the Vite preview proxying the API, `/api/health` readiness, and
frontend checks before the backend suite. Only its Python interpreter changed,
for the same two tests.

## Dedhed development

Use profile `dedhed` for the concert library and radio application. Start seeds
clearly labeled synthetic test tones in disposable local media storage. Both
on-demand set playback and shared scheduling use local audio; the isolated app
and test networks never acquire real music. Check Code runs `make verify`;
database integration uses the separate PostgreSQL 17 test service. Live source
review, acquisition, private qualification, and recovery are separate workflows.

## VHNESS metadata foundation

Use profile `vhness` for the VHNESS repository. It seeds three synthetic metadata
records, applies checksum-locked migrations, and starts Go/Vite with PostgreSQL
17. No video is acquired or stored. Application/test networks cannot reach
Internet Archive. Tests use a separate disposable PostgreSQL service. Check Code
runs `make verify`, including database tests when `TEST_DATABASE_URL` is present.
Actual source streaming and pilot qualification require separate evidence.

## Kvant disposable-test isolation

On Kvant, Test and Check Code may use the optional backend in
`~/.config/t3-dev-environments/test-backend.json`. Kuznya is a local VM with
a separate Docker daemon. Only filtered disposable snapshots are shared with
it; the original worktree and preview data remain on Kvant. Start Dev, Watch,
Sync and existing previews retain their original backend. A test-backend failure
is a failure to repair, not permission to unset Docker context or bypass the
configured isolation. The normal source, snapshot, cleanup and proof rules still
apply. Repository-owned scripts that do not call this launcher need their own
explicit backend integration; do not claim they automatically use Kuznya.
