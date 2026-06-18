from atlassian_cli.config import get_settings
from atlassian import Jira

s = get_settings()
j = Jira(url=s.atlassian_url, username=s.atlassian_email, password=s.atlassian_api_token.get_secret_value(), cloud=True)

BUG = "SI-11"
WET_FART = "SI-8"
SBD = "SI-9"
TRUMPET = "SI-10"

# Add resolution comment to the bug
comment = (
    "Bug resolved. Root cause: the wet fart subsystem lacked backpressure regulation, "
    "causing uncontrolled output bursts. Fixed by introducing a sphincter throttle mechanism "
    "with configurable release intervals. Output is now deterministic and testable. "
    "Verified with a dry run (no pun intended)."
)
j.issue_add_comment(BUG, comment)
print(f"Comment added to {BUG}")

# Transition bug to Done
j.post(f"rest/api/2/issue/{BUG}/transitions", data={"transition": {"id": "41"}})
print(f"{BUG} -> Done")

# Remove the blocking link
links = j.issue(BUG, fields="issuelinks")["fields"]["issuelinks"]
for link in links:
    if link.get("outwardIssue", {}).get("key") == WET_FART:
        j.delete(f"rest/api/2/issueLink/{link['id']}")
        print(f"Removed blocking link {BUG} -> {WET_FART}")

# Move remaining stories to In Progress
for key in [WET_FART, SBD, TRUMPET]:
    j.post(f"rest/api/2/issue/{key}/transitions", data={"transition": {"id": "21"}})
    print(f"{key} -> In Progress")
