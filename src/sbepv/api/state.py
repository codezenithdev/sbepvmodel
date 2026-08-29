"""Process-wide mutable state shared by the API and the background worker.

Everything here is a singleton for the lifetime of the process. It lives in its
own module so the request handlers, the job worker, and the tests all name the
same objects without importing each other.

Access these through the module (``state.AGENT_STORE``), never via
``from .state import AGENT_STORE``. Tests swap ``AGENT_STORE`` for a temporary
SQLite database by assigning to ``state.AGENT_STORE``; a value import would keep
pointing at the real one and quietly write to the developer's own outputs.
"""

from __future__ import annotations

import threading

from sbepv.api import config
from sbepv.store import AgentStore

# ``JOBS`` remains as a live compatibility/read-through cache for existing local
# integrations. SQLite is the authoritative registry and survives restarts.
JOBS: dict[str, dict] = {}
AGENT_STORE = AgentStore(config.OUTPUT_DIR / ".agent_state" / "solar_agent.sqlite3")
# Turn tasks outlive individual SSE connections so a browser reconnect never
# duplicates an agent run. Durable turn/event rows remain authoritative.
DECISION_AGENT_TASKS: dict[str, object] = {}
_WORKER_STOP = threading.Event()
_WORKER_WAKE = threading.Event()
_WORKER_LOCK = threading.Lock()
_ORCHESTRATION_LOCK = threading.RLock()
_WORKER_THREAD: threading.Thread | None = None
_APP_STARTED = False
