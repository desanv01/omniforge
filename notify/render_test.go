package notify

import (
	"strings"
	"testing"
	"unicode/utf8"
)

func TestTruncateBytesKeepsValidUTF8(t *testing.T) {
	// 这是本包最要紧的一条不变量。企微按**字节**限长，中文 3 字节/字，
	// 任何按字节硬切的实现都会把汉字切成半个，产出非法 UTF-8 而被平台拒收。
	// 用长度互质的多种中英混排输入去撞每一个可能的切点。
	inputs := []string{
		"Chinese test content",
		"mixed mixed content content",
		"a Chinese b Chinese c test d test e",
		"🔴🟠🟡🔵", // 4 字节 emoji，切错更明显
		strings.Repeat("loopholes", 100),
	}
	for _, in := range inputs {
		for max := 1; max <= len(in)+2; max++ {
			got := TruncateBytes(in, max)
			if !utf8.ValidString(got) {
				t.Fatalf("Input %q max=%d: output illegal UTF-8 %q", in, max, got)
			}
			if len(got) > max {
				t.Fatalf("Input %q max=%d: Result %d bytes exceed the upper limit", in, max, len(got))
			}
			// 未被截断时不得改动内容。
			if len(in) <= max && got != in {
				t.Fatalf("Input %q max=%d: The content is changed without exceeding the limit -> %q", in, max, got)
			}
		}
	}
}

func TestTruncateBytesZeroMeansUnlimited(t *testing.T) {
	long := strings.Repeat("x", 10000)
	if got := TruncateBytes(long, 0); got != long {
		t.Fatal("max=0 should mean no limit")
	}
	if got := TruncateBytes(long, -5); got != long {
		t.Fatal("max<0 should mean no limit")
	}
}

func TestTruncateBytesEllipsisBudget(t *testing.T) {
	// max 小于省略号本身时，不能因为追加省略号而反过来超限。
	got := TruncateBytes("abcdefgh", 1)
	if len(got) > 1 {
		t.Fatalf("When max=1, the result %q length %d exceeds the limit", got, len(got))
	}
	// 正常情况应带省略号。
	if got := TruncateBytes("abcdefgh", 5); !strings.HasSuffix(got, ellipsis) {
		t.Fatalf("Expected ellipsis, got %q", got)
	}
}

func TestTruncateRunesCountsCharactersNotBytes(t *testing.T) {
	// 与 TruncateBytes 的口径差异必须保留：Telegram 按字符限长，
	// 用字节口径会把中文消息切到只剩三分之一。
	s := "One, two, three, four, five, six, seven, eight, ninety"
	got := TruncateRunes(s, 5)
	if n := utf8.RuneCountInString(got); n != 5 {
		t.Fatalf("Expected 5 characters, got %d (%q)", n, got)
	}
	// 同样的字符串按字节口径应明显更短。
	if utf8.RuneCountInString(TruncateBytes(s, 5)) >= 5 {
		t.Fatal("Byte caliber should not produce the same number of characters as character caliber")
	}
}

func TestOneLineCollapsesWhitespace(t *testing.T) {
	got := OneLine("first line\n\nSecond line with tabs and multiple spaces", 0)
	if strings.ContainsAny(got, "\n\t") {
		t.Fatalf("All whitespace should be collapsed, resulting in %q", got)
	}
	if strings.Contains(got, "  ") {
		t.Fatalf("Consecutive spaces should not be preserved, resulting in %q", got)
	}
	// 截断后仍须可读且合法。
	got = OneLine("One, two, three, four, five, six, seven, eight, ninety", 4)
	if n := utf8.RuneCountInString(got); n != 4 {
		t.Fatalf("Expected 4 characters, got %d (%q)", n, got)
	}
}

func TestTruncateHTMLNeverCutsTagInHalf(t *testing.T) {
	// 直接截断 HTML 会切出 `<a href="htt` 这种残片，平台会拒收整条消息。
	s := "<b>Title</b>TextTextText <a href=\"https://example.com/very/long/path\">View details</a>"
	for max := 1; max <= utf8.RuneCountInString(s)+2; max++ {
		got := TruncateHTML(s, max)
		if n := utf8.RuneCountInString(got); max > 0 && n > max {
			t.Fatalf("max=%d: Result %d character exceeds limit", max, n)
		}
		// 尾部不能有未闭合的 `<`（即最后一段里出现 `<` 却无 `>`）。
		if lt := strings.LastIndex(got, "<"); lt >= 0 && !strings.Contains(got[lt:], ">") {
			t.Fatalf("max=%d: The tail label is cut off -> %q", max, got)
		}
	}
}

func TestAssetLineOmitsExcess(t *testing.T) {
	if got := assetLine(nil, 3); got != "" {
		t.Fatalf("If there is no asset, an empty string should be returned and %q is obtained.", got)
	}
	if got := assetLine([]string{"a", "b"}, 3); got != "a, b" {
		t.Fatalf("All items that have not exceeded the limit should be listed, and %q is obtained.", got)
	}
	// 超出上限时必须标注总数，否则读者不知道还有多少资产没列出来。
	got := assetLine([]string{"a", "b", "c", "d", "e"}, 2)
	if !strings.Contains(got, "5 total") {
		t.Fatalf("The total number should be 5, resulting in %q", got)
	}
}

func TestSeverityAndStatusLabels(t *testing.T) {
	if AtLeast("", "low") {
		t.Fatal("Empty level ordinal is 0 and should be blocked by any threshold")
	}
	if !AtLeast("critical", "") {
		t.Fatal("Empty threshold should be released")
	}
	if got := StatusLabel("fixed"); got != "Fixed" {
		t.Fatalf("Unknown state mapping, get %q", got)
	}
	// 未知状态原样回显，不臆造标签。
	if got := StatusLabel("weird_status"); got != "weird_status" {
		t.Fatalf("The unknown status should be echoed as is, getting %q", got)
	}
}

// TestTruncateHTMLNeverCutsEntity 覆盖审计指出的一处遗漏：截断不只要避开
// 半截标签，还要避开被切断的 HTML 实体。
//
// `&amp;` 被切成 `&amp` 之后，一个只认实体的解析器可能拒收**整条**消息——
// 而超长汇总消息本来就常见，代价太大。
func TestTruncateHTMLNeverCutsEntity(t *testing.T) {
	s := "aaaa&amp;bbbb&lt;cccc&quot;dddd"
	for max := 1; max <= utf8.RuneCountInString(s)+2; max++ {
		got := TruncateHTML(s, max)
		// 尾部不得出现「有 & 但没有对应 ;」的实体残片。
		if amp := strings.LastIndex(got, "&"); amp >= 0 && !strings.Contains(got[amp:], ";") {
			t.Fatalf("max=%d: leaving physical fragments %q at the tail", max, got[amp:])
		}
		if strings.Contains(got, "&amp\x00") {
			t.Fatalf("max=%d: Deformed entity appears", max)
		}
	}
}
