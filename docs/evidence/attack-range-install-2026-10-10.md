# Verify Attack Range Management Service installation — 2026-10-10

I downloaded the official Splunk Attack Range commit `fc9b9e719d8835da0bbb5c20d46c52a9778d64e2` to a separate private path and built and started the API and web UI with the official Dockerfile. Follow [Installation/Operation Instructions](../attack-range.md). The existing AegisLoop and [real web lab environment](purple-lab-ready-2026-10-10.md) were maintained.

## Actual verification results

A GET request was issued to the installed service on 2026-10-10 22:58 KST.

| Item | Verification result |
| --- | --- |
| API | `127.0.0.1:4000`, container healthy, `/health` healthy |
| Web UI | Check `127.0.0.1:4321`, container healthy, template/practice list screen |
| template | 23 official lists |
| Saved practice settings/practice server | 0 each |
| OpenAPI | `/openapi/openapi.json` OK, OpenAPI 3.1.0, 20 routes |
| Swagger UI | `/openapi/swagger` in the official image is 404. Checked with normally provided OpenAPI JSON |
| Cloud account/server | Authentication not connected, 0 creations, 0 simulation runs |
| Resource Use | API approximately 97 MiB, UI approximately 92 MiB. Total product/web practice/management container approximately 3.8 GiB / Docker allocation approximately 7.75 GiB |

The API memory limit is 1 GiB and UI is 512 MiB. We only created a dedicated network for the two services and did not connect any host Docker sockets or existing cloud authentication files. You did not copy the data/LLM connection key from the existing product.

## build identifier

| image | Docker image ID |
| --- | --- |
| API `aegis-attack-range-api:fc9b9e719d88` | `sha256:5c105051511ce7c17f499d9b385ea6f016926071a94b0fe946b58a04578ebd9a` |
| UI `aegis-attack-range-app:fc9b9e719d88` | `sha256:b4460d581ef54a6d35bf456e625cf001348b88ff4f9b56d15be4147b03a1ff27` |

Since there are mixed upstream version strings and variable downloads, I recorded the source commit and the actual image ID together. Rebuilds of the same commit may not result in the same image bytes. The total installation/view tally is stored in paths excluding Git, `.local-runtime/attack-range/installation.json` and `doctor.json`.

## Actual screen and range

On the template screen, I confirmed the configuration of the official AWS Windows·Linux·AD, etc. The list of exercises below is empty. **Installation of the management screen is not evidence of actual Windows/Linux server construction or verification of attack/detection performance.**

![Empty Lab List for Installed Attack Range](images/real-environment/03-attack-range-empty.jpg)

AWS practice is prepared in the range of $10 per day, but the server is not created until account SSO connection, actual Terraform plan, and termination procedures are confirmed. Testing Windows targets and connecting AegisLoop logs are subsequent steps.
