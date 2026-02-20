# Part A — Data Modeling (Dynamic Basin Monitoring)

## Overview
This part implements the relational schema for the Dynamic Basin Monitoring platform using Django ORM + MySQL. It includes models for `Basin`, `BasinRelation`, `DataType`, and `Observation`, plus indexing and idempotent ingestion support.

## Models (brief)
- **Basin** — `basin_id` (unique), `name`, `metadata` (JSON)  

- **BasinRelation** — `from_basin`, `to_basin`, `relation_type`, `weight` (optional)  

- **DataType** — `name` (e.g., Rainfall, Temperature), `description`  

- **Observation** — stores hourly measurements (see details below)

---

### Observation model — schema assumptions & indexing

- **Fields**
  - `basin` (FK → Basin)  
  - `data_type` (FK → DataType)  
  - `datetime` (hourly timestamp) — store normalized to UTC on ingestion.  
  - `value` (DECIMAL(12,4)) — chosen for numeric precision.  
  - `source` (string, default `'unknown'`) — helps idempotency and provenance.

- **Idempotent ingestion**
  - Unique constraint: `(basin, data_type, datetime, source)` prevents duplicate inserts from the same source.  
  - Upsert strategies: use Django `update_or_create(...)` or MySQL `INSERT ... ON DUPLICATE KEY UPDATE`.

- **Indexing (performance)**
  - Composite index `(basin, data_type, datetime)` — optimized for queries like: "observations for basin X and data_type Y between time A and B".  
  - Composite index `(data_type, datetime)` — optimized for cross-basin queries by measurement type and time range.  
  - Single-column index `(datetime)` — optimized for global time-range queries (e.g., last N hours across all basins).

- **Notes**
  - Use deterministic `source` (e.g., filename + checksum) for repeated imports to allow idempotent upserts by source.  
  - For very large datasets, consider time-based partitioning by `datetime` or moving older data to archive tables.

---

## How to run (quick)
1. Configure MySQL in `dynamic_maps/settings.py`.  
2. Install dependencies and activate venv:
   ```bash
   pip install -r requirements.txt
