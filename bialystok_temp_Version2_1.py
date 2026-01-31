#!/usr/bin/env python3
"""
Pobiera ostatni pomiar temperatury dla stacji synop (domyślnie 12295 - Białystok)
z API: https://danepubliczne.imgw.pl/api/data/synop/id/<id>

Uruchomienie:
  python3 bialystok_temp.py
  python3 bialystok_temp.py --station 12295
  python3 bialystok_temp.py --serial-port COM1 --interval 60

Wymaga: pip install requests pyserial

Wysyłany na port ciąg ma teraz format stały (11 znaków):
ttttt//dd::
- ttttt: temperatura (szerokość 5, 1 miejsce po przecinku) lub spacje, jeśli brak temperatury
- //: dwa ukośniki (stałe)
- dd: godzina pomiaru (HH) lub "00" jeśli brak czasu
- :: dwa dwukropki (stałe)
"""

import argparse
import requests
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List
import time
import sys

# Spróbuj zaimportować pyserial, ale obsłuż brak instalacji
try:
    import serial
except Exception:
    serial = None  # później sprawdzimy i poinformujemy użytkownika

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

def format_serial_string(temp: Optional[float], dt: Optional[datetime]) -> str:
    """
    Zwraca string 11-znakowy w formacie:
    ttttt//dd::
    - ttttt: temperatura w polu szerokości 5 z jedną cyfrą po przecinku (np. " 12.3", "-05.4")
              jeśli brak temperatury -> 5 spacji
    - //: dwa stałe ukośniki
    - dd: godzina pomiaru (HH). Jeśli brak dt -> "00"
    - :: dwa stałe dwukropki
    """
    if temp is None:
        temp_field = " " * 5
    else:
        # szerokość 5, 1 miejsce po przecinku
        temp_field = f"{temp:5.1f}"
    if dt is None:
        hour_field = "00"
    else:
        hour_field = f"{dt.hour:02d}"
    out = f"{temp_field}//{hour_field}::"
    # upewnij się, że dokładnie 11 znaków
    if len(out) != 11:
        out = out[:11].ljust(11)
    return out

def open_serial(port: str, baudrate: int = 9600, timeout: float = 1.0):
    if serial is None:
        raise RuntimeError("Brak modułu 'pyserial'. Zainstaluj go: pip install pyserial")
    try:
        ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
        return ser
    except Exception as e:
        raise RuntimeError(f"Nie można otworzyć portu szeregowego {port}: {e}")

def main():
    p = argparse.ArgumentParser(description="Pobierz ostatnią zmierzoną temperaturę z depesz synop (IMGW) i wyślij na port szeregowy.")
    p.add_argument("--station", "-s", type=int, default=12295, help="ID stacji synop (domyślnie 12295 - Białystok)")
    p.add_argument("--serial-port", "-p", type=str, default="COM4", help="Port szeregowy (domyślnie COM1)")
    p.add_argument("--baud", type=int, default=9600, help="Prędkość portu szeregowego (domyślnie 9600)")
    p.add_argument("--interval", "-i", type=int, default=60, help="Interwał w sekundach między zapytaniami (domyślnie 60)")
    p.add_argument("--once", action="store_true", help="Wykonaj jednorazowy odczyt i zakończ")
    args = p.parse_args()

    ser = None
    try:
        try:
            ser = open_serial(args.serial_port, baudrate=args.baud)
            print(f"Otwarty port szeregowy: {args.serial_port} @ {args.baud}")
        except RuntimeError as e:
            # nie przerywamy działania — nadal możemy drukować dane — ale informujemy użytkownika
            print(f"Uwaga: {e}", file=sys.stderr)
            ser = None

        def do_cycle():
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

            serial_str = format_serial_string(temp, dt)
            # pokaż co wysyłamy (dla debugu)
            print(f"Wysyłam na {args.serial_port}: {repr(serial_str)}")
            if ser:
                try:
                    ser.write(serial_str.encode('ascii', errors='replace'))
                except Exception as e:
                    print(f"Błąd zapisu do portu szeregowego: {e}", file=sys.stderr)

        # jeśli --once to wykonaj jeden cykl i zakończ
        if args.once:
            do_cycle()
            return

        print(f"Uruchamiam pętlę co {args.interval} sekund. Przerwij Ctrl+C.")
        # pętla główna - wykonuj co args.interval sekund
        while True:
            start = time.time()
            do_cycle()
            elapsed = time.time() - start
            sleep_for = args.interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        print("Przerwano przez użytkownika.")
    finally:
        if ser:
            try:
                ser.close()
            except Exception:
                pass

if __name__ == "__main__":
    main()