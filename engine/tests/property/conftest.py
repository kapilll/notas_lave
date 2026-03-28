"""Hypothesis profile for CI — fast enough, thorough enough."""
from hypothesis import settings, HealthCheck

settings.register_profile("ci", max_examples=200, deadline=2000)
settings.load_profile("ci")
