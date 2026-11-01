"""Shared constants: field catalogue, statuses, seed lists, roles. Carried over from the v1 app."""

STATUSES = ["L1 Interview", "L2 Interview", "L3 Interview", "Offer", "Drop",
            "Feedback Pending", "To Be Scheduled", "Scheduled", "Yet to Join"]
DEFAULT_STATUS = "To Be Scheduled"

SEED_LISTS = {
    "status": STATUSES,
    "yes_no": ["Yes", "No"],
    "notice_period": ["Immediate", "15 Days", "30 Days", "45 Days", "60 Days", "90 Days", "Serving Notice", "Other"],
    "recruiters": [],
    "clients": [],
}

# key, label, type, required flag, list name, hint
CANDIDATE_FIELDS = [
    ("date_added", "Date Added", "date", "Required", None, "Defaults to today."),
    ("recruiter", "Recruiter", "select", "Required", "recruiters", "Pick from the Settings page."),
    ("full_name", "Candidate Name", "text", "Required", None, "Full name as on the CV. Used for duplicate checking."),
    ("current_company", "Current Company", "text", "Recommended", None, "Present employer."),
    ("current_location", "Location", "text", "Required", None, "Current city."),
    ("total_experience_years", "Experience (yrs)", "number", "Required", None, "Total experience in years, e.g. 6.5"),
    ("current_ctc_lakhs", "Current CTC (LPA)", "number", "Required", None, "In lakhs per annum, e.g. 12.5"),
    ("expected_ctc_lakhs", "Expected CTC (LPA)", "number", "Required", None, "In lakhs per annum."),
    ("official_notice_period", "Notice Period", "select", "Required", "notice_period", "Official notice period."),
    ("earliest_joining_date", "Earliest Joining Date", "date", "Recommended", None, "Earliest date the candidate can join."),
    ("how_soon_can_join", "How Soon Can Join", "text", "Optional", None, "e.g. 'Can buy out in 2 weeks'."),
    ("existing_offer", "Existing Offer?", "select", "Recommended", "yes_no", "Does the candidate hold another offer?"),
    ("offer_details", "Offer Details", "text", "Optional", None, "Company, CTC and joining date of the other offer."),
    ("date_of_birth", "Date of Birth", "date", "Optional", None, "Collect only if genuinely needed. Visible to admins only."),
    ("email", "Email", "email", "Recommended", None, "Used for duplicate checking."),
    ("phone", "Phone", "text", "Required", None, "Used for duplicate checking."),
    ("primary_skill_role", "Role / Primary Skill", "text", "Recommended", None, "Role being considered for."),
    ("client", "Client", "select", "Required", "clients", "Pick from the Settings page."),
    ("job_req_id", "Job Req ID", "text", "Optional", None, "Client requisition reference."),
    ("profile_submitted_to_client", "Submitted to Client?", "select", "Recommended", "yes_no", "Yes once the profile has gone to the client."),
    ("client_submission_date", "Client Submission Date", "date", "Optional", None, "Date the profile was sent to the client."),
    ("recruiter_notes", "Recruiter Notes", "textarea", "Optional", None, "Anything else worth remembering."),
]

FIELD_KEYS = [f[0] for f in CANDIDATE_FIELDS]
NUMERIC = {"total_experience_years", "current_ctc_lakhs", "expected_ctc_lakhs"}
DATES = {"date_added", "earliest_joining_date", "date_of_birth", "client_submission_date"}
REQUIRED = {f[0] for f in CANDIDATE_FIELDS if f[3] == "Required"}
SENSITIVE = {"date_of_birth"}

INTERVIEW_FIELDS = ["candidate_id", "interview_stage", "interview_date", "interview_time", "interviewer_panel",
                    "feedback", "status", "next_action", "next_followup_date"]
INTERVIEW_DATES = {"interview_date", "next_followup_date"}

ROLES = ("owner", "admin", "recruiter", "viewer")
ADMIN_ROLES = {"owner", "admin"}
WRITE_ROLES = {"owner", "admin", "recruiter"}