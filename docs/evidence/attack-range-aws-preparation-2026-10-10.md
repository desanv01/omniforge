# Attack Range Verification of settings before AWS deployment

At 2026-10-10 23:32 KST, the private Terraform setup of [AWS Lab Preparation Plan](../attack-range-aws-plan.md) was verified in local Docker. This is not the result of AWS account authentication, actual plan inquiry, or server creation.

| Item | Verification result |
| --- | --- |
| Official Source | `fc9b9e719d8835da0bbb5c20d46c52a9778d64e2`; No change to upstream checkout |
| launch image | `aegis-attack-range-api:fc9b9e719d88` built from existing official sources |
| Terraform | `1.14.4` fixed |
| AWS Provider | `6.68.0` fixed, check lock file |
| VPC module | Fixed `6.7.3`, check installation metadata |
| Real `init -backend=false` | exit code 0 |
| Real `validate` | exit code 0 |
| Integrity after preparation | Source/variable hash and supplier/module version verification passed |
| unit verification | 15 management tools, 22 plan reviews, 17 exit devices: 54 total passed |
| Use AWS Authentication·plan·apply | Not done |
| Remote IAM·Lambda·Scheduled installation | Not done |

Provider lock file SHA-256: `9f622bef5bc604bdf62031c114aa905713d8d479e3f9d52e48bb3bb076a3a65a`.

In the first real init, I found and corrected an HCL syntax error in the provider declaration and then revalidated it with the new personal settings. Existing personal folders were not overwritten, and all settings, passwords, logs, and planning materials were stored only in `.local-runtime/`, which is excluded from Git. The current public IP was checked with the official AWS verification service and used for the `/32` limit and was not included in the public record. I have not attached the AWS authentication folder to that container.

Unit validation checks for other accounts, sessions, expiration tags, public reception, additional resources, disk conditions, EC2 termination protection, indeterminate plans, asynchronous deletes, partial failures, and delete upper bounds. Lambda input/IAM/reservation data were reviewed statically, but **unit inspection and Terraform configuration verification alone do not guarantee actual resource deletion, IAM permissions, or cost caps.** After authenticating the actual account, you must proceed with read-only plan, check remote termination device, apply the same saved plan, and configure host and collect logs.

Related codes: [Plan Preparation/Review](../../lab/attack-range/aws_plan.py), [Create Closing Materials](../../lab/attack-range/aws_ttl.py), [Termination Lambda](../../lab/attack-range/aws_cleanup.py).
