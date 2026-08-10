"""Background execution of queued model jobs.

- ``loop``           -- the worker thread: lease, heartbeat, dispatch
- ``run_validation`` -- one calibration run (Bazefield historian source)
- ``run_annual``     -- one annual simulation (MIDC source)
- ``completion``     -- recording success or failure, lease-fenced
"""
