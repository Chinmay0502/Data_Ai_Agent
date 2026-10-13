
import os
from pathlib import Path

import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv


# Load .env from the project root (assuming this file is inside utils/)
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class DatabaseUtil:

    def __init__(self):
        database_url = os.getenv("DATABASE_URL")

        if not database_url:
            raise ValueError("DATABASE_URL is missing from your .env file")

        try:
            self.connection = psycopg2.connect(database_url)
            print("Connected to Neon PostgreSQL")

        except psycopg2.Error as e:
            self.connection = None
            raise ConnectionError(
                f"Error connecting to the database: {e}"
            ) from e

    def schema_details(self, schema_name="public"):
        if self.connection is None:
            raise ConnectionError("Database connection is not available")

        schema_info_context = f"Database Schema: {schema_name}\n"

        try:
            with self.connection.cursor() as cursor:

                # Get tables in the requested schema
                cursor.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s
                      AND table_type = 'BASE TABLE'
                    ORDER BY table_name;
                    """,
                    (schema_name,)
                )

                tables = cursor.fetchall()

                for (table_name,) in tables:
                    schema_info_context += f"\nTable: {table_name}\n"

                    # Get columns for the current table
                    cursor.execute(
                        """
                        SELECT column_name, data_type
                        FROM information_schema.columns
                        WHERE table_schema = %s
                          AND table_name = %s
                        ORDER BY ordinal_position;
                        """,
                        (schema_name, table_name)
                    )

                    columns = cursor.fetchall()

                    for column_name, data_type in columns:
                        schema_info_context += (
                            f"  Column: {column_name}, "
                            f"Data Type: {data_type}\n"
                        )

                    # Get sample rows once per table
                    sample_query = sql.SQL(
                        "SELECT * FROM {}.{} LIMIT 5"
                    ).format(
                        sql.Identifier(schema_name),
                        sql.Identifier(table_name)
                    )

                    cursor.execute(sample_query)
                    sample_rows = cursor.fetchall()

                    schema_info_context += "  Sample Data:\n"

                    for row in sample_rows:
                        schema_info_context += f"    {row}\n"

            return schema_info_context

        except psycopg2.Error as e:
            raise RuntimeError(
                f"Error fetching schema details: {e}"
            ) from e

    def close(self):
        if self.connection is not None and not self.connection.closed:
            self.connection.close()
            print("PostgreSQL connection closed")

    def execute_query(self, query):
        try:
            connection = self.connection
            cursor = connection.cursor()
            cursor.execute(query)
            result = cursor.fetchall()
            connection.commit()
            return str(result)
        except Exception as e:
            print(f"Error executing query: {e}")
            return None
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

if __name__ == "__main__":
    db = None

    try:
        db = DatabaseUtil()
        result = db.schema_details("public")

        output_file = Path(__file__).resolve().parent / "test_schema_details.txt"
        output_file.write_text(result, encoding="utf-8")

        print(f"Schema details saved to: {output_file}")

    except (ConnectionError, RuntimeError, ValueError) as e:
        print(e)

    finally:
        if db is not None:
            db.close()