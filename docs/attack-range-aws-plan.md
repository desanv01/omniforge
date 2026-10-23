# AWS lab preparation plan

The local [Attack Range Management Service](attack-range.md) and [Real Web Log Lab](evidence/purple-lab-ready-2026-10-10.md) are running. I've set a budget of $10 per day with my AWS provider, and I'm using authentication from my existing local AWS CLI `attack-range` profile. Based on user requests, we reviewed and applied the new Seoul `ap-northeast-2` plan, which **cleans up after one week of operation**. 3 servers, 150 GiB disk, and 1 NAT were created, and IAM, Lambda, and Scheduler for automatic shutdown were not installed. We confirmed official role installation and Splunk collection of three actual Windows logs, and the results and limitations can be found in [AWS Construction Records](evidence/attack-range-aws-deployment-2026-10-11.md).

## Information to check first

1. Confirm the lab account and role you want to use in the local AWS CLI profile you've already authenticated. Use the `aws sts get-caller-identity` command in [Use existing CLI authentication](attack-range.md#use-existing-aws-cli-authentication) and do not require new authentication twice.
2. Decide on a practice region. The Personal Plan Preparation Tool supports Seoul `ap-northeast-2` and Frankfurt `eu-central-1`, or if omitted, uses Frankfurt, which is the same as the official template. The SSO region and target server region are separate.
3. Verify permissions to create, view, and delete EC2/VPC resources according to actual plans. Manual operation uses local Terraform state and does not require IAM/Lambda/Scheduler permissions for automatic shutdown. Just because some service inquiries are rejected does not mean that all creation tasks are impossible.
4. Proceed with [Optional SSO Settings](attack-range.md#optional-aws-sso-login-preparation) only when there is no local CLI authentication. Check the starting address and SSO region in **IAM Identity Center → Dashboard → Settings summary → AWS access portal URL**. The management console address itself is not the SSO starting address. [AWS Official Information](https://docs.aws.amazon.com/singlesignon/latest/userguide/howtochangeURL.html)

If you only see the activation screen, Traditional SSO is not ready. For organizational accounts, check with your administrator for existing portal addresses, lab accounts, and roles. If it is a personal account, first decide whether you are ready for SSO and how to log in. Do not enter passwords or long-term access keys into chat or Git.

## First target configuration

We'll use the official Windows single target template as our first candidate. AD domain configuration is separated into the next exercise and we will not be creating multiple Ranges at the same time.

| Resources | Basic configuration of fixed sources |
| --- | --- |
| VPN Router | Ubuntu 22.04, `t3.small`, gp3 30 GiB |
| Splunk·Guacamole | Ubuntu 22.04, `t3.xlarge`, gp3 60 GiB |
| Windows 대상 | Windows Server 2022, `t3.large`, gp3 60 GiB |
| network | VPC, public/private subnet, 1 NAT Gateway, 2 public IPv4 |
| Terraform status | Version controlled S3 bucket |
| Lab Region | Preparation tool defaults are Frankfurt `eu-central-1`, such as the official template; Currently reviewing Seoul `ap-northeast-2` plan |

Full EC2, EBS, and NAT resources are created from the first VPN deployment step of this template. You should not think of the router as the only charging stage. The basis is the fixed commits [Windows Templates](https://github.com/splunk/attack_range/blob/fc9b9e719d8835da0bbb5c20d46c52a9778d64e2/templates/aws/splunk_windows_aws.yml) and [Terraform Resources](https://github.com/splunk/attack_range/blob/fc9b9e719d8835da0bbb5c20d46c52a9778d64e2/terraform/aws/resources.tf).

## $10 per day operating range

AWS public price list was viewed on 2026-10-10 23:06 KST. On-demand, shared tenancy, free Linux OS, Windows license included, gp3 basic performance, 30-day monthly conversion basis. Below is the **basic amount calculation for EC2, NAT time, public IPv4, and EBS and is not a cost cap.**

| Configuration | Frankfurt 24 hours | Seoul 24 hours |
| --- | ---: | ---: |
| 1 router·Splunk·Linux target | $9.45 | $10.22 |
| 1 device for Router·Splunk·Windows | $10.11 | $10.89 |
| Router·Splunk·Windows DC·Windows 대상 | $13.27 | $14.23 |

The official Windows basic configuration starts at over $10 if you run it 24 hours a day. In the currently requested manual operation for one week, only Windows will be reduced to `t3.medium` (2 vCPU·4 GiB) and Router·Splunk·Network·Disk will be maintained. Applying Seoul's Windows hour rate `$0.0704`, the base amount is **$9.4176 per day, $65.9232 per week**. Official role installation, harmless commands, and log collection were confirmed with a small practice configuration that satisfied [EC2 specifications](https://docs.aws.amazon.com/ec2/latest/instancetypes/gp.html) and [Windows requirements](https://learn.microsoft.com/en-us/windows-server/get-started/hardware-requirements). It has not been verified for large-scale Atomic execution or long-term load performance.

Optional auto-shutdown tool maintains existing **up to 4-hour sessions** from the start of preparation. The basic price for 4 hours in a basic Windows configuration is about $1.69 in Frankfurt and $1.81 in Seoul. We have added exit code and unit validation, but have not verified installation on AWS or actual deletion. Manual operation does not install an end schedule and the expiration tag simply records the target time for the user to clean up.

Taxes, NAT processing GB, Internet/Cross-AZ transfer, T3 Unlimited CPU excess credit, snapshots, S3/CloudWatch, paid Splunk license, and LLM fees are separate. Even if the base amount is within your budget, there is no guarantee that your bill will be capped. After use, it is organized by Terraform destruction of the range and inquiry of remaining resources. **NAT, EIP, and EBS costs do not end with just stopping EC2.**

Calculation basis: [Frankfurt EC2 public price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/20261009203134/eu-central-1/index.csv), [Seoul EC2 public price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/20261009203134/ap-northeast-2/index.csv), [VPC price](https://aws.amazon.com/vpc/pricing/). The catalog version is `20261009203134`. For example, the Frankfurt Windows time base is calculated as `(0.024 + 0.192 + 0.1236 + 0.052 + 2×0.005)` plus EBS `150×0.0952/30/24`, which is approximately `$0.42143`.

## Reconstruction and subsequent practice sequence

- Check the account, role, permissions and actual region to be used with existing local CLI authentication.
- In the personal template, limit public SSH/WireGuard access to the user's public IP `/32`. Splunk·Keep target servers in a private subnet.
- Replace the upstream default password in both general and each Splunk·Guacamole·Windows role variable. Changing only the general value leaves the default password for each role. Personal YAML/Terraform state is stored in a private path.
- Check the Terraform provider/VPC module version and AMI, and review the actual plan's resources and additional charges.
- After a week, prepare to clean up directly, clean up in case of failure, and check the remaining EC2, NAT, EIP, and EBS. If you use the upstream S3 backend separately, you must also check the past version/delete marker.
- Collect real Windows behavior/host logs and Splunk alerts and register them in AegisLoop as a search connection or file basis.

Local CLI authentication is now in place, so there is no need to re-authorize a separate SSO authentication link. Authentication only connects to one-time containers for inquiry, planning, application, and organization, and does not connect to management APIs that run constantly. When your session expires, renew using the existing login method for that profile. The project's SSO wrapper is optional for users who require separate authentication.

## Prepare for private setting and review plan

[aws_plan.py](../lab/attack-range/aws_plan.py) checks the official fixed source and only creates personal settings for new `.local-runtime/attack-range/aws-plans/<UUID>/`. Does not modify existing upstream checkouts/keys/settings. Replace the 6 default passwords with random number passwords and limit the router's SSH/WireGuard access to one public IPv4 `/32`. The target server does not receive a public IP, but only receives it within the VPC. Disables EC2 termination protection and writes ownership/expiration tags to the instance/root disk.

```sh
# 실제 현재 공인 IPv4를 입력합니다. 예약 주소나 0.0.0.0/0은 거부됩니다.
RANGE_PUBLIC_IP="실제_공인_IP"
python3 lab/attack-range/aws_plan.py prepare \
  --whitelist "$RANGE_PUBLIC_IP/32" \
  --region ap-northeast-2 \
  --lifecycle-mode manual --session-hours 168 \
  --windows-instance-type t3.medium \
  --aws-provider-version 6.68.0 \
  --vpc-module-version 6.7.3
```

`--region` only accepts `ap-northeast-2` or `eu-central-1`, or if omitted, it becomes `eu-central-1`. `manual` records manual cleanup goals from 1 to 168 hours. If you omit this optional argument, the existing `automatic`·4 hours·`t3.large` preparation will be used. Terraform fixes with `1.14.4`. Suppliers/modules also use the correct version, and source/variable hash changes are refused after preparation. `prepare` uses Python from the already installed official API image without a network to read YAML, but does not run Terraform or AWS APIs.

From the personal folder, run Terraform `init`, `validate`, read-only `plan -out` and `show -json` after authentication. Pre-planning uses a **local backend** so you can review it without importing SSH keys or creating an S3 state bucket. Seoul's manual plan passed these commands and a review of the AMI, security group, resource, and tag structures, and confirmed actual 8 vCPU execution after applying the same storage plan. Plans, status, variables, and full logs may contain passwords, so they are all stored in a Git-excluded folder and the contents are not made public.

```sh
python3 lab/attack-range/aws_plan.py validate-plan "$PRIVATE_PLAN_JSON" \
  --preparation "$PRIVATE_PREPARATION_JSON"
```

The inspection checks 3 servers, 1 gp3 total of 150 GiB, 1 NAT/EIP each, reception source, disk encryption, termination deletion, termination protection, ownership tag, and AMI root disk. Additional resources, changes to existing resources, unconfirmed prerequisites, and expiration plans are rejected. We leave the confirmed AMI ID and hash in the review record, but do not copy passwords or variable bodies. Since AMI inquiry uses the latest filter upstream, **the same reviewed saved plan must be applied** to use the confirmed AMI.

Official `build` create SSH keys and S3 backend first, then Terraform `init -upgrade` and apply directly. The official `build` does not automatically apply the plan reviewed by this tool. Review the plan of the actual account, confirm the selected operation and organization method, and apply the same saved plan.

## Optional 4-hour automatic shutdown device ready

The steps below are only to be used if you select automatic shutdown. Currently does not apply to one week manual operation.

[aws_ttl.py](../lab/attack-range/aws_ttl.py) creates a session's Lambda ZIP, IAM policy/trust document, and EventBridge Scheduler request material in a new, private folder. **Material creation does not perform AWS calls, authorization, or scheduled installation.** Account, region, UUID, and UTC expiration times must be exactly aligned with the plan.

[End Lambda](../lab/attack-range/aws_cleanup.py) only cleans up overdue resources where the account, region, UUID and ownership and expiration tags all match. Request EC2 termination, NAT deletion, and orphaned EIP/EBS deletion in order, and asynchronous deletion/partial failure is checked again in the next 5-minute cycle. A successful deletion request is not judged as completion of cleanup, and completion is recorded only when there are no remaining resources after rechecking. Preserves SSH keys and remote state if any paid resources are left behind or there are lookup errors.

Remote installation requires a dedicated execution role, a log group with 1 day of log retention, and a scheduling group. First, use `inspect` mode to verify account, function, and session matching and read-only bean queries, and check the scope of the execution role and actual delete permissions. The reservation starts after expiration, and there are 5-minute intervals, service execution delays, and NAT deletion delays, so it is not guaranteed that all costs will disappear at exactly 4 hours.

If you actually use the S3 backend, prepare normal Terraform destruction and private state backup first. Emergency cleanup can even delete past object versions/delete markers, so you shouldn't rely solely on remote buckets without local state for recovery. Lambda's EC2 family cleanup is limited to ownership and expiration tags, while S3 cleanup is limited to the exact session-specific bucket name, account, and expiration conditions. The roles, reservations, and logs of the free VPC resources and the termination device itself must then be organized through normal procedures.

```sh
python3 -m unittest discover -s lab/attack-range/tests
```

Unit verification uses mock SDK·plan. Even if it passes, it does not prove actual AWS login, IAM permissions, resource deletion, or cost caps.

## Execution account without termination device permissions

[aws_permissions.py](../lab/attack-range/aws_permissions.py) creates a controller policy and administrator role provisioning procedure specific to the exact ARN of the session. No AWS calls, policy uploads, or subject permission changes are made.

```sh
python3 lab/attack-range/aws_permissions.py \
  --session "$PRIVATE_TTL_SESSION_JSON" \
  --output "$PRIVATE_PERMISSIONS_DIR"
```

The administrator first creates two roles, Lambda and Scheduler, with a trust/execution policy for the TTL data. To the running account, we only add the full policy lookup for these two roles, `PassRole` per service, Lambda/log/scheduled installs for that session, and the exact EC2 vCPU quota lookup. The Run As account does not include permissions to create roles or modify policies. We also do not use the method of granting `AdministratorAccess` to existing accounts.

Record the specific order, role, and file name in `admin-instructions.txt` and `admin-roles-recipe.json` of the output. If the created policy exceeds the IAM user inline limit of 2,048 characters, the administrator must create and attach a customer managed policy. It doesn't overwrite existing roles and matches all trust policies, one expected inline policy, and no managed policy attachments. Additional permissions are not a substitute for actual IAM evaluation and remote termination device checks.

During development, we also ran IAM Policy Autopilot `0.3.0` to check static analysis. Passing a dynamic client/function reference in the exit code was missed and returned only one `s3:ListBucket` operation, so the result is not used for execution permission. Controller documentation was reviewed based on separately specified API operations and resource/condition support in the AWS Service Authorization Reference. The Autopilot reconsider command is as follows and does not upload any policy.

```sh
uvx iam-policy-autopilot@latest generate-policies \
  "$PWD/lab/attack-range/aws_cleanup.py" \
  --region ap-northeast-2 --account "$RANGE_ACCOUNT_ID" \
  --service-hints ec2 s3 sts \
  --tf-dir "$PWD/.local-runtime/attack-range/upstream/terraform/aws" \
  --pretty
```
