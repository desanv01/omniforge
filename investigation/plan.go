package investigation

import (
	"regexp"
	"strings"
)

// BuildPlan uses documented templates. Finding text only selects a family; it
// cannot issue instructions, introduce new URLs, or establish an attack fact.
func BuildPlan(f FindingContext) Plan {
	text := strings.ToLower(f.Name + " " + f.VulnClass + " " + f.Summary)
	family := "generic"
	switch {
	case containsAny(text, "ssrf", "server-side request", "server side request", "Server-side request"):
		family = "ssrf"
	case containsAny(text, "remote code", "command injection", "code execution", "run command", "Insert command") || regexp.MustCompile(`\brce\b`).MatchString(text):
		family = "code_execution"
	case containsAny(text, "authentication", "credential", "Authentication bypass", "Authentication failed", "account takeover", "brute force"):
		family = "authentication"
	case containsAny(text, "information", "disclosure", "exposure", "directory", "listing", "information exposure", "Information exposure", "listing", "file exposure", "/ftp"):
		family = "information_exposure"
	}
	refs := []Reference{
		{Title: "CTID Vulnerability Mapping Methodology", URL: "https://ctid.mitre.org/mappings/about/methodology/cve-methodology/"},
		{Title: "NIST SP 800-61r3", URL: "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-61r3.pdf"},
	}
	base := Hypothesis{ID: "path_access", Title: "Vulnerable path access traces", Statement: "Vulnerable paths may have been requested during the investigation. Access records alone do not confirm successful exploitation or compromise.", Preconditions: []string{"Check whether the vulnerability existed in the relevant asset/path at the time of investigation"}, RequiredLogs: []string{"Web server or reverse proxy request log"}, RequiredFields: []string{"time", "target asset", "request path"}, Hunt: "Finds requests that match selected assets, time periods, and paths, and displays known ARTEX verification requests separately.", BenignAlternatives: []string{"Normal access by administrators and users", "Approved Vulnerability Checks", "Search engine or monitoring requests"}, NextSteps: []string{"Check whether you were exposed at the time and access control settings", "Comparison of the method/session/response of the original request with the approved maintenance schedule"}, References: refs}
	hs := []Hypothesis{base}
	switch family {
	case "information_exposure":
		hs = append(hs, Hypothesis{ID: "multi_path", Title: "Request flow for multiple subfiles", Statement: "Multiple subpaths may have been requested in a short period of time from the same session or origin of the same log source. Same IP does not mean same attacker.", Preconditions: []string{"Multiple files or sub-resources exist in target path", "Session or origin field exists in actual request log"}, RequiredLogs: []string{"Web request logs by path", "Transmission completion/response byte log"}, RequiredFields: []string{"time", "request path", "Session or departure point", "target asset"}, Hunt: "Check whether at least two different sub-paths are observed within 10 minutes from the same file source/session (or origin if not present). Alert duplicates are not counted as requests.", BenignAlternatives: []string{"Loading of multiple resources in normal browser", "Shared proxy/NAT", "Permitted collection/backup operations"}, NextSteps: []string{"Check requested file content and sensitivity", "Determine the actual delivery range by checking transmission completion, bytes, and authentication status"}, References: refs}, Hypothesis{ID: "exposed_credentials", Title: "Whether the exposed information is subsequently exploited", Statement: "If the exposed file actually contained credentials that were valid at the time, subsequent use of that account may need to be investigated.", Preconditions: []string{"Verify credentials from actual contents of exposed files", "Verify that the credentials were valid at the time of the investigation", "Obtain account identifier and authentication log"}, RequiredLogs: []string{"File contents at the time or archived copy", "Authentication/Account Audit Log"}, RequiredFields: []string{"account", "Certification time", "Certification Results", "session", "origin"}, Hunt: "Match logins and permission changes against verified accounts. We do not assume account takeover based solely on information exposure or the same IP address.", BenignAlternatives: []string{"Normal use by account holder", "Example Credentials Already Retired"}, NextSteps: []string{"Secure file archives and authentication logs", "Verify approval of activity with account representative"}, References: refs})
	case "authentication":
		hs = append(hs, Hypothesis{ID: "account_misuse", Title: "Investigation of authentication bypass and account use", Statement: "If the authentication vulnerability was actually exploited, traces of session issuance and permission use that differ from the normal authentication flow may remain.", Preconditions: []string{"Check weak authentication paths and necessary conditions", "Secure account/session audit logs"}, RequiredLogs: []string{"Authentication success/failure log", "Session issuance and permission change logs"}, RequiredFields: []string{"account", "session", "time", "Certification Results", "authority"}, Hunt: "We compare vulnerable path requests and account activity with actual session and account identifiers and check whether they are approved.", BenignAlternatives: []string{"Normal login retry", "SSO/Service Account Activity"}, NextSteps: []string{"After securing the authentication log, check the account representative", "Comparison of approval records for permission changes"}, References: refs})
	case "code_execution":
		hs = append(hs, Hypothesis{ID: "host_execution", Title: "Follow-up process/continuity trace investigation", Statement: "If the code is actually running on the server, you should examine the web process subprocesses and file and network activity.", Preconditions: []string{"Check execution conditions and affected servers", "Obtain host audit or EDR materials"}, RequiredLogs: []string{"EDR·Process creation log", "File change/network connection log"}, RequiredFields: []string{"host", "process id", "parent process", "command line", "time"}, Hunt: "The web process's child processes, files, and external connections are matched against the host identifier. The HTTP response does not confirm successful code execution.", BenignAlternatives: []string{"Execute normal external commands from your application", "Distribution, backup, management tasks"}, NextSteps: []string{"Secure EDR/host original evidence", "Deployment and administrator action history comparison"}, References: refs})
	case "ssrf":
		hs = append(hs, Hypothesis{ID: "server_egress", Title: "Investigate subsequent requests on the server side", Statement: "If server-side request solicitation actually occurred, you can examine the history of the connection coming from the server and the destination of the request.", Preconditions: []string{"Check for vulnerable requests and server identifiers", "Obtain server departure connection data"}, RequiredLogs: []string{"Server DNS, proxy, network transmission log", "Request target service access log"}, RequiredFields: []string{"departure host", "destination", "time", "Request ID or process"}, Hunt: "Matches input requests and server-sent events by request ID, process, and time. Temporal proximity alone does not determine causality.", BenignAlternatives: []string{"Normal URL preview/webhook", "Regular server-to-server communication"}, NextSteps: []string{"Obtain transmission and destination audit logs", "Verification of actual response and access control of sensitive subjects"}, References: refs})
	default:
		hs = append(hs, Hypothesis{ID: "impact_review", Title: "Manual investigation of vulnerability impact and subsequent actions", Statement: "Subsequent attacks cannot be determined from the current classification. After checking the vulnerability establishment conditions and impact, select the required log.", Preconditions: []string{"Check the actual conditions for the vulnerability and the status of the asset at the time"}, RequiredLogs: []string{"Application audit log", "Authentication or host logs depending on impact"}, RequiredFields: []string{"asset", "time", "Request/Session/Account Identifier"}, Hunt: "Obtain data to link observation requests to actual impacts.", BenignAlternatives: []string{"Use normal functions", "approved tests"}, NextSteps: []string{"Determine the scope of impact of vulnerabilities", "Specify required logs and fields"}, References: refs})
	}
	return Plan{EngineVersion: EngineVersion, Method: "Evidence-based conditional investigation template", Family: family, Summary: "Investigate expected attack vectors and observed behavior separately. Subsequent abuse is judged only upon establishing conditions and separate evidence.", Hypotheses: hs, Limitations: []string{"This plan is an investigation template tailored to a vulnerability classification and is not an LLM analysis or actual breach determination.", "The time of vulnerability discovery and past vulnerability status may vary.", "Automatic analysis addresses destination/path access and limited multi-path request flows. Authentication, host, and transmission correlation analysis requires manual review."}}
}
func containsAny(s string, values ...string) bool {
	for _, v := range values {
		if strings.Contains(s, v) {
			return true
		}
	}
	return false
}
