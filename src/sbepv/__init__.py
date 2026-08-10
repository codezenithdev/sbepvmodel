"""SB Energy PV operations backend.

Layout:

- ``sbepv.model``       -- PV physics (pvlib / pvmismatch) and result rendering
- ``sbepv.calibration`` -- historian data-quality review and seasonal factor fitting
- ``sbepv.store``       -- SQLite persistence for proposals, jobs, and baselines
- ``sbepv.reporting``   -- scenario comparison plus workbook/plot artifacts
- ``sbepv.dashboard``   -- deterministic assembly of the dashboard frontend
- ``sbepv.ingest``      -- Bazefield and MIDC data pullers (library + CLI)
- ``sbepv.api``         -- the FastAPI application
- ``sbepv.paths``       -- repository-root discovery shared by the above

Importing ``sbepv.api.main`` has side effects by design: it loads ``.env``,
creates the output directories, and opens the agent SQLite database.
"""
