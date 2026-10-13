
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
    Reuse existing extracted data for the same URL and session.
    """
        try:
            supported_formats = {"csv", "json", "parquet"}
            fmt = (format or "csv").lower().strip()
            
            if fmt not in supported_formats:
                return f"Unsupported format: {format}"

            # Keep the extraction directory consistent.
            relative_folder = os.path.normpath(output_folder or "extract")
            if relative_folder in (".", ""):
                relative_folder = "extract"
                
            folder_path = get_output_path(
                os.path.join(relative_folder, "extracted_data.csv")
            ).parent

            # Store the source URL so the file can be matched to the API.
            url_marker = folder_path / ".source_url"
            existing_csv = folder_path / "extracted_data.csv"

            # Reuse the existing CSV when it came from the same URL.
            if existing_csv.is_file() and url_marker.is_file():
                try:
                    saved_url = url_marker.read_text(encoding="utf-8").strip()
                    
                    if saved_url == url:
                        if fmt == "csv":
                            return (
                                f"Existing extraction reused: {existing_csv}"
                            )
                        
                        # Convert the existing extraction instead of
                        # downloading the API a second time.
                        df = pd.read_csv(existing_csv)
                        filename = folder_path / f"extracted_data.{fmt}"

                        if fmt == "json":
                            df.to_json(filename, orient="records", lines=True)
                        elif fmt == "parquet":
                            df.to_parquet(filename, index=False)
                        return f"Existing extraction converted and saved to {filename}"
                except Exception:
                    pass
            # Download the API response.
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Extract records from common API response structures.
            if isinstance(data, list):
                records = data
            elif isinstance(data, dict):
                records = None
                
                for key in ("products", "results", "data", "items", "records"):
                    if isinstance(data.get(key), list):
                        records = data[key]
                    break

                if records is None:
                    records = [data]
                else:
                    return "Unsupported API response: expected a JSON list or object."

            df = pd.json_normalize(records)

            # Always save a canonical CSV to support reuse across formats.
            existing_csv = folder_path / "extracted_data.csv"
            df.to_csv(existing_csv, index=False)
            url_marker.write_text(url, encoding="utf-8")

            # Save another format only if explicitly requested.
            if fmt == "json":
                filename = folder_path / "extracted_data.json"
                df.to_json(filename, orient="records", lines=True)
            elif fmt == "parquet":
                filename = folder_path / "extracted_data.parquet"
                df.to_parquet(filename, index=False)
            else:
                filename = existing_csv

            return (
                f"Data successfully extracted and saved to {filename}\n"
                f"Rows extracted: {len(df)}\n"
                f"Columns: {list(df.columns)}"
            )

        except requests.exceptions.RequestException as e:
            return f"Failed to extract data: {e}"
        except Exception as e:
            return f"Failed to extract and save data: {type(e).__name__}: {e}"


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