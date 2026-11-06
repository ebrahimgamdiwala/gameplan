# Trust levels

Status: draft spec for review. Nothing is built.
Decisions: D62 to D77 in [moderation decisions](moderation-decisions.md). This file adds proposals and marks them as such.

## Goal

A new contributor starts under review. A contributor who has taken part well for long enough earns more freedom without a moderator deciding. A moderator can always override.

## Levels

| Level | Approval | Content caps |
| --- | --- | --- |
| New | Applies if the Community's approval policy is on | Site caps |
| Member | Skipped | Site caps |
| Trusted | Skipped | Link, image, file, and mention caps do not apply |

Posting-rate limits apply to everyone except global admins. The stricter caps for public-access Guests apply at every level. Community staff and global admins have no level and keep today's exemptions.

## Switch

Each Community has a switch, off by default. While off, behavior is exactly what it is today, including the approval threshold of D37. A Community admin or global admin turns it on or off.

## Promotion

- **New to Member:** the member's accepted contributions in that Community reach the Member threshold (default 3). The check runs in the code that counts an accepted contribution (D38), so the promotion is immediate.
- **Member to Trusted:** accepted contributions reach the Trusted threshold (default 25), the member has belonged to the Community for the minimum days (default 30), and the record is clean (D68). A nightly job checks only members whose conditions could have changed.
- A Community ban pauses promotion while it lasts.
- A level never drops by itself.

## Manual changes

Moderators, Community admins, and global admins can:

- set a member to any level, or lower it, with a required reason (500 characters),
- lock a level, which stops all automatic changes, or unlock it.

Each manual change is written to moderation History with actor, time, reason, and old and new level. Automatic promotion to Trusted is written as System.

## Turning the switch on

A background job works through the Community in chunks. It computes each member's level from existing contributions (D39), membership age, and the moderation log. Existing approval and caps behavior continues for everyone until the job finishes. Staff are skipped. Nobody is notified for this first pass.

## Visibility

| Who | Sees |
| --- | --- |
| Moderators and admins | Every member's level, its reason, and each requirement as met or not met |
| The member | Their own level and progress to the next one, near the approval notice |
| Other members | Nothing |

## Notifications

In-app only, to the member, when they are promoted by rule or by hand. Nothing when a level is lowered. The moderator's reason stays staff-only.

## Built in the engine (branch `feat/trust-levels-engine`)

What the engine does where the proposals below were open:

- **Clean record is kept current by moderation actions.** Hiding or spam-removing a member's post, upholding a report on it, and a Community ban each stamp `last_unclean_at` on the member's row. Nothing reads the moderation log when a member is promoted. Restoring a post does not clear the stamp, so a wrongly hidden post can delay Trusted by up to 90 days; a moderator can promote by hand.
- **Rejoining recomputes.** Leaving a Community deletes the row, including any manual level and lock. A rejoining member is worked out again from their published posts (D39), so they are Member again if enough posts remain, and Trusted needs the days as a member to start over.
- **Turning levels on** starts the chunked background job (D74). Until it reaches a member, their row is worked out the first time it is read. The staff list only reads stored values and marks members the job has not reached as pending.
- **Reading endpoints:** `get_settings` and `member_levels` are read-only. `my_level` is POST because it can store a first evaluation, and Frappe discards writes made during a GET.

## Proposed implementation

These were proposals when the spec was drafted.

- **Storage:** add `level`, `locked`, and `level_changed_at` to the existing GP Approval Counter row, which is already one row per Community and member. This avoids a second table and a second lookup on the posting path.
- **Settings:** add `trust_levels_enabled`, `member_threshold`, `trusted_threshold`, `trusted_days`, and `clean_days` to the Community's approval settings. The old threshold field feeds `member_threshold`.
- **Hooks:** `approval_policy` asks the member's level instead of comparing the count. `check_caps` skips the four caps for Trusted.
- **Clean record:** read GP Moderation Log with an index on (author, community, action, creation). Add the index in a patch.
- **Nightly job:** select members with `level = Member`, not locked, with enough accepted contributions and days, in pages of 2,000. Commit every 50 rows and continue as a new job after a time budget, like the digest.
- **Backfill job:** the same loop, over all members of one Community, on the `long` queue.
- **API:** `set_member_level(community, user, level, reason)`, `lock_member_level(community, user, locked, reason)`, `member_levels(community, level, start)` with the paging cap, and `my_level(community)`. Each new method gets a one-line docstring, and the agent guide in `mcp.py` is updated.
- **Realtime:** the existing user-scoped event refreshes the member's own panel after a change.

## Scale

Checked against the scale-test findings:

- No per-view writes, and no new fan-out per reply.
- The posting path adds no query: the level lives on the row already read for approval.
- The nightly job and the backfill are chunked and resumable.
- Names are passed as text, so the static guard test applies.
- The member list is paged, with the 5,000-row offset cap.

## Tests

- Promotion at exactly the threshold, and not one below.
- Trusted needs all three signals, and each fails alone.
- Each unclean event (hidden post, spam removal, upheld report, ban) blocks Trusted for 90 days, and a rejected submission or dismissed report does not.
- A lock stops the nightly job and a manual change still works.
- A ban pauses promotion.
- Staff are skipped, and keep their tracked level after losing the role.
- Leaving and rejoining resets to New.
- The switch off leaves approval and caps exactly as today (the existing tests pass unchanged).
- Trusted skips the four caps but not posting-rate limits, and not the public-access Guest caps.
- The backfill is resumable, silent, and leaves behavior unchanged until it finishes.
- History records manual changes and Trusted promotions, and not Member promotions.
- A moderator cannot read levels outside their Community.

## Pull requests (D77)

1. **12/13, engine:** fields, settings, hooks, jobs, API, History, notifications, patch, tests.
2. **13/13, UI:** Trust levels tab, requirements panel, settings beside approval, the member's own panel, and a browser test.

## Not in this version

Using levels for posting limits, slow mode, or report weight. Weighted auto-hide and automatic silencing, which would build on levels later. A site-wide master switch. Public badges.
