#!/usr/bin/env python3
"""Review tools the AI asked for but couldn't add itself.

    python3 tools_admin.py                 # list pending requests
    python3 tools_admin.py all             # list everything (pending, approved, rejected, installed)
    python3 tools_admin.py approve 3       # approve request #3 (Python packages get installed now)
    python3 tools_admin.py reject 3        # reject request #3 (the AI is told it was declined)
    python3 tools_admin.py installed       # packages the AI has added so far

A readable copy is kept in logs/tool-requests.md.
"""
import sys

import executor


def show(reqs):
    if not reqs:
        print("Nothing here.")
    for r in reqs:
        print("#%-3d %-24s %-15s %-9s asked %dx  last %s" % (
            r["id"], r["name"], r["kind"], r["status"], r["count"], r.get("last", r["first"])[:16]))
        if r["reasons"]:
            print("      why: %s" % r["reasons"][-1][:110])
        if r["questions"]:
            print("      question: %s" % r["questions"][-1][:110].replace("\n", " "))
        if r.get("error"):
            print("      auto-install error: %s" % r["error"].strip().splitlines()[-1][:110])


def main():
    executor.write_profile()
    args = sys.argv[1:]
    reqs = executor._load_requests()
    if not args:
        show([r for r in reqs if r["status"] == "pending"])
    elif args[0] == "all":
        show(reqs)
    elif args[0] == "installed":
        for e in executor._load_installed():
            print("%-20s %-10s %s  (%s)" % (e["package"], e["version"], e["date"][:16], e["reason"][:70]))
    elif args[0] in ("approve", "reject") and len(args) == 2 and args[1].isdigit():
        rid = int(args[1])
        if args[0] == "approve":
            print(executor.approve_request(rid))
        else:
            r = executor.set_request_status(rid, "rejected", "Declined by the owner.")
            print("Rejected #%d %s." % (rid, r["name"]) if r else "No request #%d." % rid)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
