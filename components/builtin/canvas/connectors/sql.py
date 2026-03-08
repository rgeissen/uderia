"""
SQL Native Connector — executes SQL against real databases.

Supports multiple drivers with graceful ImportError handling:
  - PostgreSQL via asyncpg
  - MySQL via aiomysql
  - SQLite via aiosqlite
  - Teradata via teradatasql (sync, wrapped in run_in_executor)
  - JDBC via JayDeBeApi (sync, wrapped in run_in_executor — requires Java runtime)
"""

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from .base import BaseCanvasConnector, ExecutionResult, ConnectionTestResult

logger = logging.getLogger("quart.app")

# Thread pool for sync drivers (Teradata)
_sync_executor = ThreadPoolExecutor(max_workers=2)


class SQLNativeConnector(BaseCanvasConnector):
    """Executes SQL against PostgreSQL, MySQL, SQLite, Teradata, or any JDBC-compatible database."""

    id = 'sql_native'
    name = 'SQL (Native)'
    supported_drivers = ['postgresql', 'mysql', 'sqlite', 'teradata', 'jdbc']

    async def execute(self, code: str, credentials: dict) -> ExecutionResult:
        """Execute SQL using the appropriate driver."""
        driver = credentials.get('driver', 'postgresql')
        start = time.monotonic()

        try:
            if driver == 'postgresql':
                return await self._execute_postgresql(code, credentials, start)
            elif driver == 'mysql':
                return await self._execute_mysql(code, credentials, start)
            elif driver == 'sqlite':
                return await self._execute_sqlite(code, credentials, start)
            elif driver == 'teradata':
                return await self._execute_teradata(code, credentials, start)
            elif driver == 'jdbc':
                return await self._execute_jdbc(code, credentials, start)
            else:
                return ExecutionResult(
                    error=f"Unsupported driver: {driver}",
                    execution_time_ms=int((time.monotonic() - start) * 1000),
                )
        except Exception as e:
            return ExecutionResult(
                error=str(e),
                execution_time_ms=int((time.monotonic() - start) * 1000),
            )

    async def test_connection(self, credentials: dict) -> ConnectionTestResult:
        """Test database connectivity."""
        driver = credentials.get('driver', 'postgresql')

        try:
            if driver == 'postgresql':
                return await self._test_postgresql(credentials)
            elif driver == 'mysql':
                return await self._test_mysql(credentials)
            elif driver == 'sqlite':
                return await self._test_sqlite(credentials)
            elif driver == 'teradata':
                return await self._test_teradata(credentials)
            elif driver == 'jdbc':
                return await self._test_jdbc(credentials)
            else:
                return ConnectionTestResult(valid=False, message=f"Unsupported driver: {driver}")
        except ImportError as e:
            return ConnectionTestResult(
                valid=False,
                message=f"Driver not installed: {e}. Install with: pip install {self._pip_package(driver)}",
            )
        except Exception as e:
            return ConnectionTestResult(valid=False, message=str(e))

    # ── PostgreSQL ────────────────────────────────────────────────────────────

    async def _execute_postgresql(self, code: str, creds: dict, start: float) -> ExecutionResult:
        try:
            import asyncpg
        except ImportError:
            return ExecutionResult(error="asyncpg not installed. Run: pip install asyncpg")

        conn = await asyncpg.connect(
            host=creds.get('host', 'localhost'),
            port=int(creds.get('port', 5432)),
            database=creds.get('database', ''),
            user=creds.get('user', ''),
            password=creds.get('password', ''),
            ssl=creds.get('ssl', False) or None,
        )
        try:
            rows = await conn.fetch(code)
            elapsed = int((time.monotonic() - start) * 1000)
            if rows:
                columns = list(rows[0].keys())
                header = '\t'.join(columns)
                body = '\n'.join('\t'.join(str(v) for v in row.values()) for row in rows)
                return ExecutionResult(
                    result=f"{header}\n{body}",
                    row_count=len(rows),
                    execution_time_ms=elapsed,
                )
            return ExecutionResult(result='Query executed successfully (0 rows)', row_count=0, execution_time_ms=elapsed)
        finally:
            await conn.close()

    async def _test_postgresql(self, creds: dict) -> ConnectionTestResult:
        import asyncpg
        conn = await asyncpg.connect(
            host=creds.get('host', 'localhost'),
            port=int(creds.get('port', 5432)),
            database=creds.get('database', ''),
            user=creds.get('user', ''),
            password=creds.get('password', ''),
            ssl=creds.get('ssl', False) or None,
        )
        try:
            version = await conn.fetchval('SELECT version()')
            return ConnectionTestResult(valid=True, message='Connected', server_info=version)
        finally:
            await conn.close()

    # ── MySQL ─────────────────────────────────────────────────────────────────

    async def _execute_mysql(self, code: str, creds: dict, start: float) -> ExecutionResult:
        try:
            import aiomysql
        except ImportError:
            return ExecutionResult(error="aiomysql not installed. Run: pip install aiomysql")

        conn = await aiomysql.connect(
            host=creds.get('host', 'localhost'),
            port=int(creds.get('port', 3306)),
            db=creds.get('database', ''),
            user=creds.get('user', ''),
            password=creds.get('password', ''),
        )
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(code)
                rows = await cur.fetchall()
                elapsed = int((time.monotonic() - start) * 1000)
                if rows:
                    columns = list(rows[0].keys())
                    header = '\t'.join(columns)
                    body = '\n'.join('\t'.join(str(v) for v in row.values()) for row in rows)
                    return ExecutionResult(
                        result=f"{header}\n{body}",
                        row_count=len(rows),
                        execution_time_ms=elapsed,
                    )
                return ExecutionResult(
                    result=f'Query executed successfully ({cur.rowcount} rows affected)',
                    row_count=cur.rowcount,
                    execution_time_ms=elapsed,
                )
        finally:
            conn.close()

    async def _test_mysql(self, creds: dict) -> ConnectionTestResult:
        import aiomysql
        conn = await aiomysql.connect(
            host=creds.get('host', 'localhost'),
            port=int(creds.get('port', 3306)),
            db=creds.get('database', ''),
            user=creds.get('user', ''),
            password=creds.get('password', ''),
        )
        try:
            async with conn.cursor() as cur:
                await cur.execute('SELECT VERSION()')
                row = await cur.fetchone()
                return ConnectionTestResult(valid=True, message='Connected', server_info=row[0] if row else None)
        finally:
            conn.close()

    # ── SQLite ────────────────────────────────────────────────────────────────

    async def _execute_sqlite(self, code: str, creds: dict, start: float) -> ExecutionResult:
        try:
            import aiosqlite
        except ImportError:
            return ExecutionResult(error="aiosqlite not installed. Run: pip install aiosqlite")

        db_path = creds.get('database', ':memory:')
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(code)
            rows = await cursor.fetchall()
            elapsed = int((time.monotonic() - start) * 1000)

            if rows and cursor.description:
                columns = [d[0] for d in cursor.description]
                header = '\t'.join(columns)
                body = '\n'.join('\t'.join(str(row[c]) for c in columns) for row in rows)
                return ExecutionResult(
                    result=f"{header}\n{body}",
                    row_count=len(rows),
                    execution_time_ms=elapsed,
                )
            return ExecutionResult(
                result=f'Query executed successfully ({cursor.rowcount} rows affected)',
                row_count=max(cursor.rowcount, 0),
                execution_time_ms=elapsed,
            )

    async def _test_sqlite(self, creds: dict) -> ConnectionTestResult:
        import aiosqlite
        db_path = creds.get('database', ':memory:')
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute('SELECT sqlite_version()')
            row = await cursor.fetchone()
            return ConnectionTestResult(valid=True, message='Connected', server_info=f"SQLite {row[0]}" if row else None)

    # ── Teradata ──────────────────────────────────────────────────────────────

    async def _execute_teradata(self, code: str, creds: dict, start: float) -> ExecutionResult:
        try:
            import teradatasql
        except ImportError:
            return ExecutionResult(error="teradatasql not installed. Run: pip install teradatasql")

        def _run():
            with teradatasql.connect(
                host=creds.get('host', ''),
                user=creds.get('user', ''),
                password=creds.get('password', ''),
                database=creds.get('database', ''),
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute(code)
                    if cur.description:
                        columns = [d[0] for d in cur.description]
                        rows = cur.fetchall()
                        header = '\t'.join(columns)
                        body = '\n'.join('\t'.join(str(v) for v in row) for row in rows)
                        return header, body, len(rows)
                    return None, f'{cur.rowcount} rows affected', max(cur.rowcount, 0)

        loop = asyncio.get_event_loop()
        header, body, count = await loop.run_in_executor(_sync_executor, _run)
        elapsed = int((time.monotonic() - start) * 1000)

        if header:
            return ExecutionResult(result=f"{header}\n{body}", row_count=count, execution_time_ms=elapsed)
        return ExecutionResult(result=f'Query executed successfully ({body})', row_count=count, execution_time_ms=elapsed)

    async def _test_teradata(self, creds: dict) -> ConnectionTestResult:
        import teradatasql

        def _run():
            with teradatasql.connect(
                host=creds.get('host', ''),
                user=creds.get('user', ''),
                password=creds.get('password', ''),
                database=creds.get('database', ''),
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT InfoData FROM DBC.DBCInfoV WHERE InfoKey = 'VERSION'")
                    row = cur.fetchone()
                    return row[0].strip() if row else 'Unknown'

        loop = asyncio.get_event_loop()
        version = await loop.run_in_executor(_sync_executor, _run)
        return ConnectionTestResult(valid=True, message='Connected', server_info=f"Teradata {version}")

    # ── JDBC (Generic) ───────────────────────────────────────────────────────

    async def _execute_jdbc(self, code: str, creds: dict, start: float) -> ExecutionResult:
        try:
            import jaydebeapi
        except ImportError:
            return ExecutionResult(error="JayDeBeApi not installed. Run: pip install JayDeBeApi (requires Java runtime)")

        jdbc_url = creds.get('jdbc_url', '')
        driver_class = creds.get('jdbc_driver_class', '')
        jar_path = creds.get('jdbc_driver_path', '')

        if not jdbc_url or not driver_class:
            return ExecutionResult(error="JDBC URL and Driver Class are required")

        def _run():
            jar_list = [p.strip() for p in jar_path.split(',') if p.strip()] if jar_path else None
            conn = jaydebeapi.connect(
                driver_class,
                jdbc_url,
                [creds.get('user', ''), creds.get('password', '')],
                jar_list,
            )
            try:
                cur = conn.cursor()
                cur.execute(code)
                if cur.description:
                    columns = [d[0] for d in cur.description]
                    rows = cur.fetchall()
                    header = '\t'.join(columns)
                    body = '\n'.join('\t'.join(str(v) for v in row) for row in rows)
                    return header, body, len(rows)
                rc = cur.rowcount if cur.rowcount >= 0 else 0
                return None, f'{rc} rows affected', rc
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        header, body, count = await loop.run_in_executor(_sync_executor, _run)
        elapsed = int((time.monotonic() - start) * 1000)

        if header:
            return ExecutionResult(result=f"{header}\n{body}", row_count=count, execution_time_ms=elapsed)
        return ExecutionResult(result=f'Query executed successfully ({body})', row_count=count, execution_time_ms=elapsed)

    async def _test_jdbc(self, creds: dict) -> ConnectionTestResult:
        import jaydebeapi

        jdbc_url = creds.get('jdbc_url', '')
        driver_class = creds.get('jdbc_driver_class', '')
        jar_path = creds.get('jdbc_driver_path', '')

        if not jdbc_url or not driver_class:
            return ConnectionTestResult(valid=False, message="JDBC URL and Driver Class are required")

        def _run():
            jar_list = [p.strip() for p in jar_path.split(',') if p.strip()] if jar_path else None
            conn = jaydebeapi.connect(
                driver_class,
                jdbc_url,
                [creds.get('user', ''), creds.get('password', '')],
                jar_list,
            )
            try:
                cur = conn.cursor()
                cur.execute('SELECT 1')
                cur.fetchone()
                return jdbc_url
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(_sync_executor, _run)
        return ConnectionTestResult(valid=True, message='Connected', server_info=f"JDBC: {info}")

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _pip_package(driver: str) -> str:
        return {
            'postgresql': 'asyncpg',
            'mysql': 'aiomysql',
            'sqlite': 'aiosqlite',
            'teradata': 'teradatasql',
            'jdbc': 'JayDeBeApi',
        }.get(driver, driver)
