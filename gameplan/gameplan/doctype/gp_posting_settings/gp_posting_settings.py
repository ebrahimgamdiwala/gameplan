import frappe
from frappe.model.document import Document

from gameplan.api import require_admin
from gameplan.posting_limits import CAPS, DAILY, FIELDS, MAX_LIMIT


class GPPostingSettings(Document):
	def validate(self):
		require_admin()
		if any(self.get(switch) not in (0, 1) for switch in ("enabled", "caps_enabled", "daily_enabled")):
			frappe.throw("Choose whether posting limits, per-post limits and daily limits are enabled")
		for field in (*FIELDS, *CAPS, *DAILY):
			value = self.get(field)
			if not isinstance(value, int) or not 0 <= value <= MAX_LIMIT:
				frappe.throw(f"{self.meta.get_label(field)} must be between 0 and {MAX_LIMIT}")
