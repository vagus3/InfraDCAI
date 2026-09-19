from __future__ import annotations

import argparse
import asyncio
import time
from datetime import datetime, timezone
import httpx


async def run(target: str, ingest: str, tenant: str, interval: float):
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            started = time.perf_counter()
            ready = 0.0
            status = 0
            try:
                response = await client.get(target.rstrip("/") + "/ready")
                status = response.status_code
                ready = 1.0 if response.is_success else 0.0
            except Exception:
                ready = 0.0
            latency = time.perf_counter() - started
            now = datetime.now(timezone.utc).isoformat()
            for payload in [
                {"tenant": tenant, "metric": "readiness", "value": ready, "unit": "boolean", "observed_at": now},
                {"tenant": tenant, "metric": "p95_latency", "value": latency, "unit": "seconds", "endpoint": "/ready", "observed_at": now, "labels": {"status": str(status)}},
            ]:
                try:
                    await client.post(ingest.rstrip("/") + "/api/v1/signals/telemetry", json=payload)
                except Exception as exc:
                    print(f"collector ingest failed: {exc}")
            print(f"{now} ready={ready:.0f} latency={latency:.3f}s status={status}")
            await asyncio.sleep(interval)


def main():
    p = argparse.ArgumentParser(description="Continuously probe a workload and stream signals to IncidentOps")
    p.add_argument("--target", required=True, help="Workload base URL")
    p.add_argument("--ingest", default="http://127.0.0.1:8090", help="IncidentOps base URL")
    p.add_argument("--tenant", default="demo-customer")
    p.add_argument("--interval", type=float, default=15.0)
    args = p.parse_args()
    asyncio.run(run(args.target, args.ingest, args.tenant, args.interval))


if __name__ == "__main__":
    main()
