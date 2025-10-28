"""
Cálculo de Peak Vehicle Requirement con soporte de fecha explícita y crosswalk.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd

from src.config import Config


def _parse_time(time_str: str) -> Optional[timedelta]:
    if pd.isna(time_str):
        return None
    parts = str(time_str).split(":")
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2]) if len(parts) > 2 else 0
    except Exception:
        return None
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


def _normalize_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y%m%d")


def _choose_default_date(feed_info: pd.DataFrame) -> datetime:
    if {"feed_start_date", "feed_end_date"}.issubset(feed_info.columns):
        start = _normalize_date(feed_info["feed_start_date"].iloc[0])
        end = _normalize_date(feed_info["feed_end_date"].iloc[0])
        candidate = min(max(datetime.today(), start), end)
    else:
        candidate = datetime.today()
    while candidate.weekday() != 0:
        candidate -= timedelta(days=1)
    return candidate


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


def _precompute_trip_stats(stop_times: pd.DataFrame) -> pd.DataFrame:
    stop_times = stop_times.copy()
    stop_times["departure_td"] = stop_times["departure_time"].apply(_parse_time)
    stop_times["arrival_td"] = stop_times["arrival_time"].apply(_parse_time)
    trip_stats = stop_times.sort_values("stop_sequence").groupby("trip_id").agg(
        first_departure_td=("departure_td", "first"),
        last_arrival_td=("arrival_td", "last"),
    ).reset_index()
    return trip_stats


def _compute_headway(trip_stats: pd.DataFrame, trip_ids: List[str]) -> Optional[float]:
    subset = trip_stats[trip_stats["trip_id"].isin(trip_ids)]
    if subset.empty:
        return None
    times = subset["first_departure_td"].dropna()
    if times.empty:
        return None
    peak_start = _parse_time(f"{Config.PEAK_START}:00")
    peak_end = _parse_time(f"{Config.PEAK_END}:00")
    departures = times[(times >= peak_start) & (times <= peak_end)]
    if departures.empty:
        return None
    window_minutes = (peak_end - peak_start).total_seconds() / 60
    return window_minutes / len(departures)


def _compute_cycle(trip_stats: pd.DataFrame, trip_ids: List[str]) -> Optional[float]:
    subset = trip_stats[trip_stats["trip_id"].isin(trip_ids)]
    if subset.empty:
        return None
    durations = (subset["last_arrival_td"] - subset["first_departure_td"]).dropna()
    durations = durations[durations > timedelta(0)]
    if durations.empty:
        return None
    return durations.max().total_seconds() / 60 * 2


def main(layover_factor: Optional[float] = None, date: Optional[str] = None) -> bool:
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
    else:
        date_dt = _choose_default_date(feed_info) if not feed_info.empty else datetime.today()
        print(f"ℹ️  Fecha seleccionada para PVR: {date_dt.strftime('%Y-%m-%d')}")

    service_ids = _service_ids_for_date(calendar, calendar_dates, date_dt)
    if not service_ids:
        print("❌ No hay servicios activos para la fecha seleccionada. Prueba otra fecha.")
        return False

    filtered_trips = trips[trips["service_id"].isin(service_ids)]
    if filtered_trips.empty:
        print("❌ No hay viajes para la fecha seleccionada tras filtrar service_id.")
        return False

    trip_stats = _precompute_trip_stats(stop_times)
    crosswalk = _load_crosswalk()
    resultados = []
    warnings = []

    for _, row in crosswalk.iterrows():
        geo_code = row["geo_code"]
        route_id = row["gtfs_route_id"]
        trips_route = filtered_trips[filtered_trips["route_id"] == route_id]
        if trips_route.empty:
            warnings.append(geo_code)
            continue
        trip_ids = trips_route["trip_id"].tolist()
        headway = _compute_headway(trip_stats, trip_ids)
        cycle = _compute_cycle(trip_stats, trip_ids)
        if headway and cycle:
            cycle_adjusted = cycle * (1 + layover)
            pvr = int(np.ceil(cycle_adjusted / headway))
            resultados.append({
                "geo_code": geo_code,
                "gtfs_route_id": route_id,
                "route_short_name": row.get("gtfs_route_short"),
                "headway_min": round(headway, 2),
                "cycle_time_min": round(cycle, 2),
                "layover_factor": layover,
                "cycle_adjusted_min": round(cycle_adjusted, 2),
                "PVR": max(1, pvr),
                "fecha": date_dt.strftime("%Y-%m-%d"),
                "notes": "",
            })
        else:
            warnings.append(geo_code)

    df = pd.DataFrame(resultados)
    output_path = os.path.join(Config.DATA_PROCESSED, "pvr_por_ruta.csv")
    df.to_csv(output_path, index=False, encoding="utf-8")
    print(f"✓ PVR guardado en {output_path} ({len(df)} rutas)")
    if warnings:
        print("⚠️  Rutas sin PVR calculado:", ", ".join(sorted(set(warnings))[:10]))
    return not df.empty
