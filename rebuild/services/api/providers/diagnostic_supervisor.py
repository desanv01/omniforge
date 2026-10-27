"""Injected event controller only. Commands are proposals, never process operations."""
from uuid import UUID

from .diagnostic_protocol import Observation, Reservation, integer


class Supervisor:
    def __init__(self, operation_id, *, clock, wall_seconds=30, input_cap=32768, output_cap=1024, calls_cap=2):
        if type(operation_id) is not UUID:
            raise ValueError("invalid operation")
        integer(wall_seconds, 30)
        integer(input_cap, 32768)
        integer(output_cap, 1024)
        integer(calls_cap, 2)
        if not wall_seconds or not input_cap or not output_cap or not calls_cap:
            raise ValueError("invalid budget")
        self.operation_id, self.clock = operation_id, clock
        self.started = clock()
        self.deadline = self.started + wall_seconds
        self.input_cap, self.output_cap = input_cap, output_cap
        self.calls_cap = calls_cap
        self.state, self.reason = "bootstrap", None
        self.commands = []
        self.reservations, self.committed, self.released = {}, set(), set()
        self.observations, self.usage_acks = {}, set()
        self.candidate = None
        self.candidate_committed = False
        self.owned = {"child", "authority"}
        self.cleanup_unconfirmed = False
        self.settlement = "not_started"
        self.cleanup_deadline = self.settlement_deadline = None
        self.settlement_termination_issued = False

    def stop(self, reason="canceled"):
        if self.reason is not None or self.state == "delivered":
            return
        self.reason = reason if reason in ("canceled", "deadline", "durability", "protocol", "authority", "interrupted", "budget") else "protocol"
        self.state = "stopped"
        self.cleanup_deadline = min(self.clock(), self.deadline) + 2
        self.settlement_deadline = self.cleanup_deadline + 2
        for owner in sorted(self.owned):
            self.commands.append(("terminate", owner))
        # Termination is independent of whether any durable stop write succeeds.

    def live(self):
        if self.reason is None and self.state != "delivered" and self.clock() >= self.deadline:
            self.stop("deadline")
        return self.reason is None and self.state != "delivered"

    def tick(self):
        self.live()
        if self.reason is None:
            return
        now = self.clock()
        if now >= self.cleanup_deadline and self.owned - {"settlement"}:
            self.cleanup_unconfirmed = True
        if self.settlement == "not_started" and not self.owned and now < self.cleanup_deadline:
            self.settlement = "pending"
            self.settlement_deadline = min(self.settlement_deadline, now + 2)
            self.owned.add("settlement")
            self.commands.append(("settle_only", self.settlement_deadline))
        # Reserve the last half-second of final grace for settlement-helper disposal.
        if (self.settlement in ("pending", "recorded") and "settlement" in self.owned
                and not self.settlement_termination_issued and now >= self.settlement_deadline - 0.5):
            self.settlement_termination_issued = True
            if self.settlement == "pending":
                self.settlement = "unsettled"
            self.commands.append(("terminate", "settlement"))
        if now >= self.settlement_deadline and self.owned:
            self.cleanup_unconfirmed = True

    def admitted(self, *, pinned_wall_seconds, pinned_calls_cap=None, pinned_input_cap=None, pinned_output_cap=None):
        integer(pinned_wall_seconds, 30)
        for value, maximum in ((pinned_calls_cap, 2), (pinned_input_cap, 32768), (pinned_output_cap, 1024)):
            if value is not None:
                integer(value, maximum)
                if not value:
                    self.stop("protocol")
                    return
        if self.reservations:
            self.stop("protocol")
            return
        if not pinned_wall_seconds:
            self.stop("protocol")
            return
        # Pin can only shorten the original deadline, including elapsed bootstrap.
        self.deadline = min(self.deadline, self.started + pinned_wall_seconds)
        # Trusted admission supplies effective profile caps; None preserves an
        # already validated initialization cap. Every dimension only narrows.
        self.calls_cap = min(self.calls_cap, pinned_calls_cap if pinned_calls_cap is not None else self.calls_cap)
        self.input_cap = min(self.input_cap, pinned_input_cap if pinned_input_cap is not None else self.input_cap)
        self.output_cap = min(self.output_cap, pinned_output_cap if pinned_output_cap is not None else self.output_cap)
        if self.live() and self.state == "bootstrap":
            self.state = "running"

    def reserve(self, value):
        if not self.live():
            return
        if type(value) is not Reservation or value.operation_id != self.operation_id or self.state != "running":
            self.stop("protocol")
            return
        old = self.reservations.get(value.round_seq)
        if old is not None:
            if old != value:
                self.stop("protocol")
            return
        if value.round_seq != len(self.reservations) + 1 or len(self.usage_acks) != len(self.reservations):
            self.stop("protocol")
            return
        used_input, used_output = self.charges
        if (len(self.reservations) >= self.calls_cap or used_input + value.input_estimate > self.input_cap
                or used_output + value.output_max > self.output_cap):
            self.stop("budget")
            return
        self.reservations[value.round_seq] = value
        self.commands.append(("reserve", value))

    def reservation_ack(self, value):
        if type(value) is Reservation and value.operation_id == self.operation_id and self.reservations.get(value.round_seq) == value:
            self.committed.add(value.round_seq)  # Late committed history remains possible.
        else:
            self.stop("protocol")
            return
        if self.live() and value.round_seq not in self.released:
            self.released.add(value.round_seq)
            self.commands.append(("release_once", value))

    def observe(self, value):
        if not self.live():
            return
        if (type(value) is not Observation or value.reservation.operation_id != self.operation_id
                or self.reservations.get(value.reservation.round_seq) != value.reservation
                or value.reservation.round_seq not in self.released):
            self.stop("protocol")
            return
        seq = value.reservation.round_seq
        if seq in self.observations:
            if self.observations[seq] != value:
                self.stop("protocol")
            return
        self.observations[seq] = value
        self.commands.append(("observe_usage", value))

    def usage_ack(self, value):
        if type(value) is not Observation or self.observations.get(value.reservation.round_seq) != value:
            self.stop("protocol")
            return
        if self.live():
            self.usage_acks.add(value.reservation.round_seq)
            if self.charges[0] > self.input_cap or self.charges[1] > self.output_cap:
                self.stop("budget")

    @property
    def charges(self):
        return tuple(sum((getattr(self.observations[seq], name) if seq in self.usage_acks else getattr(r, fallback))
                         for seq, r in self.reservations.items())
                     for name, fallback in (("charged_input", "input_estimate"), ("charged_output", "output_max")))

    @property
    def usage(self):
        result = {"possible_dispatch_upper_bound": len(self.reservations), "accepted_request_lower_bound": 0}
        for name in ("input_tokens", "output_tokens"):
            values = [getattr(self.observations[seq], name) if seq in self.usage_acks else None for seq in self.reservations]
            result[name] = sum(values) if all(v is not None for v in values) else None
            result["known_" + name + "_subtotal"] = sum(v or 0 for v in values)
        return result

    def propose_candidate(self, candidate_digest):
        if not self.live():
            return
        if (self.state != "running" or not self.reservations or len(self.usage_acks) != len(self.reservations)
                or type(candidate_digest) is not str or len(candidate_digest) != 64
                or any(c not in "0123456789abcdef" for c in candidate_digest)):
            self.stop("protocol")
            return
        self.candidate, self.state = candidate_digest, "candidate_pending"
        self.commands.append(("commit_candidate", candidate_digest))

    def candidate_ack(self, candidate_digest):
        if self.candidate is None or candidate_digest != self.candidate:
            self.stop("protocol")
            return
        self.candidate_committed = True
        if self.live() and self.state == "candidate_pending":
            self.state = "child_cleanup"
            self.commands.append(("dispose", "child"))

    def closed(self, owner):
        if owner not in self.owned:
            self.stop("protocol")
            return
        self.owned.remove(owner)
        if not self.live():
            self.tick()
            return
        if owner == "child" and self.state == "child_cleanup":
            self.state = "final_authority"
            self.commands.append(("check_current_authority", self.operation_id))
        elif owner == "authority" and self.state == "authority_cleanup":
            if not self.owned and self.live():
                self.state = "delivered"
                self.commands.append(("deliver_success", self.candidate))
        else:
            self.stop("protocol")

    def authority_ack(self, allowed):
        if not self.live():
            return
        if self.state != "final_authority" or allowed is not True:
            self.stop("authority")
            return
        self.state = "authority_cleanup"
        self.commands.append(("dispose", "authority"))

    def failed_ack(self):
        self.stop("durability")

    def settlement_ack(self):
        if self.reason is not None and self.settlement == "pending" and self.clock() < self.settlement_deadline - 0.5:
            self.settlement = "recorded"
            self.commands.append(("dispose", "settlement"))
