# Central queue integration contract

The production queue remains `public.cf_jobs`, `cf_tasks`, `cf_attempts` and
`cf_workers`. Existing job IDs, attempt fencing, DAG dependencies, journals and
Storage object names are preserved. The recovered development queue is available
only in explicit demo mode; a server configured for the central queue cannot
silently submit work to it.

Human OTP sessions and AAL2 approvals use `cf_control`. A node uses its own
Ed25519 key, never a human session or service credential. The gateway checks
current account, grant, node and session state for every operation. PostgreSQL
rechecks current approval under a row lock before queue and Storage operations.

Worker identity extends to both existing Auth workers and approved device UUIDs.
An internal identity table preserves foreign keys without inventing Auth users
or passwords. The existing dispatcher and new gateway share one dispatcher body.
Only the server database role may pass an explicit identity; anonymous and human
Data API callers cannot impersonate nodes.

The gateway proxies the existing private `clayfarm` Storage bucket. Nodes may read
only inputs of their leased tasks and upload only into their current task/attempt
prefix. Callers may upload their own inputs and read their own job artifacts.
Digest-addressed immutable uploads are idempotent; cancellation, lease expiry,
revocation and mismatched hashes reject subsequent transfers and completion.
No signed URL or service key is returned to a worker. Existing legacy policies
remain in effect for existing enrollments until an explicitly authorized cutover.

The central database URL, existing farm UUID and Storage service key are server
configuration. Binding a farm is an operator action; approval never calls
`admin_init()` or creates another farm. Migration and live deployment are separate
from local implementation and tests.

Acceptance: real PostgreSQL tests for old/new queue interoperability, approval,
replay, owner isolation, simultaneous claims, attempts and revocation; real
Blender checks; then actual OTP/MFA, private Storage and SF3D/TripoSR on a CUDA
node, through Blender and result download. A mock mesh, fixture Auth/Storage,
or merely installed GPU dependency does not satisfy that final acceptance.

## Result readiness

Completed fixture or mechanically failing outputs remain downloadable under `diagnostic_candidates`. They do not appear in `ready_candidates` and cannot make the report `review_ready`. Mock ancestry is checked even when an older executor dropped the flag on a descendant. Real mechanically passing candidates still require the caller's visual review and explicit approval.
