# T3 development environments

Run a project preview and its local tests from a T3 worktree. Each worktree gets
its own source snapshot, dependency cache, database volume, and loopback port.
Tests use a separate snapshot and never use the preview database.

Agents: read [AGENT-GUIDE.md](AGENT-GUIDE.md) before preview/test work. The installer deploys this guide beside the launcher on each host. Existing threads can read it explicitly and keep their current checkout; no restart or worktree migration is required.

## Use it in T3

Choose a project on Kvant, Dozor, or Almaz, then create a worktree thread.
**Setup Worktree** installs the recipe's dependencies before the thread starts.
Use these project actions:

| Action | What it does |
| --- | --- |
| Start Dev | Copies current code, installs dependencies, starts the app and its services, and waits for readiness |
| Watch Changes | Copies source edits every two seconds and restarts the app; stop this terminal to stop watching |
| Sync Changes | Copies edits and restarts the app once |
| Preview URL | Prints the loopback URL and, on remote hosts, the command to open a tunnel from Kvant |
| Test | Runs the recipe's tests in a separate container and removes its containers and networks afterward |
| Check Code | Runs the broader checks listed in `profiles.json` |
| Dev Status / Dev Logs | Shows this worktree's containers or app logs |
| Stop Dev | Removes this worktree's containers and networks; keeps its database, source snapshot, and caches |

The existing Subcult OS recipe on Kvant remains repository-owned and also has
its demo seed and database-test actions. Its scripts live in that repository.

To use a terminal directly:

```sh
cd /path/to/project-or-worktree
t3-dev --profile dash start
t3-dev --profile dash watch
t3-dev --profile dash test
t3-dev --profile dash stop
```

For a focused check, supply the exact command to run in the isolated test snapshot:

```sh
t3-dev --profile dash test --command 'cd backend && go test ./...'
t3-dev --profile dsa-seats test --command 'npm run test:run -- src/ui/view-models.test.ts --maxWorkers=1'
```

Choose an existing package or test path in your checkout. `--command` replaces
the recipe's test command; dependency setup and disposable service cleanup still
run. Include any required test migrations in your custom command. Standard
**Test** and **Check Code** actions keep their documented scopes. One test run
per host holds the test lock; another test waits for it to finish.

Profile names are `augr`, `clpr`, `dash`, `deadweb-relay`, `dsa-seats`, `hasanara`,
`patchwork`, `productivity-suite`, `subcult-os`, `switchyard`,
`top-shelf-remodels`, `the-common-house`, and `arkhiv`. The T3 actions pass the profile explicitly, so worktree
directory names do not matter.

## Remote previews

Remote checkouts live at `~/Work/T3/<project>`. T3 worktrees remain under its
normal `~/.t3/worktrees` directory. Work on the checkout for the selected T3
environment; changes on Kvant are not automatically sent to a remote host.

Run the printed command on Kvant to open a private SSH tunnel:

```sh
t3-preview dozor dash open
t3-preview almaz dash start
# For an existing remote T3 worktree, use the exact path printed by Preview URL:
t3-preview dozor dash open --root /home/onnwee/.t3/worktrees/dash/your-worktree
```

The helper verifies an HTTP response and prints a clickable local URL. It keeps
the same local and remote port so configured application origins match. If that
port is occupied on Kvant, SSH fails without replacing the existing listener.
Use `t3-preview HOST PROJECT stop --root PATH` to stop the environment and close
its tunnel. A tunnel does not survive logout, reboot, or a sustained SSH failure;
run `open` again to reconnect. This does not add a public ingress route.

The initial remote checkouts were transferred as Git bundles from the recorded
Kvant commits, with canonical Gitea origins retained. Dozor did not have working
HTTPS Git authentication during installation. Development and local tests work
from the seeded checkouts; fetching or pushing there needs normal Gitea login.

## Isolation and test scope

The app runs on an internal Docker network with
[isolated gateway mode](https://docs.docker.com/engine/network/port-publishing/#gateway-modes),
which removes the bridge's host address. A small HTTP/WebSocket proxy exposes
only its preview, bound to `127.0.0.1`. Dependency installation has a separate
network for package registries; test commands run on the internal network.
No container mounts the original checkout, Docker socket, SSH directory, or
production database. Snapshots exclude ignored files, populated `.env` files,
known credential filenames, key files, SQLite databases, and untracked spreadsheets.
Git-tracked spreadsheet fixtures are included because source-validation tests use them.
Reviewed `.env.example`, `.env.sample`, and `.env.template` files are copied.
External symlinks are excluded; internal file symlinks are materialized.

Only the explicit development values in `profiles.json` reach the app. Unit
tests receive a smaller environment so development settings cannot mask
missing-configuration tests. External integrations have no working credentials;
offline previews do not prove OAuth, email, payments, trading, ingestion, model
providers, or production monitoring. Some apps start with an empty database. Patchwork uses its built-in fixture
backend and frontend; it does not exercise the live indexer or AT OAuth. DSA
starts with its synthetic task10 database seed while its home page can still
show checked-in public catalog data.

The app and check containers are each capped at two CPUs and 4 GiB. Supporting
services have separate limits. Kvant allows two active shared-launcher app
stacks; Dozor and Almaz allow one each. Stop an environment before starting
another when the limit is reached. These limits cover this launcher, not other
host workloads or Kvant's earlier Subcult OS stack.

`Test` and `Check Code` run the exact commands in the recipe. Several projects
use short/unit suites that skip database or external integration tests. These
actions do not replace every repository's `make verify`, browser acceptance
suite, deployment check, or CI gate. A failing assertion remains a failure; the
launcher propagates its exit status. See the Ars Malefica report `T3 development environments fleet 2026-09-24` for
which actions were exercised and their results.

## Maintenance and rollback

If Docker reports `all predefined address pools have been fully subnetted`, the
launcher lists Compose projects whose containers are stopped or absent. These
are ownership clues, not permission to remove another thread's environment.
Use the owning worktree's Stop Dev action to release its containers and networks
while keeping preview data. The launcher never prunes networks automatically and
preserves the failed command's exit status even if the diagnostic cannot run.

For hosts with many concurrent projects, configure Docker `default-address-pools`
with smaller subnets after checking LAN, VPN, and existing network ranges.
This setting needs a daemon restart. Preserve the existing daemon configuration,
back it up, validate it with `dockerd --validate`, and coordinate the restart with
active jobs. Existing networks retain their subnets; the new pool applies to new
networks. Record host changes and rollback in the canonical host briefing.

Authoring source on Kvant: `~/Work/Tools/t3-dev-environments`.
Installed launcher on each host: `~/.local/share/t3-dev-environments`.
Runtime state: `~/.local/state/t3-dev-environments/fleet`.
Each environment records its source path and Git revision in `identity.json`.
An identity record describes the snapshot, not a successful test result.

Run `python3 -m unittest -v test_dev.py` before installing launcher changes.
`python3 install.py` installs the commands and updates only the relevant T3
project overrides, preserving other settings and existing custom actions.
It backs up settings under `~/.local/state/t3-dev-environments/install-*` and
refuses to overwrite a concurrent settings change. T3 picks up the settings
without a service restart. Copy the source files to the installed directory on
remote hosts, then run their `install.py`.

For rollback, stop the affected development stacks and remove their `fleet-`
script entries from T3 project overrides. Compare the saved settings with the
current file before restoring anything; do not replace subsequent user edits.
Remote development checkouts and retained volumes can remain for recovery.
No application production deployment is part of this setup.

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
`subculture-collective/arkhiv`). The installer recognizes the checkout alias.
Go 1.26, Node 24, pnpm 10.33.0, and Poppler are supplied by the tools image.
Start Dev applies migrations, seeds two synthetic collections, and runs the Go
service and Vite. `/api/ready` checks the catalog through the frontend proxy.
The pilot includes the catalog, preservation commands, and a local PDF reader.
Live acquisition remains outside the isolated preview and test networks.
`ARKHIV_ARCHIVE` points to local preview storage. Test runs `make test`; Check Code
runs `make verify`, including the catalog integration checks against the
disposable service named by `TEST_DATABASE_URL`.

Arkhiv uses `test_db=postgres:15` to select a disposable database version compatible
with the shared `pg_dump` client. Its retained preview database stays PostgreSQL
17. This field has no effect on preview storage or on recipes that omit it.
Never downgrade a retained database volume to resolve a client mismatch. The
repository's separate `make test-browser` gate uses PostgreSQL 17 and a matching
backup client; the PostgreSQL 15 launcher check does not establish version-17
backup compatibility.
