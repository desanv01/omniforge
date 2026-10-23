package db

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/desanv01/omniforge/notify"
)

// 本文件的用例都会真连 PostgreSQL（无库时跳过）。这些 SQL 用到了
// FOR UPDATE SKIP LOCKED、make_interval、JSONB、多行 IN(...) 占位符拼接，
// 都是「编译通过但可能运行时报错」的写法，必须实跑才算验证过。

func notifyTestDB(t *testing.T) *DB {
	t.Helper()
	d, err := Open(testDSN(t))
	if err != nil {
		t.Skipf("postgres unavailable (%v) — skipping", err)
	}
	t.Cleanup(func() { d.Close() })
	return d
}

// newTestChannel 建一个渠道，测试结束自动删除。
func newTestChannel(t *testing.T, d *DB, kind, mode string, filter string) *NotificationChannel {
	t.Helper()
	if filter == "" {
		filter = `{}`
	}
	ch := &NotificationChannel{
		Name:       "Test channel-" + t.Name(),
		Kind:       kind,
		Mode:       mode,
		Config:     json.RawMessage(`{"webhook":"https://example.com/hook"}`),
		Filter:     json.RawMessage(filter),
		RatePerMin: 100,
	}
	id, err := d.SaveNotificationChannel(context.Background(), ch)
	if err != nil {
		t.Fatalf("Failed to create channel: %v", err)
	}
	t.Cleanup(func() { d.Exec(`DELETE FROM notification_channels WHERE id=$1`, id) })
	ch.ID = id
	return ch
}

// addTestEvent 直接写一条事件（不经 finding），用于测试分派与投递。
func addTestEvent(t *testing.T, d *DB, kind string, findingID int64, snap notify.Snapshot) int64 {
	t.Helper()
	snap.Kind = kind
	snap.FindingID = findingID
	id, err := d.AddNotificationEvent(context.Background(), kind, findingID, snap)
	if err != nil {
		t.Fatalf("Failed to write event: %v", err)
	}
	t.Cleanup(func() { d.Exec(`DELETE FROM notification_events WHERE id=$1`, id) })
	return id
}

func TestNotificationAssetNamesResolvesAndPreservesOrder(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()

	// 三类资产各有各的展示口径：域名、IP、URL。
	insertAsset := func(query, value string) int64 {
		t.Helper()
		var id int64
		if err := d.QueryRow(query, value).Scan(&id); err != nil {
			t.Fatal(err)
		}
		return id
	}
	domID := insertAsset(`INSERT INTO assets(type, domain) VALUES('subdomain',$1) RETURNING id`, "a.example.com")
	ipID := insertAsset(`INSERT INTO assets(type, ip) VALUES('ip',$1) RETURNING id`, "10.1.2.3")
	svcID := insertAsset(`INSERT INTO assets(type, url) VALUES('service',$1) RETURNING id`, "https://a.example.com/admin")
	t.Cleanup(func() {
		d.Exec(`DELETE FROM assets WHERE id IN ($1,$2,$3)`, domID, ipID, svcID)
	})

	// 传入顺序刻意乱序，且含一个不存在的 id。
	got, err := d.NotificationAssetNames(ctx, []int64{svcID, 999999999, domID, ipID, svcID})
	if err != nil {
		t.Fatalf("Failed to resolve asset name: %v", err)
	}
	want := []string{"https://a.example.com/admin", "a.example.com", "10.1.2.3"}
	if len(got) != len(want) {
		t.Fatalf("The number of asset names does not match, expecting %v and getting %v", want, got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("The order/value does not match, expecting %v and getting %v", want, got)
		}
	}
}

// TestRecordNotificationEventTxUnwindsOnFailure 是保存点机制的核心用例：
// 在事务里先让 notification_events 的写入必然失败（临时加一个恒 false 的约束），
// 断言 ① 该函数报 false ② 事务没有进入 aborted 状态，后续语句仍能执行。
//
// 没有保存点的话，PostgreSQL 会让整个事务作废，后续任何语句都以
// "current transaction is aborted" 失败——那正是「一个通知表的问题导致
// 漏洞存不进库」的故障路径。
//
// 这里刻意用 **ROLLBACK 收尾而不是 COMMIT**：ALTER TABLE 在 PG 里是事务性的，
// 一旦提交，那个临时约束就会永久留在 schema 里，把后续所有用例一起打挂。
// 回滚能自动撤销 DDL，无需手工清理。断言只需要「事务还活着」，
// 不需要真的提交。
func TestRecordNotificationEventTxUnwindsOnFailure(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()

	// 防御性清理：若历史运行留下过这个约束，先摘掉。
	if _, err := d.Exec(`ALTER TABLE notification_events DROP CONSTRAINT IF EXISTS notify_test_never`); err != nil {
		t.Fatal(err)
	}

	tx, err := d.BeginTx(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback() //nolint:errcheck // 撤销临时约束，见函数注释

	// NOT VALID：只约束此后写入的行，不去校验库里已有的历史事件
	// （否则存量行违规会导致约束加不上）。
	if _, err := tx.ExecContext(ctx, `ALTER TABLE notification_events ADD CONSTRAINT notify_test_never CHECK (false) NOT VALID`); err != nil {
		t.Fatalf("Failed to add temporary constraints: %v", err)
	}
	if RecordNotificationEventTx(ctx, tx, notify.EventFindingCreated, 1, notify.Snapshot{Severity: "high"}) {
		t.Fatal("Report write success despite the constraint that it must fail")
	}
	// 关键断言：事务还能用。
	var one int
	if err := tx.QueryRowContext(ctx, `SELECT 1`).Scan(&one); err != nil {
		t.Fatalf("Transaction has been tainted (savepoint is not valid): %v", err)
	}
	if err := tx.Rollback(); err != nil {
		t.Fatalf("Rollback failed: %v", err)
	}
	// 确认 DDL 已随回滚撤销，不给后续用例留雷。
	var exists bool
	if err := d.QueryRow(`SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='notify_test_never')`).Scan(&exists); err != nil {
		t.Fatal(err)
	}
	if exists {
		t.Fatal("Temporary constraints are not revoked by rollback, which will pollute subsequent use cases.")
	}
}

func TestFanOutRoutesEventsByFilter(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()

	all := newTestChannel(t, d, notify.KindDingTalk, NotifyModeRealtime, `{}`)
	onlyCritical := newTestChannel(t, d, notify.KindDingTalk, NotifyModeRealtime, `{"min_severity":"critical"}`)
	sqlOnly := newTestChannel(t, d, notify.KindDingTalk, NotifyModeRealtime, `{"vulnclass_include":["SQL"]}`)

	highSQL := addTestEvent(t, d, notify.EventFindingCreated, 1001, notify.Snapshot{Severity: "high", VulnClass: "SQL injection"})
	lowXSS := addTestEvent(t, d, notify.EventFindingCreated, 1002, notify.Snapshot{Severity: "low", VulnClass: "XSS"})
	criticalXSS := addTestEvent(t, d, notify.EventFindingCreated, 1003, notify.Snapshot{Severity: "critical", VulnClass: "XSS"})

	if _, _, err := d.FanOutPendingEvents(ctx, 100); err != nil {
		t.Fatalf("Dispatch failed: %v", err)
	}

	cases := []struct {
		name    string
		eventID int64
		channel int64
		want    bool
	}{
		{"All channels receive high", highSQL, all.ID, true},
		{"All channels receive low", lowXSS, all.ID, true},
		{"Only critical channels skip high", highSQL, onlyCritical.ID, false},
		{"Only critical channels receive critical", criticalXSS, onlyCritical.ID, true},
		{"Only SQL channels receive SQL", highSQL, sqlOnly.ID, true},
		{"SQL channel only skips XSS", lowXSS, sqlOnly.ID, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var exists bool
			if err := d.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM notification_deliveries WHERE event_id=$1 AND channel_id=$2)`,
				tc.eventID, tc.channel).Scan(&exists); err != nil {
				t.Fatal(err)
			}
			if exists != tc.want {
				t.Fatalf("Delivery exists: Expected %v got %v", tc.want, exists)
			}
		})
	}

	// 再分派一次不应产生重复投递（fanned_out 幂等）。
	events, deliveries, err := d.FanOutPendingEvents(ctx, 100)
	if err != nil {
		t.Fatal(err)
	}
	if events != 0 || deliveries != 0 {
		t.Fatalf("Dispatched events should not be processed again, get events=%d deliveries=%d", events, deliveries)
	}
}

// TestFanOutMarksEventsWithNoMatchingChannel 覆盖「事件没命中任何渠道」的情况。
// 这类事件必须照样被标记为已分派，否则它会永远留在待分派集合里、每个 tick 重扫。
func TestFanOutMarksEventsWithNoMatchingChannel(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()
	pick := newTestChannel(t, d, notify.KindDingTalk, NotifyModeRealtime, "{\"vulnclass_include\":[\"Never match type\"]}")
	_ = pick

	ev := addTestEvent(t, d, notify.EventFindingCreated, 2001, notify.Snapshot{Severity: "high", VulnClass: "XSS"})
	_, deliveries, err := d.FanOutPendingEvents(ctx, 100)
	if err != nil {
		t.Fatal(err)
	}
	if deliveries != 0 {
		t.Fatalf("Delivery should not have occurred, got %d", deliveries)
	}
	var fanned bool
	if err := d.QueryRowContext(ctx, `SELECT fanned_out FROM notification_events WHERE id=$1`, ev).Scan(&fanned); err != nil {
		t.Fatal(err)
	}
	if !fanned {
		t.Fatal("Events that miss the channel must also be marked as dispatched, otherwise they will be infinitely rescanned.")
	}
}

func TestClaimRealtimeDeliveriesHonorsLeaseAndMode(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()

	realtime := newTestChannel(t, d, notify.KindDingTalk, NotifyModeRealtime, `{}`)
	digest := newTestChannel(t, d, notify.KindDingTalk, NotifyModeDigest, `{}`)

	addTestEvent(t, d, notify.EventFindingCreated, 3001, notify.Snapshot{Severity: "high", VulnClass: "XSS"})
	if _, _, err := d.FanOutPendingEvents(ctx, 100); err != nil {
		t.Fatal(err)
	}

	// 实时领取只应拿到 realtime 渠道的那条，不该动 digest 渠道的。
	got, err := d.ClaimRealtimeDeliveries(ctx, realtime.ID, 10, time.Minute)
	if err != nil {
		t.Fatalf("Failed to collect: %v", err)
	}
	if len(got) != 1 {
		t.Fatalf("Should have received 1 piece and got %d", len(got))
	}
	if got[0].State != NotifyStateSending || got[0].Attempts != 1 {
		t.Fatalf("After receiving it, it should be sending and attempts=1, and get state=%s attempts=%d", got[0].State, got[0].Attempts)
	}
	// 关联加载的渲染上下文必须齐全（渠道配置 + 事件快照 + finding id）。
	if got[0].Channel == nil || len(got[0].Channel.Config) == 0 {
		t.Fatal("The channel configuration is missing when receiving results, and rendering will fail.")
	}
	if got[0].FindingID != 3001 {
		t.Fatalf("The finding id was not brought out from the event and got %d", got[0].FindingID)
	}

	// 租约未到期，第二次领取应为空——这是「同一行不会被两个 dispatcher 同时投递」
	// 的保证。
	again, err := d.ClaimRealtimeDeliveries(ctx, realtime.ID, 10, time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if len(again) != 0 {
		t.Fatalf("It should not be collected repeatedly during the lease period, and you will get %d", len(again))
	}

	// digest 渠道的投递不应被实时领取碰到。
	left, err := d.ClaimRealtimeDeliveries(ctx, digest.ID, 10, time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if len(left) != 0 {
		t.Fatalf("Real-time collection should not get the delivery of the digest channel, and get %d", len(left))
	}
}

// TestClaimExpiredLeaseRecovers 覆盖崩溃自愈：进程在投递途中挂掉会留下 sending
// 行，租约到期后必须能被重新领起来，否则这条投递永远卡住。
func TestClaimExpiredLeaseRecovers(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()
	ch := newTestChannel(t, d, notify.KindDingTalk, NotifyModeRealtime, `{}`)
	addTestEvent(t, d, notify.EventFindingCreated, 4001, notify.Snapshot{Severity: "high"})
	if _, _, err := d.FanOutPendingEvents(ctx, 100); err != nil {
		t.Fatal(err)
	}
	first, err := d.ClaimRealtimeDeliveries(ctx, ch.ID, 10, time.Minute)
	if err != nil || len(first) != 1 {
		t.Fatalf("Failed to collect for the first time: %v (%d)", err, len(first))
	}
	// 把租约手动推到过去，模拟「租约已过期」。
	if _, err := d.Exec(`UPDATE notification_deliveries SET next_attempt_at = now() - interval '1 minute' WHERE id=$1`, first[0].ID); err != nil {
		t.Fatal(err)
	}
	second, err := d.ClaimRealtimeDeliveries(ctx, ch.ID, 10, time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if len(second) != 1 {
		t.Fatalf("The sending row whose lease has expired should be re-acquired and get %d", len(second))
	}
	if second[0].Attempts != 2 {
		t.Fatalf("The number of re-acquisition attempts should be accumulated to obtain %d", second[0].Attempts)
	}
}

func TestClaimSkipsDisabledChannel(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()
	ch := newTestChannel(t, d, notify.KindDingTalk, NotifyModeRealtime, `{}`)
	addTestEvent(t, d, notify.EventFindingCreated, 5001, notify.Snapshot{Severity: "high"})
	if _, _, err := d.FanOutPendingEvents(ctx, 100); err != nil {
		t.Fatal(err)
	}
	// 停用会把存量待发投递一起标记为 skipped。
	if err := d.SetNotificationChannelEnabled(ctx, ch.ID, false); err != nil {
		t.Fatal(err)
	}
	var state string
	if err := d.QueryRow(`SELECT state FROM notification_deliveries WHERE channel_id=$1`, ch.ID).Scan(&state); err != nil {
		t.Fatal(err)
	}
	if state != NotifyStateSkipped {
		t.Fatalf("Inventory pending delivery for deactivated channels should be marked skipped, resulting in %s", state)
	}
	got, err := d.ClaimRealtimeDeliveries(ctx, ch.ID, 10, time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 0 {
		t.Fatalf("Deactivated channels should not be claimed and received %d", len(got))
	}
}

func TestDigestBatchDueAndStableBatchID(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()
	ch := newTestChannel(t, d, notify.KindDingTalk, NotifyModeDigest, `{}`)
	for i := 0; i < 3; i++ {
		addTestEvent(t, d, notify.EventFindingCreated, int64(6000+i), notify.Snapshot{Severity: "high"})
	}
	if _, _, err := d.FanOutPendingEvents(ctx, 100); err != nil {
		t.Fatal(err)
	}

	// 批次刚建、年龄为 0，30 分钟的周期下不该到期。
	due, err := d.DigestBatchDue(ctx, ch.ID, 30*time.Minute)
	if err != nil {
		t.Fatalf("Failure to judge batch expiration: %v", err)
	}
	if due {
		t.Fatal("Newly created batches should not expire immediately")
	}

	// 把三条投递的创建时间一起推老，模拟一个攒够周期的批次。
	if _, err := d.Exec(`UPDATE notification_deliveries SET created_at = now() - interval '40 minutes' WHERE channel_id=$1`, ch.ID); err != nil {
		t.Fatal(err)
	}
	due, err = d.DigestBatchDue(ctx, ch.ID, 30*time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if !due {
		t.Fatal("Batch that exceeds the cycle should be judged as expired")
	}

	batch, err := d.ClaimDigestBatch(ctx, ch.ID, MaxDigestBatchSize, time.Minute)
	if err != nil {
		t.Fatalf("Failed to receive summary batch: %v", err)
	}
	if len(batch) != 3 {
		t.Fatalf("The summary should collect all 3 items at once and get %d items.", len(batch))
	}
	if batch[0].BatchID == nil {
		t.Fatal("The batch_id must be written when summarizing batches, otherwise it will not be seen in the history that these items were sent together.")
	}
	firstBatchID := *batch[0].BatchID
	for _, dl := range batch {
		if dl.BatchID == nil || *dl.BatchID != firstBatchID {
			t.Fatalf("The same batch should share batch_id, get %v vs %d", dl.BatchID, firstBatchID)
		}
	}

	// 让这批**整体**失败重排后再领，batch_id 必须保持原值（COALESCE 的作用）：
	// 否则一次重试就把「这批是一起发的」这个事实抹掉了。
	//
	// 必须整批重排而不是只重排一条——投递引擎发汇总消息时就是这样处理的
	// （一条消息代表整批，成败与共）。只重排一条的话，其余仍在租约期内，
	// 重领自然只拿到那一条。
	allIDs := make([]int64, 0, len(batch))
	for _, dl := range batch {
		allIDs = append(allIDs, dl.ID)
	}
	if err := d.RescheduleDeliveries(ctx, allIDs, time.Second, "Simulation failed"); err != nil {
		t.Fatal(err)
	}
	// 把租约推到过去，模拟退避时间已到。
	if _, err := d.Exec(`UPDATE notification_deliveries SET next_attempt_at = now() - interval '1 minute' WHERE channel_id=$1`, ch.ID); err != nil {
		t.Fatal(err)
	}
	reclaimed, err := d.ClaimDigestBatch(ctx, ch.ID, MaxDigestBatchSize, time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if len(reclaimed) != 3 {
		t.Fatalf("Reclaim should get all 3 and get %d", len(reclaimed))
	}
	if reclaimed[0].BatchID == nil || *reclaimed[0].BatchID != firstBatchID {
		t.Fatalf("After retrying, batch_id should keep the original value %d and get %v", firstBatchID, reclaimed[0].BatchID)
	}
}

func TestDeliveryStateTransitions(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()
	ch := newTestChannel(t, d, notify.KindDingTalk, NotifyModeRealtime, `{}`)
	addTestEvent(t, d, notify.EventFindingCreated, 7001, notify.Snapshot{Severity: "high"})
	if _, _, err := d.FanOutPendingEvents(ctx, 100); err != nil {
		t.Fatal(err)
	}
	got, err := d.ClaimRealtimeDeliveries(ctx, ch.ID, 10, time.Minute)
	if err != nil || len(got) != 1 {
		t.Fatalf("Failed to collect: %v (%d)", err, len(got))
	}
	id := got[0].ID

	if err := d.RescheduleDeliveries(ctx, []int64{id}, time.Second, "Network jitter"); err != nil {
		t.Fatal(err)
	}
	var state, lastErr string
	if err := d.QueryRow(`SELECT state, last_error FROM notification_deliveries WHERE id=$1`, id).Scan(&state, &lastErr); err != nil {
		t.Fatal(err)
	}
	if state != NotifyStatePending || lastErr != "Network jitter" {
		t.Fatalf("After rearrangement, it should be pending and the reason will be recorded, and we will get state=%s err=%q", state, lastErr)
	}

	if err := d.FailDeliveries(ctx, []int64{id}, "Exhausted retries"); err != nil {
		t.Fatal(err)
	}
	if err := d.QueryRow(`SELECT state FROM notification_deliveries WHERE id=$1`, id).Scan(&state); err != nil {
		t.Fatal(err)
	}
	if state != NotifyStateFailed {
		t.Fatalf("Should be failed, got %s", state)
	}

	// 手动重发要清零重试计数并立即到期，否则会继承旧的失败预算。
	if err := d.RetryNotificationDelivery(ctx, id); err != nil {
		t.Fatalf("Resend failed: %v", err)
	}
	var attempts int
	var next time.Time
	if err := d.QueryRow(`SELECT state, attempts, next_attempt_at FROM notification_deliveries WHERE id=$1`, id).Scan(&state, &attempts, &next); err != nil {
		t.Fatal(err)
	}
	if state != NotifyStatePending || attempts != 0 {
		t.Fatalf("After resending, it should be pending and attempts=0, and get state=%s attempts=%d", state, attempts)
	}
	if next.After(time.Now().Add(time.Second)) {
		t.Fatal("Resend should be available immediately")
	}

	// 已送达的投递不应能被重发。
	if err := d.MarkDeliveriesSent(ctx, []int64{id}); err != nil {
		t.Fatal(err)
	}
	if err := d.RetryNotificationDelivery(ctx, id); err == nil {
		t.Fatal("Deliveries that have been delivered should not be allowed to be resent")
	}
}

func TestListNotificationDeliveriesPagingAndFilter(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()
	ch := newTestChannel(t, d, notify.KindDingTalk, NotifyModeRealtime, `{}`)
	for i := 0; i < 5; i++ {
		addTestEvent(t, d, notify.EventFindingCreated, int64(8000+i), notify.Snapshot{Severity: "high", Name: "Pagination test"})
	}
	if _, _, err := d.FanOutPendingEvents(ctx, 100); err != nil {
		t.Fatal(err)
	}
	if _, err := d.ClaimRealtimeDeliveries(ctx, ch.ID, 10, time.Minute); err != nil {
		t.Fatal(err)
	}

	page1, total, err := d.ListNotificationDeliveries(ctx, NotificationDeliveryFilter{ChannelID: ch.ID, State: NotifyStateSending}, 1, 2)
	if err != nil {
		t.Fatalf("Query failed: %v", err)
	}
	if total != 5 {
		t.Fatalf("The total should be 5, getting %d", total)
	}
	if len(page1) != 2 {
		t.Fatalf("2 items per page, get %d", len(page1))
	}
	// 新的在前：第一页首条 id 应大于第二页首条。
	page2, _, err := d.ListNotificationDeliveries(ctx, NotificationDeliveryFilter{ChannelID: ch.ID, State: NotifyStateSending}, 2, 2)
	if err != nil {
		t.Fatal(err)
	}
	if len(page2) != 2 || page2[0].ID >= page1[0].ID {
		t.Fatalf("The paging order should be new first, and get page1[0]=%d page2[0]=%d", page1[0].ID, page2[0].ID)
	}
	// 渲染上下文必须随历史一起返回，否则列表无法展示「推的是什么」。
	if page1[0].ChannelName == "" || page1[0].FindingID == 0 {
		t.Fatalf("History item is missing display field: %+v", page1[0])
	}

	// 按状态过滤：没有 pending 的。
	pending, totalPending, err := d.ListNotificationDeliveries(ctx, NotificationDeliveryFilter{ChannelID: ch.ID, State: NotifyStatePending}, 1, 50)
	if err != nil {
		t.Fatal(err)
	}
	if totalPending != 0 || len(pending) != 0 {
		t.Fatalf("There should be no pending delivery, and %d items were obtained (total=%d)", len(pending), totalPending)
	}
}

func TestSetFindingStatusWithNotifyOnlyEmitsOnRealChange(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()

	tk, err := d.CreateTask("Notification status change test", "Target", nil, 0, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer d.DeleteTask(tk.ID)
	es := d.Exploration(tk.ExplorationID)
	f, err := es.RecordFinding(ctx, RecordFindingInput{
		TaskID: tk.ID, Worker: "test", VulnClass: "SQL injection", Name: "State change use case",
		Severity: "high", Summary: "summary",
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { d.Exec(`DELETE FROM notification_events WHERE finding_id=$1`, f.FindingID) })

	// 落库时已登记一条 finding_created 事件，先把它数出来作为基线。
	var base int
	if err := d.QueryRow(`SELECT count(*) FROM notification_events WHERE finding_id=$1`, f.FindingID).Scan(&base); err != nil {
		t.Fatal(err)
	}
	if base < 1 {
		t.Fatal("The vulnerability database should register a push event in the same transaction")
	}

	// 改成同一个状态：不该产生事件（避免重复提交刷出推送噪音）。
	from, found, notified, err := d.SetFindingStatusWithNotify(ctx, f.FindingID, "pending")
	if err != nil || !found {
		t.Fatalf("Status setting failed: found=%v err=%v", found, err)
	}
	if notified {
		t.Fatal("Push events should not be registered when the status has not changed")
	}
	if from != "pending" {
		t.Fatalf("Should return to the pre-change status pending and get %q", from)
	}

	// 真正变更：应登记事件并记录 from/to。
	from, found, notified, err = d.SetFindingStatusWithNotify(ctx, f.FindingID, "fixed")
	if err != nil || !found {
		t.Fatalf("Status setting failed: found=%v err=%v", found, err)
	}
	if !notified {
		t.Fatal("Push events should be registered when the status actually changes")
	}
	if from != "pending" {
		t.Fatalf("from should be pending and get %q", from)
	}
	var snapshot []byte
	if err := d.QueryRow(`SELECT snapshot FROM notification_events WHERE finding_id=$1 AND kind=$2`,
		f.FindingID, notify.EventFindingStatusChanged).Scan(&snapshot); err != nil {
		t.Fatalf("Status change event not found: %v", err)
	}
	var snap notify.Snapshot
	if err := json.Unmarshal(snapshot, &snap); err != nil {
		t.Fatal(err)
	}
	if snap.FromStatus != "pending" || snap.ToStatus != "fixed" {
		t.Fatalf("The status flow in the snapshot is incorrect: %s → %s", snap.FromStatus, snap.ToStatus)
	}
	// 快照要带上渲染所需字段，否则状态变更消息会是空壳。
	if snap.VulnClass != "SQL injection" || snap.Severity != "high" || snap.Name != "State change use case" {
		t.Fatalf("Snapshot is missing render fields: %+v", snap)
	}
	var status string
	if err := d.QueryRow(`SELECT status FROM findings WHERE id=$1`, f.FindingID).Scan(&status); err != nil {
		t.Fatal(err)
	}
	if status != "fixed" {
		t.Fatalf("The status should have been updated to fixed, getting %s", status)
	}

	// 不存在的漏洞：found=false，不报错。
	if _, found, _, err := d.SetFindingStatusWithNotify(ctx, 999999999, "fixed"); err != nil || found {
		t.Fatalf("Vulnerabilities that do not exist should return found=false and no errors, get found=%v err=%v", found, err)
	}
}

func TestNotificationStatsSnapshot(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()
	ch := newTestChannel(t, d, notify.KindDingTalk, NotifyModeRealtime, `{}`)
	addTestEvent(t, d, notify.EventFindingCreated, 9001, notify.Snapshot{Severity: "high"})
	if _, _, err := d.FanOutPendingEvents(ctx, 100); err != nil {
		t.Fatal(err)
	}
	stats, err := d.NotificationStatsSnapshot(ctx)
	if err != nil {
		t.Fatalf("Statistics failed: %v", err)
	}
	if stats.Channels < 1 || stats.ChannelsOn < 1 {
		t.Fatalf("Incorrect channel count: %+v", stats)
	}
	if stats.Pending < 1 {
		t.Fatalf("Should be counted and ready for delivery: %+v", stats)
	}
	// 刚建的投递积压年龄应接近 0，而不是负数或巨大值。
	if stats.BacklogAgeMS < 0 || stats.BacklogAgeMS > int64(time.Hour/time.Millisecond) {
		t.Fatalf("Backlog age is illegal: %d ms", stats.BacklogAgeMS)
	}
	_ = ch
}

func TestNotificationChannelCRUDRoundTrip(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()

	ch := &NotificationChannel{
		Name:       "CRUD round trip",
		Kind:       notify.KindEmail,
		Mode:       NotifyModeDigest,
		Config:     json.RawMessage(`{"host":"smtp.example.com","port":587,"from":"a@b.c","to":["x@y.z"]}`),
		Filter:     json.RawMessage(`{"min_severity":"medium","on_status_change":true}`),
		RatePerMin: 42,
	}
	id, err := d.SaveNotificationChannel(ctx, ch)
	if err != nil {
		t.Fatalf("New creation failed: %v", err)
	}
	t.Cleanup(func() { d.Exec(`DELETE FROM notification_channels WHERE id=$1`, id) })

	got, err := d.NotificationChannelByID(ctx, id)
	if err != nil {
		t.Fatalf("Read failed: %v", err)
	}
	if got.Mode != NotifyModeDigest || got.RatePerMin != 42 || got.Name != "CRUD round trip" {
		t.Fatalf("Round trip field inconsistency: %+v", got)
	}
	if !got.IsEnabled() {
		t.Fatal("The default should be enabled")
	}
	var cfg map[string]any
	if err := json.Unmarshal(got.Config, &cfg); err != nil {
		t.Fatal(err)
	}
	if cfg["host"] != "smtp.example.com" {
		t.Fatalf("The configuration is not correctly dropped into the library: %v", cfg)
	}
	var filter notify.Filter
	if err := json.Unmarshal(got.Filter, &filter); err != nil {
		t.Fatal(err)
	}
	if filter.MinSeverity != "medium" || !filter.OnStatusChange {
		t.Fatalf("The filter conditions are not correctly entered into the database: %+v", filter)
	}

	// 更新后再读。
	got.Name = "Name changed"
	off := false
	got.Enabled = &off
	if _, err := d.SaveNotificationChannel(ctx, got); err != nil {
		t.Fatal(err)
	}
	after, err := d.NotificationChannelByID(ctx, id)
	if err != nil {
		t.Fatal(err)
	}
	if after.Name != "Name changed" || after.IsEnabled() {
		t.Fatalf("Update not taking effect: %+v", after)
	}

	// 删除后应报「不存在」而不是静默成功。
	if err := d.DeleteNotificationChannel(ctx, id); err != nil {
		t.Fatal(err)
	}
	if _, err := d.NotificationChannelByID(ctx, id); err != ErrNotificationChannelNotFound {
		t.Fatalf("Expected ErrNotificationChannelNotFound, got %v", err)
	}
	if err := d.DeleteNotificationChannel(ctx, id); err != ErrNotificationChannelNotFound {
		t.Fatalf("The duplicate deletion report does not exist, and %v is obtained.", err)
	}
}

// TestSaveNotificationChannelKeepsExplicitZeroRate 锁住一个曾经写错的地方：
// **0 是合法配置，含义是「不限流」，不能被 db 层当成「未指定」覆盖成默认值**。
//
// 历史 bug：SaveNotificationChannel 里写了 `if RatePerMin <= 0 { 取默认值 }`，
// 于是文档、UI 提示、takeTokens 都按「0=不限流」解释，唯独写库这一层悄悄改成
// 20（钉钉/企微/Telegram）或 100（飞书）——操作者以为放开了限流、实际被卡着，
// 而且没有任何提示。「未指定」与「显式 0」的区别只有请求体能表达，
// 所以默认值在 server 层填（见 notifyCreateChannel），db 层只管存。
func TestSaveNotificationChannelKeepsExplicitZeroRate(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()

	// 显式 0（不限流）：必须原样存下来。
	unlimited := &NotificationChannel{
		Name: "No current limit", Kind: notify.KindDingTalk, RatePerMin: 0,
		Config: json.RawMessage(`{"webhook":"https://example.com/h"}`),
	}
	id, err := d.SaveNotificationChannel(ctx, unlimited)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { d.Exec(`DELETE FROM notification_channels WHERE id=$1`, id) })
	got, err := d.NotificationChannelByID(ctx, id)
	if err != nil {
		t.Fatal(err)
	}
	if got.RatePerMin != 0 {
		t.Fatalf("Explicit 0 means no current limit and must be saved as is, resulting in %d", got.RatePerMin)
	}
	if got.Mode != NotifyModeRealtime {
		t.Fatalf("Default mode should be realtime, get %s", got.Mode)
	}

	// 负值是非法输入，应被拒绝而不是悄悄改成别的值。
	bad := &NotificationChannel{
		Name: "negative current limit", Kind: notify.KindDingTalk, RatePerMin: -1,
		Config: json.RawMessage(`{"webhook":"https://example.com/h"}`),
	}
	if _, err := d.SaveNotificationChannel(ctx, bad); err == nil {
		t.Fatal("Negative current limits should be rejected")
	}
}

// TestDeleteChannelCascadesDeliveries 锁住外键行为：渠道删除后其投递历史一并消失
// （配置都没了，历史无从解读），但事件本身要留下——它可能还被别的渠道引用。
func TestDeleteChannelCascadesDeliveries(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()
	ch := newTestChannel(t, d, notify.KindDingTalk, NotifyModeRealtime, `{}`)
	ev := addTestEvent(t, d, notify.EventFindingCreated, 9101, notify.Snapshot{Severity: "high"})
	if _, _, err := d.FanOutPendingEvents(ctx, 100); err != nil {
		t.Fatal(err)
	}
	var before int
	if err := d.QueryRow(`SELECT count(*) FROM notification_deliveries WHERE channel_id=$1`, ch.ID).Scan(&before); err != nil {
		t.Fatal(err)
	}
	if before == 0 {
		t.Fatal("The precondition is not met: no delivery occurs")
	}
	if err := d.DeleteNotificationChannel(ctx, ch.ID); err != nil {
		t.Fatal(err)
	}
	var after int
	if err := d.QueryRow(`SELECT count(*) FROM notification_deliveries WHERE channel_id=$1`, ch.ID).Scan(&after); err != nil {
		t.Fatal(err)
	}
	if after != 0 {
		t.Fatalf("After the channel is deleted, its deliveries should be deleted in cascade, and there are still %d", after)
	}
	var evExists bool
	if err := d.QueryRow(`SELECT EXISTS(SELECT 1 FROM notification_events WHERE id=$1)`, ev).Scan(&evExists); err != nil {
		t.Fatal(err)
	}
	if !evExists {
		t.Fatal("Deleting a channel should not also delete the event itself")
	}
}

// TestClaimDigestBatchHonorsCallerLimit 覆盖审计指出的一处口子：
// 汇总渠道此前完全绕过令牌桶——allow 被 takeTokens 扣掉却没人用，
// rate_per_min 对 digest 模式毫无作用。现在 limit 也参与约束。
func TestClaimDigestBatchHonorsCallerLimit(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()
	ch := newTestChannel(t, d, notify.KindDingTalk, NotifyModeDigest, `{}`)
	for i := 0; i < 10; i++ {
		addTestEvent(t, d, notify.EventFindingCreated, int64(7000+i), notify.Snapshot{Severity: "high"})
	}
	if _, _, err := d.FanOutPendingEvents(ctx, 100); err != nil {
		t.Fatal(err)
	}
	// 取 limit=3：只能领到 3 条，其余留在库里。
	got, err := d.ClaimDigestBatch(ctx, ch.ID, 3, time.Minute)
	if err != nil {
		t.Fatalf("Failed to collect: %v", err)
	}
	if len(got) != 3 {
		t.Fatalf("You should only receive 3 items according to the caller's current limit, and get %d", len(got))
	}
	// limit=0 表示本轮额度用尽：一条都不该领，也不该报错。
	if got, err := d.ClaimDigestBatch(ctx, ch.ID, 0, time.Minute); err != nil || len(got) != 0 {
		t.Fatalf("When the quota is 0, 0 items should be collected and no error will be reported, and %d items will be obtained. err=%v", len(got), err)
	}
}

// TestFinishFindingRetestEmitsStatusChange 覆盖审计指出的一处完整性缺口：
// 复测结论为「已修复」时，状态确实变了，但那条 UPDATE 是直接写库的、
// 绕过了带通知的版本——于是配了 on_status_change 的渠道对这种状态流转
// 完全收不到推送，界面上状态悄悄变了，运维要打开平台才知道。
//
// 这条用例锁住「所有改状态的路径都要登记状态变更事件」。
func TestFinishFindingRetestEmitsStatusChange(t *testing.T) {
	d := notifyTestDB(t)
	ctx := context.Background()

	tk, err := d.CreateTask("Retest push test", "Target", nil, 0, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer d.DeleteTask(tk.ID)
	es := d.Exploration(tk.ExplorationID)
	f, err := es.RecordFinding(ctx, RecordFindingInput{
		TaskID: tk.ID, Worker: "test", VulnClass: "SQL injection", Name: "Retest objectives",
		Severity: "high", Summary: "summary",
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { d.Exec(`DELETE FROM notification_events WHERE finding_id=$1`, f.FindingID) })

	// 建一条复测记录并直接推到完成态。
	rt, _, _, err := d.CreateFindingRetest(ctx, f.FindingID, "Review")
	if err != nil {
		t.Fatal(err)
	}
	if rt.ConversationID == nil {
		t.Fatal("Retests should be associated with a session")
	}
	// 复测必须先进入 running 才能落结论（与真实流程一致）。
	if ok, err := d.StartFindingRetest(ctx, rt.ID); err != nil || !ok {
		t.Fatalf("Failed to start retest: ok=%v err=%v", ok, err)
	}
	if err := d.RecordFindingRetestResult(ctx, *rt.ConversationID, "fixed", "Fixed", "evidence"); err != nil {
		t.Fatal(err)
	}
	if err := d.FinishFindingRetest(rt.ID, "completed", ""); err != nil {
		t.Fatalf("Failed to end retest: %v", err)
	}

	var status string
	if err := d.QueryRow(`SELECT status FROM findings WHERE id=$1`, f.FindingID).Scan(&status); err != nil {
		t.Fatal(err)
	}
	if status != FindingFixed {
		t.Fatalf("After retesting, it was determined that the status should be fixed after repair, and %s was obtained.", status)
	}

	// 关键断言：必须有一条状态变更事件，且 from/to 正确。
	var snapshot []byte
	err = d.QueryRow(`SELECT snapshot FROM notification_events WHERE finding_id=$1 AND kind=$2 ORDER BY id DESC LIMIT 1`,
		f.FindingID, notify.EventFindingStatusChanged).Scan(&snapshot)
	if err != nil {
		t.Fatalf("After retesting, it has been determined that the status change push event should be registered (otherwise the channel configured with on_status_change will not receive it): %v", err)
	}
	var snap notify.Snapshot
	if err := json.Unmarshal(snapshot, &snap); err != nil {
		t.Fatal(err)
	}
	if snap.FromStatus != "pending" || snap.ToStatus != FindingFixed {
		t.Fatalf("The status flow of the snapshot is incorrect: %s → %s", snap.FromStatus, snap.ToStatus)
	}
	// 快照要带渲染所需字段，否则推送出来是空壳。
	if snap.Name != "Retest objectives" || snap.Severity != "high" {
		t.Fatalf("Snapshot is missing render fields: %+v", snap)
	}
}
