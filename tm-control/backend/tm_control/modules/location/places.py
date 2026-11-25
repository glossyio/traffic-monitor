"""The places store: the unit's surveys, the way each of their sensors faced and how it was mounted, and the
corrections made to them.

This is the exact history (design section 5): coordinates, descriptions and reasons are kept here at full precision
and nowhere else but config.yml. Nothing in this module logs, audits or puts any of them in an error message.
"""

from typing import Annotated

from pydantic import BaseModel, Field

from tm_control.core.auth import _reading, _timestamp, _writing
from tm_control.core.state import State
from tm_control.modules.location.mounting import Mounting

STATUSES = ("planned", "in_use", "used")
SOURCES = ("ui", "csv", "default", "imported_config", "imported_backup")

_SURVEY_COLUMNS = "id, description, lat, lon, status, source, created_at, updated_at"
_MOUNTING_COLUMNS = ("pitch_deg", "height_m", "view_distance_m", "measured", "mount")  # beside heading_deg
_HOLDS_THE_FOUR = "(pitch_deg IS NOT NULL OR height_m IS NOT NULL OR view_distance_m IS NOT NULL OR mount IS NOT NULL)"
_MOUNTING_SELECT = (
    "SELECT sensor_type, sensor_name, heading_deg, pitch_deg, height_m, view_distance_m, measured, mount "
    "FROM survey_sensors WHERE survey_id = ?"
)
# In use first, then planned (newest first), then used (most recently changed first).
_LIST_ORDER = """
    ORDER BY CASE status WHEN 'in_use' THEN 0 WHEN 'planned' THEN 1 ELSE 2 END,
             CASE WHEN status = 'planned' THEN created_at END DESC,
             CASE WHEN status = 'used' THEN updated_at END DESC,
             id
"""


class SensorHeading(BaseModel):
    sensor_type: str
    sensor_name: str
    # Clockwise from true north, in whole degrees from 0 to 359; None for none. Strict: the API takes a whole number
    # only, never a numeric string, a float, or a bool, which lax validation would turn into one.
    heading_deg: Annotated[int, Field(strict=True)] | None


class Survey(BaseModel):
    id: str
    description: str | None
    lat: float | None
    lon: float | None
    status: str
    source: str
    created_at: str
    updated_at: str
    headings: list[SensorHeading]


def _insert_headings(con, survey_id: str, headings: list[SensorHeading]) -> None:
    con.executemany(
        "INSERT INTO survey_sensors (survey_id, sensor_type, sensor_name, heading_deg) VALUES (?, ?, ?, ?)",
        [(survey_id, h.sensor_type, h.sensor_name, h.heading_deg) for h in headings],
    )


def _surveys(con, where: str = "", args: tuple = ()) -> list[Survey]:
    """The surveys matching `where`, in list order, each with its sensors' headings (in the order they were
    inserted)."""
    headings: dict[str, list[SensorHeading]] = {}
    for row in con.execute(
        "SELECT survey_id, sensor_type, sensor_name, heading_deg FROM survey_sensors ORDER BY rowid"
    ):
        headings.setdefault(row["survey_id"], []).append(SensorHeading(
            sensor_type=row["sensor_type"], sensor_name=row["sensor_name"], heading_deg=row["heading_deg"]
        ))
    rows = con.execute(f"SELECT {_SURVEY_COLUMNS} FROM surveys {where} {_LIST_ORDER}", args).fetchall()
    return [Survey(**dict(row), headings=headings.get(row["id"], [])) for row in rows]


# `list` is a method of Places, so inside the class body the name no longer means the builtin; before Python 3.14
# evaluates annotations lazily, `list[SensorHeading]` or `list[Mounting]` in a signature below it would fail.
_HeadingList = list[SensorHeading]
_SurveyList = list[Survey]
_MountingList = list[Mounting]


class Places:
    def __init__(self, state: State):
        self.state = state

    def list(self) -> list[Survey]:
        with _reading(self.state) as con:
            return _surveys(con)

    def located(self) -> _SurveyList:
        """The places the device has been at (in use or used) that have both coordinates, in list order."""
        with _reading(self.state) as con:
            return _surveys(con, "WHERE status IN ('in_use', 'used') AND lat IS NOT NULL AND lon IS NOT NULL")

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
        headings: _HeadingList,
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
            _insert_headings(con, survey_id, headings)
            return _surveys(con, "WHERE id = ?", (survey_id,))[0]

    def update_planned(
        self, survey_id: str, description: str | None, lat: float | None, lon: float | None, headings: _HeadingList
    ) -> Survey:
        with _writing(self.state) as con:
            row = con.execute("SELECT status FROM surveys WHERE id = ?", (survey_id,)).fetchone()
            if row is None or row["status"] != "planned":
                raise ValueError("only a planned place can be edited this way")
            con.execute(
                "UPDATE surveys SET description = ?, lat = ?, lon = ?, updated_at = ? WHERE id = ?",
                (description, lat, lon, _timestamp(), survey_id),
            )
            kept_columns = (*_MOUNTING_COLUMNS, "unconfirmed")
            kept = {
                (row["sensor_type"], row["sensor_name"]): tuple(row[column] for column in kept_columns)
                for row in con.execute(
                    f"SELECT sensor_type, sensor_name, {', '.join(kept_columns)} FROM survey_sensors "
                    "WHERE survey_id = ?", (survey_id,)
                )
            }
            con.execute("DELETE FROM survey_sensors WHERE survey_id = ?", (survey_id,))
            _insert_headings(con, survey_id, headings)
            for (sensor_type, sensor_name), values in kept.items():  # a sensor that stays keeps its other four
                con.execute(
                    f"UPDATE survey_sensors SET {', '.join(f'{column} = ?' for column in kept_columns)} "
                    "WHERE survey_id = ? AND sensor_type = ? AND sensor_name = ?",
                    (*values, survey_id, sensor_type, sensor_name),
                )
            return _surveys(con, "WHERE id = ?", (survey_id,))[0]

    def set_in_use(self, survey_id: str, now: float | None = None) -> None:
        """Make this place the one in use; the previous one becomes used. A place that wasn't in use has each row that
        holds any of the other four marked unconfirmed: a move records none of them until a save confirms them."""
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
            con.execute(
                f"UPDATE survey_sensors SET unconfirmed = 1 WHERE survey_id = ? AND {_HOLDS_THE_FOUR}", (survey_id,)
            )

    def set_point(self, survey_id: str, lat: float | None, lon: float | None, now: float | None = None) -> None:
        with _writing(self.state) as con:
            con.execute(
                "UPDATE surveys SET lat = ?, lon = ?, updated_at = ? WHERE id = ?",
                (lat, lon, _timestamp(now), survey_id),
            )

    def set_heading(self, survey_id: str, sensor_type: str, sensor_name: str, heading_deg: int | None) -> None:
        """Replace one sensor's heading in place (so its order among the place's sensors is kept); None for none. The
        other four, and whether they are confirmed, stay as they are."""
        with _writing(self.state) as con:
            cursor = con.execute(
                "UPDATE survey_sensors SET heading_deg = ? WHERE survey_id = ? AND sensor_type = ? AND sensor_name = ?",
                (heading_deg, survey_id, sensor_type, sensor_name),
            )
            if cursor.rowcount == 0:
                new = SensorHeading(sensor_type=sensor_type, sensor_name=sensor_name, heading_deg=heading_deg)
                _insert_headings(con, survey_id, [new])

    def mountings(self, survey_id: str) -> _MountingList:
        """The place's sensors with how each is mounted, as stored, confirmed or not, in the order they were
        inserted."""
        with _reading(self.state) as con:
            return [Mounting(**dict(row)) for row in con.execute(f"{_MOUNTING_SELECT} ORDER BY rowid", (survey_id,))]

    def unconfirmed(self, survey_id: str) -> _MountingList:
        """The place's sensors whose other four wait to be confirmed (see set_in_use), as stored, in the order they
        were inserted."""
        with _reading(self.state) as con:
            return [
                Mounting(**dict(row))
                for row in con.execute(f"{_MOUNTING_SELECT} AND unconfirmed = 1 ORDER BY rowid", (survey_id,))
            ]

    def set_mounting(self, survey_id: str, mounting: Mounting) -> None:
        """Replace one sensor's heading and the other four in place (so its order among the place's sensors is kept),
        inserting the row when the sensor has none. What it stores is confirmed."""
        values = (
            mounting.heading_deg, mounting.pitch_deg, mounting.height_m, mounting.view_distance_m, mounting.measured,
            mounting.mount,
        )
        with _writing(self.state) as con:
            cursor = con.execute(
                "UPDATE survey_sensors SET heading_deg = ?, pitch_deg = ?, height_m = ?, view_distance_m = ?, "
                "measured = ?, mount = ?, unconfirmed = 0 WHERE survey_id = ? AND sensor_type = ? AND sensor_name = ?",
                (*values, survey_id, mounting.sensor_type, mounting.sensor_name),
            )
            if cursor.rowcount == 0:
                con.execute(
                    "INSERT INTO survey_sensors (survey_id, sensor_type, sensor_name, heading_deg, pitch_deg, "
                    "height_m, view_distance_m, measured, mount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (survey_id, mounting.sensor_type, mounting.sensor_name, *values),
                )

    def rename_sensor(self, sensor_type: str, old: str, new: str) -> None:
        """Move every place's heading for a sensor to its new name, keeping each row's place in the order. A place
        that already has a heading under the new name keeps that one, and its row under the old name goes."""
        if old == new:
            return
        with _writing(self.state) as con:
            con.execute(
                "UPDATE OR IGNORE survey_sensors SET sensor_name = ? WHERE sensor_type = ? AND sensor_name = ?",
                (new, sensor_type, old),
            )
            con.execute("DELETE FROM survey_sensors WHERE sensor_type = ? AND sensor_name = ?", (sensor_type, old))

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
        """Remove a place with its sensors' headings and corrections. The place in use cannot be removed."""
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
