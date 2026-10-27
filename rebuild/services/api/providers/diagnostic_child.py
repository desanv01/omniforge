"""Thin synthetic event facade, deliberately not wired to answer or live I/O."""
from .diagnostic_protocol import Observation, Reservation


class ChildFacade:
    def __init__(self, controller):
        self.controller = controller

    def request_round(self, reservation: Reservation):
        self.controller.reserve(reservation)

    def report_usage(self, observation: Observation):
        self.controller.observe(observation)

    def proposed_result(self, candidate_digest):
        # A safe ProviderResult does not bypass the controller's permanent latch.
        self.controller.propose_candidate(candidate_digest)

    def observer_failed(self):
        self.controller.failed_ack()
