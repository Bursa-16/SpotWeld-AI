
from app.domain.failure_probability import analyze_failure_probabilities


class FailureProbabilityService:
    def analyze(self, payload):
        return analyze_failure_probabilities(**payload.model_dump())
