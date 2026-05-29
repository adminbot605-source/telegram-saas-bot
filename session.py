"""
Prometheus-compatible metrics endpoint.
Implements a minimal text format /metrics handler without heavy dependencies.

Counters:
  bot_messages_deleted_total{group_id}
  bot_messages_allowed_total
  bot_cache_hits_total
  bot_cache_misses_total
  bot_payments_approved_total
  bot_payments_rejected_total
  bot_floodwait_total
  bot_delete_queue_processed_total
  bot_delete_dlq_total

Gauges:
  bot_delete_queue_depth
  bot_delete_retry_depth
  bot_delete_dlq_depth
  bot_active_groups

Histograms (simple buckets):
  bot_delete_latency_seconds_bucket
"""

import asyncio
import time
from collections import defaultdict
from typing import Dict, Optional
from aiohttp import web
from loguru import logger


class Counter:
    def __init__(self, name: str, help_text: str, labels: tuple = ()):
        self.name = name
        self.help_text = help_text
        self.labels = labels
        self._values: Dict[tuple, float] = defaultdict(float)

    def inc(self, amount: float = 1.0, **label_values) -> None:
        key = tuple(label_values.get(l, "") for l in self.labels)
        self._values[key] += amount

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} counter"]
        for key, val in self._values.items():
            if key:
                label_str = ",".join(f'{l}="{v}"' for l, v in zip(self.labels, key))
                lines.append(f"{self.name}{{{label_str}}} {val}")
            else:
                lines.append(f"{self.name} {val}")
        return "\n".join(lines)


class Gauge:
    def __init__(self, name: str, help_text: str, labels: tuple = ()):
        self.name = name
        self.help_text = help_text
        self.labels = labels
        self._values: Dict[tuple, float] = defaultdict(float)

    def set(self, value: float, **label_values) -> None:
        key = tuple(label_values.get(l, "") for l in self.labels)
        self._values[key] = value

    def inc(self, amount: float = 1.0, **label_values) -> None:
        key = tuple(label_values.get(l, "") for l in self.labels)
        self._values[key] += amount

    def dec(self, amount: float = 1.0, **label_values) -> None:
        key = tuple(label_values.get(l, "") for l in self.labels)
        self._values[key] -= amount

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} gauge"]
        for key, val in self._values.items():
            if key:
                label_str = ",".join(f'{l}="{v}"' for l, v in zip(self.labels, key))
                lines.append(f"{self.name}{{{label_str}}} {val}")
            else:
                lines.append(f"{self.name} {val}")
        return "\n".join(lines)


class Histogram:
    BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

    def __init__(self, name: str, help_text: str):
        self.name = name
        self.help_text = help_text
        self._buckets: Dict[float, int] = {b: 0 for b in self.BUCKETS}
        self._sum = 0.0
        self._count = 0

    def observe(self, value: float) -> None:
        self._sum += value
        self._count += 1
        for b in self.BUCKETS:
            if value <= b:
                self._buckets[b] += 1

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} histogram"]
        cumulative = 0
        for b, count in sorted(self._buckets.items()):
            cumulative += count
            lines.append(f'{self.name}_bucket{{le="{b}"}} {cumulative}')
        lines.append(f'{self.name}_bucket{{le="+Inf"}} {self._count}')
        lines.append(f"{self.name}_sum {self._sum}")
        lines.append(f"{self.name}_count {self._count}")
        return "\n".join(lines)


class BotMetrics:
    def __init__(self):
        self.messages_deleted = Counter("bot_messages_deleted_total", "Total messages deleted by bot")
        self.messages_allowed = Counter("bot_messages_allowed_total", "Total messages allowed through")
        self.cache_hits = Counter("bot_cache_hits_total", "Redis access cache hits")
        self.cache_misses = Counter("bot_cache_misses_total", "Redis access cache misses (DB fallback)")
        self.payments_approved = Counter("bot_payments_approved_total", "Payments approved")
        self.payments_rejected = Counter("bot_payments_rejected_total", "Payments rejected")
        self.floodwait_total = Counter("bot_floodwait_total", "Telegram FloodWait errors encountered")
        self.queue_processed = Counter("bot_delete_queue_processed_total", "Delete tasks processed from queue")
        self.dlq_total = Counter("bot_delete_dlq_total", "Delete tasks sent to DLQ")
        self.errors_total = Counter("bot_errors_total", "Unhandled errors", labels=("handler",))

        self.queue_depth = Gauge("bot_delete_queue_depth", "Current delete queue depth")
        self.retry_depth = Gauge("bot_delete_retry_depth", "Current retry queue depth")
        self.dlq_depth = Gauge("bot_delete_dlq_depth", "Current DLQ depth")
        self.active_groups = Gauge("bot_active_groups_total", "Groups with access control enabled")
        self.cache_warm_groups = Gauge("bot_cache_warm_groups", "Groups with warm access cache")

        self.delete_latency = Histogram("bot_delete_latency_seconds", "Delete message latency")

        self._start_time = time.time()

    def render_all(self) -> str:
        uptime = time.time() - self._start_time
        parts = [
            f"# HELP bot_uptime_seconds Bot uptime in seconds",
            f"# TYPE bot_uptime_seconds gauge",
            f"bot_uptime_seconds {uptime:.1f}",
        ]
        for metric in [
            self.messages_deleted, self.messages_allowed,
            self.cache_hits, self.cache_misses,
            self.payments_approved, self.payments_rejected,
            self.floodwait_total, self.queue_processed,
            self.dlq_total, self.errors_total,
            self.queue_depth, self.retry_depth,
            self.dlq_depth, self.active_groups, self.cache_warm_groups,
            self.delete_latency,
        ]:
            parts.append(metric.render())
        return "\n".join(parts) + "\n"

    async def update_queue_gauges(self, delete_queue) -> None:
        try:
            self.queue_depth.set(await delete_queue.queue_size())
            self.retry_depth.set(await delete_queue.retry_size())
            self.dlq_depth.set(await delete_queue.dlq_size())
        except Exception:
            pass


metrics = BotMetrics()


async def metrics_handler(request: web.Request) -> web.Response:
    dq = request.app.get("delete_queue")
    if dq:
        await metrics.update_queue_gauges(dq)
    return web.Response(
        text=metrics.render_all(),
        content_type="text/plain",
        charset="utf-8",
    )
