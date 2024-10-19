from fastapi import FastAPI, HTTPException, Query
from openai import OpenAI
import requests
import time
import os
from datetime import datetime
import json

# Configurar o cliente OpenAI com a chave correta
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ASSISTANT_ID = os.environ.get('ASSISTANT_ID')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
cx = os.environ.get('cx')

app = FastAPI()

# Configurar o cliente OpenAI com a chave correta
client = OpenAI(api_key=OPENAI_API_KEY)

# Função para enviar a lista de produtos para a API
def send_products_to_api(products):
    # Criar o thread
    thread = client.beta.threads.create()

    # Adicionar mensagens ao thread
    message = client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=f"{products}"
    )

    # Executar o thread com o assistente v2
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=ASSISTANT_ID
    )

    # Verificar o status do run até ser concluído
    timeout = 30
    start_time = time.time()
    while run.status != "completed":
        run = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id
        )
        time.sleep(0.5)
        if time.time() - start_time > timeout:
            raise HTTPException(status_code=500, detail="Timeout ao executar o thread")

    # Recuperar as mensagens do thread após o run ser completado
    messages = client.beta.threads.messages.list(
        thread_id=thread.id
    )

    # Extrair as informações da resposta do OpenAI
    result = None
    for message in messages:
        for content in message.content:
            if content.text:
                result = content.text.value
                break
        if result:
            break

    # Retornar a última resposta do assistente
    return result

# Endpoint de pesquisa de produtos
@app.get("/search_product/")
def search_product(product_name: str = Query(..., min_length=3, max_length=50)):
    # Realizar pesquisa no Google
    search_results = requests.get(f"https://www.googleapis.com/customsearch/v1?q={product_name}&key={GOOGLE_API_KEY}&cx={cx}").json()

    # Enviar a lista de produtos para a API
    products = search_results.get('items', [])
    result = send_products_to_api(products)

    # Retornar a resposta em formato JSON
    return json.loads(result)
