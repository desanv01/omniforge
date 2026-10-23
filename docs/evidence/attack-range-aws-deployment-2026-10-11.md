# AWS Attack Range Manual Operation Deployment History

Created AWS resources with user requested manual operational configuration for one week on 2026-10-11 KST. We used existing local CLI authentication and did not install IAM role, Lambda, or Scheduler for automatic shutdown. Only the public key was registered in AWS, and the secret key, password, and Terraform status were stored in a Git exclusion folder.

| OK | Actual Results |
| --- | --- |
| Region/Operation Method | Seoul `ap-northeast-2` cleaned up by users after a week |
| Preparation/Planning | Terraform `1.14.4`, Provider `6.68.0`, VPC Module `6.7.3`; init·validate·plan·structure check passed |
| Apply | Same saved plan confirmed by hash, apply exit code 0 |
| EC2 lookup | Router `t3.small`·Splunk `t3.xlarge`·Windows `t3.medium` 1 each `running`, total 8 vCPU |
| EBS inquiry | 3 root disks, 150 GiB total, all encrypted |
| network inquiry | 1 NAT Gateway `available`, 1 assigned EIP; Separate public IP for router only |
| Owned/Exited Goal Tags | EC2·EBS·NAT·EIP matches this session/plan end time/project |
| Router SSH | Connect with dedicated key, check Linux kernel |
| automatic shutdown | Not installed; Expiration tag does not trigger reservation termination |

In the previous [Certification/Basic Plan Verification](attack-range-aws-plan-2026-10-10.md), no resources were created. Afterwards, based on manual operation requests, we prepared, reviewed, and applied a new session that reduced Windows to 4 GiB. I don't have permission to look up EC2 quotas, but I did see an actual 8 vCPU running. This does not demonstrate the ability to create additional servers or full access to the service.

Based on the same published price list, the basic amount is `$9.4176` per day and `$65.9232` for 7 days. There is no bill cap including taxes, transfers, NAT throughput, T3 CPU excess credits, paid licenses, and LLM fees. Calculations and sources are in [AWS Operational Preparation Plan](../attack-range-aws-plan.md).

## Real host installation and log forwarding

Official role installation and separate verification were completed at 2026-10-11 00:27 KST. The Ansible exit codes for installation and final verification are 0, respectively, and we confirmed `failed=0` and `unreachable=0` in final verification on both hosts.

| OK | Actual Results |
| --- | --- |
| Splunk·Guacamole | Web HTTP 200; Guacamole New `admin` account authentication/connection list query successful, 1 Windows RDP connection |
| Windows Services | Running Sysmon·SplunkForwarder·WinRM, forwarding destination `10.0.2.10:9997` |
| Sysmon | Installed Version `15.22`, Authenticode `Valid`, Microsoft Publisher Verification; Installation File SHA256 Private Archive |
| Windows Audit | Enable process creation audit/command line recording |
| PowerShell | script block·invocation logging 활성화 |
| Atomic Red Team | Manifest check·absolute path import·`Invoke-AtomicTest` function preparation successful, module version `2.1.0` |
| Final endpoint inspection | All 15 conditions are true, no failure conditions |

I ran the harmless `cmd.exe /d /c "whoami & rem AEGIS_VERIFY_<고유값>"` on real Windows. The search requires a new marker for each run, the authenticated actual host name, and a UTC range from 10 seconds before the start of this verification to the time of each search run. It does not aggregate logs from previous runs instead. Splunk `index=win` separately requested events containing the same marker and `whoami` for each type and confirmed the following.

| Original log | Event ID | Actual number of collections |
| --- | ---: | ---: |
| Sysmon Operational | 1 | 2 |
| Windows Security | 4688 | 1 |
| PowerShell Operational | 4104 | 1 |

These four cases are **based on log collection/correlation of actual commands**. This is not a result of verifying successful attack, alert firing, detection accuracy, or AegisLoop's connection to cloud Splunk search. The official Windows role has removed the Microsoft Defender feature and is now `Installed=false` on hosts as well. Defender·EDR does not claim detection results.

## Reproduction range and private operating data

The official Attack Range source maintained `fc9b9e719d8835da0bbb5c20d46c52a9778d64e2`. The role was copied from the cache to a private folder in the next commit, and the original/cache was not modified.

- Splunk: `f1bf753a9bb24a9a752c19756a00e7e43662bcce`
- Guacamole: `af0b971a5c69e5d471aa1f3dc70770634dc85b7c`
- Windows: `b5d08da3a30dc1c7a185b163c828b20369382faf`

In the private executable, collecting Windows facts after waiting for connection, waiting for Linux cloud-init to complete, checking signatures before installing Sysmon·UF, hiding MSI password logs, and 4688 command line audit registry name correction were applied. Since the official installation path for the Atomic module is outside the general module search path, the simple list search was changed to a file·manifest·actual import·function preparation check. During installation, the Windows 10/11-only Defender condition was ignored once due to Ansible's strict boolean check on the server, but the subsequent Server-only removal and full installation were completed.

Pinning role commits and verifying the signature of an executable are separate things. Not all external Sysmon·Atomic downloads are fixed by commit or public expected hash, and SHA records are the basis for identification of used files.

Connection instructions, new password, SSH key, unique marker, original verification JSON, and status backup were stored in a folder excluding Git. We accessed Splunk, Guacamole, and Windows through a local SSH tunnel and did not open any additional public management ports. The private cleanup executable file was prepared to re-check the EC2·EBS·NAT·EIP residuals after Terraform destruction of the session. **Actual deletion has not yet been performed**, and the environment will be maintained as requested by the user.
