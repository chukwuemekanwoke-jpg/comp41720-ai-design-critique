"""Run three separate local HTTP services and verify synthetic Gateway responses.

No real model, policy fetch or broker required. All subprocesses are stopped on
completion. Uses ephemeral loopback ports; never changes running user services.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def main():
    root = Path(__file__).resolve().parents[1]
    ports = set()
    while len(ports) < 3:
        ports.add(free_port())
    retrieval_port, answer_port, gateway_port = sorted(ports)
    env = os.environ.copy()
    env.update(RETRIEVAL_BASE_URL=f"http://127.0.0.1:{retrieval_port}",
               ANSWER_BASE_URL=f"http://127.0.0.1:{answer_port}",
               ANSWER_GENERATION_MODE="evidence_only", GATEWAY_CORS_ORIGINS="http://localhost:8080",
               GATEWAY_RETRIEVAL_TIMEOUT_SECONDS="3", GATEWAY_ANSWER_TIMEOUT_SECONDS="23",
               GATEWAY_TOTAL_TIMEOUT_SECONDS="30")
    processes = []
    try:
        for target, port, factory in [
            ("retrieval_api.app:create_demo_app", retrieval_port, True),
            ("answer_service.app:app", answer_port, False),
            ("gateway.app:app", gateway_port, False),
        ]:
            command = [sys.executable, "-m", "uvicorn", target, "--host", "127.0.0.1", "--port", str(port)]
            if factory:
                command.append("--factory")
            processes.append(subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        with httpx.Client(base_url=f"http://127.0.0.1:{gateway_port}", timeout=5, trust_env=False) as client:
            deadline = time.monotonic() + 20
            while True:
                if any(process.poll() is not None for process in processes):
                    raise RuntimeError("A local service exited before readiness")
                try:
                    if client.get("/readyz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("Local HTTP services did not become ready")
                time.sleep(0.1)
            response = client.post("/v1/questions", json={"question": "Stamp 1G graduate requirements?"},
                                   headers={"X-Request-ID": "http-smoke-1", "Origin": "http://localhost:8080"})
            response.raise_for_status()
            body = response.json()
            assert body["status"] == "degraded" and body["sources"] and body["answer"] is None
            assert body["index_version"].startswith("demo-") and "stub" not in body
            assert body["request_id"] == response.headers["X-Request-ID"] == "http-smoke-1"
            assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:8080"
            missing = client.post("/v1/questions", json={"question": "zzzzzzzz"})
            missing.raise_for_status()
            assert missing.json()["status"] == "insufficient_evidence"
            print(json.dumps({"http_services": 3, "evidence_status": body["status"],
                "index_version": body["index_version"], "source_count": len(body["sources"]),
                "empty_status": missing.json()["status"], "request_id_preserved": True,
                "cors": "passed", "synthetic_evidence_only": True}))
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
