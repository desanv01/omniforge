# Local AWS certification and Seoul practice plan verification

At 2026-10-10 23:46 KST, we checked the local CLI profile that the user has already authenticated. I did not proceed with SSO login again. With existing authentication, only inquiry, planning, and dryrun were performed. **No cloud resources were created.**

| OK | Results |
| --- | --- |
| local CLI | AWS CLI `2.37.12`, macOS arm64 |
| Existing certification | STS `GetCallerIdentity` Success; No key value printing/copying |
| Target Region | Seoul `ap-northeast-2` |
| Legacy EC2 | View 0 running/standby instances |
| Terraform | `1.14.4`, AWS Provider `6.68.0`, VPC Module `6.7.3` |
| Actual init·validate·plan | Respectively exit code 0 |
| Physical Plan Structural Inspection | Passed, all managed changes plan to create new resources |
| EC2 Execution Permissions | `DryRunOperation` in request `DryRun=true`; Not actual execution/quota verification |
| End Role·Function·Reservation Search | Even the exact name of this session is `AccessDenied` |
| EC2 vCPU quota query | `servicequotas:GetServiceQuota` rejected; Not sure if 8 vCPUs are allowed |
| apply·import key·create S3·change IAM | Not done |

Plan includes 1 Router `t3.small`, 1 Splunk `t3.xlarge`, and 1 Windows `t3.large`. The gp3 root disk is 30·60·60 GiB, and the NAT Gateway and NAT EIP are 1 each. The public IP is connected only to the router, and SSH/WireGuard is currently limited to the public IP `/32`. We inspected EC2 and root EBS ownership/expiration tags, disk encryption/termination deletion, and disabling EC2 termination protection.

The actual plan JSON stored the searched AMI data in `prior_state`. We verified that the root EBS dictionary from the AWS provider is one, and the rest are explicit ephemeral mappings where EBS is empty. Match the checker to this actual output shape, but still reject additional EBS and unclear mappings. We also turned off default security group management for the VPC module. Each EC2 only uses dedicated security groups that have been reviewed separately, and does not treat unconfirmed default group rules as passing checks.

The AWS authentication file was attached to a one-time official Terraform container as read-only. There is no connection to the always-on management API. Saved plans, variables, passwords, logs, and account information are stored in the private `.local-runtime/` and are not included in this public record.

The next step is to prepare the shutdown roles and permissions for [AWS Preparation Plan](../attack-range-aws-plan.md), check the actual vCPU limit, and check the remote shutdown device. Even if the structural review and DryRun are successful, IAM, NAT, capacity, automatic termination, and cost caps have not been verified. After checking permissions and termination devices, you must apply only the same saved plan and proceed with host configuration and actual log collection.
