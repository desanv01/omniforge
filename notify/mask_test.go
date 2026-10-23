package notify

import (
	"errors"
	"strings"
	"testing"
)

func TestMaskedValueHidesBodyButKeepsTailHint(t *testing.T) {
	const secret = "https://oapi.dingtalk.com/robot/send?access_token=abcdef123456"
	got := MaskedValue(secret)
	if strings.Contains(got, "abcdef123456") {
		t.Fatalf("Mask value reveals full credentials: %q", got)
	}
	if strings.Contains(got, "oapi.dingtalk.com") {
		t.Fatalf("The mask value should not expose the address body: %q", got)
	}
	// 末 6 位要保留，用户才能认出是哪个机器人。
	if !strings.HasSuffix(got, "123456") {
		t.Fatalf("The last 6 digits should be retained as identification tips: %q", got)
	}
	if !IsMasked(got) {
		t.Fatalf("The mask value must be recognized by IsMasked: %q", got)
	}
}

func TestMaskedValueShortSecretGivesNoHint(t *testing.T) {
	// 短凭据如果也暴露末 6 位，等于把整个凭据暴露出去。
	for _, s := range []string{"abc", "abcdef", ""} {
		got := MaskedValue(s)
		if got != MaskedPrefix {
			t.Fatalf("Credentials of length %d should not give a tail hint, get %q", len(s), got)
		}
		if s != "" && strings.Contains(got, s) {
			t.Fatalf("The mask value contains the original value: %q", got)
		}
	}
}

func TestMaskConfigMasksOnlySecrets(t *testing.T) {
	cfg := map[string]any{
		"webhook": "https://example.com/hook?token=SECRETVALUE",
		"secret":  "SECtest123456",
		"port":    float64(587),
		"host":    "smtp.example.com",
	}
	masked := MaskConfig(KindDingTalk, cfg)
	for _, k := range []string{"webhook", "secret"} {
		s, _ := masked[k].(string)
		if !IsMasked(s) {
			t.Errorf("%s should be masked to get %q", k, s)
		}
	}
	// 非凭据字段必须原样保留，否则 UI 无法展示。
	if masked["port"] != float64(587) {
		t.Errorf("The non-credential field port should not be changed: %v", masked["port"])
	}
}

func TestMaskConfigUnknownKindReturnsEmpty(t *testing.T) {
	// 渠道类型无法识别时，宁可让 UI 显示空配置，也不要把可能含凭据的原始内容吐回去。
	got := MaskConfig("nope", map[string]any{"webhook": "https://x/y?token=LEAK"})
	if len(got) != 0 {
		t.Fatalf("Unknown channel type should return empty configuration, get %v", got)
	}
}

func TestMaskConfigDoesNotMutateInput(t *testing.T) {
	// 掩码是展示层行为，不能反过来把库里的真值改掉。
	cfg := map[string]any{"webhook": "https://example.com/hook", "secret": "SECtest123456"}
	_ = MaskConfig(KindDingTalk, cfg)
	if IsMasked(cfg["secret"].(string)) {
		t.Fatal("MaskConfig has modified the input parameters, which will cause the real credentials to be overwritten by the mask value.")
	}
}

func TestMergeConfigKeepsStoredOnMaskedIncoming(t *testing.T) {
	stored := map[string]any{"webhook": "https://real/hook", "secret": "REALSECRET", "method": "POST"}
	// 用户只改了 method，浏览器提交的是掩码值+新 method。
	incoming := map[string]any{
		"webhook": MaskedValue("https://real/hook"),
		"secret":  MaskedValue("REALSECRET"),
		"method":  "PUT",
	}
	got := MergeConfig(stored, incoming)
	if got["webhook"] != "https://real/hook" || got["secret"] != "REALSECRET" {
		t.Fatalf("The mask field should retain the original value in the library, resulting in %v", got)
	}
	if got["method"] != "PUT" {
		t.Fatalf("The modified fields should take effect and get %v", got["method"])
	}
}

func TestMergeConfigEmptyStringClears(t *testing.T) {
	stored := map[string]any{"webhook": "https://real/hook", "secret": "REALSECRET"}
	got := MergeConfig(stored, map[string]any{"secret": ""})
	if _, ok := got["secret"]; ok {
		t.Fatalf("An empty string should clear this field and get %v", got)
	}
	// 没提到的字段保留（局部更新语义）。
	if got["webhook"] != "https://real/hook" {
		t.Fatalf("Fields not mentioned should be retained, resulting in %v", got)
	}
}

func TestMergeConfigKeepsUnmentionedStoredKeys(t *testing.T) {
	stored := map[string]any{"host": "smtp.example.com", "port": float64(587), "password": "pw"}
	got := MergeConfig(stored, map[string]any{"port": float64(465)})
	if got["host"] != "smtp.example.com" || got["password"] != "pw" {
		t.Fatalf("Fields not mentioned should be retained, resulting in %v", got)
	}
	if got["port"] != float64(465) {
		t.Fatalf("The mentioned fields should be updated, getting %v", got["port"])
	}
}

// TestPrepareConfigUpdateBlocksDestinationSwap 是本包最重要的一条安全不变量：
// **改目标地址不能把旧凭据带过去**。
//
// 这些用例用的正是攻击形状的输入（只改地址、对凭据避而不谈），
// 而不是「防御逻辑的正确输入」——只测后者的话，防御没生效也照样全绿。
func TestPrepareConfigUpdateBlocksDestinationSwap(t *testing.T) {
	cases := []struct {
		name     string
		kind     string
		stored   map[string]any
		incoming map[string]any
		// wantMissing 是预期被点名的凭据键。
		wantMissing string
	}{
		{
			name: "General Webhook changes the address and wants to continue to use the Authorization header.",
			kind: KindWebhook,
			stored: map[string]any{
				"url":     "https://legit.example.com/hook",
				"headers": map[string]any{"Authorization": "Bearer REAL-TOKEN"},
			},
			incoming:    map[string]any{"url": "https://attacker.tld/c"},
			wantMissing: "headers",
		},
		{
			name:        "Telegram changes base_url and wants to send Bot Token to its own endpoint",
			kind:        KindTelegram,
			stored:      map[string]any{"bot_token": "123456:REAL", "chat_id": "1", "base_url": "https://api.telegram.org"},
			incoming:    map[string]any{"base_url": "https://attacker.tld"},
			wantMissing: "bot_token",
		},
		{
			name:        "Email to change SMTP host wants to hand over password",
			kind:        KindEmail,
			stored:      map[string]any{"host": "smtp.corp.com", "port": 587, "password": "REALPW", "from": "a@b.c", "to": []any{"d@e.f"}},
			incoming:    map[string]any{"host": "smtp.attacker.tld"},
			wantMissing: "password",
		},
		{
			name:        "Even if TLS is turned off for email, the password must be re-stated.",
			kind:        KindEmail,
			stored:      map[string]any{"host": "smtp.corp.com", "port": 587, "tls": false, "password": "REALPW", "from": "a@b.c", "to": []any{"d@e.f"}},
			incoming:    map[string]any{"tls": true},
			wantMissing: "password",
		},
		{
			// 掩码值 = 「沿用旧凭据」，在地址变更的语境下同样必须拒绝。
			name:        "Passback mask credentials + new address",
			kind:        KindTelegram,
			stored:      map[string]any{"bot_token": "123456:REAL", "chat_id": "1", "base_url": "https://api.telegram.org"},
			incoming:    map[string]any{"base_url": "https://attacker.tld", "bot_token": MaskedValue("123456:REAL")},
			wantMissing: "bot_token",
		},
		{
			name:        "DingTalk changes the webhook and wants to keep the signing key",
			kind:        KindDingTalk,
			stored:      map[string]any{"webhook": "https://oapi.dingtalk.com/robot/send?access_token=OLD", "secret": "REALSEC"},
			incoming:    map[string]any{"webhook": "https://attacker.tld/hook"},
			wantMissing: "secret",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			merged, err := PrepareConfigUpdate(tc.kind, tc.stored, tc.incoming)
			if err == nil {
				t.Fatalf("Changing the address without re-presenting the credentials should be rejected; get configured %v", merged)
			}
			var target *ErrDestinationChangedWithoutCredentials
			if !errors.As(err, &target) {
				t.Fatalf("A special error type should be returned so that the interface can give actionable prompts, resulting in %T: %v", err, err)
			}
			found := false
			for _, m := range target.Missing {
				if m == tc.wantMissing {
					found = true
				}
			}
			if !found {
				t.Fatalf("Should name the missing credential key %q and get %v", tc.wantMissing, target.Missing)
			}
			// 错误信息要能指导操作者怎么修。
			if !strings.Contains(err.Error(), tc.wantMissing) {
				t.Errorf("The error message should mention %q: %v", tc.wantMissing, err)
			}
		})
	}
}

// TestPrepareConfigUpdateAllowsLegitimateEdits 反向用例：正常的编辑不能被误拦，
// 否则这个防护会因为「太烦」而被绕过或删掉。
func TestPrepareConfigUpdateAllowsLegitimateEdits(t *testing.T) {
	cases := []struct {
		name     string
		kind     string
		stored   map[string]any
		incoming map[string]any
	}{
		{
			name:     "Only change the name (the configuration is returned as is)",
			kind:     KindWebhook,
			stored:   map[string]any{"url": "https://legit.example.com/hook", "headers": map[string]any{"Authorization": "Bearer REAL"}},
			incoming: map[string]any{"url": MaskedValue("https://legit.example.com/hook")},
		},
		{
			name:     "Only the request method is changed, the address and credentials are not changed.",
			kind:     KindWebhook,
			stored:   map[string]any{"url": "https://legit.example.com/hook", "method": "POST"},
			incoming: map[string]any{"method": "PUT"},
		},
		{
			name:     "Change the address and give new credentials at the same time",
			kind:     KindWebhook,
			stored:   map[string]any{"url": "https://old.example.com/hook", "headers": map[string]any{"Authorization": "Bearer OLD"}},
			incoming: map[string]any{"url": "https://new.example.com/hook", "headers": map[string]any{"Authorization": "Bearer NEW"}},
		},
		{
			name:     "Change the address and explicitly state that the credentials are no longer required",
			kind:     KindWebhook,
			stored:   map[string]any{"url": "https://old.example.com/hook", "headers": map[string]any{"Authorization": "Bearer OLD"}},
			incoming: map[string]any{"url": "https://new.example.com/hook", "headers": ""},
		},
		{
			name:     "Telegram change chat_id (not destination)",
			kind:     KindTelegram,
			stored:   map[string]any{"bot_token": "t", "chat_id": "1", "base_url": "https://api.telegram.org"},
			incoming: map[string]any{"chat_id": "-100200"},
		},
		{
			name:     "Change the recipient of the email (not the destination)",
			kind:     KindEmail,
			stored:   map[string]any{"host": "smtp.corp.com", "port": 587, "password": "PW", "from": "a@b.c", "to": []any{"x@y.z"}},
			incoming: map[string]any{"to": []any{"new@y.z"}},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			merged, err := PrepareConfigUpdate(tc.kind, tc.stored, tc.incoming)
			if err != nil {
				t.Fatalf("Legitimate editor blocked by mistake: %v", err)
			}
			if merged == nil {
				t.Fatal("The merged results should be returned")
			}
		})
	}
}

// TestPrepareConfigUpdatePortTypeTolerance 覆盖一个容易误判的细节：
// 前端提交的端口是 JSON number（float64），库里读回来也是 float64，
// 但两个值的类型可能不同（如 int vs float64）。用 == 比较会把「没改」判成「改了」，
// 从而对只改了名字的用户弹出「请重新填写密码」——假警报会让人不再信任这个防护。
func TestPrepareConfigUpdatePortTypeTolerance(t *testing.T) {
	stored := map[string]any{"host": "smtp.corp.com", "port": float64(587), "password": "PW"}
	// 同一个端口，以 int 形式提交。
	if _, err := PrepareConfigUpdate(KindEmail, stored, map[string]any{"port": 587}); err != nil {
		t.Fatalf("The same port value (only the type is different) should not be regarded as an address change: %v", err)
	}
	// 真的换了端口则必须拦。
	if _, err := PrepareConfigUpdate(KindEmail, stored, map[string]any{"port": 25}); err == nil {
		t.Fatal("Port changes should be blocked")
	}
}

// TestPrepareConfigUpdateSurvivesRepeatedSaveWithBlankDestination 覆盖「可留空的
// 目的地字段」这条路径：Telegram 的 base_url 留空表示用官方 API 地址。
//
// 曾经这里会让渠道从第二次保存起永久保存失败：
//
//	新建时库里存下 base_url:""（创建路径直接存前端提交的 config，不走 MergeConfig）
//	→ 第一次保存，MergeConfig 把空串当显式清空、delete 掉该键
//	→ 第二次保存，incoming 仍是 ""、而 stored 里已经没这个键，被判成「地址变了」
//	→ bot_token 是掩码回显值 → 400「目标地址已变更，请同时重新填写凭据字段」
//
// 用户什么都没改，却从此再也存不上，除非重新粘贴一遍 Bot Token。
func TestPrepareConfigUpdateSurvivesRepeatedSaveWithBlankDestination(t *testing.T) {
	stored := map[string]any{"bot_token": "123:ABC", "chat_id": "-100", "base_url": ""}

	// 前端 buildConfig() 对该渠道的每个字段定义都提交一个值：凭据回填掩码，
	// 空文本框提交空串。这里完整复现它的输出，而不是只提交「改动的键」。
	submit := func() map[string]any {
		return map[string]any{
			"bot_token": MaskedValue("123:ABC"),
			"chat_id":   "-100",
			"base_url":  "",
		}
	}

	// 第一次保存：只改了渠道名字，config 原样回传。
	merged, err := PrepareConfigUpdate(KindTelegram, stored, submit())
	if err != nil {
		t.Fatalf("The first save was blocked by mistake: %v", err)
	}
	if _, ok := merged["base_url"]; ok {
		t.Fatal("The premise has changed: the empty string should be deleted by MergeConfig - what this use case wants to cover is the step \"after the key disappears\"")
	}

	// 第二次保存：提交内容与上次完全一致，用户什么都没改。
	merged2, err := PrepareConfigUpdate(KindTelegram, merged, submit())
	if err != nil {
		t.Fatalf("The second save was blocked by mistake (the user did not change anything): %v", err)
	}
	// 第三次，确认不是「只错一次」而是稳定可保存。
	if _, err := PrepareConfigUpdate(KindTelegram, merged2, submit()); err != nil {
		t.Fatalf("The third save was blocked by mistake: %v", err)
	}
	// 凭据必须一路保留下来，没有被空串逻辑连带清掉。
	if got := merged2["bot_token"]; got != "123:ABC" {
		t.Fatalf("Bot Token should use the original value and get %v", got)
	}
}

// TestPrepareConfigUpdateStillGuardsBlankDestinationChanges 是上一条用例的配对
// 断言：把空串与「键不存在」视为等价，**不能**连带放过真正的地址变更。
// 这两个方向都是真实的凭据外发路径——Telegram 的 Bot Token 走在 URL 路径里，
// 换了 base_url 就等于把 Token 送给新地址。
func TestPrepareConfigUpdateStillGuardsBlankDestinationChanges(t *testing.T) {
	// 方向一：从「空」（官方地址）换到自建地址。
	official := map[string]any{"bot_token": "123:ABC", "chat_id": "-100"}
	if _, err := PrepareConfigUpdate(KindTelegram, official, map[string]any{
		"bot_token": MaskedValue("123:ABC"),
		"base_url":  "https://tg-proxy.attacker.tld",
	}); err == nil {
		t.Fatal("Changing from the official address to a self-created address requires refilling the Token.")
	}

	// 方向二：把自建地址清空（= 换回官方 API）同样是地址变更。
	proxied := map[string]any{"bot_token": "123:ABC", "base_url": "https://proxy.internal/bot"}
	if _, err := PrepareConfigUpdate(KindTelegram, proxied, map[string]any{
		"bot_token": MaskedValue("123:ABC"),
		"base_url":  "",
	}); err == nil {
		t.Fatal("Clearing the self-created address (switching back to the official API) is also an address change and requires refilling the Token.")
	}
}

func TestDestinationKeysDeclaredForEveryKind(t *testing.T) {
	// 与 SecretKeys 同理：渠道若忘记声明目的地键，PrepareConfigUpdate 就保护不到它。
	for kind, ch := range registry {
		if len(ch.DestinationKeys()) == 0 {
			t.Errorf("Channel %s does not declare the destination key, and the protection of changing the address and bringing out the credentials is invalid for it.", kind)
		}
		if len(ch.SecretKeys()) == 0 {
			t.Errorf("Channel %s did not declare a credential key", kind)
		}
	}
}

func TestSecretKeysDeclaredForEveryKind(t *testing.T) {
	// 编译器已经强制每个渠道实现 SecretKeys，这里再确认一遍「没有渠道在掩码上
	// 交白卷」——返回空切片的渠道意味着它的凭据会明文回显到浏览器。
	expect := map[string]bool{
		KindDingTalk: true, KindFeishu: true, KindWeCom: true,
		KindWebhook: true, KindTelegram: true, KindEmail: true,
	}
	for kind, ch := range registry {
		if !expect[kind] {
			t.Errorf("Channel %s did not register mask expectations in test", kind)
			continue
		}
		if len(ch.SecretKeys()) == 0 {
			t.Errorf("Channel %s does not declare any credential fields, and its configuration will be echoed in clear text.", kind)
		}
	}
}

// TestPrepareConfigUpdateRejectsMaskedInContainer 覆盖审计指出的一处口子：
// 把掩码哨兵塞进**非字符串**结构（如 webhook.headers 是个对象）时，
// MergeConfig 只认「字符串且带前缀」为掩码，于是字面量 "__masked__" 会被当成
// 真实头值存进库——后续鉴权静默失效，且没有任何报错。
func TestPrepareConfigUpdateRejectsMaskedInContainer(t *testing.T) {
	stored := map[string]any{
		"url":     "https://legit.example.com/hook",
		"headers": map[string]any{"Authorization": "Bearer REAL"},
	}
	// 对象内部夹带掩码哨兵。
	incoming := map[string]any{
		"headers": map[string]any{"Authorization": MaskedPrefix},
	}
	if _, err := PrepareConfigUpdate(KindWebhook, stored, incoming); err == nil {
		t.Fatal("Masked sentinels inside structures should be rejected (otherwise the literal will be stored in the library)")
	}
	// 整体提交对象（真实新值）照常接受。
	ok := map[string]any{"headers": map[string]any{"Authorization": "Bearer NEW"}}
	if _, err := PrepareConfigUpdate(KindWebhook, stored, ok); err != nil {
		t.Fatalf("Normal submission of new request headers should not be blocked: %v", err)
	}
}
