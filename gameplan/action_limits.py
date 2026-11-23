# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

"""Daily limits on reactions, edits and reports, as in Discourse's max_*_per_day (D137).

Each limit counts the account's actions over the last 24 hours in GP Posting Event, the table
the posting rate uses. Contributors, Regulars and Leaders get the base number times their
level's multiplier. Global admins, and Community staff in their own Communities, are exempt.
A refused action rolls back with its request, so it is never counted.
"""

import math
from datetime import timedelta

import frappe
from frappe.utils import get_datetime

import gameplan
from gameplan.posting_limits import policy, utc_now

# Kind: (base setting, verb, singular, plural), for "You can add 50 reactions a day".
KINDS = {
	"reaction": ("reactions_day", "add", "reaction", "reactions"),
	"edit": ("edits_day", "make", "edit", "edits"),
	"report": ("reports_day", "submit", "report", "reports"),
}
MULTIPLIER_FIELDS = {
	"Contributor": "contributor_daily_multiplier",
	"Regular": "regular_daily_multiplier",
	"Leader": "leader_daily_multiplier",
}
DAY = timedelta(days=1)


def check_reaction(doc, method=None):
	"""`before_insert` of GP Reaction."""
	if doc.reference_doctype and doc.reference_name:
		target = frappe.get_doc(doc.reference_doctype, doc.reference_name)
		record("reaction", target)


def check_edit(doc, method=None):
	"""`validate` of discussions, replies and polls: a saved change to the title or body."""
	from gameplan.new_user_limits import post_changed

	if not doc.is_new() and post_changed(doc):
		record("edit", doc)


def record(kind, target):
	"""Refuse the action if it is over today's limit, otherwise count it."""
	user = frappe.session.user
	limit = limit_for(kind, user, target)
	if not limit:
		return
	# Share the account-first lock order with the posting rate and approvals.
	frappe.db.get_value("User", user, "name", for_update=True)
	Event = frappe.qb.DocType("GP Posting Event")
	times = (
		frappe.qb.from_(Event)
		.select(Event.accepted_at)
		.where((Event.user == user) & (Event.kind == kind) & (Event.accepted_at > utc_now() - DAY))
		.orderby(Event.accepted_at, order=frappe.qb.desc)
		.limit(limit)
		.for_update()
		.run(pluck=True)
	)
	if len(times) >= limit:
		retry = get_datetime(times[limit - 1]) + DAY - utc_now()
		_field, verb, singular, plural = KINDS[kind]
		noun = singular if limit == 1 else plural
		frappe.throw(
			f"You can {verb} {limit} {noun} a day. Try again in {wait_text(retry.total_seconds())}.",
			frappe.RateLimitExceededError,
			title="Daily limit",
		)
	frappe.get_doc(doctype="GP Posting Event", user=user, kind=kind, accepted_at=utc_now()).insert(
		ignore_permissions=True
	)


def limit_for(kind, user, target):
	"""Today's limit for `user`, or 0 when no limit applies."""
	config = policy()
	base = config[KINDS[kind][0]]
	if not config["daily_enabled"] or not base or is_exempt(user, target):
		return 0
	return math.floor(base * multiplier(user))


def multiplier(user):
	from gameplan.trust_levels import LEVELS, config, level_of

	level = level_of(user)
	field = MULTIPLIER_FIELDS.get(LEVELS[level]) if level is not None else None
	return max(1, config()[field]) if field else 1


def is_exempt(user, target):
	"""Global admins, and Community staff inside the Communities they help run (D135)."""
	from gameplan.community_bans import can_moderate_community
	from gameplan.permissions import get_content_project

	if gameplan.is_anonymous(user) or gameplan.is_admin(user):
		return True
	project = target and get_content_project(target)
	community = project and frappe.db.get_value("GP Project", project, "team")
	return bool(community) and can_moderate_community(community, user)


def wait_text(seconds):
	"""Round up, in hours from two hours, then minutes, then seconds."""
	seconds = max(1, math.ceil(seconds))
	for size, unit in ((3600, "hour"), (60, "minute"), (1, "second")):
		if seconds >= size * 2 or size == 1:
			count = math.ceil(seconds / size)
			return f"{count} {unit}{'' if count == 1 else 's'}"
