"""#!/usr/bin/env python3
"""
Pobiera ostatni pomiar temperatury dla stacji synop (domyślnie 12295 - Białystok)
z API: https://danepubliczne.imgw.pl/api/data/synop/id/<id>

Uruchomienie:
  python3 bialystok_temp.py
  python3 bialystok_temp.py --station 12295
Wymaga: pip install requests
"""

import argparse
import requests
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List

# POPRAWIONY ENDPOINT: używamy 'id' zamiast 'station'
API_BASE = "https://danepubliczne.imgw.pl/api/data/synop/id/{}"

def try_parse_datetime(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    fmts = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H",
        "%Y-%m-%d",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(date_str, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(date_str)
    except Exception:
        return None

def record_datetime(rec: Dict[str, Any]) -> Optional[datetime]:
    # Najczęściej pola w API IMGW: 'data_pomiaru' i 'godzina_pomiaru'
    if 'data_pomiaru' in rec:
        date_part = rec.get('data_pomiaru')
        time_part = rec.get('godzina_pomiaru') or rec.get('godzina') or rec.get('time')
        if isinstance(time_part, (int, float)):
            # np. 12 -> "12:00:00"
            time_part = f"{int(time_part):02d}:00:00"
        if date_part and time_part:
            combined = f"{date_part} {time_part}"
            d = try_parse_datetime(combined)
            if d:
                return d
        d = try_parse_datetime(str(date_part))
        if d:
            return d

    # inne możliwe pola
    for key in ('timestamp', 'date', 'data'):
        if key in rec and rec.get(key):
            d = try_parse_datetime(str(rec.get(key)))
            if d:
                return d
    return None

def extract_temp(rec: Dict[str, Any]) -> Optional[float]:
    # Najczęściej pole to 'temperatura'
    candidates = ['temperatura', 'temp', 'temperature', 't']
    for k in candidates:
        if k in rec and rec[k] not in (None, ''):
            v = rec[k]
            try:
                if isinstance(v, str):
                    v = v.replace(',', '.')
                return float(v)
            except Exception:
                continue
    return None

def fetch_latest_for_station(station_id: int) -> Tuple[Optional[float], Optional[datetime], Optional[Dict[str, Any]]]:
    url = API_BASE.format(station_id)
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    # API może zwracać listę rekordów (ostatnie pomiary).
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = [data]
    else:
        records = []

    if not records:
        return None, None, None

    # spróbuj policzyć datetime dla każdego rekordu i posortować malejąco
    with_dt: List[Tuple[Optional[datetime], Dict[str, Any]]] = []
    for rec in records:
        d = record_datetime(rec)
        with_dt.append((d, rec))
    with_dt.sort(key=lambda x: (x[0] is None, x[0]), reverse=True)

    # weź pierwszy rekord który ma temperaturę
    for d, rec in with_dt:
        temp = extract_temp(rec)
        if temp is not None:
            return temp, d, rec

    first_d, first_rec = with_dt[0]
    return None, first_d, first_rec

def main():
    p = argparse.ArgumentParser(description="Pobierz ostatnią zmierzoną temperaturę z depesz synop (IMGW).")
    p.add_argument("--station", "-s", type=int, default=12295, help="ID stacji synop (domyślnie 12295 - Białystok)")
    args = p.parse_args()

    try:
        temp, dt, rec = fetch_latest_for_station(args.station)
    except requests.RequestException as e:
        print(f"Błąd połączenia z API: {e}")
        return

    if rec is None:
        print(f"Brak danych dla stacji {args.station}.")
        return

    station_name = rec.get('stacja') or rec.get('station') or f"id={args.station}"
    if temp is None:
        print(f"Stacja: {station_name} (id={args.station})")
        if dt:
            print(f"Nie znaleziono pola z temperaturą w ostatnich rekordach. Ostatni dostępny czas pomiaru: {dt}")
        else:
            print("Nie znaleziono danych pomiarowych zawierających czas ani temperaturę.")
    else:
        time_str = dt.isoformat(sep=' ') if dt else "brak czasu pomiaru"
        print(f"Stacja: {station_name} (id={args.station})")
        print(f"Temperatura: {temp:.1f} °C")
        print(f"Czas pomiaru: {time_str}")

if __name__ == "__main__":
    main()