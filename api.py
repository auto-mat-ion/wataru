import hmac
import logging
import os
from typing import Optional
import msal
import json
import mysql.connector
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import Response


logger = logging.getLogger(__name__)
app = FastAPI(title="Oneapp")

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "root101."),
    "database": os.getenv("DB_NAME", "oneapp"),
}
API_TOKEN = os.getenv("CACHE_BIN_API_TOKEN")


def require_api_token(x_api_key: Optional[str] = Header(default=None)) -> None:
    if not API_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Set CACHE_BIN_API_TOKEN before using the cache-bin endpoint",
        )
    if x_api_key is None or not hmac.compare_digest(x_api_key, API_TOKEN):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "API key"},
        )


@app.get("/cache-bin", response_class=Response)
def get_cache_bin(
    server_ip: Optional[str] = Query(default=None, min_length=1, max_length=45),
    bot_type: Optional[str] = Query(default=None, min_length=1, max_length=50),
    _: None = Depends(require_api_token),
) -> Response:
    connection = None
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        with connection.cursor() as cursor:
            if server_ip is not None and bot_type is not None:
                cursor.execute(
                    """
                    SELECT cache_bin_file
                    FROM cache_bins
                    WHERE server_ip = %s AND bot_type = %s
                    ORDER BY date_time DESC
                    LIMIT 1
                    """,
                    (server_ip, bot_type),
                )
                rows = cursor.fetchall()
            else:
                filters = []
                params = []
                if server_ip is not None:
                    filters.append("server_ip = %s")
                    params.append(server_ip)
                if bot_type is not None:
                    filters.append("bot_type = %s")
                    params.append(bot_type)
                where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
                cursor.execute(
                    f"""
                    SELECT cache_bin_file
                    FROM cache_bins
                    {where_clause}
                    ORDER BY server_ip, bot_type, date_time
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall()
    except mysql.connector.Error as exc:
        logger.exception("Could not retrieve cache bin from the database")
        raise HTTPException(
            status_code=503,
            detail="Could not retrieve cache bin from the database",
        ) from exc
    finally:
        if connection is not None:
            connection.close()
    combined_data = {
        "Account": {},
        "IdToken": {},
        "AccessToken": {},
        "RefreshToken": {},
        "AppMetadata": {},
    }

    for result in rows:
        if result and result[0]:
            temp_cache = msal.SerializableTokenCache()
            temp_cache.deserialize(result[0].decode("utf-8"))
            raw_data = json.loads(temp_cache.serialize())
            for category in combined_data.keys():
                if category in raw_data:
                    combined_data[category].update(raw_data[category])

    if not combined_data:
        raise HTTPException(status_code=404, detail="Cache bin not found")

    return Response(
        content=json.dumps(combined_data).encode("utf-8"),
        media_type="application/json",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="cache-bins.json"',
        },
    )
