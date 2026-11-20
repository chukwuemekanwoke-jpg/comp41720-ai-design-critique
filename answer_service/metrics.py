"""Per-process Prometheus metrics with bounded, non-content labels."""
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class AnswerMetrics:
    def __init__(self):
        # A registry per app avoids shared counters across tests/app factories.
        self.registry = CollectorRegistry()
        self.requests = Counter('studentpath_answer_requests', 'Answer HTTP requests.',
                                ['status_class'], registry=self.registry)
        self.duration = Histogram('studentpath_answer_request_duration_seconds',
                                  'Answer HTTP latency, including model waiting.',
                                  buckets=(.01, .05, .1, .25, .5, 1, 2, 5, 10, 20, 30),
                                  registry=self.registry)
        self.responses = Counter('studentpath_answer_responses', 'Validated answer outcomes.',
                                 ['status'], registry=self.registry)
        self.attempts = Counter('studentpath_answer_model_attempts', 'Ollama HTTP attempts.',
                                ['result'], registry=self.registry)
        self.retries = Counter('studentpath_answer_model_retries', 'Retries scheduled within the deadline.',
                               registry=self.registry)
        self.active = Gauge('studentpath_answer_model_active', 'Admitted model requests, including backoff.',
                            registry=self.registry)
        self.rejected = Counter('studentpath_answer_model_rejected', 'Requests rejected by the bulkhead.',
                                registry=self.registry)
        self.tokens = Counter('studentpath_answer_model_tokens', 'Tokens reported by Ollama; not a budget.',
                              ['kind'], registry=self.registry)
        self.missing_usage = Counter('studentpath_answer_model_usage_missing',
                                     'Successful HTTP responses without a valid token count.',
                                     ['kind'], registry=self.registry)

    def observe_usage(self, body):
        for kind, field in (('input', 'prompt_eval_count'), ('output', 'eval_count')):
            value = body.get(field) if isinstance(body, dict) else None
            if type(value) is int and value >= 0:
                self.tokens.labels(kind=kind).inc(value)
            else:
                self.missing_usage.labels(kind=kind).inc()
