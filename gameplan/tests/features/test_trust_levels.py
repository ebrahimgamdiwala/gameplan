from datetime import timedelta
from unittest.mock import patch

import frappe

from gameplan.approval_policy import needs_approval, set_policy
from gameplan.approvals import decide, detail, submit
from gameplan.community_bans import set_ban
from gameplan.posting_limits import save_settings as save_caps
from gameplan.restrictions import utc_now
from gameplan.tests.base import GameplanTestCase
from gameplan.tests.fixtures import create_community, create_discussion, create_space
from gameplan.trust_levels import (
	backfill,
	save_settings,
	set_member_level,
	set_member_lock,
	settings,
	target_level,
)
from gameplan.trust_levels import promote_trusted as run_promote_trusted


def config(**values):
	return frappe._dict(
		{"enabled": 1, "member_count": 3, "trusted_count": 4, "trusted_days": 30, "clean_days": 90, **values}
	)


class TestTargetLevel(GameplanTestCase):
	def test_each_requirement_is_needed_for_trusted_and_none_can_be_missing(self):
		now = utc_now()
		old_event = now - timedelta(days=91)
		recent_event = now - timedelta(days=5)
		cases = [
			((2, 99, None), "New"),
			((3, 99, None), "Member"),
			((4, 29, None), "Member"),
			((4, 30, None), "Trusted"),
			((4, 99, recent_event), "Member"),
			((4, 99, old_event), "Trusted"),
			((50, 0, None), "Member"),
		]
		for (accepted, days, event), expected in cases:
			with self.subTest(accepted=accepted, days=days, event=event):
				self.assertEqual(target_level(config(), accepted, days, event, now), expected)


class TestTrustLevels(GameplanTestCase):
	def setUp(self):
		super().setUp()
		self.community = create_community(
			"Trust levels", members=[self.member, self.second_member, self.outsider]
		)
		self.community.set_member_moderator(self.second_member.name, 1)
		self.space = create_space("Trust Space", self.community)
		self.parent = create_discussion("Parent", self.space, owner=self.outsider)
		set_policy(self.community.name, 3)

	def turn_on(self, **values):
		with self.as_user(self.admin):
			save_settings(
				self.community.name,
				**{"enabled": 1, "trusted_count": 4, "trusted_days": 0, "clean_days": 90, **values},
			)

	def row(self, user=None):
		return frappe.db.get_value(
			"GP Approval Counter",
			{"community": self.community.name, "user": (user or self.member).name},
			["name", "level", "locked", "accepted", "last_unclean_at", "level_changed_at"],
			as_dict=True,
		)

	def submit(self, content="<p>Review these words</p>"):
		with self.as_user(self.member):
			return submit(
				"GP Discussion",
				frappe.generate_hash(),
				content,
				project=str(self.space.name),
				title="A discussion",
			)

	def accept(self, count):
		"""Get `count` contributions accepted: approved from the queue, or published once a Member."""
		for _ in range(count):
			result = self.submit()
			if result.get("status") != "Pending":
				continue
			with self.as_user(self.second_member):
				row = detail(result["name"])
				decide(result["name"], "Approve", str(row.modified), "")

	def promote_trusted(self):
		# The job commits as it goes; a test must not keep its data.
		with patch("frappe.db.commit"):
			run_promote_trusted()

	def level_logs(self, action):
		return frappe.get_all(
			"GP Moderation Log", filters={"community": self.community.name, "action": action}, fields=["*"]
		)

	# Switch ---------------------------------------------------------------------------------

	def test_levels_are_off_until_a_community_admin_turns_them_on(self):
		self.assertEqual(settings(self.community.name).enabled, 0)
		self.accept(3)
		self.assertEqual(self.row().level, "New")
		self.assertEqual(self.submit()["doctype"], "GP Discussion")
		with self.as_user(self.member), self.assertRaises(frappe.PermissionError):
			save_settings(self.community.name, 1, 25, 30, 90)

	def test_turning_levels_on_works_out_existing_members_from_their_published_posts(self):
		for index in range(3):
			create_discussion(f"Existing {index}", self.space, owner=self.member)
		self.turn_on()
		with self.as_user(self.member):
			self.assertEqual(
				needs_approval(frappe._dict(doctype="GP Discussion", project=self.space.name)), False
			)
		self.assertEqual(self.row().level, "Member")
		self.assertFalse(
			frappe.db.exists("GP Notification", {"to_user": self.member.name, "type": "Trust Level"})
		)

	def test_turning_levels_back_on_keeps_a_level_that_was_already_earned(self):
		self.turn_on()
		self.accept(3)
		self.assertEqual(self.row().level, "Member")
		self.turn_on(enabled=0)
		self.turn_on()
		with self.as_user(self.member):
			needs_approval(frappe._dict(doctype="GP Discussion", project=self.space.name))
		self.assertEqual(self.row().level, "Member")

	def test_the_backfill_works_out_every_member_silently_and_skips_staff(self):
		for index in range(3):
			create_discussion(f"Existing {index}", self.space, owner=self.member)
		self.turn_on()
		with patch("frappe.db.commit"):
			backfill(self.community.name)
		self.assertEqual(self.row().level, "Member")
		self.assertEqual(self.row(self.outsider).level, "New")
		self.assertIsNone(self.row(self.second_member))
		self.assertFalse(frappe.db.exists("GP Notification", {"type": "Trust Level"}))

	def test_the_backfill_continues_in_a_new_job_after_its_time_budget(self):
		self.turn_on()
		with patch("frappe.db.commit"), patch("frappe.enqueue") as enqueue:
			backfill(self.community.name, budget=-1)
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.kwargs["community"], str(self.community.name))
		self.assertTrue(enqueue.call_args.kwargs["after"])

	# Promotion ------------------------------------------------------------------------------

	def test_a_member_is_promoted_when_the_threshold_contribution_is_accepted_and_told(self):
		self.turn_on()
		self.accept(2)
		self.assertEqual(self.row().level, "New")
		self.assertEqual(self.submit()["status"], "Pending")
		self.accept(1)
		self.assertEqual(self.row().level, "Member")
		self.assertEqual(self.submit()["doctype"], "GP Discussion")
		self.assertTrue(
			frappe.db.exists("GP Notification", {"to_user": self.member.name, "type": "Trust Level"})
		)

	def test_a_new_member_is_still_held_when_the_approval_policy_is_on(self):
		self.turn_on()
		self.assertEqual(self.submit()["status"], "Pending")

	def test_automatic_promotion_to_member_writes_no_history_entry(self):
		self.turn_on()
		self.accept(3)
		self.assertEqual(self.level_logs("Level Changed"), [])
		self.assertEqual(self.level_logs("Trusted Promotion"), [])

	# Trusted --------------------------------------------------------------------------------

	def test_the_nightly_job_promotes_a_member_who_meets_every_requirement_and_logs_it(self):
		self.turn_on()
		self.accept(4)
		self.assertEqual(self.row().level, "Member")
		self.promote_trusted()
		self.assertEqual(self.row().level, "Trusted")
		logs = self.level_logs("Trusted Promotion")
		self.assertEqual(
			[(log.user, log.previous_level, log.level) for log in logs],
			[(self.member.name, "Member", "Trusted")],
		)

	def test_the_nightly_job_waits_for_the_days_as_a_member(self):
		self.turn_on(trusted_days=30)
		self.accept(4)
		self.promote_trusted()
		self.assertEqual(self.row().level, "Member")

	def test_a_recent_unclean_event_holds_back_trusted_and_an_old_one_does_not(self):
		self.turn_on()
		self.accept(4)
		frappe.db.set_value(
			"GP Approval Counter", self.row().name, "last_unclean_at", utc_now() - timedelta(days=10)
		)
		self.promote_trusted()
		self.assertEqual(self.row().level, "Member")
		frappe.db.set_value(
			"GP Approval Counter", self.row().name, "last_unclean_at", utc_now() - timedelta(days=100)
		)
		self.promote_trusted()
		self.assertEqual(self.row().level, "Trusted")

	def test_hiding_a_post_marks_the_author_and_an_upheld_report_does_too(self):
		self.turn_on()
		self.accept(1)
		published = frappe.get_all("GP Discussion", filters={"owner": self.member.name}, pluck="name")[0]
		self.assertIsNone(self.row().last_unclean_at)
		with self.as_user(self.second_member):
			frappe.get_doc("GP Discussion", published).hide("Off topic")
		self.assertIsNotNone(self.row().last_unclean_at)

	def test_a_ban_marks_the_member_and_pauses_promotion_while_it_lasts(self):
		self.turn_on()
		self.accept(4)
		with self.as_user(self.second_member):
			set_ban(self.community.name, self.member.name, 1, "Spam")
		self.assertIsNotNone(self.row().last_unclean_at)
		self.promote_trusted()
		self.assertEqual(self.row().level, "Member")

	def test_a_locked_level_is_left_alone_by_the_nightly_job(self):
		self.turn_on()
		self.accept(4)
		with self.as_user(self.second_member):
			set_member_lock(self.community.name, self.member.name, 1, "Watching this one")
		self.promote_trusted()
		self.assertEqual(self.row().level, "Member")

	def test_the_nightly_job_continues_in_a_new_job_after_its_time_budget(self):
		from gameplan.trust_levels import promote_community

		self.turn_on()
		self.accept(4)
		with patch("frappe.db.commit"), patch("frappe.enqueue") as enqueue:
			promote_community(self.community.name, budget=-1)
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.kwargs["community"], self.community.name)
		self.assertTrue(enqueue.call_args.kwargs["after"])

	# Manual changes -------------------------------------------------------------------------

	def test_a_moderator_sets_a_level_with_a_reason_and_it_goes_in_history(self):
		self.turn_on()
		with self.as_user(self.second_member):
			result = set_member_level(
				self.community.name, self.member.name, "Trusted", "Long-time contributor"
			)
		self.assertEqual(result["level"], "Trusted")
		self.assertEqual(self.row().level, "Trusted")
		log = self.level_logs("Level Changed")[0]
		self.assertEqual(
			(log.previous_level, log.level, log.reason), ("New", "Trusted", "Long-time contributor")
		)
		self.assertTrue(
			frappe.db.exists("GP Notification", {"to_user": self.member.name, "type": "Trust Level"})
		)

	def test_lowering_a_level_records_it_and_tells_nobody(self):
		self.turn_on()
		self.accept(3)
		frappe.db.delete("GP Notification", {"to_user": self.member.name})
		with self.as_user(self.second_member):
			set_member_level(self.community.name, self.member.name, "New", "Trial ended")
		self.assertEqual(self.row().level, "New")
		self.assertFalse(frappe.db.exists("GP Notification", {"to_user": self.member.name}))
		self.assertEqual(self.level_logs("Level Changed")[0].reason, "Trial ended")

	def test_changes_need_a_reason_a_moderator_a_member_and_a_non_staff_target(self):
		self.turn_on()
		with self.as_user(self.second_member):
			with self.assertRaises(frappe.ValidationError):
				set_member_level(self.community.name, self.member.name, "Member", " ")
			with self.assertRaises(frappe.ValidationError):
				set_member_level(self.community.name, self.second_member.name, "Member", "Staff")
			with self.assertRaises(frappe.ValidationError):
				set_member_level(self.community.name, self.guest.name, "Member", "Not a member")
		with self.as_user(self.member), self.assertRaises(frappe.PermissionError):
			set_member_level(self.community.name, self.outsider.name, "Member", "Not staff")

	def test_nothing_changes_by_hand_while_levels_are_off(self):
		with self.as_user(self.second_member), self.assertRaises(frappe.ValidationError):
			set_member_level(self.community.name, self.member.name, "Member", "Because")

	def test_a_lock_and_unlock_are_logged_and_unlocking_lets_the_rules_look_again(self):
		self.turn_on()
		with self.as_user(self.second_member):
			set_member_lock(self.community.name, self.member.name, 1, "Hold")
			self.assertEqual(self.row().locked, 1)
			set_member_lock(self.community.name, self.member.name, 0, "Release")
		self.assertEqual(self.row().locked, 0)
		self.assertIsNone(self.row().level_changed_at)
		self.assertEqual(len(self.level_logs("Level Locked")), 1)
		self.assertEqual(len(self.level_logs("Level Unlocked")), 1)

	# Staff, leaving, caps -------------------------------------------------------------------

	def test_staff_post_without_review_and_have_no_level_to_change(self):
		self.turn_on()
		with self.as_user(self.second_member):
			self.assertFalse(needs_approval(frappe._dict(doctype="GP Discussion", project=self.space.name)))
		self.assertIsNone(self.row(self.second_member))

	def test_leaving_the_community_drops_a_manual_level_and_rejoining_works_it_out_again(self):
		self.turn_on()
		self.accept(3)
		with self.as_user(self.second_member):
			set_member_level(self.community.name, self.member.name, "Trusted", "Long-time contributor")
			set_member_lock(self.community.name, self.member.name, 1, "Hold")
		self.community.reload()
		self.community.remove(self.community.get_member(self.member.name))
		self.community.save(ignore_permissions=True)
		self.assertIsNone(self.row())
		self.community.reload()
		self.community.add_member(self.member.name)
		self.community.save(ignore_permissions=True)
		with self.as_user(self.member):
			needs_approval(frappe._dict(doctype="GP Discussion", project=self.space.name))
		# The three published posts still count (D39), but the manual Trusted level and the lock are gone.
		self.assertEqual((self.row().level, self.row().locked), ("Member", 0))

	def test_trusted_members_skip_the_content_caps_and_members_do_not(self):
		with self.as_user(self.admin):
			save_caps(0, 0, 0, 0, 0, caps_enabled=1, max_links=1)
		self.turn_on()
		links = "<p>" + " ".join(f'<a href="https://example.com/{i}">l{i}</a>' for i in range(3)) + "</p>"
		set_policy(self.community.name, 0)
		with self.as_user(self.member), self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				doctype="GP Discussion", project=self.space.name, title="Links", content=links
			).insert()
		with self.as_user(self.second_member):
			set_member_level(self.community.name, self.member.name, "Trusted", "Long-time contributor")
		with self.as_user(self.member):
			frappe.get_doc(
				doctype="GP Discussion", project=self.space.name, title="Links", content=links
			).insert()

	# Reading ---------------------------------------------------------------------------------
