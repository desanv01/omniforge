# Official Splunk Attack Range local installation

This configuration installs the **Administration Web Screen·API** from the official [Splunk Attack Range](https://github.com/splunk/attack_range) as a separate Docker Compose project. The existing AegisLoop·PostgreSQL and [Juice Shop·WAF·Splunk practice environment](purple-lab.md) are maintained in their respective configurations.

**Installing the management service is separate from building the actual lab server.** Running this Compose will not create a Windows/Linux target server or a new Splunk server in your local Docker. The official Attack Range builds a target environment for AWS, Azure, and GCP using templates and Terraform and Ansible, and executes actions on the target server with Atomic Red Team, etc. Cloud selection, resource size, budget, and dedicated access rights must be determined and then built separately. This local installation does not associate any credentials with the user's existing cloud login.

## execution

Requires Docker Compose, Git, and Python 3. Attack Range is not required for a basic installation of the product.

```sh
# 고정 공식 소스 준비 → 이미지 빌드 → 관리 서비스 시작 → 조회 확인
./scripts/attack-range.sh install
```

You can also run it in separate steps.

```sh
./scripts/attack-range.sh init
./scripts/attack-range.sh build
./scripts/attack-range.sh start
./scripts/attack-range.sh doctor
./scripts/attack-range.sh status
```

| Item | Address·Route |
| --- | --- |
| Management web screen | <http://localhost:4321> |
| Management API | <http://localhost:4000> |
| OpenAPI JSON document | <http://localhost:4000/openapi/openapi.json> |
| Official Fixed Source | `.local-runtime/attack-range/upstream/` |
| Personal Settings/SSH Keys | `.local-runtime/attack-range/config/`, `ssh_keys/` |
| Installation proof | `.local-runtime/attack-range/installation.json` |
| Inquiry Confirmation Evidence | `.local-runtime/attack-range/doctor.json` |

Ports 4000 and 4321 are used in accordance with the browser CORS tolerance of the official source. If another program is using the port, check for conflicts first. The management port is only exposed to `127.0.0.1`, and the official management API without authentication is not exposed to external networks.

The first build takes time and requires a network as the official Dockerfile downloads Python·Node·Terraform·AWS CLI·Azure CLI·Google Cloud CLI and project dependencies. API/app image builds are executed sequentially to reduce memory burden. When building an image, it accesses the tool's provider but does not perform cloud account authentication or server creation. We limited the API runtime memory to 1 GiB and the UI to 512 MiB. Check Docker memory usage when running alongside an existing Splunk lab environment.

## Reproducibility and preservation of original state

Recorded official repository and commit `fc9b9e719d8835da0bbb5c20d46c52a9778d64e2` in [upstream.json](../lab/attack-range/upstream.json). Build from the source without changing the official API/app Dockerfile. New sources are moved to `upstream/` only after being downloaded and verified in the temporary folder, so after a download failure, you can try again with the same command. If the local source is a different commit or has been modified, initialization/build will stop and will not be automatically overwritten. It also does not replace or delete existing personal settings or SSH keys.

The upstream README describes v5, but the API health says `1.0.0` and the Python project metadata says `3.1.2`. The installation result is not determined by the version string alone. `installation.json` records the fixed source commit, Compose SHA-256, and actual build image ID. Because the base image and some downloads use variable versions in the upstream Dockerfile itself, there is no guarantee that rebuilds from the same source commit will always produce the same image bytes.

Personal settings and original checkouts are stored only in the Git-excluded path `.local-runtime/`. A public repository contains only Compose, Wrapper, and Fixed Commit information and Description. It uses a separate management network and does not automatically connect to the AegisLoop/practice target network.

## What range does `doctor` check?

`doctor` only performs the following GET request:

- `/health`: API ready status
- `/templates`: Template list
- `/configs`: Save settings list
- `/attack-range/list`: Lab List
- `/openapi/openapi.json`: API document format and number of paths
- UI `/`: Web screen response

Only the list count and fixed commits are left in the verification results. The original response text, settings text, access password, and VPN settings are not recorded. `doctor` does not call cloud build·simulate·destroy API.

`/openapi/swagger` in the upstream instructions returns 404 in images built with this official Dockerfile. Currently, there are no Swagger UI additional packages in the upstream dependencies, so installation verification uses the normally provided OpenAPI JSON document.

Queries are limited to GET, but upstream `/attack-range/list` implementations can update stale build states to error states. This check does not guarantee complete immutability of upstream internal settings, and this state update does not apply to first-time installations without saved settings.

**`provider_available: true` in the template is not an authentication verification result.** This fixed source does not perform any actual CLI/credential verification on its representation. Distinguish between opening a web screen and establishing a cloud lab environment.

The cloud authentication path connects only to the empty, dedicated `.local-runtime/attack-range/cloud-disabled/` folder. Users `~/.aws`, `~/.azure`, `~/.config/gcloud` and host Docker socket/privileged mode are not used. We also disabled credential lookup through AWS instance metadata. In this configuration, pressing the Create Cloud button in the UI does not have an account associated with it to use.

## Use existing AWS CLI authentication

If you have already authenticated with your local AWS CLI profile, you do not need to log in again. The current lab uses authentication from the local `attack-range` profile. Verify the account and role of the profile you want to use with the following read-only command:

```sh
aws sts get-caller-identity --profile <your-profile>
```

Replace `<your-profile>` with your profile name. Verify that the account/role in the response is appropriate for the exercise, and do not place the original response text or temporary credentials in a public repository. Successful authentication and creation/deletion permissions for EC2, VPC, IAM, etc. are checked separately.

Local authentication is delivered only to **one-time containers** for viewing, planning, application, and cleanup. The container is removed after execution, and host authentication is not attached to the Attack Range Management API/UI while it is still running. There is no need to copy or change existing host profiles, keys, or sessions to this project's SSO folder.

## Optional AWS SSO login preparation

In the [AWS Preparation Plan](attack-range-aws-plan.md), we have summarized where to check account information, Windows configuration, cost calculation based on the actual price list, and the order of rebuilding and follow-up exercises. The actual installation and log collection verification of the current manual operating environment can be found in [AWS Construction Records](evidence/attack-range-aws-deployment-2026-10-11.md).

In the AWS console, open **IAM Identity Center → Dashboard → Settings summary** and check the **AWS access portal URL**. The SSO starting address is usually in the form `https://d-xxxxxxxxxx.awsapps.com/start`. Use the region on the same IAM Identity Center screen as the SSO region. This location is described in [AWS Official Guide](https://docs.aws.amazon.com/singlesignon/latest/userguide/howtochangeURL.html). You don't need to customize your address or change any settings.

If you don't have a portal address and see activation instructions, your existing SSO isn't ready. For organizational accounts, check the existing access address and practice account permissions with the administrator, and for personal accounts, check the login method and whether SSO is ready. Selecting account permissions is done after logging in, and for actual deployment, permission to create, view, and delete EC2/VPC resources is required in the selected practice account. When using the official S3 backend, you also need S3 state management permissions, but currently manual operations use local state. This installation does not automatically grant new IAM permissions.

Run the wrapper below only if you do not have local CLI authentication and want to use a separate SSO profile for this project. Prepare the **SSO launch URL and SSO region** for AWS IAM Identity Center. The SSO Region may be different from the AWS Region where you will later install the target server. You must log in directly to the browser as a user with permission to select Account/Permission Set. Do not enter long-term Access Keys into chat or privacy settings files.

```sh
# 공식 API 이미지에 포함된 AWS CLI를 별도 임시 컨테이너로 실행
./scripts/attack-range.sh sso-configure

# 설정한 aegisloop 프로필의 세션이 만료됐을 때 다시 로그인
./scripts/attack-range.sh sso-login
```

In the setup wizard, manually select the SSO starting address, SSO region, account, and role. For `CLI profile name`, enter **`aegisloop`**. Since you are using `--use-device-code --no-browser`, open the AWS authentication URL displayed in the terminal in your browser to complete login/authorization. The options are according to AWS official [configure sso](https://docs.aws.amazon.com/cli/latest/reference/configure/sso.html) and [sso login](https://docs.aws.amazon.com/cli/latest/reference/sso/login.html) documents.

SSO settings and session cache are stored only in `.local-runtime/attack-range/aws-sso/` and are excluded from Git. This one folder only attaches to `/root/.aws` in the temporary CLI container and does not read or change the existing `~/.aws` on the host. Existing SSO settings and cache are not deleted by the wrapper and are updated by the AWS CLI during the setup and login process. Temporary containers are removed after termination and are limited to 512 MiB of memory and 1 CPU.

**This step only involves logging into AWS and preparing temporary credentials.** It does not include creating an EC2·S3·VPC, building an Attack Range or simulating an attack, or connecting credentials to the management API. Check the cloud cost limit and target configuration separately before proceeding to the next deployment step.

## Order to use for AegisLoop testing

1. Current Docker web labs verify actual requests, normal activity, WAF, and Splunk evidence collection.
2. Review Attack Range's templates and supported OS/log collection configurations.
3. Set the cloud provider, budget, resource size, and termination criteria and build a target server with dedicated access rights.
4. Register AegisLoop's search connection in Splunk or export the original log to use for investigation. This integration is not auto-registered.
5. After checking the attack behavior through execution history and target status, compare the actual alert and investigation results. Successful installation of the management screen alone does not prove attack reproduction or detection performance.

To verify actual Windows operation, such as Windows AD·Sysmon, a corresponding Windows target server is required. This macOS Docker managed installation is not a replacement for running Windows Server.

## Halting and Unit Verification

```sh
./scripts/attack-range.sh stop
python3 -m unittest discover -s lab/attack-range/tests -v
```

`stop` only stops the `aegis-attack-range` project and preserves the source/private state. Unit validation uses mock responses to check source change protection, private key preservation, lookup path restrictions, credential-free aggregate history, and does not run in the cloud or Docker.
