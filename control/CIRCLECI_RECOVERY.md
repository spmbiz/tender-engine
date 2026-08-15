# CircleCI Recovery / Capacity Activation

Last verified: 2026-08-15

## What is already proven

- The CircleCI project was connected to `walidgdg1-ai/tender-engine`.
- A historical `say-hello` job completed successfully.
- CircleCI build #11 was triggered from `circleci-fleet` and posted the GitHub status context `ci/circleci: connectivity-smoke`.
- Therefore repository visibility and the original GitHub↔CircleCI integration were real, not inferred from config files.
- After build #11, multiple later pushes to `circleci-fleet` created **no CircleCI status at all**.
- A fresh diagnostic branch containing a minimal known-good CircleCI config also created no CircleCI status.

This means the current blocker is outside repository YAML alone. Treat the Circle project trigger / project enabled state / account credits or plan / project settings as degraded until a new pipeline is actually observed.

## Repository-side configuration already prepared

The repository contains:

- `.circleci/config.yml` with split health gates.
- `pipeline/circleci_contracts_daily_worker.py` using the official Contracts Finder daily CSV harvesting route.
- `pipeline/circleci_contracts_worker.py` with bounded internal I/O concurrency, retry/backoff/jitter, metrics and durable Release persistence.
- `pipeline/circleci_aggregate.py` with parallel durable asset downloads and a single-writer merge.

Configured heavy capacity is currently:

- 30 CircleCI workers.
- `resource_class: medium` for heavy workers.
- 2 vCPU per configured medium worker.
- 60 vCPU theoretical configured burst capacity.

This 60-vCPU figure is **configured only**, not observed live. Do not report it as active until a 30-way Circle run is actually seen.

## Required CircleCI UI checks

Do these in the CircleCI web app for the `tender-engine` project. Never paste tokens into chat or commit them to the repository.

1. **Project trigger / setup**
   - Open Projects → `tender-engine` → Project Settings / Project Setup.
   - Confirm the GitHub repository is followed/connected and pushes create pipelines.
   - If the project is stopped/unfollowed, set it up/follow it again.
   - Use all-push triggering while diagnosing; branch filtering remains inside `.circleci/config.yml`.

2. **Project enabled state**
   - Check Project Settings → Advanced.
   - Ensure any setting equivalent to **Block all new work** is OFF.

3. **Durable bridge secret**
   - Project Settings → Environment Variables.
   - Create `FLEET_GITHUB_TOKEN` if it does not already exist.
   - Use a fine-grained GitHub token with the least privileges needed for this repository's durable Releases/contents writes.
   - Do not print the token in Circle logs.

4. **Plan / usage / credits**
   - Confirm the organization can start new jobs and has usable credits/entitlement.
   - The repository must not infer live capacity from an advertised plan. Only an observed Circle run counts as active capacity.

## Expected gate sequence after recovery

A push/tick to `circleci-fleet` should produce CircleCI status contexts in this order:

1. `executor-smoke`
2. GitHub egress / source route health
3. `durable-bridge`
4. one medium worker smoke
5. 30-way fanout only after the gates pass

If no CircleCI GitHub status appears at all, the problem is still at project-trigger/account level rather than worker code.

If `durable-bridge` fails, fix `FLEET_GITHUB_TOKEN` or its repository permissions. Do **not** bypass the gate: disposable Circle workers are not allowed to claim success unless their valuable outputs are durably persisted.

## Source-aware speed strategy

For UK Contracts Finder:

- Historical backfill: official daily CSV route, naturally sharded by date across workers.
- Live/current: short Search API windows only.
- HTTP 403 is treated as source rate limiting and triggers the official cooldown behavior rather than more parallel requests.

The objective is durable useful records per runner-minute, not maximum request count.

## GitHub fallback already live

CircleCI is not a blocker for the whole Tender Engine. Public GitHub Actions capacity was observed on 2026-08-15 with 19 concurrent `ubuntu-latest` jobs, each exposing 4 logical CPUs, i.e. ~76 configured/observed logical CPUs across the burst test. The live discovery and DCE fleet is already using that pool dynamically while Circle remains degraded.
