import hashlib
import random
import requests
import time
import uuid
import json
from tqdm import tqdm



def generate_qrator_token(url):
    """
    Генерирует токен и временную метку для QRATOR.

    :param url: URL-адрес, для которого требуется токен.
    :return: Tuple (токен, временная метка).
    """
    static_key = "3daca8c0f63e0f1094fbba6cc874d615"
    timestamp = str(int(time.time()))
    token = hashlib.md5(f"{static_key}{url}{timestamp}".encode('utf-8')).hexdigest()
    return token, timestamp


def generate_device_id():
    """
    Генерирует уникальный идентификатор устройства.

    :return: Строковый идентификатор устройства.
    """
    return f"{uuid.uuid4()}-{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))}"


def create_headers(device_id, session_token, url, additional_headers=None):
    """
    Создаёт заголовки HTTP-запроса.

    :param device_id: Идентификатор устройства.
    :param session_token: Токен сессии.
    :param url: URL-адрес запроса.
    :param additional_headers: Дополнительные заголовки (необязательно).
    :return: Словарь с заголовками.
    """
    traceparent = f"00-{str(uuid.uuid4()).replace('-', '')}-01"
    qrator_token, timestamp = generate_qrator_token(url)
    headers = {
        'Traceparent': traceparent,
        'App-Version': '6.24.1',
        'Timestamp': timestamp,
        'Qrator-Token': qrator_token,
        'Sessiontoken': session_token,
        'Deviceid': device_id,
        'X-Retail-Brand': 'lo',
        'X-Platform': 'omniapp',
        'Accept-Encoding': 'gzip, deflate, br',
        'User-Agent': 'okhttp/4.9.1',
        'Connection': 'keep-alive'
    }
    if additional_headers:
        headers.update(additional_headers)
    return headers


def get_session_token(device_id):
    """
    Получает токен сессии для взаимодействия с API.

    :param device_id: Идентификатор устройства.
    :return: Токен сессии или None в случае ошибки.
    """
    url = "https://lentochka.lenta.com/api/rest/siteSettingsGet"
    headers = create_headers(device_id, 'null', url, {
        'Localtime': time.strftime('%Y-%m-%dT%H:%M:%S+03:00', time.gmtime()),
        'Sentry-Trace': str(uuid.uuid4()).replace('-', ''),
        'Baggage': f"sentry-environment=production,sentry-public_key=f9ad83e90a2441998bd9ec0acb1a3dbe,sentry-release=com.icemobile.lenta.prod%406.24.1%2B2371,sentry-sample_rate=0.300000011920929,sentry-sampled=false,sentry-trace_id={str(uuid.uuid4()).replace('-', '')},sentry-transaction=MainActivity"
    })
    response = requests.get(url, headers=headers, params={"request": json.dumps({
        "Head": {
            "Method": "siteSettingsGet",
            "RequestId": str(uuid.uuid4()),
            "DeviceId": device_id,
            "Client": "android_9_6.24.1",
            "AdvertisingId": "",
            "Experiments": "",
            "Status": None,
            "MarketingPartnerKey": "mp402-8a74f99040079ea25d64d14b5212b0e3"
        }
    })})
    return response.json()['Head'].get('SessionToken') if response.status_code == 200 else None


def get_catalog_item(device_id, session_token, item_id):
    """
    Получает информацию о товаре из каталога по его ID.

    :param device_id: Идентификатор устройства.
    :param session_token: Токен сессии.
    :param item_id: ID товара.
    :return: Название бренда товара или None.
    """
    url = f"https://api.lenta.com/v1/catalog/items/{item_id}"
    headers = create_headers(device_id, session_token, url)
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return next((attr["value"] for attr in response.json()["attributes"] if attr["name"] == "Бренд"), None)
    elif response.status_code == 429:
        time.sleep(5)
    return None


def set_store(device_id, session_token, storeId):
    """
    Устанавливает магазин для текущей сессии.

    :param device_id: Идентификатор устройства.
    :param session_token: Токен сессии.
    :param storeId: ID магазина.
    :return: Ответ сервера или сообщение об ошибке.
    """
    url = 'https://lentochka.lenta.com/jrpc/pickupStoreSelectedSet'
    headers = create_headers(device_id, session_token, url, {
        'Content-Type': 'application/json; charset=utf-8',
        'Localtime': time.strftime('%Y-%m-%dT%H:%M:%S+03:00', time.gmtime())
    })
    response = requests.post(url, headers=headers, data=json.dumps({
        "jsonrpc": "2.0",
        "method": "pickupStoreSelectedSet",
        "id": 1738023249752,
        "params": {"storeId": storeId}
    }))
    return response.json() if response.status_code == 200 else f"Ошибка: {response.status_code}"


def get_store_ids(device_id, session_token):
    """
    Получает ID магазинов в Москве и Санкт-Петербурге.
    :param device_id: Идентификатор устройства.
    :param session_token: Токен сессии.
    :return: Список ID магазинов.
    """
    url = "https://lenta.com/api/v1/stores/"
    headers = create_headers(device_id, session_token, url)
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"Ошибка при получении списка магазинов: {response.status_code}")
        return []
    stores_data = response.json()
    store_ids = [
        (store["id"], store['name'])
        for store in stores_data
        if store["cityKey"] in ('spb', 'msk')
    ]
    return store_ids


def get_catalog(categoryId, limit_total, storeId):
    """
    Получает список товаров из каталога по указанной категории с ограничением общего количества.
    :param categoryId: ID категории товаров.
    :param limit_total: Общее количество товаров для загрузки.
    :param storeId: ID магазина.
    :return: Список товаров или сообщение об ошибке.
    """
    def check_code_exists(data: dict, target_code: str) -> bool:
        """
        Проверяет наличие искомого значения в графах 'code' входного словаря.
        :param data: Входной словарь для проверки.
        :param target_code: Искомое значение кода.
        :return: True, если искомое значение найдено, иначе False.
        """
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, dict) and 'code' in value.keys():
                    if value['code'] == target_code:
                        return True
                elif isinstance(value, list):
                    for item in value:
                        if check_code_exists(item, target_code):
                            return True
        return False

    url = f'https://lenta.com/api/v1/stores/{storeId}/skus'
    device_id = generate_device_id()
    session_token = get_session_token(device_id)
    headers = create_headers(device_id, session_token, url, {
        'Content-Type': 'application/json; charset=utf-8'
    })

    all_products = []
    page_limit = 24
    offset = 0
    progress_bar = tqdm(total=limit_total, desc="Загрузка товаров", unit="товар")

    while len(all_products) < limit_total:
        response = requests.post(url, headers=headers, data=json.dumps({
            "offset": offset,
            "limit": page_limit
        }))
        if response.status_code != 200:
            print(f"Ошибка при получении данных: {response.status_code}")
            break

        data = response.json()
        if "skus" not in data or not data["skus"]:
            break

        extracted_data = [{
            "id": item["code"],
            "name": item["title"],
            "regular_price": item["regularPrice"],
            "promo_price": item["discountPrice"],
            "brand": item['brand']
        } for item in data["skus"] if check_code_exists(item['categories'], categoryId)]


        all_products.extend(extracted_data)

        progress_bar.update(len(extracted_data))

        if len(all_products) >= limit_total:
            break

        offset += page_limit

    progress_bar.close()
    return all_products[:limit_total]


def save_to_json(filename, products):
    """
    Сохраняет список товаров в JSON-файл.

    :param filename: Имя файла.
    :param products: Список товаров.
    """
    with open(filename, "w", encoding="utf-8") as jsonfile:
        json.dump(products, jsonfile, indent=4, ensure_ascii=False)


def get_all_categories_from_catalog(storeId):
    """
    Получает список всех категорий путем запроса всего каталога без фильтрации.

    :param storeId: ID магазина.
    :return: Словарь, где ключ - ID категории, значение - название категории.
    """
    url = f"https://lenta.com/api/v1/stores/{storeId}/catalog"
    device_id = generate_device_id()
    session_token = get_session_token(device_id)

    headers = create_headers(device_id, session_token, url, {
        'Content-Type': 'application/json; charset=utf-8'
    })

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Ошибка запроса: {response.status_code}")

    data = response.json()
    categories_dict = {}

    def find(dictionary):
        categories_dict[dictionary['code']] = dictionary['name']
        if 'categories' in dictionary.keys() :
            if dictionary['categories']:
                for cat in dictionary['categories']:
                    find(cat)
        if 'subcategories' in dictionary.keys():
            if dictionary['subcategories']:
                for cat in dictionary['subcategories']:
                    find(cat)

    for category in data:
        find(category)
    return categories_dict


def select_store(device_id, session_token):
    """
    Позволяет пользователю выбрать магазин из списка доступных.
    :param device_id: Идентификатор устройства.
    :param session_token: Токен сессии.
    :return: Выбранный ID магазина или None, если выбор не был сделан.
    """
    store_ids = get_store_ids(device_id, session_token)
    if not store_ids:
        print("Не удалось найти доступные магазины.")
        return None

    print("Доступные магазины:")
    for idx, (store_id, address) in enumerate(store_ids, start=1):
        print(f"{idx}. ID: {store_id}, Адрес: {address}")

    while True:
        try:
            choice = input("Выберите номер магазина: ")
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(store_ids):
                selected_store_id, selected_address = store_ids[choice_idx]
                print(f"Выбран магазин: ID={selected_store_id}, Адрес={selected_address}")
                return selected_store_id
            else:
                print("Неверный номер. Пожалуйста, выберите существующий номер из списка.")
        except ValueError:
            print("Пожалуйста, введите число.")


def main():
    """
    Основная функция программы.
    Загружает товары из каталога и сохраняет их в файл.
    Также получает список всех категорий через запрос всего каталога.
    """
    device_id = generate_device_id()
    session_token = get_session_token(device_id)

    if not session_token:
        print("Не удалось получить токен сессии.")
        return

    selected_store_id = select_store(device_id, session_token)
    print("\n" * 100)
    if not selected_store_id:
        print("Магазин не выбран. Программа завершается.")
        return

    set_store_result = set_store(device_id, session_token, selected_store_id)
    if isinstance(set_store_result, str) and "Ошибка" in set_store_result:
        print(set_store_result)
        return

    print("Получение списка всех категорий...")
    categories = get_all_categories_from_catalog(selected_store_id)
    if categories:
        print("Список категорий:")
        for ind, key in enumerate(categories.keys()):
            print(f"Номер: {ind} -> ID: {key}, Название: {categories[key]}")
    selected_category_id = list(categories.keys())[int(input('Введите номер категории: '))]
    print("\n" * 100)
    all_products = get_catalog(selected_category_id, 100, selected_store_id)
    if all_products:
        save_to_json("продукты.json", all_products)
        print("Данные сохранены.")


if __name__ == "__main__":
    main()
