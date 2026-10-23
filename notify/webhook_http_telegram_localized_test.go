package notify

import (
	"context"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

// 이 파일은 F4 ④⑤(telegram·webhook·공용 HTTP 전송 계층) 한국어화를 회귀로부터
// 지킨다. telegram.go 의 메시지 라벨·배치 제목, webhook.go 의 설정 검증 오류,
// http.go 의 전송 오류, 그리고 다섯 채널이 공유하는 validateHTTPURL 이 중국어로
// 되돌아가면 잡아낸다. 헬퍼 hasHan·hasHangul·assertEnglish 은
// notify_localized_test.go 에 있다(같은 패키지).
//
// 데이터(제목·유형·자산·개요)는 전부 ASCII 로 둔다. 그래야 "출력 전체에 한자 0"
// 이라는 단언이 콘텐츠가 아니라 골격 라벨의 회귀만 정확히 포착한다. 심각도·상태
// 라벨은 F4 ①에서 이미 한국어라 출력에 한글로 나오며(한자 아님) 단언을 통과한다.

// TestTelegramItemLabelsLocalized 는 단건 Telegram 메시지의 모든 라벨 분기를 켠 뒤
// 골격이 한국어이고 중국어 한자가 없음을 확인한다.
func TestTelegramItemLabelsLocalized(t *testing.T) {
	m := Message{
		HomeURL: "https://example.com/panel",
		Items: []Item{{
			Name:       "sqli-login", // Title() = Name
			VulnClass:  "injection",  // Title() 과 달라야 유형 줄이 렌더됨
			Severity:   "high",       // SeverityLabel → 높음(한글)
			Summary:    "login form is injectable",
			Assets:     []string{"host-a.example.com"},
			DetailURL:  "https://example.com/f/1",
			FromStatus: "pending", // IsStatusChange()=true → 상태 변경 줄
			ToStatus:   "fixed",
		}},
	}
	out, kept := telegramHTML(m)
	if kept != 1 {
		t.Fatalf("Single message must report 1, received value %d", kept)
	}
	if hasHan(out) {
		t.Errorf("Chinese characters remain in the Telegram text:\n%s", out)
	}
	for _, want := range []string{"Status change", "Type", "Asset", "Overview", "View details"} {
		if !strings.Contains(out, want) {
			t.Errorf("There is no %q label in the Telegram body:\n%s", want, out)
		}
	}
}

// TestTelegramBatchTitleLocalized 는 배치(digest) 제목의 넘침·시간창 분기가
// 한국어로 렌더되는지 확인한다. markdownTitle 과 글자까지 맞춰야 채널 간 혼재가
// 생기지 않는다.
func TestTelegramBatchTitleLocalized(t *testing.T) {
	items := []Item{{Name: "a", Severity: "high"}, {Name: "b", Severity: "low"}}

	// 넘침 있음 + 시간창: 요약·총건수·앞 N건·나머지·다음 메시지·최근 N분간.
	over := telegramBatchTitle(Message{WindowMinutes: 30}, items, 5)
	assertEnglish(t, "telegramBatchTitle(overflow)", over)
	for _, want := range []string{"Vulnerability Summary · Total 5", "Only the first 2 items", "the remaining 3 items", "next message", "Last 30 minutes"} {
		if !strings.Contains(over, want) {
			t.Errorf("%q is missing in the overflow title: %q", want, over)
		}
	}

	// 넘침 없음 + 시간창 없음: 다음 메시지 안내가 없어야 한다.
	full := telegramBatchTitle(Message{}, items, 2)
	assertEnglish(t, "telegramBatchTitle (all)", full)
	if !strings.Contains(full, "Vulnerability Summary · Total 2") {
		t.Errorf("All titles must have ‘Vulnerability Summary · Total of 2’: %q", full)
	}
	if strings.Contains(full, "next message") {
		t.Errorf("It didn't overflow, but the 'next message' notification came in: %q", full)
	}
}

// TestTelegramValidateLocalized 는 필수 필드 누락 오류가 한국어이고 어떤 필드가
// 비었는지 알려 주는지 확인한다. 기술 용어 Bot Token·Chat ID 는 그대로 보존한다.
func TestTelegramValidateLocalized(t *testing.T) {
	if err := (telegramChannel{}).Validate(map[string]any{}); err == nil {
		t.Fatal("Missing bot_token must be a validation failure")
	} else {
		assertEnglish(t, "telegram Validate(bot_token)", err.Error())
		if !strings.Contains(err.Error(), "Bot Token") {
			t.Errorf("We need to inform you of missing Bot Token: %q", err.Error())
		}
	}
	if err := (telegramChannel{}).Validate(map[string]any{"bot_token": "t"}); err == nil {
		t.Fatal("Missing chat_id should be a validation failure")
	} else {
		assertEnglish(t, "telegram Validate(chat_id)", err.Error())
		if !strings.Contains(err.Error(), "Chat ID") {
			t.Errorf("You need to let us know that your Chat ID is missing: %q", err.Error())
		}
	}
}

// TestWebhookValidateLocalized 는 범용 Webhook 설정 검증 오류 세 가지가 한국어이고
// 각 오류가 문제의 원인을 알려 주는지 확인한다.
func TestWebhookValidateLocalized(t *testing.T) {
	if err := (webhookChannel{}).Validate(map[string]any{}); err == nil {
		t.Fatal("Missing url should be a validation failure")
	} else {
		assertEnglish(t, "webhook Validate(url)", err.Error())
		if !strings.Contains(err.Error(), "Target URL") {
			t.Errorf("You should let us know that the target URL is missing: %q", err.Error())
		}
	}
	// 지원하지 않는 메서드: 한국어 + 허용 목록 노출.
	if err := (webhookChannel{}).Validate(map[string]any{"url": "https://example.com/hook", "method": "DELETE"}); err == nil {
		t.Fatal("DELETE must be a validation failure")
	} else {
		assertEnglish(t, "webhook Validate(method)", err.Error())
		if !strings.Contains(err.Error(), "GET/POST/PUT/PATCH") {
			t.Errorf("You need to tell us the list of allowed methods: %q", err.Error())
		}
	}
	// 템플릿 문법 오류: 한국어(래핑된 원인은 Go 템플릿 오류라 한자가 없다).
	if err := (webhookChannel{}).Validate(map[string]any{"url": "https://example.com/hook", "body_template": "{{"}); err == nil {
		t.Fatal("A broken template should be a validation failure")
	} else {
		assertEnglish(t, "webhook Validate(template)", err.Error())
		if !strings.Contains(err.Error(), "template") {
			t.Errorf("This should indicate a template error: %q", err.Error())
		}
	}
}

// TestValidateHTTPURLLocalized 는 다섯 채널(telegram·webhook·dingtalk·feishu·wecom)이
// 공유하는 URL 검증 헬퍼의 오류가 한국어인지 확인한다. 이 헬퍼가 중국어로 남아 있으면
// 한국어 접두("API 주소가 올바르지 않습니다: ...")와 섞여 반한반중이 된다.
func TestValidateHTTPURLLocalized(t *testing.T) {
	// 지원하지 않는 스킴.
	if err := validateHTTPURL("ftp://example.com/x"); err == nil {
		t.Fatal("ftp scheme should be rejected")
	} else {
		assertEnglish(t, "validateHTTPURL(scheme)", err.Error())
		if !strings.Contains(err.Error(), "http") {
			t.Errorf("You must tell us your support scheme (http/https): %q", err.Error())
		}
	}
	// 호스트 이름 없음.
	if err := validateHTTPURL("http://"); err == nil {
		t.Fatal("Addresses without a host should be rejected")
	} else {
		assertEnglish(t, "validateHTTPURL(host)", err.Error())
	}
}

// TestHTTPLocalTargetBlockedLocalized 는 로컬/링크 로컬 주소 차단 오류가 한국어이고
// 우회 방법(환경 변수)을 알려 주는지 확인한다.
func TestHTTPLocalTargetBlockedLocalized(t *testing.T) {
	t.Setenv(AllowLocalTargetsEnv, "") // 명시적으로 꺼서 차단 경로를 탄다
	err := blockInternalDial("tcp", "127.0.0.1:25", nil)
	if err == nil {
		t.Fatal("Local addresses should be blocked by default")
	}
	assertEnglish(t, "blockInternalDial", err.Error())
	if !strings.Contains(err.Error(), AllowLocalTargetsEnv) {
		t.Errorf("The blocking error should tell you how to bypass it (%s): %q", AllowLocalTargetsEnv, err.Error())
	}
}

// TestHTTPRedactHelpersLocalized 는 주소 탈감(redact) 자리표시자와 전송 오류의
// "알 수 없는 오류" 분기가 한국어인지 확인한다.
func TestHTTPRedactHelpersLocalized(t *testing.T) {
	if got := redactRequestTarget(""); !strings.Contains(got, "could not be resolved") {
		t.Errorf("Uninterpretable address must be a Korean placeholder, received value %q", got)
	}
	// *url.Error 의 Err 가 nil 인 분기.
	got := redactTransportError(&url.Error{Op: "Get", URL: "http://api.example", Err: nil})
	if hasHan(got) {
		t.Errorf("Chinese characters remain in the transmission error desensitization result: %q", got)
	}
	if !strings.Contains(got, "Unknown error") {
		t.Errorf("If Err is nil, it must be 'unknown error', the received value is %q", got)
	}
}

// TestHTTPStatusErrorsLocalized 는 실제 doJSON 왕복으로 상태코드 분류(거부/서버
// 오류/제한)의 사용자 노출 오류가 한국어인지 확인한다. 127.0.0.1 httptest 로의
// 전송은 기본 차단이라 이 테스트에서만 명시적으로 허용한다.
func TestHTTPStatusErrorsLocalized(t *testing.T) {
	t.Setenv(AllowLocalTargetsEnv, "1")
	cases := []struct {
		code int
		want string
	}{
		{http.StatusForbidden, "rejected the request"},
		{http.StatusInternalServerError, "An error occurred"},
		{http.StatusTooManyRequests, "limited the request"},
	}
	for _, tc := range cases {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(tc.code)
			_, _ = w.Write([]byte("body"))
		}))
		_, err := doJSON(context.Background(), http.MethodPost, srv.URL, nil, map[string]any{"a": 1})
		srv.Close()
		if err == nil {
			t.Fatalf("HTTP %d should be an error", tc.code)
		}
		assertEnglish(t, "doJSON(HTTP status)", err.Error())
		if !strings.Contains(err.Error(), tc.want) {
			t.Errorf("HTTP %d error should have %q, received value is %q", tc.code, tc.want, err.Error())
		}
	}
}
