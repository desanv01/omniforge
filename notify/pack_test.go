package notify

import (
	"strings"
	"testing"
	"unicode/utf8"
)

// 本文件覆盖「按整条打包」这个修复：汇总消息超出渠道长度上限时，必须**按整条**
// 截断并把没装下的条目数如实报出来，让调用方只标记真正送达的那些。
//
// 之前的做法是渲染完整篇再截断、然后整批标记已送达：消息后半截凭空消失，
// 而投递历史显示全部成功——漏洞就这么没了，且没有任何地方能发现。

func TestMarkdownBodyPacksWholeItemsWithinByteLimit(t *testing.T) {
	// 200 条中文汇总，必然远超企微 4096 字节。
	m := batchMsg(200)
	body, kept := markdownBody(m, weComMarkdownLimit)

	if len(body) > weComMarkdownLimit {
		t.Fatalf("Text %d Bytes exceed the upper limit %d", len(body), weComMarkdownLimit)
	}
	if !utf8.ValidString(body) {
		t.Fatal("The body text is not legal UTF-8")
	}
	if kept <= 0 || kept >= len(m.Items) {
		t.Fatalf("Only part of it should be loaded (0 < kept < %d), resulting in %d", len(m.Items), kept)
	}
	// 头部必须如实说明本条只包含多少条、其余有多少条——否则读者会把头部
	// 那个数字当成全部。
	if !strings.Contains(body, "remain") || !strings.Contains(body, "in the next message") {
		t.Fatalf("The header should indicate how many items are not included in this article:\n%s", body[:minInt(400, len(body))])
	}
	// 只应包含前 kept 条。
	for i := 0; i < kept; i++ {
		if !strings.Contains(body, m.Items[i].Name) {
			t.Fatalf("Item %d should be in this message:\n%s", i+1, body)
		}
	}
	if strings.Contains(body, m.Items[kept].Name) {
		t.Fatalf("Item %d should not be there (it belongs to the next batch)", kept+1)
	}
}

func TestMarkdownBodyKeepsEverythingWhenUnderLimit(t *testing.T) {
	m := batchMsg(3)
	body, kept := markdownBody(m, 0) // 0 = 不限制
	if kept != len(m.Items) {
		t.Fatalf("If the length is not limited, all should be kept, and we get kept=%d", kept)
	}
	if strings.Contains(body, "the remaining") {
		t.Fatalf("The truncation prompt should not appear when there is no truncation:\n%s", body)
	}
}

func TestMarkdownBodyAlwaysKeepsAtLeastOneItem(t *testing.T) {
	// 预算小到连一条都装不下时，仍要发出一条（由最终截断兜底）。
	// 否则一条超长漏洞会把整批永久卡在原地：每次领取都装不下、每次都不发。
	m := batchMsg(5)
	_, kept := markdownBody(m, 50)
	if kept != 1 {
		t.Fatalf("At least 1 should be kept to get %d", kept)
	}
}

func TestMarkdownBodySingleReturnsOne(t *testing.T) {
	_, kept := markdownBody(singleMsg(), 4096)
	if kept != 1 {
		t.Fatalf("A single message should be reported as delivered, and %d is obtained.", kept)
	}
	// 空消息没有可送达的条目。
	if _, k := markdownBody(Message{}, 4096); k != 0 {
		t.Fatalf("0 empty messages should be reported, and %d is obtained.", k)
	}
}

func TestTelegramPackingUsesRuneBudget(t *testing.T) {
	m := batchMsg(200)
	text, kept := telegramHTML(m)
	// Telegram 按**字符数**限长；用字节口径会把中文消息压到三分之一。
	if n := utf8.RuneCountInString(text); n > telegramTextLimit {
		t.Fatalf("Text %d Characters exceed the upper limit %d", n, telegramTextLimit)
	}
	if kept <= 0 || kept >= len(m.Items) {
		t.Fatalf("Should only install the next part, get %d", kept)
	}
	if !strings.Contains(text, "next message") {
		t.Fatalf("It should be noted that there are remaining amounts not included:\n%.300s", text)
	}
}

func TestFeishuPackingReportsKept(t *testing.T) {
	m := batchMsg(2000)
	_, kept := feishuCard(m)
	if kept <= 0 || kept >= len(m.Items) {
		t.Fatalf("The card should only hold part of it, getting %d", kept)
	}
}

func TestWebhookAndEmailReportAllItems(t *testing.T) {
	// 这两个渠道不截断正文，整批都算送达。
	m := batchMsg(7)
	if n := len(m.Items); n != 7 {
		t.Fatal("The precondition is not established")
	}
	// 通过渲染器的返回值间接确认：markdownBody(0) 不限制时全部保留。
	if _, k := markdownBody(m, 0); k != len(m.Items) {
		t.Fatalf("Apply all without limiting the length and get %d", k)
	}
}

// TestMarkdownEscapesUntrustedContent 是「不可信内容不得改变消息结构」的回归测试。
// 标题与摘要来自模型输出（模型读的是被测目标响应），资产名来自被测目标的 URL。
func TestMarkdownEscapesUntrustedContent(t *testing.T) {
	cases := []struct {
		name  string
		item  Item
		must  []string // 结果里必须出现（转义形态）
		wrong []string // 结果里不得出现（未转义形态）
	}{
		{
			name: "Line breaks in the title + external links",
			item: Item{
				Severity: "high",
				Name:     "Login SQL injection\n[Emergency: Click here to verify account](http://attacker.tld)",
			},
			// 换行必须被折叠（否则能伪造出新的列表项/引用块）；
			// 方括号与圆括号必须被转义（否则是可点击的外链）。
			must:  []string{"\\[Emergency: Click here to verify account\\]", `\(http://attacker.tld\)`},
			wrong: []string{"\n[urgent", "\n\n[urgent"},
		},
		{
			name: "Image beacon in header",
			item: Item{
				Severity: "high",
				Name:     "Vulnerability ![](http://attacker.tld/beacon)",
			},
			must:  []string{`\!`, `\(http://attacker.tld/beacon\)`},
			wrong: []string{"![]("},
		},
		{
			name: "Emphasis and citation in asset names",
			item: Item{
				Severity: "high",
				Name:     "normal title",
				Assets:   []string{"a.com/*injection*>reference"},
			},
			must:  []string{"\\*injection\\*", `\>`},
			wrong: []string{"*injection*"},
		},
		{
			name: "Backticks and vertical bars in abstracts",
			item: Item{
				Severity: "high",
				Name:     "title",
				Summary:  "`code` | Form",
			},
			must:  []string{"\\`code\\`", `\|`},
			wrong: []string{"`code`"},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			m := Message{Items: []Item{tc.item}}
			// 单条模式的写Item 是三个 markdown 渠道共用的渲染路径。
			var b strings.Builder
			writeItem(&b, tc.item, "", true)
			got := b.String()
			for _, want := range tc.must {
				if !strings.Contains(got, want) {
					t.Errorf("Missing escape form %q:\n%s", want, got)
				}
			}
			for _, bad := range tc.wrong {
				if strings.Contains(got, bad) {
					t.Errorf("The unescaped form %q appears (can be used to inject structures or external links):\n%s", bad, got)
				}
			}
			_ = m
		})
	}
}

// TestMarkdownEscapeBackslashFirst 锁住转义顺序：反斜杠必须最先处理，
// 否则会给后面补上的反斜杠再套一层，输出里出现双反斜杠。
func TestMarkdownEscapeBackslashFirst(t *testing.T) {
	if got := markdownEscape(`a\b*c`); got != `a\\b\*c` {
		t.Fatalf("Wrong escape order, you get %q", got)
	}
}

// TestTelegramTitleHasNoMarkdownEscapes 锁住一个具体的回归：
// markdown 转义不能泄漏到 Telegram 的 HTML 输出里（曾经在共享的标题函数里
// 加过转义，结果 Telegram 消息里出现 `\(1\)` 这种可见反斜杠）。
func TestTelegramTitleHasNoMarkdownEscapes(t *testing.T) {
	m := Message{Items: []Item{{Severity: "high", Name: "alert(1) *Key points*"}}}
	text, _ := telegramHTML(m)
	if strings.Contains(text, `\(`) || strings.Contains(text, `\*`) {
		t.Fatalf("Markdown backslash escaping appears in Telegram text:\n%s", text)
	}
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
