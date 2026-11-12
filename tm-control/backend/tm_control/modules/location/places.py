"""The places store: the unit's surveys, their sensor bearings, and the corrections made to them.

This is the exact history (design section 5): coordinates, descriptions and reasons are kept here at full precision
and nowhere else but config.yml. Nothing in this module logs, audits or puts any of them in an error message.
"""

from pydantic import BaseModel

from tm_control.core.auth import _reading, _timestamp, _writing
from tm_control.core.state import State

STATUSES = ("planned", "in_use", "used")
SOURCES = ("ui", "csv", "default", "imported_config", "imported_backup")

_SURVEY_COLUMNS = "id, description, lat, lon, status, source, created_at, updated_at"
# In use first, then planned (newest first), then used (most recently changed first).
_LIST_ORDER = """
    ORDER BY CASE status WHEN 'in_use' THEN 0 WHEN 'planned' THEN 1 ELSE 2 END,
             CASE WHEN status = 'planned' THEN created_at END DESC,
             CASE WHEN status = 'used' THEN updated_at END DESC,
             id
"""


class Bearing(BaseModel):
    sensor_type: str
    sensor_name: str
    bearing: str


class Survey(BaseModel):
    id: str
    description: str | None
    lat: float | None
    lon: float | None
    status: str
    source: str
    created_at: str
    updated_at: str
    bearings: list[Bearing]


def _insert_bearings(con, survey_id: str, bearings: list[Bearing]) -> None:
    con.executemany(
        "INSERT INTO survey_bearings (survey_id, sensor_type, sensor_name, bearing) VALUES (?, ?, ?, ?)",
        [(survey_id, b.sensor_type, b.sensor_name, b.bearing) for b in bearings],
    )


def _surveys(con, where: str = "", args: tuple = ()) -> list[Survey]:
    """The surveys matching `where`, in list order, each with its bearings (in the order they were inserted)."""
    bearings: dict[str, list[Bearing]] = {}
    for row in con.execute(
        "SELECT survey_id, sensor_type, sensor_name, bearing FROM survey_bearings ORDER BY rowid"
    ):
        bearings.setdefault(row["survey_id"], []).append(
            Bearing(sensor_type=row["sensor_type"], sensor_name=row["sensor_name"], bearing=row["bearing"])
        )
    rows = con.execute(f"SELECT {_SURVEY_COLUMNS} FROM surveys {where} {_LIST_ORDER}", args).fetchall()
    return [Survey(**dict(row), bearings=bearings.get(row["id"], [])) for row in rows]


# `list` is a method of Places, so inside the class body the name no longer means the builtin; before Python 3.14
# evaluates annotations lazily, `list[Bearing]` in a signature below it would fail.
_BearingList = list[Bearing]


class Places:
    def __init__(self, state: State):
        self.state = state

    def list(self) -> list[Survey]:
        with _reading(self.state) as con:
            return _surveys(con)

    def get(self, survey_id: str) -> Survey | None:
        with _reading(self.state) as con:
            found = _surveys(con, "WHERE id = ?", (survey_id,))
        return found[0] if found else None

    def in_use(self) -> Survey | None:
        with _reading(self.state) as con:
            found = _surveys(con, "WHERE status = 'in_use'")
        return found[0] if found else None

    def create(
        self,
        survey_id: str,
        description: str | None,
        lat: float | None,
        lon: float | None,
        bearings: _BearingList,
        source: str,
        status: str,
        user_id: int | None,
        now: float | None = None,
        updated_now: float | None = None,
    ) -> Survey:
        """updated_now, when given, sets updated_at apart from created_at (an imported place's last use)."""
        at = _timestamp(now)
        updated_at = at if updated_now is None else _timestamp(updated_now)
        with _writing(self.state) as con:
            if status == "in_use" and con.execute("SELECT 1 FROM surveys WHERE status = 'in_use'").fetchone():
                raise ValueError("a place is already in use")
            con.execute(
                "INSERT INTO surveys (id, description, lat, lon, status, source, created_at, updated_at, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (survey_id, description, lat, lon, status, source, at, updated_at, user_id),
            )
            _insert_bearings(con, survey_id, bearings)
            return _surveys(con, "WHERE id = ?", (survey_id,))[0]

    def update_planned(
        self, survey_id: str, description: str | None, lat: float | None, lon: float | None, bearings: _BearingList
    ) -> Survey:
        with _writing(self.state) as con:
            row = con.execute("SELECT status FROM surveys WHERE id = ?", (survey_id,)).fetchone()
            if row is None or row["status"] != "planned":
                raise ValueError("only a planned place can be edited this way")
            con.execute(
                "UPDATE surveys SET description = ?, lat = ?, lon = ?, updated_at = ? WHERE id = ?",
                (description, lat, lon, _timestamp(), survey_id),
            )
            con.execute("DELETE FROM survey_bearings WHERE survey_id = ?", (survey_id,))
            _insert_bearings(con, survey_id, bearings)
            return _surveys(con, "WHERE id = ?", (survey_id,))[0]

    def set_in_use(self, survey_id: str, now: float | None = None) -> None:
        """Make this place the one in use; the previous one becomes used."""
        at = _timestamp(now)
        with _writing(self.state) as con:
            row = con.execute("SELECT status FROM surveys WHERE id = ?", (survey_id,)).fetchone()
            if row is None:
                raise ValueError("no such place")
            if row["status"] == "in_use":
                return
            con.execute("UPDATE surveys SET status = 'used', updated_at = ? WHERE status = 'in_use' AND id != ?",
                        (at, survey_id))
            con.execute("UPDATE surveys SET status = 'in_use', updated_at = ? WHERE id = ?", (at, survey_id))

    def set_point(self, survey_id: str, lat: float | None, lon: float | None, now: float | None = None) -> None:
        with _writing(self.state) as con:
            con.execute(
                "UPDATE surveys SET lat = ?, lon = ?, updated_at = ? WHERE id = ?",
                (lat, lon, _timestamp(now), survey_id),
            )

    def set_bearing(self, survey_id: str, sensor_type: str, sensor_name: str, bearing: str) -> None:
        """Replace one sensor's bearing in place (so its order among the bearings is kept)."""
        with _writing(self.state) as con:
            cursor = con.execute(
                "UPDATE survey_bearings SET bearing = ? WHERE survey_id = ? AND sensor_type = ? AND sensor_name = ?",
                (bearing, survey_id, sensor_type, sensor_name),
            )
            if cursor.rowcount == 0:
                new = Bearing(sensor_type=sensor_type, sensor_name=sensor_name, bearing=bearing)
                _insert_bearings(con, survey_id, [new])

    def rename_sensor(self, sensor_type: str, old: str, new: str) -> None:
        """Move every place's bearing for a sensor to its new name, keeping each row's place in the order. A place
        that already has a bearing under the new name keeps that one, and its row under the old name goes."""
        with _writing(self.state) as con:
            con.execute(
                "UPDATE OR IGNORE survey_bearings SET sensor_name = ? WHERE sensor_type = ? AND sensor_name = ?",
                (new, sensor_type, old),
            )
            con.execute("DELETE FROM survey_bearings WHERE sensor_type = ? AND sensor_name = ?", (sensor_type, old))

    def record_correction(
        self,
        survey_id: str,
        deployment_id: str | None,
        field: str,
        old_value: str | None,
        new_value: str | None,
        reason: str | None,
        source: str,  # 'ui' or 'config'
        user_id: int | None,
        now: float | None = None,
    ) -> None:
        with _writing(self.state) as con:
            con.execute(
                "INSERT INTO survey_corrections "
                "(survey_id, deployment_id, field, old_value, new_value, reason, source, at, user_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (survey_id, deployment_id, field, old_value, new_value, reason, source, _timestamp(now), user_id),
            )

    def delete(self, survey_id: str) -> None:
        """Remove a place with its bearings and corrections. The place in use cannot be removed."""
        with _writing(self.state) as con:
            row = con.execute("SELECT status FROM surveys WHERE id = ?", (survey_id,)).fetchone()
            if row is not None and row["status"] == "in_use":
                raise ValueError("the place in use cannot be deleted")
            con.execute("DELETE FROM surveys WHERE id = ?", (survey_id,))

    def kept_precision(self) -> str | None:
        """The database precision last chosen, which a config.yml reset from the template gets back; None until one
        has been seen."""
        with _reading(self.state) as con:
            row = con.execute("SELECT value FROM device WHERE key = 'database_precision'").fetchone()
        return None if row is None else row["value"]

    def keep_precision(self, precision: str) -> None:
        with _writing(self.state) as con:
            con.execute("INSERT OR REPLACE INTO device (key, value) VALUES ('database_precision', ?)", (precision,))

    def reconciled_at(self) -> str | None:
        with _reading(self.state) as con:
            row = con.execute("SELECT value FROM device WHERE key = 'surveys_reconciled_at'").fetchone()
        return None if row is None else row["value"]

    def mark_reconciled(self, now: float | None = None) -> None:
        with _writing(self.state) as con:
            con.execute(
                "INSERT OR REPLACE INTO device (key, value) VALUES ('surveys_reconciled_at', ?)", (_timestamp(now),)
            )
