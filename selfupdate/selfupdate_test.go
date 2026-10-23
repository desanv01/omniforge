package selfupdate

import (
	"archive/zip"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// testPaths 造一个隔离的升级目录。不能直接用 ResolvePaths()——那会指向测试
// 二进制本身，一跑就把 go test 的可执行文件改名了。
func testPaths(t *testing.T) Paths {
	t.Helper()
	dir := t.TempDir()
	return Paths{
		Dir:     dir,
		Current: filepath.Join(dir, "omniforge"),
		New:     filepath.Join(dir, "omniforge.new"),
		Sum:     filepath.Join(dir, "omniforge.new.sha256"),
		Old:     filepath.Join(dir, "omniforge.old"),
		Marker:  filepath.Join(dir, "omniforge.upgrade.json"),
	}
}

// fakeBin 写一个可执行的壳脚本冒充 omniforge。smokeTest 只是用 -h 拉起它看退出码，
// 脚本完全够用，而且比编译一个真二进制快得多。
func fakeBin(t *testing.T, path, marker string, exitCode int) {
	t.Helper()
	script := "#!/bin/sh\necho " + marker + "\nexit " + itoa(exitCode) + "\n"
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatalf("Write fake binary %s: %v", path, err)
	}
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	return string(rune('0' + n))
}

// stage 把 bin 布置成"已暂存待换装"的样子：写好 omniforge.new 和它的校验和。
func stage(t *testing.T, p Paths, marker string, exitCode int) {
	t.Helper()
	fakeBin(t, p.New, marker, exitCode)
	sum, err := fileSHA256(p.New)
	if err != nil {
		t.Fatalf("Calculate checksum: %v", err)
	}
	if err := os.WriteFile(p.Sum, []byte(sum), 0o644); err != nil {
		t.Fatalf("Write checksum: %v", err)
	}
}

func readAll(t *testing.T, path string) string {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("Read %s: %v", path, err)
	}
	return string(b)
}

func requireUnix(t *testing.T) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("The fake binary uses sh script and cannot run on Windows.")
	}
}

func TestCompareVersions(t *testing.T) {
	cases := []struct {
		a, b       string
		want       int
		comparable bool
	}{
		{"0.3.7", "0.3.8", -1, true},
		{"0.3.8", "0.3.7", 1, true},
		{"0.3.7", "0.3.7", 0, true},
		{"v0.3.7", "0.3.8", -1, true}, // build.sh 去掉 v，tag 带 v，两边都要认
		{"0.3.7", "v0.3.7", 0, true},
		{"0.9.0", "0.10.0", -1, true}, // 按数字比而不是字典序
		{"1.0.0", "0.99.99", 1, true},
		// 开发构建必须判为不可比较，否则会被正式版覆盖掉未提交的改动。
		{"dev", "0.3.8", 0, false},
		{"0.3.7-2-gabc1234", "0.3.8", 0, false},
		{"0.3.7-dirty", "0.3.8", 0, false},
		{"0.3", "0.3.8", 0, false},
		{"", "0.3.8", 0, false},
	}
	for _, c := range cases {
		got, ok := CompareVersions(c.a, c.b)
		if ok != c.comparable {
			t.Errorf("CompareVersions(%q,%q) comparable=%v, expected %v", c.a, c.b, ok, c.comparable)
			continue
		}
		if ok && got != c.want {
			t.Errorf("CompareVersions(%q,%q)=%d, expect %d", c.a, c.b, got, c.want)
		}
	}
}

func TestResolvePathsNaming(t *testing.T) {
	p, err := ResolvePaths()
	if err != nil {
		t.Fatalf("ResolvePaths: %v", err)
	}
	// 关键不变量：所有升级文件都和可执行文件同目录。落到 CWD 会让服务化运行
	// （工作目录可能是 /）时的换装彻底失效。
	for name, path := range map[string]string{"New": p.New, "Sum": p.Sum, "Old": p.Old, "Marker": p.Marker} {
		if filepath.Dir(path) != p.Dir {
			t.Errorf("%s is not in the executable directory: %s (expected %s)", name, path, p.Dir)
		}
	}
	// Windows 上 .new/.old 必须保留 .exe，否则冒烟测试和换装后的执行都会失败。
	if runtime.GOOS == "windows" {
		if !strings.HasSuffix(p.New, ".exe") || !strings.HasSuffix(p.Old, ".exe") {
			t.Errorf("On Windows .new/.old must end with .exe: new=%s old=%s", p.New, p.Old)
		}
	}
}

func TestVerifyStagedRejectsTamperedBinary(t *testing.T) {
	requireUnix(t)
	p := testPaths(t)
	stage(t, p, "new", 0)

	// 校验和写好之后再改动文件，模拟下载损坏 / 被掉包。
	fakeBin(t, p.New, "tampered", 0)
	if err := verifyStaged(p); err == nil {
		t.Fatal("Expected SHA256 mismatch to be rejected, passed instead")
	}
}

func TestVerifyStagedRejectsUnrunnableBinary(t *testing.T) {
	requireUnix(t)
	p := testPaths(t)
	stage(t, p, "broken", 1) // 能执行但退出码非 0

	if err := verifyStaged(p); err == nil {
		t.Fatal("Expected smoke test to fail and be rejected, but passed")
	}
}

func TestApplyStagedHappyPath(t *testing.T) {
	requireUnix(t)
	p := testPaths(t)
	fakeBin(t, p.Current, "old", 0)
	stage(t, p, "new", 0)
	if err := writeMarker(p.Marker, marker{From: "0.3.7", To: "0.3.8"}); err != nil {
		t.Fatalf("Write mark: %v", err)
	}

	action, st := applyStaged(p)
	if action != Restart {
		t.Fatalf("Expected Restart, got %v", action)
	}
	if !st.Pending {
		t.Error("After the change, the status should be Pending.")
	}
	if !strings.Contains(readAll(t, p.Current), "new") {
		t.Error("omniforge should have been replaced with the new version")
	}
	if !strings.Contains(readAll(t, p.Old), "old") {
		t.Error("Old versions should be backed up to omniforge.old")
	}
	if _, err := os.Stat(p.New); !os.IsNotExist(err) {
		t.Error("omniforge.new should disappear after the change.")
	}
	if _, err := os.Stat(p.Sum); !os.IsNotExist(err) {
		t.Error("The checksum file should be cleaned after the replacement")
	}
	// 标记必须留着，下一次启动（跑的是新版）靠它计数、必要时回滚。
	if _, ok := readMarker(p.Marker); !ok {
		t.Error("The upgrade mark should be retained after the change of equipment.")
	}
}

func TestApplyStagedKeepsCurrentWhenVerifyFails(t *testing.T) {
	requireUnix(t)
	p := testPaths(t)
	fakeBin(t, p.Current, "old", 0)
	stage(t, p, "new", 0)
	fakeBin(t, p.New, "tampered", 0) // 破坏校验和

	action, st := applyStaged(p)
	if action != Continue {
		t.Fatalf("Expect Continue when verification fails and get %v", action)
	}
	if !st.FailedStage {
		t.Error("The status should be marked as FailedStage")
	}
	if !strings.Contains(readAll(t, p.Current), "old") {
		t.Fatal("When verification fails, the current version must not be touched.")
	}
	if _, err := os.Stat(p.New); !os.IsNotExist(err) {
		t.Error("The temporary files that failed the verification should be cleared, otherwise the next startup will try again.")
	}
}

func TestSwapOverwritesPreviousBackup(t *testing.T) {
	requireUnix(t)
	p := testPaths(t)
	fakeBin(t, p.Current, "v2", 0)
	fakeBin(t, p.Old, "v1", 0) // 上一轮升级留下的备份
	stage(t, p, "v3", 0)

	if err := swap(p); err != nil {
		t.Fatalf("swap: %v", err)
	}
	if !strings.Contains(readAll(t, p.Current), "v3") {
		t.Error("Should switch to v3")
	}
	if !strings.Contains(readAll(t, p.Old), "v2") {
		t.Error("The backup should be updated to the v2 that was just replaced")
	}
}

func TestConfirmCountsAttemptsThenRollsBack(t *testing.T) {
	requireUnix(t)
	p := testPaths(t)
	fakeBin(t, p.Current, "broken-new", 0)
	fakeBin(t, p.Old, "good-old", 0)
	m := marker{From: "0.3.7", To: "0.3.8"}

	// 前 maxAttempts 次启动只累计计数，让新版有机会自己站稳。
	for i := 1; i <= maxAttempts; i++ {
		action, st := confirmOrRollback(p, m)
		if action != Continue {
			t.Fatalf("The %dth attempt expected Continue and got %v", i, action)
		}
		if !st.Pending {
			t.Errorf("The %dth attempt status should be Pending", i)
		}
		got, ok := readMarker(p.Marker)
		if !ok || got.Attempts != i {
			t.Fatalf("After %d attempts attempts=%d (ok=%v), expect %d", i, got.Attempts, ok, i)
		}
		m = got
	}

	// 再崩一次就超限，自动把旧版换回来。
	action, st := confirmOrRollback(p, m)
	if action != Restart {
		t.Fatalf("Restart is expected when the upper limit of attempts is exceeded, and %v is obtained.", action)
	}
	if !st.RolledBack {
		t.Error("The status should be marked as RolledBack")
	}
	if !strings.Contains(readAll(t, p.Current), "good-old") {
		t.Fatal("Should have been rolled back to the older version")
	}
	if _, err := os.Stat(p.Marker); !os.IsNotExist(err) {
		t.Error("The mark should be cleared after rollback, otherwise it will rollback infinitely")
	}
	// 起不来的那个版本留作排查，不直接删。
	if _, err := os.Stat(p.Current + ".failed"); err != nil {
		t.Error("Failed versions should be retained as .failed for troubleshooting")
	}
}

func TestManualRollbackIsReversible(t *testing.T) {
	requireUnix(t)
	p := testPaths(t)
	fakeBin(t, p.Current, "v2", 0)
	fakeBin(t, p.Old, "v1", 0)

	// Rollback() 走 ResolvePaths()，这里直接测底层的交换语义。
	tmp := p.Current + ".swap"
	if err := os.Rename(p.Current, tmp); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(p.Old, p.Current); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(tmp, p.Old); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(readAll(t, p.Current), "v1") {
		t.Error("After rollback the current version should be v1")
	}
	if !strings.Contains(readAll(t, p.Old), "v2") {
		t.Error("After the rollback, the backup should be v2 so that you can roll back again.")
	}
}

func TestParseSums(t *testing.T) {
	const (
		linuxSum = "1111111111111111111111111111111111111111111111111111111111111111"
		winSum   = "ABCDEF0000000000000000000000000000000000000000000000000000000000"
	)
	// sha256sum 输出是双空格分隔；shasum -a 256 在二进制模式下会给文件名加 *。
	raw := linuxSum + "  omniforge-0.3.8-linux-amd64.zip\n" +
		winSum + " *omniforge-0.3.8-windows-amd64.zip\n" +
		"\n" +
		"garbage line\n" + // 恰好两个字段，但第一个不是摘要
		"deadbeef  omniforge-0.3.8-darwin-arm64.zip\n" // 摘要长度不对

	out := parseSums(raw)
	if out["omniforge-0.3.8-linux-amd64.zip"] != linuxSum {
		t.Errorf("linux entry parsing error: %v", out)
	}
	// 摘要统一小写，比对时才不会因大小写误判为不匹配。
	if got := out["omniforge-0.3.8-windows-amd64.zip"]; got != strings.ToLower(winSum) {
		t.Errorf("Windows entry error (* prefix should be stripped, summary should be converted to lowercase): %q", got)
	}
	if len(out) != 2 {
		t.Errorf("Empty lines, non-summary lines, and lines of incorrect length should be ignored, resulting in %v", out)
	}
}

func TestExtractBinaryFindsNestedEntry(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("The base name in the package is omniforge.exe on Windows, and this use case is constructed according to Unix naming")
	}
	dir := t.TempDir()
	zipPath := filepath.Join(dir, "release.zip")

	f, err := os.Create(zipPath)
	if err != nil {
		t.Fatal(err)
	}
	zw := zip.NewWriter(f)
	// 真实发布包的结构：omniforge-<版本>-<os>-<arch>/omniforge，外加若干干扰文件。
	for name, body := range map[string]string{
		"omniforge-0.3.8-linux-amd64/README.md":           "readme",
		"omniforge-0.3.8-linux-amd64/skills/a.md":         "skill",
		"omniforge-0.3.8-linux-amd64/omniforge":           "#!/bin/sh\nexit 0\n",
		"omniforge-0.3.8-linux-amd64/config.example.json": "{}",
	} {
		w, err := zw.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := w.Write([]byte(body)); err != nil {
			t.Fatal(err)
		}
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	f.Close()

	dst := filepath.Join(dir, "out")
	if err := extractBinary(zipPath, dst); err != nil {
		t.Fatalf("extractBinary: %v", err)
	}
	if got := readAll(t, dst); !strings.Contains(got, "exit 0") {
		t.Errorf("The unzipped file is not an omniforge executable file: %q", got)
	}
	info, err := os.Stat(dst)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm()&0o111 == 0 {
		t.Error("The decompressed binary must have an execution bit")
	}
}

func TestExtractBinaryMissingEntry(t *testing.T) {
	dir := t.TempDir()
	zipPath := filepath.Join(dir, "release.zip")
	f, err := os.Create(zipPath)
	if err != nil {
		t.Fatal(err)
	}
	zw := zip.NewWriter(f)
	w, _ := zw.Create("omniforge-0.3.8-linux-amd64/README.md")
	_, _ = w.Write([]byte("readme"))
	_ = zw.Close()
	f.Close()

	if err := extractBinary(zipPath, filepath.Join(dir, "out")); err == nil {
		t.Fatal("An error should be reported when there is no executable file in the package.")
	}
}

func TestCheckURLRejectsNonGitHub(t *testing.T) {
	bad := []string{
		"http://github.com/x",            // 非 HTTPS
		"https://evil.com/omniforge.zip", // 域名不在白名单
		"https://github.com.evil.com/x",  // 后缀伪装
		"https://raw.githubusercontent.com.evil.com/x",
	}
	for _, raw := range bad {
		u := mustParse(t, raw)
		if err := checkURL(u); err == nil {
			t.Errorf("checkURL(%q) should be rejected", raw)
		}
	}
	good := []string{
		"https://api.github.com/repos/x/releases/latest",
		"https://objects.githubusercontent.com/blah",
		"https://GitHub.com/x", // 域名大小写不敏感
	}
	for _, raw := range good {
		u := mustParse(t, raw)
		if err := checkURL(u); err != nil {
			t.Errorf("checkURL(%q) should be allowed, but an error is reported: %v", raw, err)
		}
	}
}

func TestAssetNameMatchesBuildScript(t *testing.T) {
	// build.sh 的 package_binary 用的是 omniforge-<版本>-<os>-<arch>.zip，且版本号
	// 去掉了 v 前缀。这里对错一个字符，所有平台的一键更新都会找不到资产。
	if got := AssetName("v0.3.8", "linux", "amd64"); got != "omniforge-0.3.8-linux-amd64.zip" {
		t.Errorf("AssetName = %q", got)
	}
	if got := AssetName("0.3.8", "windows", "amd64"); got != "omniforge-0.3.8-windows-amd64.zip" {
		t.Errorf("AssetName = %q", got)
	}
}

func mustParse(t *testing.T, raw string) *url.URL {
	t.Helper()
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatalf("Analysis %q: %v", raw, err)
	}
	return u
}

func TestSettleClearsMarkerAndStopsRollback(t *testing.T) {
	requireUnix(t)
	p := testPaths(t)
	fakeBin(t, p.Current, "new", 0)
	fakeBin(t, p.Old, "old", 0)
	if err := writeMarker(p.Marker, marker{From: "0.3.7", To: "0.3.8", Attempts: 2}); err != nil {
		t.Fatal(err)
	}

	settle(p)

	if _, err := os.Stat(p.Marker); !os.IsNotExist(err) {
		t.Fatal("After confirming stability, the upgrade mark must be cleared.")
	}
	// 标记没了，后续正常重启就不会再累计次数、也不会误触发回滚。
	if _, ok := readMarker(p.Marker); ok {
		t.Error("Tag read should fail")
	}
	// 备份要留着，用户还能手动回滚。
	if _, err := os.Stat(p.Old); err != nil {
		t.Error("After confirming that it is stable, you should still keep the backup of the previous version.")
	}
}

func TestSettleIsNoopWithoutMarker(t *testing.T) {
	requireUnix(t)
	p := testPaths(t)
	fakeBin(t, p.Current, "cur", 0)
	settle(p) // 普通启动路径，不该 panic 也不该动任何文件
	if _, err := os.Stat(p.Current); err != nil {
		t.Error("settle should not affect any files when unmarked")
	}
}
