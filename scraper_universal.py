"""
Универсальный скрапер для работы с несколькими сайтами бронирования:
- lisarent.ru (существующая логика)
- psycho.place (новый функционал)
"""
import re
import requests
import datetime as dt
import json
import ast
import logging
from typing import List, Tuple, Dict, Optional, Union
from abc import ABC, abstractmethod
from google_utils import is_slot_free
from urllib.parse import urlparse
import time


# Базовый класс для всех скраперов
class BaseScraper(ABC):
    """Абстрактный базовый класс для всех скраперов"""
    
    def __init__(self, travel_time: int = 60):
        self.travel_time = travel_time
        self.headers = {"User-Agent": "Mozilla/5.0"}
    
    @abstractmethod
    def load_schedule(self, location: str, date_str: str) -> dict:
        """Загружает расписание для указанной локации и даты"""
        pass
    
    @abstractmethod
    def get_location_title(self, location: str) -> str:
        """Возвращает полное название локации"""
        pass
    
    @abstractmethod
    def is_valid_cabinet(self, location: str, cabinet_name: str) -> bool:
        """Проверяет, подходит ли кабинет для бронирования"""
        pass


class LisaRentScraper(BaseScraper):
    """Скрапер для сайта lisarent.ru"""
    
    TOKENS = {
        "novoslobodskaya": "ef73785cf2e42719d1ab861aa44cef39",
        "serpukhovskaya": "9cd85a2ad37efb34b51102589ab3404e",
        "sokolniki": "9c0cee2175bd6f749b2d3dce21f5b59e",
    }
    
    LOC_TITLES = {
        "novoslobodskaya": "U‑LISA Новослободская",
        "serpukhovskaya": "U‑LISA Серпуховская",
        "sokolniki": "U‑LISA Сокольники",
    }
    
    CAB_FILTER = {
        "novoslobodskaya": re.compile(r".*", re.I),
        "serpukhovskaya": re.compile(r"Кабинет\s+[CС][\s\-]?\d", re.I),
        "sokolniki": re.compile(r".*", re.I),
    }
    
    PATTERN = re.compile(r"JSON\.parse\(\s*'(.*?)'\s*\)", re.S)
    
    def load_schedule(self, location: str, date_str: str) -> dict:
        """Загружает расписание с lisarent.ru"""
        if location not in self.TOKENS:
            logging.error(f"Unknown location for LisaRent: {location}")
            return {"resources": [], "events": []}
            
        url = f"https://lisarent.ru/scheduler/index.php?token={self.TOKENS[location]}&date={date_str}"
        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            html = response.text
            m = self.PATTERN.search(html)
            if not m:
                raise RuntimeError("❗ JSON-данные не найдены — возможно, поменялась вёрстка")
            
            raw_json = ast.literal_eval(f"'{m.group(1)}'")
            return json.loads(raw_json)
        except Exception as e:
            logging.error(f"Error loading LisaRent schedule for {location} on {date_str}: {e}")
            return {"resources": [], "events": []}
    
    def get_location_title(self, location: str) -> str:
        return self.LOC_TITLES.get(location, location)
    
    def is_valid_cabinet(self, location: str, cabinet_name: str) -> bool:
        if location == "novoslobodskaya":
            return "Кабинет с кушеткой" in cabinet_name
        else:
            cab_filter = self.CAB_FILTER.get(location)
            if cab_filter:
                return cab_filter.search(cabinet_name) and "парикмахер" not in cabinet_name.lower()
        return False


class PsychoPlaceScraper(BaseScraper):
    """Скрапер для сайта psycho.place"""
    
    # Маппинг URL-ключей на читаемые названия
    LOCATION_MAPPING = {
        "novokuznetskaya": "Новокузнецкая",
        "bakuninskaya": "Бакунинская", 
        "myasnitskaya-8": "Мясницкая 8",
        "polyanka": "Полянка",
        "pokrovka": "Покровка",
    }
    
    def __init__(self, travel_time: int = 60):
        super().__init__(travel_time)
        self.session = requests.Session()
        self.session.headers.update(self.headers)
    
    def _extract_location_from_url(self, url: str) -> Tuple[str, str]:
        """Извлекает локацию и ID кабинета из URL"""
        # Пример: https://psycho.place/ru/places/novokuznetskaya/novokuznetskaya-2
        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/')
        
        if len(path_parts) >= 4 and path_parts[1] == "places":
            location = path_parts[2]  # novokuznetskaya
            cabinet_id = path_parts[3] if len(path_parts) > 3 else None  # novokuznetskaya-2
            return location, cabinet_id
        return None, None
    
    def load_schedule(self, location: str, date_str: str) -> dict:
        """
        Загружает расписание с psycho.place
        location может быть как ключом (novokuznetskaya), так и полным URL
        """
        try:
            # Если передан URL, извлекаем из него локацию
            if location.startswith("http"):
                loc_key, cabinet_id = self._extract_location_from_url(location)
                if not loc_key:
                    logging.error(f"Cannot extract location from URL: {location}")
                    return {"resources": [], "events": []}
            else:
                loc_key = location
                cabinet_id = None
            
            # Формируем базовый URL для API запросов
            base_url = f"https://psycho.place/api/v1/places/{loc_key}"
            
            # Загружаем информацию о локации
            location_resp = self.session.get(f"{base_url}/info", timeout=15)
            location_resp.raise_for_status()
            location_data = location_resp.json()
            
            # Загружаем расписание
            schedule_url = f"{base_url}/schedule"
            params = {
                "date": date_str,
                "cabinet_id": cabinet_id
            }
            
            schedule_resp = self.session.get(schedule_url, params=params, timeout=15)
            schedule_resp.raise_for_status()
            schedule_data = schedule_resp.json()
            
            # Преобразуем в формат, совместимый с существующей логикой
            resources = []
            events = []
            
            # Обрабатываем кабинеты
            for cabinet in schedule_data.get("cabinets", []):
                resources.append({
                    "id": cabinet.get("id"),
                    "name": cabinet.get("name", f"Кабинет {cabinet.get('number', '?')}")
                })
                
                # Обрабатываем занятые слоты
                for booking in cabinet.get("bookings", []):
                    events.append({
                        "resource": cabinet.get("id"),
                        "start": f"{date_str} {booking.get('start_time')}",
                        "end": f"{date_str} {booking.get('end_time')}"
                    })
            
            return {"resources": resources, "events": events}
            
        except requests.exceptions.RequestException as e:
            logging.error(f"Error loading PsychoPlace schedule for {location} on {date_str}: {e}")
            return {"resources": [], "events": []}
        except Exception as e:
            logging.error(f"Unexpected error in PsychoPlace scraper: {e}")
            return {"resources": [], "events": []}
    
    def get_location_title(self, location: str) -> str:
        """Возвращает название локации"""
        if location.startswith("http"):
            loc_key, _ = self._extract_location_from_url(location)
            location = loc_key
        
        # Используем маппинг или делаем название из ключа
        if location in self.LOCATION_MAPPING:
            return f"PsychoPlace {self.LOCATION_MAPPING[location]}"
        
        # Преобразуем ключ в читаемое название
        readable = location.replace("-", " ").title()
        return f"PsychoPlace {readable}"
    
    def is_valid_cabinet(self, location: str, cabinet_name: str) -> bool:
        """Для PsychoPlace все кабинеты считаются валидными"""
        # Можно добавить специфичные фильтры при необходимости
        return True


class UniversalScraper:
    """Универсальный скрапер, который автоматически выбирает нужный скрапер"""
    
    def __init__(self, use_schedule_scraper=True):
        self.lisarent_scraper = LisaRentScraper()
        
        # Используем schedule-скрапер по умолчанию
        if use_schedule_scraper:
            try:
                from scraper_psychoplace_schedule import PsychoPlaceScheduleScraper
                self.psychoplace_scraper = PsychoPlaceScheduleScraper()
                logging.info("🚀 Using PsychoPlace Schedule Scraper (direct schedule URLs)")
            except ImportError:
                try:
                    from scraper_psychoplace_mock import PsychoPlaceMockScraper
                    self.psychoplace_scraper = PsychoPlaceMockScraper()
                    logging.warning("Schedule scraper not found, using MOCK version")
                except ImportError:
                    self.psychoplace_scraper = PsychoPlaceScraper()
                    logging.warning("Using fallback PsychoPlace scraper")
        else:
            self.psychoplace_scraper = PsychoPlaceScraper()
        
        # Кэш для хранения информации о локациях
        self._location_cache = {}
        self._load_location_mapping()
    
    def _load_location_mapping(self):
        """Загружает маппинг локаций из файла или создает новый"""
        try:
            with open("location_mapping.json", "r", encoding="utf-8") as f:
                self._location_cache = json.load(f)
        except FileNotFoundError:
            # Инициализируем базовыми локациями
            self._location_cache = {
                "novoslobodskaya": {"type": "lisarent", "display_name": "Новослободская"},
                "serpukhovskaya": {"type": "lisarent", "display_name": "Серпуховская"},
                "sokolniki": {"type": "lisarent", "display_name": "Сокольники"},
            }
            self._save_location_mapping()
    
    def _save_location_mapping(self):
        """Сохраняет маппинг локаций в файл"""
        with open("location_mapping.json", "w", encoding="utf-8") as f:
            json.dump(self._location_cache, f, ensure_ascii=False, indent=2)
    
    def _detect_scraper_type(self, location: str) -> str:
        """Определяет тип скрапера по локации"""
        # Если это URL
        if location.startswith("http"):
            if "psycho.place" in location:
                return "psychoplace"
            elif "lisarent.ru" in location:
                return "lisarent"
        
        # Проверяем кэш
        if location in self._location_cache:
            return self._location_cache[location]["type"]
        
        # Проверяем известные локации
        if location in LisaRentScraper.TOKENS:
            return "lisarent"
        
        # По умолчанию считаем psychoplace
        return "psychoplace"
    
    def register_location(self, location_key: str, scraper_type: str, display_name: str):
        """Регистрирует новую локацию"""
        self._location_cache[location_key] = {
            "type": scraper_type,
            "display_name": display_name
        }
        self._save_location_mapping()
    
    def get_all_locations(self) -> Dict[str, dict]:
        """Возвращает все доступные локации"""
        return self._location_cache.copy()
    
    def add_schedule_url(self, location_key: str, schedule_url: str, display_name: str = None):
        """Добавляет новую ссылку на расписание PsychoPlace"""
        try:
            # Обновляем конфигурацию schedule URLs
            if hasattr(self.psychoplace_scraper, 'add_schedule_url'):
                self.psychoplace_scraper.add_schedule_url(location_key, schedule_url)
            
            # Обновляем маппинг локаций
            if display_name:
                self.register_location(location_key, "psychoplace", display_name)
            
            logging.info(f"Added schedule URL for {location_key}: {schedule_url}")
        except Exception as e:
            logging.error(f"Error adding schedule URL: {e}")
    
    def test_location_connection(self, location_key: str, date_str: str = None) -> bool:
        """Тестирует подключение к локации"""
        if not date_str:
            from datetime import datetime, timedelta
            date_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        try:
            scraper_type = self._detect_scraper_type(location_key)
            if scraper_type == "psychoplace":
                if hasattr(self.psychoplace_scraper, 'test_connection'):
                    return self.psychoplace_scraper.test_connection(location_key, date_str)
            
            # Для LisaRent или если метод test_connection недоступен
            data = self.get_available(location_key, date_str, "10:00", "18:00", min_len=90)
            return data is not None
            
        except Exception as e:
            logging.error(f"Error testing connection for {location_key}: {e}")
            return False
    
    def get_available(self, loc_key: str, date_str: str,
                      win_start: str, win_end: str,
                      min_len: int = 90,
                      verbose: bool = False,
                      gcal_id: str = None) -> List[Union[str, Tuple[str, str, str]]]:
        """
        Универсальный метод получения доступных слотов
        Автоматически выбирает нужный скрапер
        """
        # Определяем тип скрапера
        scraper_type = self._detect_scraper_type(loc_key)
        
        if scraper_type == "lisarent":
            scraper = self.lisarent_scraper
        else:
            scraper = self.psychoplace_scraper
        
        logging.info(f"🔍 [UniversalScraper] Using {scraper_type} scraper for {loc_key}")
        
        try:
            data = scraper.load_schedule(loc_key, date_str)
        except Exception as e:
            logging.error(f"Error in load_schedule: {e}")
            return []
        
        # Фильтруем кабинеты
        id2name = {}
        for r in data["resources"]:
            name = r.get("name", "—")
            if name != "—" and scraper.is_valid_cabinet(loc_key, name):
                id2name[r["id"]] = name
        
        # Создаем карту занятости для каждого ресурса
        website_busy_minutes: Dict[str, set[int]] = {rid: set() for rid in id2name}
        for ev in data["events"]:
            rid = ev["resource"]
            if rid not in id2name:
                continue
            event_date = ev["start"].split()[0]
            if event_date != date_str:
                continue
            sh, sm = map(int, ev["start"].split()[1].split(":")[:2])
            eh, em = map(int, ev["end"].split()[1].split(":")[:2])
            start_min = sh * 60 + sm
            end_min = eh * 60 + em
            for m in range(start_min, end_min):
                website_busy_minutes[rid].add(m)
        
        ws_min = int(win_start[:2]) * 60 + int(win_start[3:])
        we_min = int(win_end[:2]) * 60 + int(win_end[3:])
        
        final_slots = []
        
        # Проверяем слоты для каждого кабинета
        for rid, cabinet_name in id2name.items():
            logging.info(f"  Processing cabinet: {cabinet_name}")
            
            last_gcal_booked_end_time_plus_travel = ws_min
            
            for slot_start_min in range(ws_min, we_min - min_len + 1, 30):
                slot_end_min = slot_start_min + min_len
                
                if slot_start_min < last_gcal_booked_end_time_plus_travel:
                    continue
                
                # Проверяем занятость на сайте
                is_website_free = True
                for m in range(slot_start_min, slot_end_min):
                    if m in website_busy_minutes[rid]:
                        is_website_free = False
                        break
                
                if is_website_free:
                    slot_start_str = f"{slot_start_min // 60:02}:{slot_start_min % 60:02}"
                    slot_end_str = f"{slot_end_min // 60:02}:{slot_end_min % 60:02}"
                    
                    is_gcal_free, event_gcal_location, event_gcal_end_str = True, None, None
                    if gcal_id:
                        is_gcal_free, event_gcal_location, event_gcal_end_str = is_slot_free(
                            gcal_id, date_str, slot_start_str, slot_end_str
                        )
                    
                    if is_gcal_free:
                        final_slots.append((cabinet_name, slot_start_str, slot_end_str))
                    else:
                        # Обработка времени на дорогу между локациями
                        if event_gcal_location:
                            current_loc_title = scraper.get_location_title(loc_key)
                            if current_loc_title.lower() in event_gcal_location.lower():
                                # Та же локация
                                if event_gcal_end_str:
                                    gcal_end_dt = dt.datetime.fromisoformat(event_gcal_end_str)
                                    gcal_end_min = gcal_end_dt.hour * 60 + gcal_end_dt.minute
                                    last_gcal_booked_end_time_plus_travel = max(
                                        last_gcal_booked_end_time_plus_travel, gcal_end_min
                                    )
                            else:
                                # Разные локации - добавляем время на дорогу
                                if event_gcal_end_str:
                                    gcal_end_dt = dt.datetime.fromisoformat(event_gcal_end_str)
                                    gcal_end_min = gcal_end_dt.hour * 60 + gcal_end_dt.minute
                                    last_gcal_booked_end_time_plus_travel = max(
                                        last_gcal_booked_end_time_plus_travel, 
                                        gcal_end_min + scraper.travel_time
                                    )
        
        # Сортируем слоты
        final_slots.sort(key=lambda x: (x[1], x[0]))
        
        if verbose:
            result = [f"{cab:<35}{beg} – {end}" for cab, beg, end in final_slots]
        else:
            result = final_slots
        
        logging.info(f"✅ Found {len(final_slots)} available slots")
        return result


# Для обратной совместимости экспортируем функцию get_available
_universal_scraper = UniversalScraper()
get_available = _universal_scraper.get_available


if __name__ == "__main__":
    import argparse
    from datetime import datetime
    
    ap = argparse.ArgumentParser()
    ap.add_argument("--loc", required=True, help="Location key or URL")
    ap.add_argument("--date", required=True, help="Date in DD-MM-YYYY format")
    ap.add_argument("--from", dest="from_", required=True)
    ap.add_argument("--to", required=True)
    ap.add_argument("--min", type=int, default=90)
    ap.add_argument("--gcal", help="Google Calendar ID")
    args = ap.parse_args()
    
    try:
        date_str = datetime.strptime(args.date, "%d-%m-%Y").strftime("%Y-%m-%d")
        result = get_available(args.loc, date_str, args.from_, args.to, args.min, 
                             verbose=True, gcal_id=args.gcal)
        print("\n".join(result))
        print(f"Всего свободных интервалов: {len(result)}")
    except Exception as e:
        print("❗ Ошибка:", e)