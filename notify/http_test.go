package notify

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
)

// 本文件覆盖 doJSON 的 HTTP 层错误分级。
//
// 为什么要单独测：各渠道适配器只管平台自己的业务错误码（钉钉 errcode、
// 飞书 code、Telegram ok 字段），而**HTTP 层**的分级是 doJSON 统一做的，
// 两者是两道独立的防线。少了这道，一个返回 503 的中转网关会被当成永久失败、
// 直接放弃重试；而一个 403 会被当成可重试、白白退避三轮。

func replyServer(t *testing.T, status int, body string) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestDoJSONClassifiesHTTPStatus(t *testing.T) {
	cases := []struct {
		name      string
		status    int
		permanent bool
	}{
		{"200 Success is not a mistake", 200, false},
		{"429 Current limit can be retried.", 429, false},
		{"408 Request timed out and can be retried", 408, false},
		{"500 server error can be retried", 500, false},
		{"502 gateway error can be retried", 502, false},
		{"503 Service unavailable, please try again", 503, false},
		{"400 parameter error permanent failure", 400, true},
		{"401 Authentication failed, permanent failure", 401, true},
		{"403 Forbidden access permanently failed", 403, true},
		{"404 Address does not exist. Permanent failure.", 404, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			srv := replyServer(t, tc.status, `{"detail":"upstream says no"}`)
			_, err := doJSON(context.Background(), "GET", srv.URL, nil, nil)
			if tc.status < 300 {
				if err != nil {
					t.Fatalf("2xx should not report error: %v", err)
				}
				return
			}
			if err == nil {
				t.Fatal("If it is not 2xx, an error should be reported.")
			}
			if got := IsPermanent(err); got != tc.permanent {
				t.Fatalf("HTTP %d permanent judgment error: Expect %v and get %v (%v)",
					tc.status, tc.permanent, got, err)
			}
			// 状态码必须出现在错误里，否则用户无从判断是自己配错了还是对端挂了。
			// 断言数字而不是 Go 的英文 StatusText：本包的文案是中文的
			// （与项目其它部分一致），数字才是语言无关、可稳定断言的部分。
			if !strings.Contains(err.Error(), strconv.Itoa(tc.status)) {
				t.Errorf("The error message should carry HTTP status code %d, get %v", tc.status, err)
			}
		})
	}
}

// TestDoJSONIncludesResponseSnippet 覆盖 snippet：对端返回的错误说明要带回来，
// 否则用户只知道「失败了」，不知道对端为什么拒绝。
func TestDoJSONIncludesResponseSnippet(t *testing.T) {
	srv := replyServer(t, 400, `{"error":"invalid webhook token"}`)
	_, err := doJSON(context.Background(), "GET", srv.URL, nil, nil)
	if err == nil {
		t.Fatal("An error should be reported")
	}
	if !strings.Contains(err.Error(), "invalid webhook token") {
		t.Errorf("The error message should bring back instructions to the peer, get %v", err)
	}
}

// TestDoJSONSnippetIsSingleLineAndBounded 约束 snippet 的形态：
// 它对端响应会原样进 last_error 列与前端表格，多行/超长会破坏排版与载荷。
func TestDoJSONSnippetIsSingleLineAndBounded(t *testing.T) {
	// 带换行、制表符与 5000 字符超长内容的响应。
	long := strings.Repeat("x", 5000)
	srv := replyServer(t, 500, "line1\nline2\r\n\tline3 "+long)
	_, err := doJSON(context.Background(), "GET", srv.URL, nil, nil)
	if err == nil {
		t.Fatal("An error should be reported")
	}
	msg := err.Error()
	if strings.ContainsAny(msg, "\r\n\t") {
		t.Errorf("The error message should be compressed into a single line, resulting in %q", msg)
	}
	// snippet 上限 200 字符 + 固定前缀，总量必须远小于原始响应。
	if len(msg) > 400 {
		t.Errorf("The error message is too long (%d bytes) and should be truncated by snippet: %q", len(msg), msg)
	}
}

// TestDoJSONRejectsOversizedResponse 确认读取有上限：对端异常返回超大内容时
// 不能把整个响应读进内存（投递历史里每一条都会存一份 last_error）。
func TestDoJSONRejectsOversizedResponse(t *testing.T) {
	huge := strings.Repeat("A", 1<<20) // 1 MiB
	srv := replyServer(t, 400, huge)
	_, err := doJSON(context.Background(), "GET", srv.URL, nil, nil)
	if err == nil {
		t.Fatal("An error should be reported")
	}
	if len(err.Error()) > 400 {
		t.Errorf("Oversized responses should be read with limited length and truncated, error message length %d", len(err.Error()))
	}
}
