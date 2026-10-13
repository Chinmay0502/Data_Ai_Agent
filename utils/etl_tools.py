
import os
import requests
import pandas as pd

from utils.session_storage import get_output_path, get_session_folder


class ETLTools:

    def __init__(self):
        pass

    def extract_load(self, url: str, output_folder: str, format: str):
        """
        Extract API data and save it inside the current session folder.
        """
        try:
            supported_formats = {"csv", "json", "parquet"}
            if format not in supported_formats:
                return f"Unsupported format: {format}"

            # Keep outputs such as data/extract inside the session folder.
            relative_folder = os.path.normpath(output_folder)

            if relative_folder in (".", ""):
                relative_folder = "extract"

            filename = get_output_path(
                os.path.join(relative_folder, f"extracted_data.{format}")
            )

            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Support APIs that return a list directly, as well as
            # APIs that wrap records in a "results" property.
            if isinstance(data, dict) and "results" in data:
                records = data["results"]
            elif isinstance(data, list):
                records = data
            else:
                records = data

            df = pd.json_normalize(records)

            if format == "csv":
                df.to_csv(filename, index=False)
            elif format == "json":
                df.to_json(filename, orient="records", lines=True)
            elif format == "parquet":
                df.to_parquet(filename, index=False)

            return f"Data successfully extracted and saved to {filename}"

        except requests.exceptions.RequestException as e:
            return f"Failed to extract data: {e}"
        except Exception as e:
            return f"Failed to extract and save data: {e}"

    def transform_load_context(self, file_path: str):
        """
        Read an extracted file and return its first three rows.
        """
        try:
            path = os.path.abspath(file_path)
            session_folder = get_session_folder().resolve()

            # Only read files belonging to this session.
            if (
                path != str(session_folder)
                and str(session_folder) not in os.path.commonpath(
                    [str(session_folder), path]
                )
            ):
                return "Error: File must be inside the current session folder."

            if not os.path.isfile(path):
                return f"File not found: {path}"

            file_extension = os.path.splitext(path)[1].lower()

            if file_extension == ".csv":
                df = pd.read_csv(path)
            elif file_extension == ".json":
                df = pd.read_json(path, lines=True)
            elif file_extension == ".parquet":
                df = pd.read_parquet(path)
            else:
                return f"Unsupported file format: {file_extension}"

            return str(df.head(3))

        except Exception as e:
            return f"Failed to read file: {e}"

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