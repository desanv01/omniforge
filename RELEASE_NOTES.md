# AegisLoop source distribution — 2026-10-11

This is a source distribution that combines the functions implemented to date and the actual verification traces. It is based on ARTEX-KO and maintains the original/Korean version copyright notice and AGPL-3.0 license. We've cleaned up the current version for distribution without adding any new features.

## Contents reflected in this release

- [Usage Guide](docs/USER_GUIDE_KO.md) and Chapter 7 capturing vulnerability diagnosis, defense verification, and infringement investigation performed by the user.
- Modifications to convey actual log types, representative evidence, and investigation questions to AI research and reduce unnecessary model calls.
- Preserve Splunk target field mappings and preserve the full text of events of dubious origin. Do not mark incomplete collections as complete.
- 351 regression tests and web build verification of the latest research fixes. This is different from the results verified by actual completion of the LLM survey.

The distribution includes up-to-date sources and documentation. We also preserved the state of the capture's investigation execution limit being reached.

## Included features

- Diagnosis and re-verification of existing ARTEX vulnerabilities.
- Preparation of defense verification and infringement investigation basis using file upload or Splunk query.
- Defensive incidents and read-only AI investigations start without vulnerabilities.
- Closed-loop execution history, rule evaluation, and comparison of evidence before and after improvement.
- Optional AWS Windows Lab: 3 Fixed Atomic Explorations, PowerShell → Scheduled Tasks → Delayed Execution Chaining, Normal Business Contrast, and Separate Variant Validation.
- Practice Applying Splunk's dedicated rules, collecting actual audits and alerts, and exporting step-by-step evidence, false positive causes, timeline, and JSON.

There is no ability to select the full Atomic Red Team catalog. Candidates for chain improvement are fixed behavior profiles and not self-generating/operating SIEM auto-deployment functions of arbitrary rules.

## Real AWS Verification

| specimen | Before improvement | After improvement |
|---|---|---|
| 1 common attack chain | detection | Maintain detection |
| 1 normal maintenance task | False positives | Normal classification, no false positives |
| 1 separate variant attack | Not included in reference sample | detection |

After standard and improvement, there are 0 cases that cannot be judged. Based on results from a limited, hands-on sample, no claims are made regarding accuracy or false positive rates for enterprise operating environments. [Actual web capture and verification records](docs/evidence/windows-task-chain-2026-10-11.md) and [Fully public records](docs/evidence/README.md) are provided together.

## new installation

Run Docker and Compose v2 and run the following command from the extracted source folder:

```sh
./scripts/local-start.sh
```

Set your administrator password in `http://localhost:8787/setup/`. The default distribution starts only ARTEX and PostgreSQL. Juice Shop, Splunk, and AWS servers are not automatically installed. AI capabilities require your own LLM connection. The AWS Lab tab is available after configuring [Separate Lab Environment Connection](docs/aws-windows-loop.md).

The developer's API key, AWS·Splunk account, JWT key, `.env.local`, operational DB, original lab log, and `.git` history are not included in source compression. Public screens and documents are included, but the execution history in the capture is not included in the new installation DB.

## Upload to GitHub

When updating an existing repository, the source files in the archive are reflected in the corresponding repository folder. Existing `.git` folders and personal environment files will not be overwritten. Review, commit, and push your change list in GitHub Desktop. If it is a new repository, create the unzipped source folder as a Git repository and then connect it to your GitHub repository.

The ZIP file itself can also be used as a GitHub Release attachment. If you want to clone a repository and make it run, you need to commit the source files within it instead of just uploading the ZIP. In this work, we did not push directly to GitHub.

Please refer to [Deployment Guide](docs/release.md) for execution, testing, and exclusion criteria, and [Deployment Verification Record](docs/evidence/release-guide-validation-2026-10-11.md) for verification of this new installation.
