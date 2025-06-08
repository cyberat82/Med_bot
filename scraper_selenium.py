from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import time
from selenium.webdriver.common.action_chains import ActionChains
import datetime

# 🔧 URL локаций
LOCATION_URLS = {
    "novoslobodskaya": "https://u-lisa.ru/novoslobodskaya",
    "serpukhovskaya": "https://u-lisa.ru/serpukhovskaya",
    "sokolniki": "https://u-lisa.ru/sokolniki"
}

# 🔧 Префиксы кабинетов
CABINET_PREFIXES = {
    "novoslobodskaya": ["N" + str(i) for i in range(2, 12)],
    "serpukhovskaya": ["S" + str(i) for i in range(1, 7)],
    "sokolniki": ["E" + str(i) for i in range(2, 8)],
}

# 🚀 Настройка драйвера
def get_driver():
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless=new")  # Оставьте закомментированным для отладки
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    service = Service(executable_path="chromedriver.exe")
    return webdriver.Chrome(service=service, options=options)

# 🔍 Основная логика
def check_cabinets(location_key, date=None, start_time=None, end_time=None):
    url = LOCATION_URLS[location_key]
    driver = get_driver()
    driver.get(url)

    ru_months = [
        "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
    ]

    def add_hours_to_time(time_str, hours):
        t = datetime.datetime.strptime(time_str, "%H:%M")
        t_new = t + datetime.timedelta(hours=hours)
        return t_new.strftime("%H:%M")

    try:
        # Попытка закрыть cookie-баннер
        try:
            cookie_btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, '//button[contains(text(), "Принять все")]'))
            )
            cookie_btn.click()
            print("✅ Куки-баннер закрыт")
        except:
            print("⚠️ Куки-баннер не найден")

        # Кнопка "Забронировать"
        book_btn = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//button[contains(text(), "Забронировать")]'))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", book_btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", book_btn)
        print("✅ Кнопка 'Забронировать' нажата через JS")

        # Ждём появления виджета
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "likesolo-widget"))
        )
        print("✅ Виджет загрузился")

        # Проверка наличия iframe
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        print(f"Найдено iframe: {len(iframes)}")
        for idx, iframe in enumerate(iframes):
            print(f"Iframe {idx}: {iframe.get_attribute('outerHTML')[:200]}")
        if iframes:
            driver.switch_to.frame(iframes[0])
            print("Переключились в первый iframe")

        # Попытка кликнуть по тексту 'По часам'
        try:
            el = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'По часам')]"))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
            time.sleep(0.2)
            el.click()
            print("✅ Клик по тексту 'По часам' прошёл успешно")
        except Exception as e:
            print("❌ Не удалось кликнуть по тексту 'По часам':", e)
            driver.save_screenshot("click_hours_failed.png")
            driver.quit()
            return []

        # --- Новый этап: выбор даты и времени ---
        try:
            if date:
                # Преобразуем дату
                dt = datetime.datetime.strptime(date, "%Y-%m-%d")
                month_name = ru_months[dt.month - 1]
                year = dt.year
                day = dt.day
                # Выбрать месяц
                month_select = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "select.flatpickr-monthDropdown-months"))
                )
                select = Select(month_select)
                select.select_by_visible_text(month_name)
                print(f"✅ Месяц выбран: {month_name}")
                # Выбрать год
                year_input = driver.find_element(By.CSS_SELECTOR, "input.cur-year")
                year_input.clear()
                year_input.send_keys(str(year))
                year_input.send_keys('\n')
                print(f"✅ Год выбран: {year}")
                time.sleep(0.5)
                # Клик по нужному дню
                date_elem = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, f"//span[contains(@class, 'flatpickr-day') and not(contains(@class, 'flatpickr-disabled')) and text()='{day}']"))
                )
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", date_elem)
                time.sleep(0.2)
                date_elem.click()
                print(f"✅ Клик по дате {date}")
            else:
                # Клик по первой доступной дате
                date_elem = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".flatpickr-day:not(.flatpickr-disabled):not(.prevMonthDay):not(.nextMonthDay)"))
                )
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", date_elem)
                time.sleep(0.2)
                date_elem.click()
                print("✅ Клик по первой доступной дате")
        except Exception as e:
            print("❌ Не удалось выбрать дату:", e)
            driver.save_screenshot("date_failed.png")
            driver.quit()
            return []

        # --- Вывод всех доступных временных слотов для отладки ---
        start_elems = driver.find_elements(By.XPATH, "//div[contains(@class, 'js-slider') and contains(@class, 'time-start')]//div[contains(@class, 'js-slide')]")
        print(f"Start times:")
        for elem in start_elems:
            print(elem.get_attribute("data-time"), elem.get_attribute("class"))
        end_elems = driver.find_elements(By.XPATH, "//div[contains(@class, 'js-slider') and contains(@class, 'time-end')]//div[contains(@class, 'js-slide')]")
        print(f"End times:")
        for elem in end_elems:
            print(elem.get_attribute("data-time"), elem.get_attribute("class"))

        # --- Клик по времени начала (левый слайдер) с прокруткой вверх ---
        try:
            selected_start = None
            up_arrow = driver.find_element(By.CSS_SELECTOR, ".wrap-slider.start-time .js-up")
            for _ in range(20):  # ограничение по числу прокруток
                start_elems = driver.find_elements(By.XPATH, "//div[contains(@class, 'js-slider') and contains(@class, 'time-start')]//div[contains(@class, 'js-slide')]")
                available_starts = [elem.get_attribute("data-time") for elem in start_elems if "disabled" not in elem.get_attribute("class") and elem.get_attribute("data-time")]
                print(f"Доступные начала (итерация): {available_starts}")
                for elem in start_elems:
                    t = elem.get_attribute("data-time")
                    if t and ("disabled" not in elem.get_attribute("class")) and t >= start_time and t < end_time:
                        selected_start = t
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                        time.sleep(0.2)
                        elem.click()
                        print(f"✅ Клик по времени начала {selected_start}")
                        break
                if selected_start:
                    break
                up_arrow.click()
                time.sleep(0.2)
            if not selected_start:
                print("❌ Нет доступных времён начала в выбранном интервале!")
                driver.quit()
                return []
        except Exception as e:
            print("❌ Не удалось выбрать время начала:", e)
            driver.save_screenshot("start_time_failed.png")
            driver.quit()
            return []

        # --- Клик по времени окончания (правый слайдер, 1 час интервал, но не позже end_time) ---
        try:
            if start_time and end_time and selected_start:
                t_start = datetime.datetime.strptime(selected_start, "%H:%M")
                t_end_limit = datetime.datetime.strptime(end_time, "%H:%M")
                t_end_target = t_start + datetime.timedelta(hours=1)
                if t_end_target > t_end_limit:
                    t_end_target = t_end_limit
                target_end = t_end_target.strftime("%H:%M")
                # Прокрутка для end_time
                end_up_arrow = driver.find_element(By.CSS_SELECTOR, ".wrap-slider.end-time .js-up")
                found = None
                for _ in range(20):
                    end_elems = driver.find_elements(By.XPATH, "//div[contains(@class, 'js-slider') and contains(@class, 'time-end')]//div[contains(@class, 'js-slide')]")
                    available_ends = [elem.get_attribute("data-time") for elem in end_elems if "disabled" not in elem.get_attribute("class") and elem.get_attribute("data-time")]
                    print(f"Доступные окончания (итерация): {available_ends}")
                    for elem in end_elems:
                        t = elem.get_attribute("data-time")
                        if t and ("disabled" not in elem.get_attribute("class")) and t >= target_end and t <= end_time:
                            found = t
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                            time.sleep(0.2)
                            elem.click()
                            print(f"✅ Клик по времени окончания {found}")
                            break
                    if found:
                        break
                    end_up_arrow.click()
                    time.sleep(0.2)
                if not found:
                    # fallback: последний <= end_time
                    for elem in reversed(end_elems):
                        t = elem.get_attribute("data-time")
                        if t and ("disabled" not in elem.get_attribute("class")) and t <= end_time:
                            found = t
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                            time.sleep(0.2)
                            elem.click()
                            print(f"✅ Клик по времени окончания (fallback) {found}")
                            break
                if not found:
                    print("❌ Нет доступных времён окончания в выбранном интервале!")
                    driver.quit()
                    return []
            elif end_time:
                end_elem = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, f"//div[contains(@class, 'js-slider') and contains(@class, 'time-end')]//div[contains(@class, 'js-slide') and @data-time='{end_time}' and not(contains(@class, 'disabled'))]"))
                )
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", end_elem)
                time.sleep(0.2)
                end_elem.click()
                print(f"✅ Клик по времени окончания {end_time}")
            else:
                print("❌ Не удалось определить время окончания!")
                driver.save_screenshot("end_time_failed.png")
                driver.quit()
                return []
        except Exception as e:
            print("❌ Не удалось выбрать время окончания:", e)
            driver.save_screenshot("end_time_failed.png")
            driver.quit()
            return []

        # Клик по кнопке "Далее"
        try:
            next_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "a.btn.js-go[data-step='js-hours-step2']"))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
            time.sleep(0.2)
            next_btn.click()
            print("✅ Клик по кнопке 'Далее' для перехода к карточкам кабинетов")
        except Exception as e:
            print("❌ Не удалось кликнуть по кнопке 'Далее':", e)
            driver.save_screenshot("next_failed.png")
            driver.quit()
            return []

        # Дождаться появления карточек кабинетов (js-hours-step2)
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.ID, "js-hours-step2"))
            )
            print("✅ Карточки кабинетов загружены (js-hours-step2)")
        except Exception as e:
            print("❌ Не дождались карточек js-hours-step2:", e)
            driver.save_screenshot("no_cards.png")
            driver.quit()
            return []

    except Exception as e:
        print("❌ Общая ошибка при переходе по шагам:", e)
        driver.save_screenshot("debug_step_error.png")
        driver.quit()
        return []

    time.sleep(1)
    html = driver.page_source
    with open("debug_full_page.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("HTML страницы сохранён в debug_full_page.html")
    driver.quit()

    # 🧠 Парсим HTML карточки кабинетов
    soup = BeautifulSoup(html, "html.parser")
    results = []

    cards = soup.find_all("div", class_="card-body")
    print(f"Найдено карточек: {len(cards)}")
    if not cards:
        print("❗ ВНИМАНИЕ: Карточки не найдены! Проверьте debug_full_page.html и селектор.")
        return []

    for card in cards:
        room = card.find("div", class_="room-title")
        if not room:
            continue
        name = room.get_text(strip=True)
        status = "Свободно" if (
            card.find(string="Свободно") or card.find("div", class_="status-free")
        ) else "Занято"
        results.append(f"{name}: {status}")

    print(f"Найдено слотов: {len(results)}")
    return results

# 📤 Используется из Telegram-бота
def run_scraper(location_key, date, start_time, end_time):
    return check_cabinets(location_key, date, start_time, end_time)
