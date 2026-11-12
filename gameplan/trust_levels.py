"""Per-Community trust levels: New, Member and Trusted (decisions D62 to D77).

The level lives on the member's GP Approval Counter row, which approval already reads, so the
posting path adds no query. Levels are worked out when a row is first read after the switch
goes on, when a contribution is accepted, and in a nightly job. Nothing scans a Community.
"""

import frappe
from frappe import _
from frappe.query_builder import functions as fn
from frappe.utils import add_days, cint, get_datetime

from gameplan.community_bans import can_moderate_community, is_banned
from gameplan.permissions import require_can_manage_community
from gameplan.restrictions import utc_now

LEVELS = ("New", "Member", "Trusted")
SETTING_FIELDS = (
	"trust_levels_enabled",
	"approval_post_count",
	"trust_trusted_count",
	"trust_trusted_days",
	"trust_clean_days",
)
LEVEL_ACTIONS = ("Level Changed", "Level Locked", "Level Unlocked", "Trusted Promotion")
PAGE = 50
JOB_BATCH = 500
COMMIT_EVERY = 50
TIME_BUDGET = 240
CONTINUATION_BUDGET = 1200


def clock():
	import time

	return time.monotonic()


def settings(community):
	"""The Community's trust settings. Member threshold is the approval threshold (D64)."""
	row = frappe.db.get_value("GP Team", str(community), list(SETTING_FIELDS), as_dict=True) or {}
	return frappe._dict(
		enabled=cint(row.get("trust_levels_enabled")),
		member_count=cint(row.get("approval_post_count")),
		trusted_count=cint(row.get("trust_trusted_count")),
		trusted_days=cint(row.get("trust_trusted_days")),
		clean_days=cint(row.get("trust_clean_days")),
	)


def is_enabled(community):
	return bool(cint(frappe.db.get_value("GP Team", str(community), "trust_levels_enabled")))


def is_trusted(community, user=None):
	"""True for a Trusted member of a Community with levels on. One indexed read, no lock."""
	user = user or frappe.session.user
	if not is_enabled(community):
		return False
	level = frappe.db.get_value("GP Approval Counter", {"community": str(community), "user": user}, "level")
	return level == "Trusted"


def target_level(config, accepted, days_as_member, last_unclean_at, now=None):
	"""The level the rules give a member. Pure, so it is easy to test."""
	if accepted < config.member_count:
		return "New"
	now = now or utc_now()
	clean = not last_unclean_at or get_datetime(last_unclean_at) <= add_days(now, -config.clean_days)
	if accepted >= config.trusted_count and days_as_member >= config.trusted_days and clean:
		return "Trusted"
	return "Member"


def higher(current, other):
	return max(current, other, key=LEVELS.index)


def days_as_member(community, user, now=None):
	joined = frappe.db.get_value(
		"GP Member", {"parent": str(community), "parenttype": "GP Team", "user": user}, "creation"
	)
	if not joined:
		return 0
	return max(0, (get_datetime(now or utc_now()) - get_datetime(joined)).days)


def last_unclean_event(community, user, now=None):
	"""When this member last had a post hidden or spam-removed, a report upheld, or a ban.

	Only used the first time a member's level is worked out; moderation actions keep it current.
	"""
	community, user = str(community), str(user)
	cutoff = add_days(now or utc_now(), -max(1, settings(community).clean_days))
	Project, Discussion, Comment, Review, Log = (
		frappe.qb.DocType(dt)
		for dt in ("GP Project", "GP Discussion", "GP Comment", "GP Review", "GP Moderation Log")
	)
	times = []
	spaces = frappe.qb.from_(Project).select(Project.name).where(Project.team == community)
	discussions = (
		frappe.qb.from_(Discussion).where(Discussion.project.isin(spaces)).where(Discussion.owner == user)
	)
	for column in (Discussion.hidden_at, Discussion.spam_removed_at):
		times += discussions.select(fn.Max(column)).where(column > cutoff).run(pluck=True)
	in_community = frappe.qb.from_(Discussion).select(Discussion.name).where(Discussion.project.isin(spaces))
	comments = frappe.qb.from_(Comment).where(
		(Comment.owner == user)
		& (Comment.reference_doctype == "GP Discussion")
		& Comment.reference_name.isin(in_community)
	)
	for column in (Comment.hidden_at, Comment.spam_removed_at):
		times += comments.select(fn.Max(column)).where(column > cutoff).run(pluck=True)
	own = discussions.select(fn.Cast_(Discussion.name, "varchar"))
	times += (
		frappe.qb.from_(Review)
		.select(fn.Max(Review.decided_at))
		.where((Review.decision == "Uphold") & (Review.decided_at > cutoff))
		.where((Review.reference_doctype == "GP Discussion") & Review.reference_name.isin(own))
		.run(pluck=True)
	)
	times += (
		frappe.qb.from_(Log)
		.select(fn.Max(Log.creation))
		.where(
			(Log.community == community)
			& (Log.user == user)
			& (Log.action == "Ban")
			& (Log.creation > cutoff)
		)
		.run(pluck=True)
	)
	times = [t for t in times if t]
	return max(times) if times else None


def mark_unclean(community, user):
	"""Record that a moderation action just touched this member, for the clean-record rule."""
	if not community or not user or not is_enabled(community):
		return
	name = frappe.db.get_value("GP Approval Counter", {"community": str(community), "user": user}, "name")
	if name:
		frappe.db.set_value("GP Approval Counter", name, "last_unclean_at", utc_now(), update_modified=False)


def evaluate(community, user, row, config=None):
	"""Work out a row's level the first time it is read with levels on. Never lowers a level."""
	if row.locked or row.level_changed_at:
		return row
	config = config or settings(community)
	if not config.enabled:
		return row
	level = higher(
		row.level or "New",
		target_level(
			config,
			cint(row.accepted),
			days_as_member(community, user),
			last_unclean_event(community, user),
		),
	)
	if is_banned(community, user):
		level = row.level or "New"
	apply_level(community, user, row, level, notify=False)
	return row


def apply_level(community, user, row, level, *, notify=True):
	"""Store a level on the row, tell the member about a promotion, and keep the row current."""
	previous = row.level or "New"
	values = {"level": level, "level_changed_at": utc_now()}
	frappe.db.set_value("GP Approval Counter", row.name, values, update_modified=False)
	row.update(values)
	if notify and LEVELS.index(level) > LEVELS.index(previous):
		notify_promotion(community, user, level)


def notify_promotion(community, user, level):
	title = frappe.db.get_value("GP Team", str(community), "title") or ""
	frappe.get_doc(
		doctype="GP Notification",
		type="Trust Level",
		to_user=user,
		from_user=user,
		team=community,
		message=_("You are now a Member of {0}. Your posts publish without approval.").format(title)
		if level == "Member"
		else _("You are now Trusted in {0}. Your posts skip the link, image, file and mention caps.").format(
			title
		),
	).insert(ignore_permissions=True)
	from gameplan.realtime import notify_notification_counts_refresh

	notify_notification_counts_refresh([user])


def promote_on_accept(community, row):
	"""New to Member as soon as the contribution that reaches the threshold is accepted (D70)."""
	config = settings(community)
	if not config.enabled or row.locked or (row.level or "New") != "New":
		return
	if cint(row.accepted) >= config.member_count and not is_banned(community, row.user):
		apply_level(community, row.user, row, "Member")


def log_level(community, user, action, reason="", previous="", level=""):
	frappe.get_doc(
		doctype="GP Moderation Log",
		community=str(community),
		user=user,
		action=action,
		reason=reason,
		previous_level=previous,
		level=level,
	).insert(ignore_permissions=True)


# Settings -----------------------------------------------------------------------------------


@frappe.whitelist(methods=["GET", "POST"])
def get_settings(community: str):
	"""Return the trust level switch and thresholds to Community admins."""
	require_can_manage_community(community)
	config = settings(community)
	return {
		**config,
		"defaults": {"member_count": 3, "trusted_count": 25, "trusted_days": 30, "clean_days": 90},
	}


@frappe.whitelist(methods=["POST"])
def save_settings(community: str, enabled: int, trusted_count: int, trusted_days: int, clean_days: int):
	"""Turn trust levels on or off for a Community and set the Trusted thresholds. Community admins only."""
	require_can_manage_community(community)
	if not 1 <= trusted_count <= 100:
		frappe.throw(_("Choose a Trusted contribution count between 1 and 100"))
	if not 0 <= trusted_days <= 3650 or not 1 <= clean_days <= 3650:
		frappe.throw(_("Choose a number of days between 1 and 3650"))
	community = str(community)
	if not frappe.db.get_value("GP Team", community, "name", for_update=True):
		raise frappe.DoesNotExistError(f"GP Team {community} not found")
	was_enabled = is_enabled(community)
	frappe.db.set_value(
		"GP Team",
		community,
		{
			"trust_levels_enabled": 1 if cint(enabled) else 0,
			"trust_trusted_count": trusted_count,
			"trust_trusted_days": trusted_days,
			"trust_clean_days": clean_days,
		},
	)
	if cint(enabled) and not was_enabled:
		# Every row is worked out again the next time it is read. Stored levels are kept: a
		# level only goes up by rule.
		frappe.db.set_value(
			"GP Approval Counter",
			{"community": community, "locked": 0},
			"level_changed_at",
			None,
			update_modified=False,
		)
		frappe.enqueue(backfill, queue="long", enqueue_after_commit=True, community=community)
	return settings(community)


# Manual changes ------------------------------------------------------------------------------


def target_row(community, user):
	"""The member's counter row, created from their existing contributions if they have none."""
	from gameplan.approval_policy import counter

	return counter(str(community), user)


def check_can_change(community, user):
	if not can_moderate_community(community):
		frappe.throw(_("Only Community moderators can change a level"), frappe.PermissionError)
	if not is_enabled(community):
		frappe.throw(_("Trust levels are not turned on for this Community"))
	if not frappe.db.exists("GP Member", {"parent": str(community), "parenttype": "GP Team", "user": user}):
		frappe.throw(_("Member not found"))
	if can_moderate_community(community, user):
		frappe.throw(_("Community staff do not have a level"))


def clean_reason(reason):
	reason = (reason or "").strip()
	if not reason or len(reason) > 500:
		frappe.throw(_("Give a reason of up to 500 characters"))
	return reason


@frappe.whitelist(methods=["POST"])
def set_member_level(community: str, user: str, level: str, reason: str):
	"""Set a member's level by hand, or lower it, with a reason. Community moderators and admins."""
	if level not in LEVELS:
		frappe.throw(_("Choose New, Member or Trusted"))
	reason = clean_reason(reason)
	check_can_change(community, user)
	row = target_row(community, user)
	previous = row.level or "New"
	if previous == level:
		return {"level": level, "locked": cint(row.locked)}
	apply_level(community, user, row, level)
	log_level(community, user, "Level Changed", reason, previous, level)
	return {"level": level, "locked": cint(row.locked)}


@frappe.whitelist(methods=["POST"])
def set_member_lock(community: str, user: str, locked: int, reason: str):
	"""Lock a member's level so no rule changes it, or unlock it. Community moderators and admins."""
	reason = clean_reason(reason)
	check_can_change(community, user)
	row = target_row(community, user)
	locked = 1 if cint(locked) else 0
	if cint(row.locked) == locked:
		return {"level": row.level, "locked": locked}
	frappe.db.set_value("GP Approval Counter", row.name, "locked", locked, update_modified=False)
	if not locked:
		# Unlocking lets the rules look at the member again.
		frappe.db.set_value("GP Approval Counter", row.name, "level_changed_at", None, update_modified=False)
	log_level(community, user, "Level Locked" if locked else "Level Unlocked", reason, row.level, row.level)
	return {"level": row.level, "locked": locked}


# Nightly job ---------------------------------------------------------------------------------


def promote_trusted():
	"""Daily: queue one job per Community that uses trust levels, to promote members to Trusted."""
	for community in frappe.get_all("GP Team", filters={"trust_levels_enabled": 1}, pluck="name"):
		frappe.enqueue(promote_community, queue="long", community=str(community), now=frappe.in_test)


def promote_community(community, after="", budget=TIME_BUDGET):
	"""Promote the members of one Community who now meet every Trusted requirement.

	Reads only rows with enough accepted contributions, through the trust_candidates index.
	"""
	config = settings(community)
	if not config.enabled:
		return

	def candidates(after):
		return frappe.get_all(
			"GP Approval Counter",
			filters=[
				["community", "=", str(community)],
				["locked", "=", 0],
				["level", "!=", "Trusted"],
				["accepted", ">=", config.trusted_count],
				["name", ">", after],
			],
			pluck="name",
			order_by="name asc",
			limit=JOB_BATCH,
		)

	in_slices(
		candidates,
		lambda name: promote_row(community, name, config),
		lambda after: frappe.enqueue(
			promote_community, queue="long", community=community, after=after, budget=CONTINUATION_BUDGET
		),
		after,
		budget,
	)


def promote_row(community, name, config):
	fields = ["name", "user", "accepted", "level", "locked", "last_unclean_at"]
	row = frappe.db.get_value("GP Approval Counter", name, fields, as_dict=True)
	if not row or row.locked or can_moderate_community(community, row.user) or is_banned(community, row.user):
		return
	level = target_level(config, cint(row.accepted), days_as_member(community, row.user), row.last_unclean_at)
	previous = row.level or "New"
	if LEVELS.index(level) <= LEVELS.index(previous):
		return
	apply_level(community, row.user, row, level)
	if level == "Trusted":
		log_level(community, row.user, "Trusted Promotion", "", previous, level)


def backfill(community, after="", budget=TIME_BUDGET):
	"""Work out every member's level from their existing contributions after the switch goes on (D74).

	Nobody is told, and staff are skipped. Until it finishes, rows are worked out as they are read.
	"""
	config = settings(community)
	if not config.enabled:
		return

	def members(after):
		filters = {"parent": str(community), "parenttype": "GP Team", "user": [">", after]}
		return frappe.get_all(
			"GP Member", filters=filters, pluck="user", order_by="user asc", limit=JOB_BATCH
		)

	def work_out(user):
		if not can_moderate_community(community, user):
			evaluate(community, user, target_row(community, user), config)

	in_slices(
		members,
		work_out,
		lambda after: frappe.enqueue(
			backfill, queue="long", community=str(community), after=after, budget=CONTINUATION_BUDGET
		),
		after,
		budget,
	)


def in_slices(fetch, handle, resume, after, budget):
	"""Handle each key `fetch(after)` returns, a page at a time, committing as it goes.

	After `budget` seconds it commits, calls `resume(last key)` to queue the rest as a new job, and stops.
	"""
	started = clock()
	while keys := fetch(after):
		for number, key in enumerate(keys, 1):
			after = key
			handle(key)
			if number % COMMIT_EVERY == 0:
				frappe.db.commit()  # nosemgrep
			if clock() - started > budget:
				frappe.db.commit()  # nosemgrep
				resume(after)
				return
		frappe.db.commit()  # nosemgrep
