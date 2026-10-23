# Source deployment and new checkout verification

The units of deployment are the sources and documents in this repository. The default run builds the sources on `Dockerfile.local` and starts **ARTEX and PostgreSQL** with `docker-compose.local.yml`. There is no need for an undisclosed upstream ARTEX image, developer's API key, or existing operational DB. Juice Shop is a separate exercise used to create screen captures and is not included in the base product deployment.

[User Guide](USER_GUIDE_KO.md) is provided together with 7 pages of self-conducted diagnosis, defense verification, and infringement investigation captures. You must upload the source and `docs/` together on GitHub for the image to be displayed. Instead of just uploading a ZIP, the source in the archive is reflected in the repository, and commits and pushes are performed by the repository owner. The verification scope of this distribution is in [Latest Distribution Verification Record](evidence/release-guide-validation-2026-10-11.md).

## Execution order for first-time user

1. Clone the repository or download the source archive and unzip it.
2. Run Docker Desktop or Docker Engine and Compose v2.
3. Run the following command from the repository root:

```sh
./scripts/local-start.sh
```

We currently build the UI and Go backend inside a container, so no host Go·Node.js is required. The initial build downloads images, packages and browser runtime.

[http://localhost:8787/setup/](http://localhost:8787/setup/)에서 Set your administrator password. When performing vulnerability check/re-verification or AI investigation, set the connection you want to use in **System → LLM Settings**. A model key is not required for initial run and file basis preparation. Connect with your own search account or token only when using Splunk.

The script generates a random DB password in `.env.local` and a key for encrypting login signature/connection authentication information in `.local-runtime/jwt.key`. Existing files are maintained, and if the existing key is empty, recovery is requested without automatic replacement. JWT keys must be kept locally with the corresponding DB and not included in public repositories.

For detailed operating commands and port changes, refer to [Local Execution Guide](local-development.md). The existing `install.sh`·`docker-compose.yml` in the root is an upstream reference path and is not the default installation procedure for this extension.

## Optional AWS Windows Lab Connection

The new checkout's **Closed-loop → AWS Windows Lab** starts in an unconfigured state. Open source includes the bridge and scheduled task chain executors, but does not include Windows/Splunk servers, private connection settings, and past execution history. A basic run alone does not create any AWS resources or run any scenarios.

To connect a lab environment that you already own and prepare, follow the procedures in the AWS Windows Lab Guide (aws-windows-loop.md) for verifying an existing session, setting up a bridge, and preparing for audit collection. `local-start.sh` will read `docker-compose.range-bridge.yml` only when your `.local-runtime/attack-range/bridge/compose.env` is ready. This file and its linking key/token/original basis are not copied in public distribution. The official Attack Range 4321 management screen is separate from this connection.

The scheduled task chain runs fixed attack/normal controls and separate variant samples, and puts Splunk's limited detection profile into practice. Separate them from permissions for regular Splunk search connections. The confirmed samples and limits are in [Real Chain Verification Records](evidence/windows-task-chain-2026-10-11.md). Public captures and summaries are for reference only and will not be automatically loaded into the database or execution history of new installations.

## test

Run from the repository root.

```sh
./scripts/local-test.sh
python3 -I scripts/check-doc-links.py
```

The first command uses a separate `artex-purple-test` Compose project and a temporary PostgreSQL. In concurrent verification, you can specify a different test project name, such as `ARTEX_TEST_PROJECT_NAME=artex-clean-test ./scripts/local-test.sh`. Perform integration tests of extension functions without accessing the actual service DB, actual LLM, or actual Splunk, and then organize the test container. The second command examines document internal paths and anchors on a host with Python 3.

The source build of `local-start.sh` includes a front-end static build and Go compilation. Splunk's TLS mock test verifies connection, search scope, credential processing, and original text preservation, but does not verify actual log collection or detection quality in an enterprise environment. Model execution tests also verify execution control with mock responses and do not guarantee the success of the actual provider call.

## Scope of public files

| Included | exclude |
|---|---|
| Application source, dependency lock files, tests | `.env`, `.env.local`, other actual configuration files |
| Dockerfile·Compose·Execution script for source build | JWT key, API key, authentication token, certificate private key |
| README and feature/development/deployment documentation | `data/`, `.local-runtime/`, `evidence-local/`, DB dump·volume |
| Separate Local Lab Screens Reviewed | Export all original upload logs, operational vulnerabilities and investigation results |
| Copyright notice and license for the original and Korean version | Developer-only workspace and verification output |

The virtual accounts/tokens and illustrative examples in the test code are fixtures that you do not have actual access to. Do not save actual values ​​by converting them into test examples. `.gitignore` only excludes new files and does not remove secrets from already tracked files or past commits.

The source compression or public commit includes `Dockerfile.range-bridge`, `docker-compose.range-bridge.yml`, `lab/attack-range/bridge.py`·`runtime.py`·`chain_runtime.py`, and `requirements-bridge.txt`, configuration and audit preparation tools, and related tests. In particular, the optional bridge image build will fail if the new `chain_runtime.py` is omitted. `git archive HEAD` only includes the last commit, so changes/new files that have not been committed yet are left out. Check the inclusion list and file contents before compression. The existing platform-specific binary ZIP of `build.sh` is a different output from this Docker source distribution.

In the commit you want to publish, check the following:

- Make sure that only the intended sources, documents, and reviewed screens are included with `git status --short` and `git diff --cached --stat`.
- API keys, passwords, JWTs, original logs, and DB dumps are excluded not only from new files but also from the actual Git history that will be released.
- Directly check whether there are any values ​​that should not be disclosed in the user information, connection address, and log contents on the screen.
- Make sure the initial setup screen asks for a new administrator password and that there are no other users' actions, logs, or connections.
- Make sure that the default run does not create a separate lab app or Splunk.

## Check out in independent checkout

Use a new checkout that does not copy `.env.local`, `.local-runtime`, and `data/` from the existing development folder. If an existing app is running on the same computer, separate the project, image, and host port.

```sh
ARTEX_PROJECT_NAME=artex-clean-check \
ARTEX_LOCAL_IMAGE=artex-clean-check:dev \
ARTEX_LOCAL_PORT=18887 \
ARTEX_LOCAL_PROXY_PORT=18888 \
./scripts/local-start.sh
```

[http://localhost:18887/setup/](http://localhost:18887/setup/)에서 Check the new initial setup screen. Since the key/DB has not been copied, the existing developer's login, LLM connection, tasks and logs should not appear. This command creates its own data volume and does not automatically run physical checks or AI investigations.

Once confirmed, stop the test app with the same project name. The command below does not delete any data.

```sh
ARTEX_PROJECT_NAME=artex-clean-check \
ARTEX_LOCAL_IMAGE=artex-clean-check:dev \
ARTEX_LOCAL_PORT=18887 \
ARTEX_LOCAL_PROXY_PORT=18888 \
docker compose --env-file .env.local -f docker-compose.local.yml stop
```

The practice screen and the actual confirmed range are recorded separately in [Public trace information](evidence/README.md). Passing implementation and testing, verifying local screens, and verifying actual external systems do not express the same success.
