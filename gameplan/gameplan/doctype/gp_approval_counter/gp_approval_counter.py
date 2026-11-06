# Copyright (c) 2026, Frappe Technologies Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class GPApprovalCounter(Document):
	def notify_update(self):
		pass


def on_doctype_update():
	frappe.db.add_unique("GP Approval Counter", ["community", "user"])
	# The nightly job reads the rows that could become Trusted.
	frappe.db.add_index("GP Approval Counter", ["community", "locked", "level", "accepted"], "trust_candidates")
