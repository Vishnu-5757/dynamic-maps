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







## Part B — Data Ingestion Pipeline (management command)

### Overview
A management command ingests hourly CSV files (Rainfall / Temperature) into the Django `Observation` table, handling duplicates idempotently and logging errors.  
Command path: `monitoring/management/commands/ingest_observations.py`.

Key goals:
- Support both CSV header shapes used in the dataset (e.g. `Datetime,Value,Basin.ID` and `datetime,value,basin`).
- Idempotent ingestion (re-running the same file will not create duplicates).
- Graceful error logging for invalid datetime, missing basin_id, non-numeric values, unknown data types.
- Fast bulk upsert using batched multi-row `INSERT ... ON DUPLICATE KEY UPDATE` (tuned by `--batch-size`).

---

### Features
- Accepts `--data-type` CLI argument (e.g., `Rainfall` or `Temperature`) or infers data type from CSV filename or CSV column.
- Deterministic `source` for idempotency: `filename::sha1prefix` (so same file re-run updates existing rows).
- Cached `Basin` lookups and automatic `Basin` creation on first encounter.
- Batch upsert to the DB for high performance (default `BATCH_SIZE = 2000`).
- Detailed per-run logfile written to `logs/ingest_observations_<timestamp>.log`.

---

### Files committed
- `monitoring/management/commands/ingest_observations.py` — main ingestion command
- `logs/` — (recommended) include a trimmed sample logfile showing success/errors (optional)
- `README.md` — this documentation

---

### Usage

1. Place CSV(s) at the project root `data/` folder (same level as `manage.py`):


dynamic_maps/
├─ manage.py
├─ monitoring/
├─ data/
│ ├─ january_data_temp.csv
│ └─ january_data_rain.csv
└─ logs/


2. Ensure `DataType` rows exist in DB (one-time):

--```bash
-- python manage.py shell
-- >>> from monitoring.models import DataType
-- >>> DataType.objects.get_or_create(name='Rainfall')
-- >>> DataType.objects.get_or_create(name='Temperature')
-- >>> exit()



# Temperature
--- python manage.py ingest_observations data/january_data_temp.csv --data-type Temperature

# Rainfall
--- python manage.py ingest_observations data/january_data_rain.csv --data-type Rainfall





## Part C — Django REST API (DRF)

Base path (all endpoints): `http://<host>:<port>/api/`  
Example base: `http://127.0.0.1:8000/api/`

---

### Summary of resources
- **Basins** — `/api/basins/` (CRUD + search + timeseries + upstream aggregation)
- **Basin relations** — `/api/basin-relations/` (CRUD)
- **Data types** — `/api/data-types/` (CRUD)
- **Observations** — `/api/observations/` (CRUD + filtering + pagination + threshold search)

---

## 1) Basins

POST /api/basins/

curl -X POST http://127.0.0.1:8000/api/basins/ \
  -H "Content-Type: application/json" \
  -d '{"basin_id":"2046","name":"Example Basin","metadata":{"region":"north"}}'

sample response (201)


  {
    "id": 677,
    "basin_id": "20463",
    "name": "Example Basin",
    "metadata": {
        "region": "north"
    },
    "created_at": "2026-02-21T11:22:49.019252Z",
    "updated_at": "2026-02-21T11:22:49.019543Z"
}


GET /api/basins/{id}/
PUT /api/basins/{id}/
PATCH /api/basins/{id}/
DELETE /api/basins/{id}/



## 2) BasinRelations

POST /api/basin-relations/

curl -X POST http://127.0.0.1:8000/api/basin-relations/ \

-H "Content-Type: application/json" \
-d '{
    "from_basin": 1,
    "to_basin": 2,
    "relation_type": "upstream_to_downstream",
    "weight": 1.0
}'


GET /api/basin-relations/{id}/
PUT /api/basin-relations/{id}/
PATCH /api/basin-relations/{id}/
DELETE /api/basin-relations/{id}/



## 3. Data Types CRUD

POST /api/data-types/


curl -X POST http://127.0.0.1:8000/api/data-types/ \
-H "Content-Type: application/json" \
-d '{
    "name": "Rainfall",
    "description": "Hourly rainfall in mm"
}'


GET /api/data-types/{id}/
PUT /api/data-types/{id}/
PATCH /api/data-types/{id}/
DELETE /api/data-types/{id}/


## 4. Observation CRUD

POST /api/observations/



curl -X POST http://127.0.0.1:8000/api/observations/ \
-H "Content-Type: application/json" \
-d '{
    "basin": 1,
    "data_type": 1,
    "datetime": "2019-01-01T01:00:00Z",
    "value": 2.5,
    "source": "manual"
}'



GET /api/observations/{id}/
PUT /api/observations/{id}/
PATCH /api/observations/{id}/
DELETE /api/observations/{id}/




- Analytics:
  - Basin timeseries (last 24h or custom window)
    GET /api/basins/{id}/timeseries?data_type=Temperature&window=24h

  - Upstream rainfall aggregation
    GET /api/basins/{id}/upstream_aggregate?data_type=Rainfall&window=24h&depth=1




### Part D: Basic UI Dashboard

The dashboard provides a centralized view for environmental data analysis.
* **Interactive Filtering:** Toggle between Rainfall and Temperature for any Basin ID.
* **Time Windows:** Support for custom ranges and a "Last 24 Hours" quick-toggle.
* **Visual Analytics:** Responsive line charts powered by **Chart.js**.
* **Live Summary:** Instant calculation of Min, Max, Mean, and Total values.



Main Dashboard	/monitoring/dashboard/	      The primary interactive UI with line charts and data summary cards.
Timeseries API	/monitoring/api/timeseries/	  Raw JSON endpoint (supports basin_id, data_type, start, and end parameters).
Django Admin	/admin/	                      secure administrative panel to manage Basins, Relationships, and Observations.





## ⚡ Performance & Caching (Part E)

To ensure sub-second response times, the system implements a robust caching strategy using **Redis**.

### 1. Caching Strategy
* **Timeseries Cache:** Caches the result of API calls based on a unique key: `timeseries:{basin_id}:{data_type}:{resolution}:{start}:{end}`.
* **Upstream Cache:** Caches recursive parent-child aggregations to avoid heavy database JOINs.
* **TTL (Time-To-Live):** 300 seconds (5 minutes) default.






## 🛠️ Testing & Quality (Part F)

### 1. Database Optimization
The `Observation` model is optimized with a **composite index** on `(basin, data_type, datetime)`. 
* **Benefit:** Reduces query time from $O(n)$ to $O(\log n)$, allowing the dashboard to remain fast even with millions of observations.

**Run tests:**
bash
pip install pytest pytest-django
pytest



## How to run (quick)


# Clone the repository
git clone https://github.com/Vishnu-5757/dynamic-maps.git
cd dynamic_maps

# Create and activate a virtual environment
python -m venv venv

# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt


1. Configure MySQL in `dynamic_maps/settings.py`.  
Open dynamic_maps/settings.py and update the DATABASES section with your MySQL USER and PASSWORD.

# Apply migrations to create tables and performance indexes
python manage.py migrate

# Create a superuser for the Admin Panel
python manage.py createsuperuser

# Create Data Types (Rainfall and Temperature)
python manage.py shell -c "from monitoring.models import DataType; DataType.objects.get_or_create(name='Rainfall'); DataType.objects.get_or_create(name='Temperature')"

# Ingest Temperature data
python manage.py ingest_observations data/january_data_temp.csv --data-type Temperature

# Ingest Rainfall data
python manage.py ingest_observations data/january_data_rain.csv --data-type Rainfall

5. Start the Application
Bash
python manage.py runserver

Dashboard: http://127.0.0.1:8000/monitoring/dashboard/

Admin: http://127.0.0.1:8000/admin/

6. Run Automated Tests (Part F)
To verify the API and aggregation logic:

Bash
pytest