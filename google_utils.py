"""Утилиты работы с Google Sheets и Google Calendar через service -account."""

import os, datetime as dt, logging, json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv
from typing import Tuple
load_dotenv()
# ────────────────── переменные окружения ──────────────────
SERVICE_FILE = os.getenv("GOOGLE_SERVICE_FILE", "service_account.json")
GSHEET_ID    = os.getenv("GSHEET_ID")
GCAL_ID      = os.getenv("GCAL_ID")

if not GSHEET_ID:
    raise RuntimeError("❗ GSHEET_ID не задан. Добавьте его в .env или переменные окружения.")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar",
]
creds = service_account.Credentials.from_service_account_file(SERVICE_FILE, scopes=SCOPES)

sheets_service   = build("sheets",   "v4", credentials=creds)
calendar_service = build("calendar", "v3", credentials=creds)

# ───────────────── Sheets ───────────────────────────────

def append_row(row: list[str]):
    """Добавить строку в конец листа 'Bookings'."""
    try:
        body = {"values": [row]}
        logging.info(f"📅 append_row: {row}")
        result = sheets_service.spreadsheets().values().append(
            spreadsheetId=GSHEET_ID,
            range="Bookings!A1",
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()
        logging.info(f"✅ Данные успешно записаны: {result}")
    except Exception as e:
        logging.error("❌ Ошибка при записи в Google Sheets", exc_info=True)

# --- New: Get all bookings for a user (by user_id) ---
def get_user_bookings(user_id: str):
    """Вернуть список всех бронирований пользователя по user_id из листа 'Bookings'."""
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=GSHEET_ID,
            range="Bookings!A1:Z1000"
        ).execute()
        rows = result.get("values", [])
        # Assume: [timestamp, user_id, username, booking_id, ...]
        bookings = []
        for row in rows[1:]:  # Skip header row
            if len(row) > 3 and row[1] == str(user_id):
                bookings.append({
                    "id": row[3],
                    "date": row[4] if len(row) > 4 else "",
                    "time": row[5] if len(row) > 5 else "",
                    "location": row[6] if len(row) > 6 else "",
                    "raw": row
                })
        return bookings
    except Exception as e:
        logging.error(f"❌ Ошибка при получении бронирований пользователя: {e}")
        return []

# --- New: Delete a booking by booking_id ---
def delete_booking(booking_id: str):
    """Удалить бронирование по booking_id (удаляет строку из листа 'Bookings')."""
    try:
        # Get all rows
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=GSHEET_ID,
            range="Bookings!A1:Z1000"
        ).execute()
        rows = result.get("values", [])
        # Find the row index (1-based for Sheets API), skip header
        for idx, row in enumerate(rows[1:], start=2):
            logging.info(f"Checking row {idx}: {row} for booking_id {booking_id}")
            if len(row) > 3 and row[3] == booking_id:
                # Delete the row
                sheets_service.spreadsheets().batchUpdate(
                    spreadsheetId=GSHEET_ID,
                    body={
                        "requests": [{
                            "deleteDimension": {
                                "range": {
                                    # Find the sheetId for 'Bookings' tab
                                    "sheetId": get_sheet_id_by_name('Bookings'),
                                    "dimension": "ROWS",
                                    "startIndex": idx-1,
                                    "endIndex": idx
                                }
                            }
                        }]
                    }
                ).execute()
                logging.info(f"✅ Бронирование с ID {booking_id} удалено из листа 'Bookings'.")
                return True
        logging.warning(f"❗ Бронирование с ID {booking_id} не найдено для удаления.")
        return False
    except Exception as e:
        logging.error(f"❌ Ошибка при удалении бронирования: {e}")
        return False

# --- Helper: Get sheetId by name ---
def get_sheet_id_by_name(sheet_name: str) -> int:
    try:
        spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=GSHEET_ID).execute()
        for sheet in spreadsheet.get('sheets', []):
            if sheet.get('properties', {}).get('title') == sheet_name:
                return sheet.get('properties', {}).get('sheetId')
    except Exception as e:
        logging.error(f"❌ Ошибка при получении sheetId для '{sheet_name}': {e}")
    return 0  # Default to first sheet if not found

def append_client_row(row: list[str]):
    """Добавить строку в конец листа 'Clients'."""
    try:
        body = {"values": [row]}
        logging.info(f"👤 append_client_row: {row}")
        result = sheets_service.spreadsheets().values().append(
            spreadsheetId=GSHEET_ID,
            range="Clients!A1",
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()
        logging.info(f"✅ Данные клиента успешно записаны: {result}")
    except Exception as e:
        logging.error("❌ Ошибка при записи в Google Sheets (Clients)", exc_info=True)

# ───────────────── Calendar ──────────────────────────────

FMT = "%Y-%m-%dT%H:%M:%S"

def _rfc(dtobj: dt.datetime) -> str:
    return dtobj.strftime(FMT + "+00:00")

def is_slot_free(calendar_id: str, date: str, beg: str, end: str) -> Tuple[bool, str | None, str | None]:
    """Проверить, свободен​ли интервал (UTC) и вернуть местоположение и время окончания конфликтующего события."""
    d0 = dt.datetime.fromisoformat(f"{date} {beg}")
    d1 = dt.datetime.fromisoformat(f"{date} {end}")
    events_result = calendar_service.events().list(
        calendarId=calendar_id,
        timeMin=_rfc(d0), timeMax=_rfc(d1), singleEvents=True,
        orderBy="startTime"
    ).execute()
    events = events_result.get("items", [])
    
    if not events:
        logging.info(f"⏰ Google Calendar: {beg}-{end} is FREE.")
        return True, None, None
    else:
        first_event = events[0]
        event_summary = first_event.get('summary', 'No Summary')
        event_location = first_event.get('location', 'Unknown Location')
        event_end_datetime_str = first_event.get('end', {}).get('dateTime')
        logging.info(f"⏰ Google Calendar: {beg}-{end} is BUSY due to event '{event_summary}' at '{event_location}' ending at '{event_end_datetime_str or "N/A"}'.")
        return False, event_location, event_end_datetime_str

def add_event(calendar_id: str, title: str, date: str, beg: str, end: str):
    d0 = dt.datetime.fromisoformat(f"{date} {beg}")
    d1 = dt.datetime.fromisoformat(f"{date} {end}")
    event = {
        "summary": title,
        "start": {"dateTime": _rfc(d0)},
        "end":   {"dateTime": _rfc(d1)},
    }
    calendar_service.events().insert(calendarId=calendar_id, body=event).execute()
