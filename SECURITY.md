# Security Policy

Korean · [English](SECURITY.en.md)

This document explains how to report a security vulnerability in the ARTEX Korean version (`artex-ko`) code itself.
Explain. ARTEX is an offensive security tool that performs penetration testing, but what this article covers is
This is not the result of an attack using a tool, but a vulnerability that arises when operating and distributing this software.

For example:

- Authentication bypass, privilege escalation, SSRF, injection of web UI/API server (`server/`)
- Exposure or storage of stored credentials/API keys in plaintext
- Skip human-in-the-loop approval process and allow agents to use tools out of scope
  defect that causes it to run
- Vulnerabilities related to supply chain and dependency

## How to report

**Please do not post security vulnerabilities as public issues.** If disclosed, they may be exploited before a patch is released.
You can. Please use the following private path instead:

1. **Security** tab in the repository → **"Report a vulnerability"** (private security advisory, GitHub Private
   Report it to Vulnerability Reporting. This path is visible only to maintainers.
2. If the above feature is not open, please do not enter any sensitive details and use the “Security-related confidential contact information.”
   Open only the minimum number of issues you "want" and ask the maintainer to open a private channel.

Please include the following in your report to speed up classification:

- Affected components and versions (release tag or commit hash)
- Reproducibility and scope of impact (what can be done)
- If possible, a proof of concept (PoC) and proposed mitigations.

## Processing Procedure

- Once received, we will respond within a reasonable period of time to confirm and assess the validity and severity.
- Once the correction is ready, coordinate with the reporter to make it a **coordinated disclosure**.
  Timing the disclosure is correct. Details will not be disclosed before modification.
- If you give consent, we will disclose your contribution when we make it public.

## scope of support

This repository is a volunteer-maintained **Korean localized version of the original ARTEX**. The security fix is
**Provided based on the latest default branch**. Retroactive backports to past releases are not guaranteed.
If it is a vulnerability in the original (upstream) code, regardless of localization,
We also recommend reporting to [Autumn-27/ARTEX](https://github.com/Autumn-27/ARTEX).

## Report out of scope

The following are **not** covered by this security policy:

- A vulnerability in **that external system** discovered by attacking an external system with ARTEX. It's the system's
  This is a matter to report to the owner.
- Problems caused by using tools targeting other people’s systems without permission. Such use itself
  [Scope of use](README.md#features) and violates domestic laws.
- The fact that ARTEX executes the attack tool “as designed”. This tool is used within the permitted scope.
  It is made to perform penetration testing.

If you witness **misuse** (use outside the scope of permission) of this tool, please do not report it via GitHub.
Please use the legal reporting process for such actions (damaged system owner/related organizations).
