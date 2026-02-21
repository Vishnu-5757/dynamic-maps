# monitoring/management/commands/ingest_observations.py
import os
import csv
import hashlib
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime
import datetime as _dt
from dateutil import parser as dateparser  # pip install python-dateutil

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.db import connection, transaction

from monitoring.models import Basin, DataType, Observation


# CONFIG
BATCH_SIZE = 2000  # tune this for your environment


def make_file_source(path):
    """Return deterministic source string for a file: filename::sha1(first 1MB)."""
    filename = os.path.basename(path)
    h = hashlib.sha1()
    with open(path, "rb") as f:
        chunk = f.read(1024 * 1024)  # read up to 1MB
        h.update(chunk)
    return f"{filename}::{h.hexdigest()[:12]}"


def get_logger(log_dir="logs"):
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    logfile = os.path.join(log_dir, f"ingest_observations_{ts}.log")
    logger = logging.getLogger(f"ingest_observations_{ts}")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(logfile, encoding="utf-8")
        fh.setLevel(logging.INFO)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
        fh.setFormatter(fmt)
        ch.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(ch)
    return logger, logfile


class Command(BaseCommand):
    help = "Ingest observations CSV. Usage: python manage.py ingest_observations <path> [--data-type Rainfall]"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str, help="Path to CSV file to ingest")
        parser.add_argument("--data-type", type=str, default=None,
                            help="DataType name (e.g. Rainfall, Temperature). Overrides CSV/filename inference.")
        parser.add_argument("--log-dir", type=str, default="logs", help="Directory to store logs")
        parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="Batch size for bulk upsert")
        parser.add_argument("--assume-tz-utc", action="store_true", default=True,
                            help="Assume naive datetimes are UTC (default True).")

    def handle(self, *args, **options):
        csv_path = options["csv_path"]
        data_type_arg = options["data_type"]
        log_dir = options["log_dir"]
        batch_size = options["batch_size"]
        assume_tz_utc = options["assume_tz_utc"]

        logger, logfile = get_logger(log_dir)
        logger.info("Starting ingestion: %s", csv_path)

        if not os.path.exists(csv_path):
            logger.error("CSV path does not exist: %s", csv_path)
            raise CommandError(f"CSV path does not exist: {csv_path}")

        source_deterministic = make_file_source(csv_path)
        logger.info("Deterministic source for this file: %s", source_deterministic)

        # Resolve CLI DataType
        cli_data_type_obj = None
        if data_type_arg:
            try:
                cli_data_type_obj = DataType.objects.get(name__iexact=data_type_arg.strip())
                logger.info("Using DataType from CLI: %s (id=%s)", cli_data_type_obj.name, cli_data_type_obj.id)
            except DataType.DoesNotExist:
                logger.error("DataType provided via --data-type not found: %s", data_type_arg)
                raise CommandError(f"DataType not found: {data_type_arg}")

        # Pre-load basin mapping (external basin identifier -> PK)
        basin_map = {b.basin_id: b.id for b in Basin.objects.all()}
        # We'll create new basins as we encounter them and update this map

        # Resolve/validate file reading
        total = 0
        ingested = 0
        skipped = 0
        errors = 0

        # Prepare batch containers for SQL multi-row upsert
        insert_rows = []  # list of tuples -> (basin_pk, data_type_pk, datetime_str, value_decimal_str, source_str)

        # Helper: flush batch to DB using INSERT ... ON DUPLICATE KEY UPDATE
        def flush_batch():
            nonlocal insert_rows, ingested, errors
            if not insert_rows:
                return
            # Build SQL with placeholders
            values_sql_parts = []
            params = []
            for (basin_pk, data_type_pk, dt_str, val_str, source_str) in insert_rows:
                values_sql_parts.append("(%s, %s, %s, %s, %s, NOW(), NOW())")
                params.extend([basin_pk, data_type_pk, dt_str, val_str, source_str])
            insert_sql = (
                "INSERT INTO monitoring_observation "
                "(basin_id, data_type_id, datetime, value, source, created_at, updated_at) VALUES "
                + ",".join(values_sql_parts)
                + " ON DUPLICATE KEY UPDATE value = VALUES(value), updated_at = NOW()"
            )
            try:
                with transaction.atomic():
                    with connection.cursor() as cur:
                        cur.execute(insert_sql, params)
                ingested += len(insert_rows)
                logger.info("Flushed batch of %d rows to DB", len(insert_rows))
            except Exception as e:
                # If the batch fails, log and attempt fallback (per-row)
                logger.exception("Batch upsert failed: %s. Falling back to per-row upsert.", e)
                # fallback per-row
                for (basin_pk, data_type_pk, dt_str, val_str, source_str) in insert_rows:
                    try:
                        # Use ORM update_or_create as fallback
                        b_obj = Basin.objects.get(pk=basin_pk)
                        dt_obj = DataType.objects.get(pk=data_type_pk)
                        dt_parsed = _dt.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_dt.timezone.utc)
                        Observation.objects.update_or_create(
                            basin=b_obj,
                            data_type=dt_obj,
                            datetime=dt_parsed,
                            source=source_str,
                            defaults={"value": Decimal(val_str)}
                        )
                        ingested += 1
                    except Exception as inner_e:
                        logger.exception("Fallback per-row upsert failed: %s", inner_e)
                        errors += 1
            insert_rows = []

        # Open CSV and iterate
        with open(csv_path, newline="", encoding="utf-8") as fh:
            sample = fh.read(8192)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample)
            except Exception:
                dialect = csv.get_dialect("excel")
            reader = csv.DictReader(fh, dialect=dialect)

            headers = reader.fieldnames or []
            normalized_headers = [h.strip().lower().replace(".", "_") for h in headers]
            header_map = dict(zip(normalized_headers, headers))

            for row_index, raw_row in enumerate(reader, start=1):
                total += 1
                # Normalize row: lower-case keys, replace '.' with '_'
                row = {}
                for orig_k, v in raw_row.items():
                    if orig_k is None:
                        continue
                    nk = orig_k.strip().lower().replace(".", "_")
                    row[nk] = (v or "").strip()

                # --- basin ---
                basin_key = "basin_id" if "basin_id" in row else ("basin" if "basin" in row else None)
                if not basin_key:
                    logger.error("Row %d: missing basin column -> skipping", row_index)
                    skipped += 1
                    errors += 1
                    continue
                basin_val = row.get(basin_key, "").strip()
                if not basin_val:
                    logger.error("Row %d: empty basin_id -> skipping", row_index)
                    skipped += 1
                    errors += 1
                    continue

                # --- data_type resolution ---
                dt_obj = None
                if cli_data_type_obj:
                    dt_obj = cli_data_type_obj
                else:
                    dt_name = row.get("data_type") or row.get("type") or ""
                    if dt_name:
                        try:
                            dt_obj = DataType.objects.get(name__iexact=dt_name.strip())
                        except DataType.DoesNotExist:
                            logger.error("Row %d: unknown data_type '%s' -> skipping", row_index, dt_name)
                            skipped += 1
                            errors += 1
                            continue
                    else:
                        fname = os.path.basename(csv_path).lower()
                        if "temp" in fname or "temperature" in fname:
                            guess = "Temperature"
                        elif "rain" in fname or "precip" in fname:
                            guess = "Rainfall"
                        else:
                            guess = None
                        if guess:
                            try:
                                dt_obj = DataType.objects.get(name__iexact=guess)
                                # only log initial inference; not per-row to reduce noise
                                if total == 1:
                                    logger.info("Inferred data_type '%s' from filename", guess)
                            except DataType.DoesNotExist:
                                logger.error("Row %d: inferred data_type '%s' not present -> skipping", row_index, guess)
                                skipped += 1
                                errors += 1
                                continue
                        else:
                            logger.error("Row %d: data_type not provided and cannot infer -> skipping", row_index)
                            skipped += 1
                            errors += 1
                            continue

                # --- parse datetime ---
                dt_raw = row.get("datetime") or row.get("date") or row.get("datetime_utc") or ""
                if not dt_raw:
                    logger.error("Row %d: missing datetime -> skipping", row_index)
                    skipped += 1
                    errors += 1
                    continue
                try:
                    parsed = dateparser.parse(dt_raw, dayfirst=True)
                    if parsed is None:
                        raise ValueError("dateutil returned None")
                    if parsed.tzinfo is None:
                        # treat naive timestamps as UTC (configurable)
                        if assume_tz_utc:
                            parsed = timezone.make_aware(parsed, timezone=_dt.timezone.utc)
                        else:
                            parsed = parsed.replace(tzinfo=_dt.timezone.utc)
                    parsed_utc = parsed.astimezone(_dt.timezone.utc)
                    # MySQL datetime format (no timezone): store as 'YYYY-MM-DD HH:MM:SS'
                    dt_for_db = parsed_utc.strftime("%Y-%m-%d %H:%M:%S")
                except Exception as e:
                    logger.error("Row %d: invalid datetime '%s' (%s) -> skipping", row_index, dt_raw, e)
                    skipped += 1
                    errors += 1
                    continue

                # --- parse value ---
                val_raw = row.get("value") or row.get("val") or ""
                if val_raw == "":
                    logger.error("Row %d: missing value -> skipping", row_index)
                    skipped += 1
                    errors += 1
                    continue
                try:
                    val_dec = Decimal(val_raw)
                    # convert to string for DB param (avoid Decimal->float issues)
                    val_str = format(val_dec, "f")
                except (InvalidOperation, ValueError) as e:
                    logger.error("Row %d: non-numeric value '%s' -> skipping", row_index, val_raw)
                    skipped += 1
                    errors += 1
                    continue

                # --- basin PK resolution (cache & create if missing) ---
                basin_pk = basin_map.get(basin_val)
                if basin_pk is None:
                    # create new Basin row and add to map
                    try:
                        b_obj, created = Basin.objects.get_or_create(basin_id=basin_val)
                        basin_pk = b_obj.id
                        basin_map[basin_val] = basin_pk
                        if created:
                            logger.info("Row %d: created new Basin basin_id=%s (id=%d)", row_index, basin_val, basin_pk)
                    except Exception as e:
                        logger.exception("Row %d: error creating/reading Basin %s -> skipping (%s)", row_index, basin_val, e)
                        skipped += 1
                        errors += 1
                        continue

                # --- prepare row for batch insert ---
                insert_rows.append((basin_pk, dt_obj.id, dt_for_db, val_str, source_deterministic))

                # flush if batch full
                if len(insert_rows) >= batch_size:
                    flush_batch()
                    # progress log
                    logger.info("Processed %d rows", total)

            # end for rows

        # flush remaining rows
        flush_batch()

        # final summary
        logger.info("Finished ingestion. total=%d ingested=%d skipped=%d errors=%d", total, ingested, skipped, errors)
        logger.info("Logfile: %s", logfile)
        self.stdout.write(self.style.SUCCESS(
            f"Ingestion complete. total={total} ingested={ingested} skipped={skipped} errors={errors}"
        ))
        self.stdout.write(self.style.NOTICE(f"See logfile: {logfile}"))
