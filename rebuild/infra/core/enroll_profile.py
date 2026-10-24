"""Trusted local callable requiring explicit authentication and injected I/O.

No CLI, environment discovery, default prompt or OS store is provided. Actual
enrollment must be a separately authorized local invocation; this slice uses fakes.
"""
from adapters.secrets.enrollment import EnrollmentBinding, EnrollmentReceipt, enroll_new
from services.api.errors import Problem
from services.api.profiles import bindings


def enroll_profile(engine, *, bearer_token, request, store, hidden_input):
    captured = None
    def reserve(candidate):
        nonlocal captured
        result = bindings.reserve(engine, bearer_token, candidate)
        if result.disposition == "ready":
            captured = result.binding
        return result
    try:
        result = enroll_new(request=request, reserve=reserve, hidden_input=hidden_input,
                            authorize_put=lambda bound: bindings.authorize_put(engine, bearer_token, bound), store=store)
        if type(result) is EnrollmentReceipt:
            return result  # Historical receipt; never re-prompt, put, append or activate.
        if type(result) is not EnrollmentBinding or result != captured:
            raise Problem(409, "enrollment_uncertain", "conflict", "Enrollment outcome requires explicit recovery")
        return bindings.attach(engine, bearer_token, result)
    except (Exception, KeyboardInterrupt):
        if captured is not None:
            bindings.unresolved(engine, captured)
        raise Problem(409, "enrollment_incomplete", "conflict", "Enrollment did not complete; explicit recovery required") from None
