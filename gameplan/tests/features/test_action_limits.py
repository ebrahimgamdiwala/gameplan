from datetime import timedelta
from unittest.mock import patch

import frappe

from gameplan.action_limits import wait_text
from gameplan.posting_limits import save_settings, utc_now
from gameplan.reporting import submit as submit_report
from gameplan.tests.base import GameplanTestCase
from gameplan.tests.fixtures import (
	create_comment,
	create_community,
	create_discussion,
	create_space,
	grant_guest_access,
)
from gameplan.trust_levels import CONTRIBUTOR, LEADER, REGULAR
from gameplan.trust_levels import save_settings as save_trust_settings

POSTING = dict(enabled=0, discussions_hour=0, discussions_day=0, replies_hour=0, replies_day=0)


class TestActionLimits(GameplanTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.clear_cache, doctype="GP Posting Settings")
		self.addCleanup(frappe.clear_cache, doctype="GP Trust Settings")
		self.addCleanup(frappe.cache.delete_keys, "gameplan:trust:")
		self.community = create_community(
			"Daily limits", members=[self.member, self.second_member, self.outsider, self.guest]
		)
		self.community.set_member_moderator(self.outsider.name, 1)
		self.space = create_space("Daily limits", self.community)
		self.posts = [
			create_discussion(f"Post {index}", self.space, owner=self.second_member) for index in range(5)
		]
		self.now = utc_now()
		self.enterContext(patch("gameplan.action_limits.utc_now", side_effect=lambda: self.now))

	def limits(self, **values):
		config = dict(POSTING, daily_enabled=1, reactions_day=2, edits_day=2, reports_day=2)
		config.update(values)
		with self.as_user(self.admin):
			save_settings(**config)

	def levels_on(self, **values):
		with self.as_user(self.admin), patch("frappe.enqueue"):
			save_trust_settings(1, **values)

	def set_level(self, user, level):
		frappe.get_doc(doctype="GP Trust Level", user=user.name, level=level).insert(ignore_permissions=True)

	def react(self, post, user=None, emoji="👍", operation="add"):
		with self.as_user(user or self.member):
			doc = frappe.get_doc("GP Discussion", post.name)
			return doc.react(operations=[{"emoji": emoji, "operation": operation}])

	def report(self, post, user=None):
		with self.as_user(user or self.member):
			return submit_report("GP Discussion", str(post.name), "Spam")

	def edit(self, doc, user=None, **values):
		with self.as_user(user or self.member):
			doc = frappe.get_doc(doc.doctype, doc.name)
			doc.update(values or {"content": f"<p>{frappe.generate_hash()}</p>"})
			doc.save()

	def test_off_by_default(self):
		for post in self.posts:
			self.react(post)

	def test_reactions_stop_at_the_limit_and_removing_one_gives_nothing_back(self):
		self.limits()
		self.react(self.posts[0])
		self.react(self.posts[1])
		self.react(self.posts[0], operation="remove")
		with self.assertRaises(frappe.RateLimitExceededError) as refused:
			self.react(self.posts[2])
		self.assertEqual(str(refused.exception), "You can add 2 reactions a day. Try again in 24 hours.")
		# Each account and each kind has its own count.
		self.react(self.posts[2], user=self.second_member)
		self.report(self.posts[2])

	def test_the_limit_is_over_the_last_24_hours(self):
		self.limits(reactions_day=1)
		self.react(self.posts[0])
		self.now += timedelta(hours=23)
		with self.assertRaises(frappe.RateLimitExceededError) as refused:
			self.react(self.posts[1])
		self.assertIn("Try again in 60 minutes", str(refused.exception))
		self.now += timedelta(hours=1, seconds=1)
		self.react(self.posts[1])

	def test_zero_turns_one_limit_off(self):
		self.limits(reactions_day=0, edits_day=1)
		for post in self.posts:
			self.react(post)

	def test_edits_count_title_and_body_changes_only(self):
		self.limits(edits_day=2)
		mine = create_discussion("Mine", self.space, owner=self.member)
		reply = create_comment(self.posts[0], owner=self.member)
		self.edit(mine)
		self.edit(mine, closed_at=frappe.utils.now(), closed_by=self.member.name)
		self.edit(reply)
		with self.assertRaises(frappe.RateLimitExceededError) as refused:
			self.edit(mine, title="Retitled")
		self.assertIn("You can make 2 edits a day", str(refused.exception))
		self.assertEqual(frappe.db.get_value("GP Discussion", mine.name, "title"), "Mine")

	def test_reports_stop_at_the_daily_limit_and_keep_the_hourly_one(self):
		self.limits(reports_day=1)
		self.report(self.posts[0])
		# Reporting the same post again changes nothing and is not counted.
		self.report(self.posts[0])
		with self.assertRaises(frappe.RateLimitExceededError) as refused:
			self.report(self.posts[1])
		self.assertIn("You can submit 1 report a day", str(refused.exception))

	def test_admins_and_community_staff_in_their_community_are_exempt(self):
		self.limits(reactions_day=1)
		for post in self.posts[:3]:
			self.react(post, user=self.admin)
			self.react(post, user=self.outsider)
		elsewhere = create_space("Elsewhere", create_community("Other", members=[self.outsider]))
		self.react(create_discussion("Other post", elsewhere, owner=self.admin), user=self.outsider)
		with self.assertRaises(frappe.RateLimitExceededError):
			self.react(create_discussion("Other post 2", elsewhere, owner=self.admin), user=self.outsider)

	def test_guests_get_the_limits(self):
		grant_guest_access(self.guest, self.space)
		self.limits(reactions_day=1)
		self.react(self.posts[0], user=self.guest)
		with self.assertRaises(frappe.RateLimitExceededError):
			self.react(self.posts[1], user=self.guest)

	def test_higher_levels_get_more_and_levels_off_gives_everyone_the_base(self):
		self.limits(reactions_day=2)
		self.set_level(self.member, CONTRIBUTOR)
		self.set_level(self.second_member, LEADER)
		# Levels off: the stored levels do not count.
		self.react(self.posts[0])
		self.react(self.posts[1])
		with self.assertRaises(frappe.RateLimitExceededError):
			self.react(self.posts[2])

		self.levels_on()
		# Contributor: 2 × 1.5 = 3. Leader: 2 × 3 = 6.
		self.react(self.posts[2])
		with self.assertRaises(frappe.RateLimitExceededError) as refused:
			self.react(self.posts[3])
		self.assertIn("add 3 reactions", str(refused.exception))
		for post in self.posts:
			self.react(post, user=self.second_member)
		self.react(self.posts[0], user=self.second_member, emoji="🎉")
		with self.assertRaises(frappe.RateLimitExceededError):
			self.react(self.posts[1], user=self.second_member, emoji="🎉")

	def test_multipliers_stay_in_range_and_never_drop_with_a_promotion(self):
		with self.assertRaises(frappe.ValidationError):
			self.levels_on(contributor_daily_multiplier=0.5)
		with self.assertRaises(frappe.ValidationError):
			self.levels_on(leader_daily_multiplier=6)
		with self.assertRaises(frappe.ValidationError):
			self.levels_on(regular_daily_multiplier=1.2)
		self.levels_on(contributor_daily_multiplier=1.2, regular_daily_multiplier=1.2)
		self.set_level(self.member, REGULAR)
		self.limits(reactions_day=5)
		for post in self.posts:
			self.react(post)
		self.react(self.posts[0], emoji="🎉")
		with self.assertRaises(frappe.RateLimitExceededError):
			self.react(self.posts[1], emoji="🎉")

	def test_wait_text_rounds_up(self):
		self.assertEqual(wait_text(30), "30 seconds")
		self.assertEqual(wait_text(61), "61 seconds")
		self.assertEqual(wait_text(121), "3 minutes")
		self.assertEqual(wait_text(3 * 3600 - 5), "3 hours")
