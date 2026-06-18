from atlassian_cli.config import get_settings
from atlassian import Jira

s = get_settings()
j = Jira(url=s.atlassian_url, username=s.atlassian_email, password=s.atlassian_api_token.get_secret_value(), cloud=True)

epic = j.create_issue(fields={
    "project": {"key": s.jira_project},
    "summary": "try all farts",
    "description": "Comprehensive fart testing initiative covering all major fart types.",
    "issuetype": {"name": "Epic"},
})
epic_key = epic["key"]
print("Epic:", epic_key)

farts = ["Silent", "Squeaky", "Wet", "SBD", "Trumpet"]
task_keys = {}
for name in farts:
    t = j.create_issue(fields={
        "project": {"key": s.jira_project},
        "summary": name + " fart",
        "description": "Test the " + name.lower() + " fart.",
        "issuetype": {"name": "Story"},
        "parent": {"key": epic_key},
    })
    task_keys[name] = t["key"]
    print("  Story " + name + ": " + t["key"])

for name in ["Silent", "Squeaky"]:
    j.post("rest/api/2/issue/" + task_keys[name] + "/transitions", data={"transition": {"id": "41"}})
    print("  Marked Done: " + task_keys[name])

bug = j.create_issue(fields={
    "project": {"key": s.jira_project},
    "summary": "Diarrhea",
    "description": "Critical bug blocking the wet fart. Uncontrolled output makes wet fart untestable.",
    "issuetype": {"name": "Bug"},
    "parent": {"key": epic_key},
})
bug_key = bug["key"]
print("Bug:", bug_key)

j.create_issue_link(data={
    "type": {"name": "Blocks"},
    "inwardIssue": {"key": bug_key},
    "outwardIssue": {"key": task_keys["Wet"]},
})
print(bug_key + " blocks " + task_keys["Wet"])

print("\nSummary:")
print("  " + epic_key + " [Epic] try all farts")
for name, key in task_keys.items():
    status = " [DONE]" if name in ["Silent", "Squeaky"] else ""
    print("    " + key + " [Story] " + name + " fart" + status)
print("    " + bug_key + " [Bug] Diarrhea -> blocks " + task_keys["Wet"] + " (Wet fart)")
