# AegisLoop's first MVP verification record

Confirmed in local ARTEX·PostgreSQL environment on 2026-10-10. The new screen below is proof of implementation of the product feature. To distinguish it from existing Juice Shop hands-on evidence, synthetic examples are not presented as actual attack/compromise/detection success stories.

## Checked screen

![Integration Status](images/aegisloop/01-overview.png)

Go to Offensive·Defensive·Closed-loop in one web app. The numbers on the integrated screen are the number of saved tasks, events, and evaluation records. It is not interpreted as overall detection accuracy or attack success rate. The final screen contains one composite event and one evaluation record below.

![Save Independent Case](images/aegisloop/02-defensive-case.png)

Uploaded [`incident.jsonl`](../examples/aegisloop/incident.jsonl) to save the incident without linking the vulnerability. Target `demo.example`, 3 events preserved between 2026-10-09 18:00 and 20:00 Korean time. Since the data was not exported from the original system, the collection scope check item was not selected and the evidence scope incomplete warning was maintained. AI execution has not started. On the screen, we confirmed that `collection.files[0].content` in the exported JSON exactly matches the uploaded file.

![Rule evaluation history](images/aegisloop/03-closed-loop-comparison.png)

We loaded the synthetic example, checked the candidate proposed function using only the improvement data, and compared it with the [example candidate rule](../examples/aegisloop/candidate-rule.json) prepared in advance. We saved the results and linked the independent events. Saved history preserves comparison results with the original snapshot. This does not mean that the incident and assessment logs you link to are collected from the same actual attack.

![Calculate indicators of synthetic input](images/aegisloop/04-closed-loop-metrics.png)

In the synthetic evaluation data, which were two cases each of attack and normal, we confirmed the reference TP=1·FP=1·TN=1·FN=1 and the candidate TP=2·FP=0·TN=2·FN=0. This is a computational validation of a small rule matcher and does not demonstrate generalization performance. Since there is no verification of the source of the actual alarm time, MTTD cannot be calculated. We also confirmed that the browser rejected the content for improvement due to a duplicate event error when comparing it with the content for evaluation.

## Automatic verification and retention checks

- Passed all Go package tests and `go vet`. Passed all tests including DB·API on separately initialized PostgreSQL.
- Defensive tests: Independent incident · Splunk mock HTTPS lookup · Change source · Planner/Worker mock execution · Cancellation · Limit duplicate execution · Restart recovery · Original export.
- Closed-loop testing: Candidate generation Input separation · Duplicate JSON keys · Reserved fields · Duplicate data · Unconfirmed fields · Alert time conditions · Server recalculation · Snapshot · Authentication · Export.
- Passing static web build·TypeScript·Biome commands. In the overall Biome output, 125 existing warnings and 767 information remain, with no errors. The new screen target test passed separately.
- 0 Chinese character leaks in 35 static HTML. Pass internal document linking and whitespace checking. Last change Gitleaks scan detected 0 confidential information.
- Two existing tasks, two vulnerabilities, one log connection, and one vulnerability investigation were preserved. Only 1 new synthesis event and 1 evaluation record were added, and the number of independent AI runs is 0. I didn't change any local preferences and JWT/connection encryption keys.

The actual model provider call, enterprise Splunk, operational detection rule deployment, and automatic response were not executed in this screen verification. Automated validation of Splunk and AI paths used mock servers/models. The scope of existing actual practice records is separately described in [Public Practice Records](README.md).

Please refer to [AegisLoop Guide](../aegisloop.md) for installation and usage instructions, and [Source Analysis](../aegisloop-source-analysis.md) for this implementation and subsequent requirements.
