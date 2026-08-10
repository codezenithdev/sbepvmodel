"""run_pipeline.py

One command to run the whole flow:

    1) sbepv.ingest.bazefield  -> pulls the STAC1 data to stac1.csv
    2) sbepv.model             -> reads stac1.csv, writes predictions + plots + Excel

Usage:
    python src/run_pipeline.py

Settings live in the two modules themselves:
  - Time window / interval  -> FROM_TIME / TO_TIME / INTERVAL in sbepv/ingest/bazefield.py
  - Model options / output  -> constants at the top of sbepv/model.py
The historian's OUTPUT_FILE must match the model's INPUT_CSV (both default to stac1.csv).
"""

from __future__ import annotations

import sys

from sbepv import model
from sbepv.ingest import bazefield as historian


def main() -> int:
    # Sanity: the model reads what the historian writes.
    if model.INPUT_CSV != historian.OUTPUT_FILE:
        print(
            f"Config mismatch: historian writes '{historian.OUTPUT_FILE}' but model reads "
            f"'{model.INPUT_CSV}'. Align OUTPUT_FILE / INPUT_CSV.",
            file=sys.stderr,
        )
        return 2

    print(f"[1/2] Pulling historian data -> {historian.OUTPUT_FILE} ...")
    rc = historian.main([])  # [] = defaults = static STAC1 pull
    if rc not in (0, None):
        print(f"Historian step failed (exit {rc}); not running the model.", file=sys.stderr)
        return int(rc)

    print(f"[2/2] Running PV model on {model.INPUT_CSV} ...")
    model.main()
    print("Pipeline complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
