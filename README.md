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
`patchwork`, `productivity-suite`, `subcult-os`, `switchyard`, and
`top-shelf-remodels`, and `the-common-house`. The T3 actions pass the profile explicitly, so worktree
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

## The Common House design-stage recipe

`the-common-house` currently contains a Unity design pack, without a Unity
project, package manifest, Editor version pin, database, or existing tests.
The recipe uses Python 3 from the shared tools image with no package installs.
Start Dev serves the copied `docs/` tree as static source files; browse
`/design/`. Markdown is not rendered, and this is not a game preview.
Test checks nonempty Markdown documents and simple inline local file links
in the repository README and `docs/`. Check Code also parses the import
provenance JSON. It does not validate remote links, heading anchors, creative
consistency, historical import hashes, Unity code, or gameplay.

The app has explicit development settings, no database services or credentials,
and the launcher's isolated snapshot and loopback proxy. Test uses its own
snapshot. These actions also work in the original design-only checkout; no
new repository script is required. Replace this recipe after creating and
qualifying the real Unity project. Do not invent an Editor pin or copy another
game's project settings.
