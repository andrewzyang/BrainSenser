#!/usr/bin/env python3
"""
Compare two pytest JUnit XML reports (``--junitxml``) of the same suite.

Usage:
    python tools/compare_junit.py BASELINE.xml AFTER.xml

Prints the tests that newly fail or error in AFTER, the ones that failed,
errored or xfailed in BASELINE and pass in AFTER, and the ones in BASELINE that
AFTER no longer has. Exits 1 if anything newly fails or errors, else 0.
Compare runs made with the same known-failures gate setting: the gate reports
listed failures as xfail.
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from collections import Counter

FAILING = {"failed", "error"}
WAS_FAILING = FAILING | {"xfailed"}


def outcomes(path):
    """{"classname::name": outcome} for every testcase in a JUnit XML report."""
    results = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        children = {child.tag: child for child in case}
        if "failure" in children:
            outcome = "failed"
        elif "error" in children:
            outcome = "error"
        elif "skipped" in children:
            is_xfail = children["skipped"].get("type") == "pytest.xfail"
            outcome = "xfailed" if is_xfail else "skipped"
        else:
            outcome = "passed"
        results[f"{case.get('classname')}::{case.get('name')}"] = outcome
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare two pytest JUnit XML reports.")
    parser.add_argument("baseline", help="JUnit XML of the reference run")
    parser.add_argument("after", help="JUnit XML of the run to check")
    args = parser.parse_args(argv)

    before, after = outcomes(args.baseline), outcomes(args.after)
    new = sorted(t for t, o in after.items() if o in FAILING and before.get(t) not in WAS_FAILING)
    fixed = sorted(t for t, o in before.items() if o in WAS_FAILING and after.get(t) == "passed")
    gone = sorted(before.keys() - after.keys())

    for label, results in (("baseline", before), ("after", after)):
        counts = Counter(results.values())
        print(f"{label}: " + ", ".join(f"{counts[o]} {o}" for o in sorted(counts)))
    for title, tests in (("New failures/errors", new), ("Fixed", fixed), ("Disappeared", gone)):
        print(f"\n{title} ({len(tests)}):")
        for test in tests:
            print(f"  {test}  [{before.get(test, 'absent')} -> {after.get(test, 'absent')}]")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
