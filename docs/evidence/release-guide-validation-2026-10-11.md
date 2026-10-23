# Verification of distribution with user guide — 2026-10-11

I copied and checked the latest source, [User Guide](../USER_GUIDE_KO.md), and 7 hands-on practice captures to a separate distribution folder. The execution data and Git history of the existing development folder were not copied.

## Check for new installation

- I verified the source build and initial run with `./scripts/local-start.sh` in a separate Docker Compose project. We used dependency/build cache and have not verified that it can be installed without internet.
- Both ARTEX and PostgreSQL containers have returned to normal status. In the default installation, the Juice Shop·Splunk·AWS bridge is not created.
- I ran it with the LLM environment variable empty and checked the initial password setting screen at `/setup/`. I didn't set an admin password on my behalf or call the model.
- The new DB's LLM connection, security log connection, operation, vulnerability, defensive incident, vulnerability investigation, and actual loop records were 0 each.
- We have organized temporary containers, networks, and empty test volumes that have been verified. There were no changes to the existing app, training environment, or AWS resources.

![Initial password setting screen when running a new distribution](images/release-guide-clean-setup-20261011.jpg)

## Inspection range

- 351 regression tests and web builds passed immediately after the latest survey fix. In this packaging, no additional modifications were made to the application code, and the source build and initial execution of the distribution copy were checked separately.
- Internal paths, images, and anchors of public documents were inspected. The 7 images in the user guide are linked by relative paths.
- We ran a secret detection check on the distribution file and internally matched it against five locally extracted real secrets. There was no actual secret value match in the scope of the test. Detected strings were verified with test fixtures or empty environment variable examples.
- We inspected 49 existing public images and guide captures using OCR, and supplemented and visually confirmed sensitive screens. I also took a look at the new installation capture we added. This test is not a security certification that guarantees the absence of any sensitive information.
- `.git`, actual `.env` files, API·JWT·AWS·Splunk authentication information, DB·volume, original upload log, full investigation export, and local verification output were excluded from distribution. Includes `.env.example` for explanation and virtual data for testing.

`SOURCE_MANIFEST.sha256` in the distribution folder records SHA-256 per file. `.zip.sha256` next to ZIP is a value that verifies the integrity of the compressed file. When reflecting on an existing repository, the past Git history of that repository must be managed separately. There is no Git history in this ZIP.

Capture shows actual save history. We also explicitly state that the execution limit for the breach investigation has been reached, and do not express the success of a new installation as completion of an actual LLM investigation or verification of operational detection performance.
