import os
import json
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from supabase import create_client, Client
from dotenv import load_dotenv
import logging
import time
from tabulate import tabulate

# --- Логирование ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# --- Загрузка переменных окружения ---
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", "chunks")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 500))
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")

# --- Проверка конфигов ---
if not SUPABASE_URL or not SUPABASE_KEY or not OPENAI_API_KEY:
    logging.error("Не заданы переменные окружения SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai = OpenAI(api_key=OPENAI_API_KEY)

# --- Загрузка URL ---
with open("docu/source-urls.json", encoding="utf-8") as f:
    urls = [item["url"] for item in json.load(f)]

def extract_main_content(html):
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")
    if main:
        return main.get_text(separator="\n", strip=True)
    return soup.body.get_text(separator="\n", strip=True) if soup.body else soup.get_text(separator="\n", strip=True)

def chunk_text(text, chunk_size=2048, chunk_overlap=200):
    """
    Рекурсивно разбивает текст на чанки по chunk_size символов с overlap.
    Сначала пытается делить по параграфам, затем по предложениям, затем по словам, затем по символам.
    """
    import re
    def split_recursive(text, chunk_size, chunk_overlap):
        # Базовый случай: если текст короткий — вернуть как есть
        if len(text) <= chunk_size:
            return [text.strip()]
        # 1. Параграфы
        paragraphs = re.split(r'\n{2,}', text)
        if len(paragraphs) > 1:
            return _split_chunks(paragraphs, chunk_size, chunk_overlap, joiner='\n\n')
        # 2. Предложения
        sentences = re.split(r'(?<=[.!?]) +', text)
        if len(sentences) > 1:
            return _split_chunks(sentences, chunk_size, chunk_overlap, joiner=' ')
        # 3. Слова
        words = text.split()
        if len(words) > 1:
            return _split_chunks(words, chunk_size, chunk_overlap, joiner=' ')
        # 4. Символы
        return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size - chunk_overlap)]

    def _split_chunks(parts, chunk_size, chunk_overlap, joiner):
        chunks = []
        current = []
        current_len = 0
        for part in parts:
            part_len = len(part) + len(joiner) if current else len(part)
            if current_len + part_len > chunk_size and current:
                chunk = joiner.join(current).strip()
                chunks.append(chunk)
                # Overlap: захватываем последние элементы
                overlap = []
                overlap_len = 0
                for p in reversed(current):
                    overlap_len += len(p) + len(joiner)
                    overlap.insert(0, p)
                    if overlap_len >= chunk_overlap:
                        break
                current = overlap + [part]
                current_len = sum(len(p) + len(joiner) for p in current)
            else:
                current.append(part)
                current_len += part_len
        if current:
            chunk = joiner.join(current).strip()
            chunks.append(chunk)
        # Рекурсивно разбиваем слишком большие чанки
        result = []
        for chunk in chunks:
            if len(chunk) > chunk_size * 1.2:  # запас
                result.extend(split_recursive(chunk, chunk_size, chunk_overlap))
            else:
                result.append(chunk)
        return result

    return split_recursive(text, chunk_size, chunk_overlap)

def get_embedding(text):
    try:
        response = openai.embeddings.create(
            input=text,
            model=OPENAI_EMBEDDING_MODEL
        )
        return response.data[0].embedding
    except Exception as e:
        logging.error(f"Ошибка получения embedding: {e}")
        return None

def upload_chunk(chunk, embedding, url, topic):
    metadata = {
        "source_url": url,
        "topic": topic
    }
    data = {
        "content": chunk,
        "metadata": metadata,
        "embedding": embedding
    }
    try:
        supabase.table(SUPABASE_TABLE).insert(data).execute()
        logging.info(f"Загружен чанк длиной {len(chunk)} символов")
    except Exception as e:
        logging.error(f"Ошибка загрузки в Supabase: {e}")

def estimate_price(num_chunks, chunk_size=2048, model_price_per_1k=0.00002):
    # 2048 символов ≈ 700 токенов (очень грубо)
    tokens_per_chunk = 700
    total_tokens = num_chunks * tokens_per_chunk
    price = (total_tokens / 1000) * model_price_per_1k
    return round(price, 5)

MODEL_PRICES = {
    "text-embedding-3-large": 0.00013,
    "text-embedding-3-small": 0.00002
}

def main():
    url_stats = []
    all_chunks = []
    model_price = MODEL_PRICES.get(OPENAI_EMBEDDING_MODEL, 0.00002)
    for url in urls:
        logging.info(f"Оценка: {url}")
        try:
            html = requests.get(url, timeout=20).text
        except Exception as e:
            logging.error(f"Ошибка скачивания {url}: {e}")
            url_stats.append((url, 0, 0.0))
            continue
        main_content = extract_main_content(html)
        topic = url.split("/")[2]
        chunks = chunk_text(main_content)
        all_chunks.append((url, topic, chunks))
        price = estimate_price(len(chunks), model_price_per_1k=model_price)
        url_stats.append((url, len(chunks), price))
    print("\nОценка стоимости embedding:")
    url_stats_sorted = sorted(url_stats, key=lambda x: x[2], reverse=True)
    print(tabulate(url_stats_sorted, headers=["url", "number of chunks", "price, $"], tablefmt="github"))
    total_chunks = sum(x[1] for x in url_stats)
    total_price = sum(x[2] for x in url_stats)
    print(f"\nВсего чанков: {total_chunks}, примерная стоимость: ${total_price:.4f}")
    total_chunk_bytes = sum(sum(len(c.encode('utf-8')) for c in chunks) for _, _, chunks in all_chunks)
    total_chunk_mb = total_chunk_bytes / (1024 * 1024)
    print(f"\nОценочный объём памяти для всех чанков: {total_chunk_mb:.2f} МБ")
    answer = input("\nПродолжить загрузку embedding в Supabase? (y/n): ").strip().lower()
    if answer != "y":
        print("Операция отменена. Вы можете удалить ненужные URL из docu/source-urls.json и запустить скрипт снова.")
        return
    # Только теперь отправляем чанки в OpenAI и Supabase
    for url, topic, chunks in all_chunks:
        for chunk in chunks:
            embedding = get_embedding(chunk)
            if embedding:
                upload_chunk(chunk, embedding, url, topic)
            time.sleep(0.5)

if __name__ == "__main__":
    main() 