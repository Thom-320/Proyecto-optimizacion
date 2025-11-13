"""Cálculo de PVR con fallback de ventana y reporte detallado."""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.config import Config

BASE_WINDOWS = [
    ("07:00", "09:00", "base"),
    ("06:30", "09:30", "extended"),
]
FALLBACK_WINDOW_MINUTES = 120


def _parse_time(value: str) -> Optional[timedelta]:
    if pd.isna(value):
        return None
    parts = str(value).split(":")
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2]) if len(parts) > 2 else 0
    except Exception:
        return None
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


def _format_td(value: timedelta) -> str:
    total_seconds = int(value.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"


def _normalize_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y%m%d")


def _choose_default_date(feed_info: pd.DataFrame) -> datetime:
    if {"feed_start_date", "feed_end_date"}.issubset(feed_info.columns):
        start = _normalize_date(feed_info["feed_start_date"].iloc[0])
        end = _normalize_date(feed_info["feed_end_date"].iloc[0])
        candidate = min(max(datetime.today(), start), end)
    else:
        candidate = datetime.today()
    while candidate.weekday() != 0:  # Monday
        candidate -= timedelta(days=1)
    return candidate


def _find_last_weekday_with_service(
    calendar: pd.DataFrame,
    calendar_dates: pd.DataFrame,
    start_date: datetime,
    target_weekday: int = 0,
) -> datetime:
    date_candidate = start_date
    for _ in range(60):  # safeguard
        if date_candidate.weekday() == target_weekday:
            services = _service_ids_for_date(calendar, calendar_dates, date_candidate)
            if services:
                return date_candidate
        date_candidate -= timedelta(days=1)
    return start_date


def _service_ids_for_date(calendar: pd.DataFrame, calendar_dates: pd.DataFrame, date: datetime) -> List[str]:
    date_str = date.strftime("%Y%m%d")
    weekday_col = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ][date.weekday()]

    weekday_flags = calendar[weekday_col].astype(str)
    valid = calendar[
        (weekday_flags == "1")
        & (calendar["start_date"] <= date_str)
        & (calendar["end_date"] >= date_str)
    ]["service_id"].tolist()

    if not calendar_dates.empty:
        additions = calendar_dates[(calendar_dates["date"] == date_str) & (calendar_dates["exception_type"] == "1")]
        removals = calendar_dates[(calendar_dates["date"] == date_str) & (calendar_dates["exception_type"] == "2")]
        valid = list(set(valid + additions["service_id"].tolist()) - set(removals["service_id"].tolist()))
    return valid


def _load_crosswalk() -> pd.DataFrame:
    path = os.path.join(Config.DATA_PROCESSED, "route_crosswalk.csv")
    if not os.path.exists(path):
        raise FileNotFoundError("route_crosswalk.csv no encontrado. Ejecuta primero python -m src.cli crosswalk")
    df = pd.read_csv(path, dtype=str)
    matched = df[df["gtfs_route_id"].notna()].copy()
    if matched.empty:
        raise ValueError("Crosswalk sin coincidencias. Completa route_crosswalk_manual.csv y reintenta.")
    return matched


def _precompute_trip_stats(stop_times: pd.DataFrame, trips: pd.DataFrame) -> pd.DataFrame:
    st = stop_times.copy()
    st["departure_td"] = st["departure_time"].apply(_parse_time)
    st["arrival_td"] = st["arrival_time"].apply(_parse_time)
    trip_stats = st.sort_values("stop_sequence").groupby("trip_id").agg(
        first_departure_td=("departure_td", "first"),
        last_arrival_td=("arrival_td", "last"),
    ).reset_index()
    trip_stats = trip_stats.merge(trips[["trip_id", "route_id"]], on="trip_id", how="left")
    return trip_stats


def _departures_in_window(
    trip_stats: pd.DataFrame,
    trip_ids: Iterable[str],
    start: timedelta,
    end: timedelta,
) -> int:
    subset = trip_stats[trip_stats["trip_id"].isin(trip_ids)]
    departures = subset["first_departure_td"].dropna()
    if departures.empty:
        return 0
    return int(((departures >= start) & (departures <= end)).sum())


def _compute_cycle_minutes(trip_stats: pd.DataFrame, trip_ids: Iterable[str]) -> Optional[float]:
    subset = trip_stats[trip_stats["trip_id"].isin(trip_ids)]
    durations = (subset["last_arrival_td"] - subset["first_departure_td"]).dropna()
    durations = durations[durations > timedelta(0)]
    if durations.empty:
        return None
    return durations.max().total_seconds() / 60 * 2


def _best_window(
    trip_stats: pd.DataFrame,
    trip_ids: Iterable[str],
    window_minutes: int = FALLBACK_WINDOW_MINUTES,
) -> Tuple[Optional[timedelta], Optional[timedelta], int]:
    subset = trip_stats[trip_stats["trip_id"].isin(trip_ids)]
    departures = subset["first_departure_td"].dropna().sort_values()
    if departures.empty:
        return None, None, 0
    departures = departures.tolist()
    best_count = 0
    best_start = None
    end_delta = timedelta(minutes=window_minutes)
    j = 0
    for i, start in enumerate(departures):
        while j < len(departures) and departures[j] <= start + end_delta:
            j += 1
        count = j - i
        if count > best_count:
            best_count = count
            best_start = start
    if best_count == 0 or best_start is None:
        return None, None, 0
    return best_start, best_start + end_delta, best_count


def main(
    layover_factor: Optional[float] = None,
    date: Optional[str] = None,
    auto_weekday: bool = False,
) -> bool:
    layover = layover_factor if layover_factor is not None else Config.LAYOVER_FACTOR

    gtfs_dir = os.path.join(Config.DATA_RAW, "gtfs")
    trips = pd.read_csv(os.path.join(gtfs_dir, "trips.txt"), dtype=str)
    stop_times = pd.read_csv(os.path.join(gtfs_dir, "stop_times.txt"), dtype=str)
    calendar = pd.read_csv(os.path.join(gtfs_dir, "calendar.txt"), dtype=str)
    try:
        calendar_dates = pd.read_csv(os.path.join(gtfs_dir, "calendar_dates.txt"), dtype=str)
    except FileNotFoundError:
        calendar_dates = pd.DataFrame(columns=["service_id", "date", "exception_type"])
    try:
        feed_info = pd.read_csv(os.path.join(gtfs_dir, "feed_info.txt"), dtype=str)
    except FileNotFoundError:
        feed_info = pd.DataFrame()

    if date:
        date_dt = datetime.strptime(date, "%Y-%m-%d")
    elif auto_weekday:
        base = _choose_default_date(feed_info) if not feed_info.empty else datetime.today()
        date_dt = base
    else:
        date_dt = _choose_default_date(feed_info) if not feed_info.empty else datetime.today()
        print(f"ℹ️  Fecha seleccionada para PVR: {date_dt.strftime('%Y-%m-%d')}")

    if auto_weekday:
        base_candidate = date_dt
        date_dt = _find_last_weekday_with_service(calendar, calendar_dates, base_candidate)
        print(f"ℹ️  Fecha auto seleccionada (último lunes con servicio): {date_dt.strftime('%Y-%m-%d')}")

    service_ids = _service_ids_for_date(calendar, calendar_dates, date_dt)
    if not service_ids:
        print("❌ No hay servicios activos para la fecha seleccionada. Prueba otra fecha o usa --auto-weekday.")
        return False

    filtered_trips = trips[trips["service_id"].isin(service_ids)]
    if filtered_trips.empty:
        print("❌ No hay viajes para la fecha seleccionada tras filtrar service_id.")
        return False

    trip_stats = _precompute_trip_stats(stop_times, filtered_trips)
    crosswalk = _load_crosswalk()

    resultados = []
    fallback_summary = defaultdict(list)
    excluded_routes = []

    for _, row in crosswalk.iterrows():
        geo_code = row["geo_code"]
        route_id = row["gtfs_route_id"]
        trips_route = filtered_trips[filtered_trips["route_id"] == route_id]
        if trips_route.empty:
            excluded_routes.append((geo_code, "no_service"))
            continue

        trip_ids = trips_route["trip_id"].tolist()
        cycle = _compute_cycle_minutes(trip_stats, trip_ids)
        if cycle is None:
            excluded_routes.append((geo_code, "no_cycle"))
            continue

        window_used: Optional[Tuple[str, str]] = None
        window_label = "base"
        departures_count = 0
        headway = None

        for start_str, end_str, label in BASE_WINDOWS:
            start_td = _parse_time(f"{start_str}:00")
            end_td = _parse_time(f"{end_str}:00")
            if start_td is None or end_td is None:
                continue
            departures_count = _departures_in_window(trip_stats, trip_ids, start_td, end_td)
            if departures_count > 0:
                window_used = (start_str, end_str)
                window_label = label
                window_minutes = (end_td - start_td).total_seconds() / 60
                headway = window_minutes / departures_count
                break

        if headway is None:
            best_start, best_end, count = _best_window(trip_stats, trip_ids)
            if best_start is not None and count > 0:
                departures_count = count
                headway = FALLBACK_WINDOW_MINUTES / count
                window_used = (_format_td(best_start), _format_td(best_end))
                window_label = "best"
            else:
                excluded_routes.append((geo_code, "excluded_no_service"))
                resultados.append({
                    "geo_code": geo_code,
                    "gtfs_route_id": route_id,
                    "route_short_name": row.get("gtfs_route_short"),
                    "headway_min": np.nan,
                    "cycle_time_min": round(cycle, 2),
                    "layover_factor": layover,
                    "cycle_adjusted_min": np.nan,
                    "PVR": 0,
                    "fecha": date_dt.strftime("%Y-%m-%d"),
                    "window_start": "",
                    "window_end": "",
                    "window_method": "excluded_no_service",
                    "departures_window": 0,
                    "notes": "excluded_no_service",
                })
                continue

        cycle_adjusted = cycle * (1 + layover)
        pvr_value = max(1, int(np.ceil(cycle_adjusted / headway))) if headway > 0 else 0

        if window_label != "base":
            fallback_summary[window_label].append(geo_code)

        resultados.append({
            "geo_code": geo_code,
            "gtfs_route_id": route_id,
            "route_short_name": row.get("gtfs_route_short"),
            "headway_min": round(headway, 2) if headway else np.nan,
            "cycle_time_min": round(cycle, 2),
            "layover_factor": layover,
            "cycle_adjusted_min": round(cycle_adjusted, 2),
            "PVR": pvr_value,
            "fecha": date_dt.strftime("%Y-%m-%d"),
            "window_start": window_used[0] if window_used else "",
            "window_end": window_used[1] if window_used else "",
            "window_method": window_label,
            "departures_window": departures_count,
            "notes": "" if window_label == "base" else f"window_{window_label}",
        })

    df = pd.DataFrame(resultados)
    output_path = os.path.join(Config.DATA_PROCESSED, "pvr_por_ruta.csv")
    df.to_csv(output_path, index=False, encoding="utf-8")
    print(f"✓ PVR guardado en {output_path} ({len(df[df['PVR'] > 0])} rutas con PVR>0)")

    if excluded_routes:
        excl = ", ".join(sorted({geo for geo, _ in excluded_routes}))
        print("⚠️  Rutas excluidas por falta de servicio:", excl)

    _write_report(date_dt, resultados, fallback_summary, excluded_routes)

    return df[df["PVR"] > 0].empty is False


def _write_report(
    date_dt: datetime,
    resultados: List[Dict[str, object]],
    fallback_summary: Dict[str, List[str]],
    excluded_routes: List[Tuple[str, str]],
) -> None:
    report_path = os.path.join(Config.DATA_PROCESSED, "pvr_report.txt")
    total_routes = len(resultados)
    base = sum(1 for r in resultados if r.get("window_method") == "base")
    extended = len(fallback_summary.get("extended", []))
    best = len(fallback_summary.get("best", []))
    excluded = {geo: reason for geo, reason in excluded_routes}

    lines = [
        f"Fecha utilizada: {date_dt.strftime('%Y-%m-%d')}",
        f"Total rutas procesadas: {total_routes}",
        f"Ventana base (07:00-09:00): {base}",
        f"Ventana extendida (06:30-09:30): {extended}",
        f"Ventana optimizada (mejor bloque de 120 min): {best}",
        f"Rutas excluidas sin servicio: {len(excluded)}",
    ]

    if fallback_summary:
        lines.append("\nDetalle de fallbacks:")
        for key, routes in fallback_summary.items():
            if routes:
                lines.append(f"- {key}: {', '.join(sorted(routes))}")
    if excluded:
        lines.append("\nRutas excluidas:")
        for geo, reason in excluded.items():
            lines.append(f"- {geo}: {reason}")

    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"ℹ️  Reporte de PVR generado en {report_path}")
