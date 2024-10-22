from datetime import datetime
from fastapi import FastAPI, HTTPException, Query
from openai import OpenAI
from pydantic import BaseModel
import html
import json
import re
import time
import os
import asyncio
import httpx  # Importa o httpx para requisições assíncronas

# Configurar o cliente OpenAI com a chave correta
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ASSISTANT_ID = os.environ.get('ASSISTANT_ID')
ASSISTANT_ID_GROUP = os.environ.get('ASSISTANT_ID_GROUP')
SEARXNG_UNIFIED_ENDPOINT = os.environ.get('SEARXNG_UNIFIED_ENDPOINT')
# GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
# cx = os.environ.get('cx')

app = FastAPI()

# Configurar o cliente OpenAI com a chave correta
client = OpenAI(api_key=OPENAI_API_KEY)

class ProductRequest(BaseModel):
    product_name: str

# Função para enviar a lista de produtos para a API
async def send_products_to_api(products, assistant_id):
    # Criar o thread
    thread = await asyncio.to_thread(client.beta.threads.create)

    # Adicionar mensagens ao thread
    message = await asyncio.to_thread(
        client.beta.threads.messages.create,
        thread_id=thread.id,
        role="user",
        content=f"{products}"
    )

    # Executar o thread com o assistente v2
    run = await asyncio.to_thread(
        client.beta.threads.runs.create,
        thread_id=thread.id,
        assistant_id=assistant_id
    )

    # Verificar o status do run até ser concluído
    timeout = 30
    start_time = time.time()
    while run.status != "completed":
        run = await asyncio.to_thread(
            client.beta.threads.runs.retrieve,
            thread_id=thread.id,
            run_id=run.id
        )
        await asyncio.sleep(0.5)
        if time.time() - start_time > timeout:
            raise HTTPException(status_code=500, detail="Timeout ao executar o thread")

    # Recuperar as mensagens do thread após o run ser completado
    messages = await asyncio.to_thread(
        client.beta.threads.messages.list,
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

# Função para validar e sanitizar a entrada do nome do produto
def validate_and_sanitize_product_name(product_name: str):
    # Validar se existe nome de produto
    if len(product_name) <= 0:
        raise HTTPException(status_code=400, detail="Nome de produto não informado.")
    
    # Limitar o tamanho do nome do produto para evitar ataques de buffer overflow
    if len(product_name) > 50:
        raise HTTPException(status_code=400, detail="Nome do produto excede o tamanho permitido.")

    # Sanitização básica contra XSS
    product_name = html.escape(product_name)

    # Expressão regular para permitir apenas letras, números, espaço, e alguns símbolos seguros (- e _)
    if not re.match(r"^[a-zA-Z0-9 _-]+$", product_name):
        raise HTTPException(status_code=400, detail="Nome do produto contém caracteres inválidos.")
    
    # Prevenção contra SQL injection: restrição simplificada apenas para os termos críticos
    sql_keywords = ["SELECT", "DROP", "INSERT", "DELETE", "UNION", "--", ";"]

    for keyword in sql_keywords:
        if re.search(rf"\b{keyword}\b", product_name, re.IGNORECASE):
            raise HTTPException(status_code=400, detail="Nome do produto contém termos suspeitos.")
    
    return product_name

# Endpoint de pesquisa de produtos
@app.post("/search_product/")
async def search_product(request: ProductRequest):
    # Extrair o nome do produto do corpo da requisição
    product_name = request.product_name
    # Continue com a lógica de validação e pesquisa
    validate_and_sanitize_product_name(product_name)
    
    try:
        async with httpx.AsyncClient() as client_http:
            search_response = await client_http.get(
                f"{SEARXNG_UNIFIED_ENDPOINT}/search",
                params={
                    "q": f"{product_name} (site:zoom.com.br OR site:buscape.com.br)",
                    "format": "json"
                },
                timeout=30
            )
            search_results = search_response.json()
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Não foi possível conectar ao serviço de pesquisa")

    if not search_results:
        return {"error": "Resposta vazia ou não é um JSON válido"}
    
    try:
        products = search_results.get('results', [])
        result = await send_products_to_api(products, ASSISTANT_ID)
        return json.loads(result)
    except json.JSONDecodeError:
        return {"error": "Resposta não é um JSON válido"}
        
# Função auxiliar para buscar produtos por tipo
async def fetch_product_type(client_http, product_type):
    try:
        search_response = await client_http.get(
            f"{SEARXNG_UNIFIED_ENDPOINT}/search",
            params={
                "q": f"{product_type} (site:zoom.com.br OR site:buscape.com.br)",
                "format": "json"
            },
            timeout=5
        )
        search_results = search_response.json()
        products = search_results.get('results', [])
        return (product_type, products)
    except httpx.RequestError:
        return (product_type, {"error": "Falha na pesquisa"})

# Função para pesquisar produtos por tipo
async def search_products_by_type():
    # Lista de tipos de produtos
    product_types = [
        "geladeira",
        "fogão",
        "micro-ondas",
        "lava-louças",
        "máquina de lavar roupa",
        "secadora de roupas",
        "aspirador de pó",
        "air fryer",
        "cafeteira",
        "torradeira",
        "liquidificador",
        "batedeira",
        "ferro de passar",
        "purificador de água",
        "ar-condicionado",
        "ventilador",
        "aquecedor",
        "panela elétrica",
        "grill elétrico",
        "forno elétrico",
        "sanduicheira",
        "fritadeira elétrica",
        "processador de alimentos",
        "coifa",
        "exaustor",
        "máquina de gelo",
        "adega climatizada",
        "máquina de costura",
        "lavadora de alta pressão",
        "cortador de grama",
        "triturador de alimentos",
        "fogão cooktop",
        "forno a gás",
        "bebedouro",
        "desumidificador",
        "umidificador",
        "aspirador robô",
        "chaleira elétrica",
        "espremedor de frutas",
        "sorveteira",
        "panela de arroz",
        "panela de pressão elétrica",
        "máquina de pão",
        "mopa a vapor",
        "purificador de ar",
        "cervejeira",
        "massageador",
        "máquina de crepe",
        "máquina de waffles",
        "forno elétrico de embutir",
        "sofá",
        "cama",
        "mesa de jantar",
        "cadeira",
        "guarda-roupa",
        "escrivaninha",
        "estante",
        "rack para TV",
        "mesa de centro",
        "poltrona",
        "colchão",
        "criado-mudo",
        "aparador",
        "penteadeira",
        "banqueta",
        "beliche",
        "painel para TV",
        "cabeceira",
        "cômoda",
        "mesa de escritório",
        "estante de livros",
        "sapateira",
        "buffet",
        "cristaleira",
        "divã",
        "camiseta",
        "calça jeans",
        "tênis",
        "bota",
        "bolsa",
        "relógio",
        "óculos de sol",
        "vestido",
        "saia",
        "camisa social",
        "jaqueta",
        "moletom",
        "blazer",
        "gravata",
        "brincos",
        "colar",
        "pulseira",
        "meia",
        "cueca",
        "sutiã",
        "boné",
        "chinelo",
        "cinto",
        "luvas",
        "cachecol",
        "perfume",
        "maquiagem",
        "shampoo",
        "condicionador",
        "creme hidratante",
        "protetor solar",
        "escova de dentes elétrica",
        "secador de cabelo",
        "chapinha",
        "barbeador elétrico",
        "aparador de pelos",
        "esfoliante",
        "sabonete líquido",
        "máscara facial",
        "kit manicure",
        "depilador elétrico",
        "lixa elétrica",
        "hidratante corporal",
        "kit de pincéis de maquiagem",
        "pinça",
        "creme anti-idade",
        "serum facial",
        "loção pós-barba",
        "tônico facial",
        "base para maquiagem",
        "bicicleta",
        "esteira",
        "roupas de ginástica",
        "halteres",
        "tênis de corrida",
        "bola de futebol",
        "skate",
        "patins",
        "suplementos alimentares",
        "tapete de yoga",
        "bicicleta ergométrica",
        "elíptico",
        "luvas de boxe",
        "barras de flexão",
        "corda de pular",
        "banco de musculação",
        "faixas elásticas",
        "step",
        "bola de pilates",
        "kettlebell",
        "roupas de natação",
        "mochila de hidratação",
        "gorro de natação",
        "óculos de natação",
        "acessórios para bicicleta",
        "smartphone",
        "notebook",
        "tablet",
        "smart TV",
        "headphone",
        "smartwatch",
        "câmera digital",
        "console de videogame",
        "caixa de som Bluetooth",
        "home theater",
        "projetor",
        "fone de ouvido sem fio",
        "monitor",
        "disco rígido externo",
        "impressora",
        "roteador",
        "mouse gamer",
        "teclado",
        "headset gamer",
        "placa de vídeo",
        "memória RAM",
        "SSD",
        "HD interno",
        "microfone",
        "leitor de e-book",
        "controle remoto universal",
        "antena digital",
        "estabilizador",
        "nobreak",
        "câmera de segurança",
        "drone",
        "power bank",
        "Chromecast",
        "Apple TV",
        "pen drive",
        "carregador de celular",
        "cabo HDMI",
        "suporte para TV",
        "adaptador USB",
        "carregador sem fio",
        "câmera instantânea",
        "fone com cancelamento de ruído",
        "placa-mãe",
        "processador",
        "kit de ferramentas eletrônicas",
        "leitor de cartão de memória",
        "lente para câmera",
        "flash para câmera",
        "livros",
        "DVDs",
        "blu-rays",
        "e-books",
        "CDs de música",
        "revistas",
        "áudiolivros",
        "quadrinhos",
        "mangás",
        "box de séries",
        "box de filmes",
        "enciclopédias",
        "mapas",
        "calendários",
        "agendas",
        "boneca",
        "carrinho de controle remoto",
        "quebra-cabeça",
        "Lego",
        "jogos de tabuleiro",
        "videogames",
        "bonecos de ação",
        "pelúcia",
        "drones infantis",
        "massinha de modelar",
        "brinquedos educativos",
        "blocos de montar",
        "patinete",
        "triciclo",
        "piscina de bolinhas",
        "casa de bonecas",
        "carrinho de bebê de brinquedo",
        "instrumentos musicais infantis",
        "jogo de dardos",
        "pista de carrinhos",
        "castelo inflável",
        "bolas esportivas",
        "fantasias",
        "jogos de cartas",
        "kit de mágica",
        "pneus",
        "GPS automotivo",
        "som automotivo",
        "suporte veicular para celular",
        "capa de volante",
        "tapetes para carro",
        "câmera de ré",
        "kit de primeiros socorros para carro",
        "carregador veicular",
        "aspirador de pó automotivo",
        "ração para pets",
        "coleira",
        "casinha para pets",
        "brinquedos para pets",
        "caixa de transporte",
        "arranhador",
        "comedouro automático",
        "aquário",
        "areia higiênica",
        "bebedouro para pets"
    ]

    # Dicionário para armazenar os resultados
    results = {}

    # Pesquisar produtos por tipo
    async with httpx.AsyncClient() as client_http:
        tasks = []
        for product_type in product_types:
            tasks.append(fetch_product_type(client_http, product_type))
        responses = await asyncio.gather(*tasks)
        results = dict(responses)

    # Enviar a lista de produtos para a API
    result = await send_products_to_api(results, ASSISTANT_ID_GROUP)
    
    # Verificar se a resposta é vazia ou não é um JSON válido
    if not result:
        return {"error": "Resposta vazia ou não é um JSON válido"}
    else:
        try:
            # Retornar a resposta em formato JSON
            return json.loads(result)
        except json.JSONDecodeError:
            return {"error": "Resposta não é um JSON válido"}

# Endpoint de pesquisa de produtos por tipo
@app.post("/search_products_by_type/")
async def search_products_by_type_endpoint():
    return await search_products_by_type()
