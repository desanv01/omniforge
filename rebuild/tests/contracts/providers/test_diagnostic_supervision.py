import unittest
from dataclasses import replace
from uuid import uuid4

from services.api.providers.diagnostic_child import ChildFacade
from services.api.providers.diagnostic_protocol import Observation, Reservation
from services.api.providers.diagnostic_supervisor import Supervisor


class Clock:
    now = 0

    def __call__(self):
        return self.now


class SupervisionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.s = Supervisor(uuid4(), clock=self.clock)
        self.child = ChildFacade(self.s)
        self.s.admitted(pinned_wall_seconds=30)

    def round(self, seq=1, reported=20):
        value = Reservation(self.s.operation_id, seq, "a" * 64, 100, 512)
        self.child.request_round(value)
        self.s.reservation_ack(value)
        obs = Observation(value, reported, reported, "provider_reported", "response_received",
                          max(100, reported), max(512, reported))
        self.child.report_usage(obs)
        self.s.usage_ack(obs)
        return value, obs

    def commands(self, name):
        return [v for key, v in self.s.commands if key == name]

    def test_late_candidate_commit_after_deadline_cannot_deliver(self):
        self.round()
        self.child.proposed_result("b" * 64)  # DB guard may have passed now.
        self.clock.now = 30
        self.s.tick()
        self.s.candidate_ack("b" * 64)  # DB commits after local stop.
        self.assertTrue(self.s.candidate_committed)
        self.assertEqual(self.s.reason, "deadline")
        self.assertEqual(self.commands("deliver_success"), [])

    def test_cancel_without_durable_stop_does_not_wait_for_journal(self):
        self.s.stop("canceled")
        self.s.failed_ack()
        self.assertEqual(set(self.commands("terminate")), {"child", "authority"})
        self.assertEqual(self.s.reason, "canceled")
        self.clock.now = 2
        self.s.tick()
        self.assertTrue(self.s.cleanup_unconfirmed)
        self.assertEqual(self.commands("settle_only"), [])

    def test_lost_reserve_ack_counts_possible_and_never_releases_on_readback(self):
        r = Reservation(self.s.operation_id, 1, "a" * 64, 100, 512)
        self.child.request_round(r)
        self.s.failed_ack()
        self.assertEqual(self.s.usage["possible_dispatch_upper_bound"], 1)
        self.assertEqual(self.s.usage["accepted_request_lower_bound"], 0)
        self.assertIsNone(self.s.usage["input_tokens"])
        self.s.reservation_ack(r)
        self.assertEqual(self.commands("release_once"), [])
        self.assertEqual(self.s.charges, (100, 512))

    def test_duplicate_ack_and_observer_replay_never_double_release_or_charge(self):
        r, o = self.round(reported=700)
        self.s.reservation_ack(r)
        self.child.report_usage(o)
        self.s.usage_ack(o)
        self.assertEqual(len(self.commands("release_once")), 1)
        self.assertEqual(len(self.commands("observe_usage")), 1)
        self.assertEqual(self.s.charges, (700, 700))
        self.assertEqual(self.s.usage["input_tokens"], 700)
        self.child.report_usage(replace(o, input_tokens=701, charged_input=701))
        self.assertEqual(self.s.reason, "protocol")

    def test_observer_failure_latch_wins_over_safe_answer(self):
        r = Reservation(self.s.operation_id, 1, "a" * 64, 100, 512)
        self.child.request_round(r)
        self.s.reservation_ack(r)
        o = Observation(r, 50, 20, "provider_reported", "response_received", 100, 512)
        self.child.report_usage(o)
        self.child.observer_failed()
        self.s.usage_ack(o)  # Lost original ack arrives late.
        self.child.proposed_result("b" * 64)
        self.child.request_round(Reservation(self.s.operation_id, 2, "c" * 64, 100, 512))
        self.assertEqual(self.s.reason, "durability")
        self.assertEqual(len(self.commands("release_once")), 1)
        self.assertEqual(self.commands("commit_candidate"), [])
        self.assertIsNone(self.s.usage["input_tokens"])

    def test_bootstrap_consumes_original_lower_deadline(self):
        self.s = Supervisor(uuid4(), clock=self.clock, wall_seconds=20)
        self.clock.now = 7
        self.s.admitted(pinned_wall_seconds=8)
        self.assertEqual(self.s.deadline, 8)
        self.clock.now = 8
        self.s.tick()
        self.assertEqual(self.s.reason, "deadline")
        self.s.admitted(pinned_wall_seconds=30)
        self.assertEqual(self.s.deadline, 8)

    def test_normal_final_authority_precedes_helper_disposal_and_delivery(self):
        self.round()
        self.child.proposed_result("b" * 64)
        self.s.candidate_ack("b" * 64)
        self.assertEqual(self.commands("dispose"), ["child"])
        self.s.closed("child")
        self.assertIn("authority", self.s.owned)
        self.assertEqual(self.s.state, "final_authority")
        self.s.authority_ack(True)
        self.assertEqual(self.commands("dispose"), ["child", "authority"])
        self.assertEqual(self.commands("deliver_success"), [])
        self.s.closed("authority")
        self.assertEqual(self.commands("deliver_success"), ["b" * 64])

    def test_deadline_during_final_helper_disposal_blocks_delivery(self):
        self.round()
        self.child.proposed_result("b" * 64)
        self.s.candidate_ack("b" * 64)
        self.s.closed("child")
        self.s.authority_ack(True)
        self.clock.now = 30
        self.s.closed("authority")
        self.assertEqual(self.commands("deliver_success"), [])
        self.assertEqual(self.s.reason, "deadline")

    def test_final_authority_denial_retains_known_partial_usage(self):
        self.round()
        self.child.proposed_result("b" * 64)
        self.s.candidate_ack("b" * 64)
        self.s.closed("child")
        self.s.authority_ack(False)
        self.assertEqual(self.s.reason, "authority")
        self.assertEqual(self.s.usage["input_tokens"], 20)
        self.assertEqual(self.commands("deliver_success"), [])

    def test_settlement_helper_must_itself_exit_within_final_grace(self):
        self.s.stop("canceled")
        self.s.closed("child")
        self.s.closed("authority")
        self.assertEqual(self.commands("settle_only"), [2])
        self.s.settlement_ack()
        self.assertEqual(self.s.settlement, "recorded")
        self.clock.now = 1.5
        self.s.tick()
        self.s.tick()
        self.clock.now = 1.75
        self.s.tick()
        self.assertIn("settlement", self.commands("terminate"))
        self.assertEqual(self.commands("terminate").count("settlement"), 1)
        self.clock.now = 2
        self.s.tick()
        self.assertTrue(self.s.cleanup_unconfirmed)
        self.assertIn("settlement", self.s.owned)

    def test_settlement_outage_and_confirmed_close_not_success(self):
        self.s.stop("interrupted")
        self.s.closed("child")
        self.s.closed("authority")
        self.clock.now = 1.5
        self.s.tick()
        self.s.closed("settlement")
        self.clock.now = 4
        self.s.tick()
        self.assertEqual(self.s.settlement, "unsettled")
        self.assertFalse(self.s.cleanup_unconfirmed)
        self.assertEqual(self.commands("deliver_success"), [])

    def test_late_original_owner_closure_bounds_helper_from_actual_start(self):
        self.s.stop("canceled")
        self.clock.now = 1.9
        self.s.closed("child")
        self.assertEqual(self.commands("settle_only"), [])
        self.s.closed("authority")
        self.assertEqual(self.commands("settle_only"), [3.9])
        self.clock.now = 3.4
        self.s.tick()
        self.assertEqual(self.s.settlement, "unsettled")
        self.assertEqual(self.commands("terminate").count("settlement"), 1)
        self.s.closed("settlement")
        self.clock.now = 4
        self.s.tick()
        self.assertFalse(self.s.cleanup_unconfirmed)

    def test_one_call_cap_blocks_second_before_reservation_and_release(self):
        self.s.admitted(pinned_wall_seconds=30, pinned_calls_cap=1)
        self.round()
        self.child.request_round(Reservation(self.s.operation_id, 2, "b" * 64, 100, 512))
        self.assertEqual(self.s.reason, "budget")
        self.assertEqual(len(self.commands("reserve")), 1)
        self.assertEqual(len(self.commands("release_once")), 1)
        self.assertEqual(len(self.s.reservations), 1)

    def test_two_calls_cap_permits_both_without_refund(self):
        self.round()
        self.round(seq=2)
        self.assertIsNone(self.s.reason)
        self.assertEqual(len(self.commands("release_once")), 2)
        self.assertEqual(self.s.charges, (200, 1024))

    def test_budget_admission_only_narrows_before_first_reservation(self):
        self.s = Supervisor(uuid4(), clock=self.clock, wall_seconds=20,
                            calls_cap=1, input_cap=200, output_cap=512)
        self.s.admitted(pinned_wall_seconds=30, pinned_calls_cap=2,
                        pinned_input_cap=32768, pinned_output_cap=1024)
        self.assertEqual((self.s.deadline, self.s.calls_cap, self.s.input_cap, self.s.output_cap),
                         (20, 1, 200, 512))
        self.s.admitted(pinned_wall_seconds=10, pinned_calls_cap=1,
                        pinned_input_cap=100, pinned_output_cap=256)
        self.assertEqual((self.s.deadline, self.s.calls_cap, self.s.input_cap, self.s.output_cap),
                         (10, 1, 100, 256))
        self.s.reserve(Reservation(self.s.operation_id, 1, "a" * 64, 100, 256))
        self.s.admitted(pinned_wall_seconds=10, pinned_calls_cap=1)
        self.assertEqual(self.s.reason, "protocol")

    def test_invalid_calls_caps_reject_bool_and_out_of_range(self):
        for value in (True, False, 0, -1, 3, 1.0):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    Supervisor(uuid4(), clock=self.clock, calls_cap=value)
        for value in (True, -1, 3, 1.0):
            with self.subTest(admission=value), self.assertRaises(ValueError):
                self.s.admitted(pinned_wall_seconds=30, pinned_calls_cap=value)
        self.s.admitted(pinned_wall_seconds=30, pinned_calls_cap=0)
        self.assertEqual(self.s.reason, "protocol")

    def test_charge_caps_unknown_usage_and_invalid_frames(self):
        r = Reservation(self.s.operation_id, 1, "a" * 64, 100, 512)
        self.child.request_round(r)
        self.s.reservation_ack(r)
        o = Observation(r, None, None, "absent", "transport_failed", 100, 512)
        self.child.report_usage(o)
        self.s.usage_ack(o)
        self.assertIsNone(self.s.usage["input_tokens"])
        self.assertEqual(self.s.usage["known_input_tokens_subtotal"], 0)
        self.assertEqual(self.s.charges, (100, 512))
        self.child.request_round(Reservation(self.s.operation_id, 2, "b" * 64, 32700, 512))
        self.assertEqual(self.s.reason, "budget")
        with self.assertRaises(ValueError):
            Observation(r, True, 0, "provider_reported", "response_received", 100, 512)
        with self.assertRaises(ValueError):
            Reservation(self.s.operation_id, 1, "arbitrary-private-text", 100, 512)

    def test_stalled_selected_boundaries_all_cut_off_without_cooperation(self):
        for stage in ("bootstrap", "reserve", "transport", "observer", "candidate", "authority"):
            with self.subTest(stage=stage):
                self.setUp()
                r = Reservation(self.s.operation_id, 1, "a" * 64, 100, 512)
                if stage == "bootstrap":
                    self.s = Supervisor(uuid4(), clock=self.clock)
                elif stage in ("reserve", "transport", "observer"):
                    self.child.request_round(r)
                    if stage != "reserve":
                        self.s.reservation_ack(r)
                    if stage == "observer":
                        self.child.report_usage(Observation(r, 30, 20, "provider_reported",
                                                           "response_received", 100, 512))
                else:
                    self.round()
                    self.child.proposed_result("b" * 64)
                    if stage == "authority":
                        self.s.candidate_ack("b" * 64)
                        self.s.closed("child")
                self.clock.now = 30
                self.s.tick()
                self.assertEqual(self.s.reason, "deadline")
                self.assertIn("authority", self.commands("terminate"))
                self.assertEqual(self.commands("deliver_success"), [])
                self.clock.now = 32
                self.s.tick()
                self.assertTrue(self.s.cleanup_unconfirmed)

    def test_changed_or_foreign_reservation_ack_stops_without_release(self):
        r = Reservation(self.s.operation_id, 1, "a" * 64, 100, 512)
        self.child.request_round(r)
        self.s.reservation_ack(replace(r, operation_id=uuid4()))
        self.assertEqual(self.s.reason, "protocol")
        self.assertEqual(self.commands("release_once"), [])


if __name__ == "__main__":
    unittest.main()
