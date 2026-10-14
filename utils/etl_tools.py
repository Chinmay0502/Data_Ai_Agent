import os
import shutil
import tempfile
import time
from pathlib import Path

import pandas as pd
import requests


# Shared temporary workspace for the portfolio demo.
DATA_ROOT = Path(tempfile.gettempdir()) / "ola_data_agent"
EXTRACT_DIR = DATA_ROOT / "extract"
TRANSFORM_DIR = DATA_ROOT / "transform"

EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
TRANSFORM_DIR.mkdir(parents=True, exist_ok=True)

CLEANUP_AFTER_SECONDS = 10 * 60


def cleanup_old_files():
    """Delete generated files after 10 minutes without activity."""
    marker = DATA_ROOT / ".activity"

    if marker.exists():
        if time.time() - marker.stat().st_mtime < CLEANUP_AFTER_SECONDS:
            return

    for folder in (EXTRACT_DIR, TRANSFORM_DIR):
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
            
    marker.unlink(missing_ok=True)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)


def touch_activity():
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    (DATA_ROOT / ".activity").touch()


class ETLTools:
    def extract_load(self, url: str, output_folder: str, format: str):
        try:
            cleanup_old_files()

            fmt = format.lower().strip()

            if fmt not in {"csv", "json", "parquet"}:
                return f"Unsupported format: {format}"

            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            records = None

            if isinstance(data, list):
                records = data
            elif isinstance(data, dict):
                for key in (
                    "products", "results", "data", "items", "records"
                ):
                    if isinstance(data.get(key), list):
                        records = data[key]
                        break

                if records is None:
                    records = [data]

            if not records:
                return "Extraction failed: API returned no records."

            if not all(isinstance(row, dict) for row in records):
                return "Extraction failed: Expected JSON objects as records."

            df = pd.json_normalize(records)

            # Keep only the latest extracted dataset.
            shutil.rmtree(EXTRACT_DIR, ignore_errors=True)
            EXTRACT_DIR.mkdir(parents=True, exist_ok=True)

            filename = EXTRACT_DIR / f"extracted_data.{fmt}"

            if fmt == "csv":
                df.to_csv(filename, index=False)
            elif fmt == "json":
                df.to_json(filename, orient="records", lines=True)
            else:
                df.to_parquet(filename, index=False)

            touch_activity()

            return (
                "Extraction successful.\n"
                f"File: {filename}\n"
                f"Rows extracted: {len(df)}\n"
                f"Columns: {list(df.columns)}\n"
                f"First 5 rows:\n{df.head(5).to_string(index=False)}"
            )

        except requests.exceptions.RequestException as e:
            return f"Extraction failed: {e}"
        except Exception as e:
            return f"Extraction failed: {type(e).__name__}: {e}"

    def transform_load_context(self, file_path: str = ""):
        """Read the latest extracted file and return a preview."""
        try:
            cleanup_old_files()

            candidates = [
                path for path in EXTRACT_DIR.glob("extracted_data.*")
                if path.suffix.lower() in {".csv", ".json", ".parquet"}
            ]

            if not candidates:
                return "No extracted file found. Extract data first."

            path = candidates[0]
            df = self._read_file(path)
            touch_activity()

            return (
                f"Input file: {path}\n"
                f"Rows: {len(df)}\n"
                f"Columns: {list(df.columns)}\n"
                f"Preview:\n{df.head(5).to_string(index=False)}"
            )

        except Exception as e:
            return f"Failed to read extracted data: {type(e).__name__}: {e}"

    @staticmethod
    def _read_file(path: Path):
        suffix = path.suffix.lower()

        if suffix == ".csv":
            return pd.read_csv(path)
        if suffix == ".json":
            return pd.read_json(path, lines=True)
        if suffix == ".parquet":
            return pd.read_parquet(path)

        raise ValueError(f"Unsupported file format: {suffix}")

    def execute_code(self, code: str):
        """
        Execute generated transformation code.

        NOTE: exec() is not sandboxed. Do not expose this unrestricted
        execution to untrusted users in a public deployment.
        """
        try:
            exec(code)
            return "Code executed successfully."
        except Exception as e:
            return f"Failed to execute code: {e}"