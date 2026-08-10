"""Vendor data pullers that produce the CSVs the PV model consumes.

Both modules are library + CLI hybrids. Nothing is re-exported here on purpose:
``sbepv.ingest.bazefield`` is standard-library only, and pulling it through a
package-level re-export alongside ``sbepv.ingest.midc`` would drag pandas into
that dependency-free path.
"""
